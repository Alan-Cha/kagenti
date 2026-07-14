# Copyright 2025 IBM Corp.
# Licensed under the Apache License, Version 2.0

"""Mission Authority proxy router.

Forwards all /missions and /token-exchange requests to the Mission Authority
service. The UI never talks to Mission Authority directly — all traffic flows
through this proxy so auth, CORS, and service discovery remain centralised.

Configuration:
    MISSION_AUTHORITY_URL — base URL of the Mission Authority service, e.g.
        http://mission-authority.kagenti-system.svc.cluster.local:8000
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.core.auth import ROLE_OPERATOR, ROLE_VIEWER, require_roles
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["missions"])

_FORWARD_HEADERS = {"Content-Type", "Accept"}


def _mission_authority_url() -> str:
    url = settings.mission_authority_url.rstrip("/")
    if not url:
        raise HTTPException(
            status_code=503,
            detail="Mission Authority is not configured (MISSION_AUTHORITY_URL not set)",
        )
    return url


async def _proxy(
    request: Request,
    path: str,
    method: str | None = None,
) -> Response:
    """Forward a request to Mission Authority and return the response verbatim."""
    base = _mission_authority_url()
    target = f"{base}{path}"

    method = method or request.method
    body = await request.body()

    # Forward Content-Type from the original request (important for form-encoded
    # token-exchange requests)
    headers: dict[str, str] = {}
    if ct := request.headers.get("content-type"):
        headers["content-type"] = ct

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method=method,
                url=target,
                content=body,
                headers=headers,
                params=dict(request.query_params),
            )
    except httpx.RequestError as exc:
        logger.error("Mission Authority unreachable: %s", exc)
        raise HTTPException(status_code=503, detail="Mission Authority unreachable")

    # Pass the response back as-is, preserving status and body
    try:
        data = resp.json()
        return JSONResponse(content=data, status_code=resp.status_code)
    except Exception:
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/octet-stream"),
        )


# ---------------------------------------------------------------------------
# Mission CRUD
# ---------------------------------------------------------------------------

@router.get(
    "/missions",
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
    summary="List missions",
)
async def list_missions(request: Request) -> Response:
    return await _proxy(request, "/api/v1/missions")


@router.post(
    "/missions",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
    summary="Create a mission",
    status_code=201,
)
async def create_mission(request: Request) -> Response:
    return await _proxy(request, "/api/v1/missions")


@router.get(
    "/missions/{mission_id}",
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
    summary="Get a mission",
)
async def get_mission(mission_id: str, request: Request) -> Response:
    return await _proxy(request, f"/api/v1/missions/{mission_id}")


@router.post(
    "/missions/{mission_id}/approve",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
    summary="Approve a pending mission",
)
async def approve_mission(mission_id: str, request: Request) -> Response:
    return await _proxy(request, f"/api/v1/missions/{mission_id}/approve")


@router.post(
    "/missions/{mission_id}/cancel",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
    summary="Cancel a mission",
)
async def cancel_mission(mission_id: str, request: Request) -> Response:
    return await _proxy(request, f"/api/v1/missions/{mission_id}/cancel")


# ---------------------------------------------------------------------------
# Scope expansions
# ---------------------------------------------------------------------------

@router.post(
    "/missions/{mission_id}/expand-scope",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
    summary="Request a scope expansion",
    status_code=201,
)
async def request_scope_expansion(mission_id: str, request: Request) -> Response:
    return await _proxy(request, f"/api/v1/missions/{mission_id}/expand-scope")


@router.post(
    "/missions/{mission_id}/expansions/{expansion_id}/approve",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
    summary="Approve a scope expansion",
)
async def approve_scope_expansion(
    mission_id: str, expansion_id: str, request: Request
) -> Response:
    return await _proxy(
        request,
        f"/api/v1/missions/{mission_id}/expansions/{expansion_id}/approve",
    )


@router.post(
    "/missions/{mission_id}/expansions/{expansion_id}/deny",
    dependencies=[Depends(require_roles(ROLE_OPERATOR))],
    summary="Deny a scope expansion",
)
async def deny_scope_expansion(
    mission_id: str, expansion_id: str, request: Request
) -> Response:
    return await _proxy(
        request,
        f"/api/v1/missions/{mission_id}/expansions/{expansion_id}/deny",
    )


# ---------------------------------------------------------------------------
# Token exchange (RFC 8693)
# ---------------------------------------------------------------------------

@router.post(
    "/missions/token-exchange",
    dependencies=[Depends(require_roles(ROLE_VIEWER))],
    summary="Exchange a mission token for a service access token (RFC 8693)",
)
async def token_exchange(request: Request) -> Response:
    return await _proxy(request, "/api/v1/token-exchange")


# ---------------------------------------------------------------------------
# JWKS — public endpoint, no auth required
# ---------------------------------------------------------------------------

@router.get(
    "/missions/jwks",
    summary="Mission Authority public key set",
)
async def jwks(request: Request) -> Response:
    return await _proxy(request, "/.well-known/jwks.json")
