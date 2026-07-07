"""Token exchange endpoint (RFC 8693)."""

from datetime import datetime
from fastapi import APIRouter, Form, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import jwt
import logging

from mission_authority.config import settings
from mission_authority.database import get_db
from mission_authority.models.mission import Mission, MissionStatus
from mission_authority.services.token_service import TokenService, get_public_key
from cryptography.hazmat.primitives import serialization

router = APIRouter()
logger = logging.getLogger(__name__)

GRANT_TYPE_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
TOKEN_TYPE_JWT = "urn:ietf:params:oauth:token-type:jwt"


class TokenExchangeResponse(BaseModel):
    """RFC 8693 token exchange response."""
    access_token: str
    issued_token_type: str = "urn:ietf:params:oauth:token-type:access_token"
    token_type: str = "Bearer"
    expires_in: int
    scope: str
    mission_id: str
    resource: str
    issued_at: str


@router.post("/token-exchange", response_model=TokenExchangeResponse)
async def exchange_token(
    grant_type: str = Form(...),
    subject_token: str = Form(...),
    subject_token_type: str = Form(...),
    resource: str = Form(...),
    scope: str = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Exchange a mission token for a short-lived service access token (RFC 8693).

    Validates:
    - Correct grant_type and subject_token_type
    - Token signature and expiration
    - Mission is still active (not canceled or expired)
    - Requested scope is in the mission's approved scopes
    - on_demand missions: valid_until not exceeded, max_uses not exceeded

    Request (application/x-www-form-urlencoded):
        grant_type: Must be "urn:ietf:params:oauth:grant-type:token-exchange"
        subject_token: Mission token (JWT)
        subject_token_type: Must be "urn:ietf:params:oauth:token-type:jwt"
        resource: Target service URI
        scope: Optional specific scope (must be in mission scopes)

    Returns a short-lived (15 min) access token scoped to the requested resource.
    """
    if grant_type != GRANT_TYPE_TOKEN_EXCHANGE:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_grant_type",
                "error_description": f"grant_type must be {GRANT_TYPE_TOKEN_EXCHANGE}",
            },
        )

    if subject_token_type != TOKEN_TYPE_JWT:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_request",
                "error_description": f"subject_token_type must be {TOKEN_TYPE_JWT}",
            },
        )

    # Decode the mission token to get the mission_id (pre-validation in TokenService)
    public_key_pem = get_public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    try:
        raw_payload = jwt.decode(
            subject_token,
            public_key_pem,
            algorithms=["RS256"],
            audience="mission-authority",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=403,
            detail={"error": "invalid_grant", "error_description": "Mission token has expired"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=403,
            detail={"error": "invalid_grant", "error_description": f"Invalid mission token: {e}"},
        )

    mission_id = raw_payload["mission_id"]

    # Load mission and validate its current state
    result = await db.execute(select(Mission).where(Mission.mission_id == mission_id))
    mission = result.scalar_one_or_none()

    if not mission:
        raise HTTPException(
            status_code=403,
            detail={"error": "invalid_grant", "error_description": f"Mission {mission_id} not found"},
        )

    if mission.status != MissionStatus.ACTIVE:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "invalid_grant",
                "error_description": f"Mission {mission_id} is {mission.status.value}, not active",
            },
        )

    # Validate on_demand policy constraints
    validation = mission.validation or {}
    if validation.get("type") == "on_demand":
        max_uses = validation.get("max_uses")
        if max_uses is not None and mission.usage_count >= max_uses:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "invalid_grant",
                    "error_description": (
                        f"Mission {mission_id} usage limit exceeded "
                        f"({mission.usage_count}/{max_uses})"
                    ),
                },
            )

        valid_until = validation.get("valid_until")
        if valid_until:
            valid_until_dt = datetime.fromisoformat(
                valid_until.replace("Z", "+00:00")
            ).replace(tzinfo=None)
            if datetime.utcnow() > valid_until_dt:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "invalid_grant",
                        "error_description": f"Mission {mission_id} valid_until has passed",
                    },
                )

    # Exchange via token service (validates revocation and scope)
    token_service = TokenService()
    try:
        access_token, expires_at = token_service.exchange_token(
            mission_token=subject_token,
            resource=resource,
            scope=scope,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=403,
            detail={"error": "invalid_grant", "error_description": str(e)},
        )

    # Track usage
    mission.usage_count = (mission.usage_count or 0) + 1
    mission.last_exchange_at = datetime.utcnow()
    await db.commit()

    now = datetime.utcnow()
    expires_in = int((expires_at - now).total_seconds())

    decoded = jwt.decode(
        access_token,
        public_key_pem,
        algorithms=["RS256"],
        options={"verify_signature": False},
    )

    return TokenExchangeResponse(
        access_token=access_token,
        expires_in=expires_in,
        scope=decoded["scope"],
        mission_id=mission_id,
        resource=resource,
        issued_at=now.isoformat() + "Z",
    )
