"""Mission CRUD and scope expansion endpoints."""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from uuid import uuid4
import logging

from mission_authority.auth.keycloak import TokenClaims, require_agent_token, require_user_token
from mission_authority.database import get_db
from mission_authority.models.mission import Mission, MissionStatus, ScopeExpansion
from mission_authority.schemas.mission import (
    MissionCreateRequest,
    MissionCreateResponse,
    MissionApproveRequest,
    MissionApproveResponse,
    MissionResponse,
    MissionListResponse,
    MissionCancelRequest,
    ScopeExpansionRequest,
    ScopeExpansionApproveRequest,
    ScopeExpansionDenyRequest,
    ScopeExpansionResponse,
)
from mission_authority.services.token_service import TokenService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", response_model=MissionCreateResponse, status_code=201)
async def create_mission(
    request: MissionCreateRequest,
    db: AsyncSession = Depends(get_db),
    agent: TokenClaims = Depends(require_agent_token),
):
    """Create a new mission.

    Mission starts in 'pending' status and requires approval before activation.
    """
    mission_id = f"M-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:8]}"

    validation = request.validation
    if validation.get("type") == "scheduled":
        duration_days = validation.get("duration_days", 90)
        expires_at = datetime.utcnow() + timedelta(days=duration_days)
    elif validation.get("type") == "on_demand":
        expires_at = datetime.fromisoformat(
            validation["valid_until"].replace("Z", "+00:00")
        ).replace(tzinfo=None)
    else:
        expires_at = datetime.utcnow() + timedelta(hours=24)

    mission = Mission(
        mission_id=mission_id,
        task=request.task,
        agent_id=request.agent_id,
        scope=request.scope,
        sub_agents=[sa.model_dump() for sa in request.sub_agents] if request.sub_agents else None,
        status=MissionStatus.PENDING,
        validation=validation,
        created_by=agent.preferred_username,
        expires_at=expires_at,
        labels=request.labels or {},
    )

    db.add(mission)
    await db.commit()
    await db.refresh(mission)

    logger.info(f"Created mission {mission_id} for agent {request.agent_id}")

    return MissionCreateResponse(
        mission_id=mission.mission_id,
        status=mission.status.value,
        created_at=mission.created_at,
        expires_at=mission.expires_at,
        approval_url=f"/missions/{mission_id}/approve",
    )


@router.post("/{mission_id}/approve", response_model=MissionApproveResponse)
async def approve_mission(
    mission_id: str,
    request: MissionApproveRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenClaims = Depends(require_user_token),
):
    """Approve a pending mission and issue a mission token."""
    result = await db.execute(select(Mission).where(Mission.mission_id == mission_id))
    mission = result.scalar_one_or_none()

    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    if mission.status != MissionStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Mission {mission_id} is {mission.status.value}, cannot approve",
        )

    mission.status = MissionStatus.ACTIVE
    mission.approved_at = datetime.utcnow()
    mission.approved_by = user.preferred_username

    await db.commit()
    await db.refresh(mission)

    token_service = TokenService()
    mission_token = token_service.generate_mission_token(mission)

    logger.info(f"Approved mission {mission_id} by {request.approved_by}")

    # TODO: Publish mission.approved CloudEvent

    return MissionApproveResponse(
        mission_id=mission.mission_id,
        status=mission.status.value,
        approved_at=mission.approved_at,
        approved_by=mission.approved_by,
        mission_token=mission_token,
    )


@router.get("/{mission_id}", response_model=MissionResponse)
async def get_mission(
    mission_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get mission details."""
    result = await db.execute(select(Mission).where(Mission.mission_id == mission_id))
    mission = result.scalar_one_or_none()

    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    return MissionResponse.model_validate(mission)


@router.get("", response_model=MissionListResponse)
async def list_missions(
    status: Optional[str] = Query(None, description="Filter by status"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    """List missions with optional filters."""
    query = select(Mission)

    if status:
        try:
            status_enum = MissionStatus(status)
            query = query.where(Mission.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if agent_id:
        query = query.where(Mission.agent_id == agent_id)

    # Count before pagination
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    query = query.order_by(Mission.created_at.desc())
    query = query.limit(page_size).offset((page - 1) * page_size)

    result = await db.execute(query)
    missions = result.scalars().all()

    return MissionListResponse(
        missions=[MissionResponse.model_validate(m) for m in missions],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{mission_id}/cancel")
async def cancel_mission(
    mission_id: str,
    request: MissionCancelRequest,
    db: AsyncSession = Depends(get_db),
    user: TokenClaims = Depends(require_user_token),
):
    """Cancel a pending or active mission. Revokes all issued tokens."""
    result = await db.execute(select(Mission).where(Mission.mission_id == mission_id))
    mission = result.scalar_one_or_none()

    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    if mission.status not in [MissionStatus.PENDING, MissionStatus.ACTIVE]:
        raise HTTPException(
            status_code=400,
            detail=f"Mission {mission_id} is {mission.status.value}, cannot cancel",
        )

    mission.status = MissionStatus.CANCELED
    mission.canceled_at = datetime.utcnow()
    mission.cancellation_reason = request.reason

    await db.commit()

    logger.info(f"Canceled mission {mission_id} by {user.preferred_username}: {request.reason}")

    # TODO: Publish mission.canceled CloudEvent

    return {"mission_id": mission_id, "status": "canceled"}


# --- Scope Expansion ---


@router.post(
    "/{mission_id}/expand-scope",
    response_model=ScopeExpansionResponse,
    status_code=201,
)
async def request_scope_expansion(
    mission_id: str,
    request: ScopeExpansionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request additional scopes for an active mission.

    The agent provides a justification; a human must approve before the
    new scopes are added to the mission.
    """
    result = await db.execute(select(Mission).where(Mission.mission_id == mission_id))
    mission = result.scalar_one_or_none()

    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    if mission.status != MissionStatus.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail=f"Mission {mission_id} is {mission.status.value}, can only expand active missions",
        )

    expansion_id = f"EXP-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:8]}"

    expansion = ScopeExpansion(
        expansion_id=expansion_id,
        mission_id=mission_id,
        requested_by=request.requesting_agent,
        additional_scopes=request.additional_scopes,
        justification=request.justification,
        status="pending",
    )

    db.add(expansion)
    await db.commit()
    await db.refresh(expansion)

    logger.info(
        f"Scope expansion {expansion_id} requested for mission {mission_id} "
        f"by {request.requesting_agent}: {request.additional_scopes}"
    )

    return ScopeExpansionResponse.model_validate(expansion)


@router.post(
    "/{mission_id}/expansions/{expansion_id}/approve",
    response_model=ScopeExpansionResponse,
)
async def approve_scope_expansion(
    mission_id: str,
    expansion_id: str,
    request: ScopeExpansionApproveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending scope expansion.

    Merges the additional scopes into the mission's scope list.
    """
    result = await db.execute(
        select(ScopeExpansion).where(
            ScopeExpansion.expansion_id == expansion_id,
            ScopeExpansion.mission_id == mission_id,
        )
    )
    expansion = result.scalar_one_or_none()

    if not expansion:
        raise HTTPException(status_code=404, detail=f"Expansion {expansion_id} not found")

    if expansion.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Expansion {expansion_id} is {expansion.status}, cannot approve",
        )

    # Merge scopes into mission
    mission_result = await db.execute(
        select(Mission).where(Mission.mission_id == mission_id)
    )
    mission = mission_result.scalar_one_or_none()
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    # Merge without duplicates
    merged = list(set(mission.scope) | set(expansion.additional_scopes))
    mission.scope = merged

    expansion.status = "approved"
    expansion.approved_at = datetime.utcnow()
    expansion.approved_by = request.approved_by

    await db.commit()
    await db.refresh(expansion)

    logger.info(
        f"Approved scope expansion {expansion_id} for mission {mission_id} "
        f"by {request.approved_by}"
    )

    return ScopeExpansionResponse.model_validate(expansion)


@router.post(
    "/{mission_id}/expansions/{expansion_id}/deny",
    response_model=ScopeExpansionResponse,
)
async def deny_scope_expansion(
    mission_id: str,
    expansion_id: str,
    request: ScopeExpansionDenyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Deny a pending scope expansion request."""
    result = await db.execute(
        select(ScopeExpansion).where(
            ScopeExpansion.expansion_id == expansion_id,
            ScopeExpansion.mission_id == mission_id,
        )
    )
    expansion = result.scalar_one_or_none()

    if not expansion:
        raise HTTPException(status_code=404, detail=f"Expansion {expansion_id} not found")

    if expansion.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Expansion {expansion_id} is {expansion.status}, cannot deny",
        )

    expansion.status = "denied"

    await db.commit()
    await db.refresh(expansion)

    logger.info(
        f"Denied scope expansion {expansion_id} for mission {mission_id} "
        f"by {request.denied_by}"
    )

    return ScopeExpansionResponse.model_validate(expansion)
