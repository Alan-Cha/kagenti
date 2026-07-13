"""Keycloak token validation for Mission Authority.

When keycloak_enabled=True, all endpoints require a Bearer token validated
against Keycloak's JWKS endpoint.

When keycloak_enabled=False (standalone/test mode), the dependencies return
a stub identity so the service runs without a Keycloak instance.
"""

from dataclasses import dataclass
from typing import Optional
import logging

import jwt
from jwt import PyJWKClient, PyJWKClientError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from mission_authority.config import settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

# PyJWKClient caches keys and refreshes when it encounters an unknown kid.
_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(settings.keycloak_jwks_url, cache_keys=True)
    return _jwks_client


@dataclass
class TokenClaims:
    """Verified claims from a Keycloak-issued token."""
    sub: str                    # Subject (user or service account ID)
    preferred_username: str     # Human-readable identity
    email: Optional[str]        # Present for user tokens
    client_id: Optional[str]    # Present for service account tokens
    roles: list                 # Realm roles
    raw: dict                   # Full decoded payload


def _decode_keycloak_token(token: str) -> TokenClaims:
    """Validate token signature against Keycloak JWKS and return claims."""
    client = _get_jwks_client()
    try:
        signing_key = client.get_signing_key_from_jwt(token)
    except PyJWKClientError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unable to fetch signing key: {e}",
        )

    try:
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.keycloak_issuer,
            options={"verify_aud": False},  # audience varies by use case
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )

    realm_access = payload.get("realm_access", {})
    # sub may be absent when a Keycloak client uses a custom token mapper
    # that strips it; fall back to preferred_username or azp
    sub = payload.get("sub") or payload.get("preferred_username") or payload.get("azp", "unknown")
    preferred_username = payload.get("preferred_username") or payload.get("azp") or sub
    return TokenClaims(
        sub=sub,
        preferred_username=preferred_username,
        email=payload.get("email"),
        client_id=payload.get("azp"),
        roles=realm_access.get("roles", []),
        raw=payload,
    )


def _stub_agent_claims() -> TokenClaims:
    return TokenClaims(
        sub="stub-agent",
        preferred_username="stub-agent",
        email=None,
        client_id="stub-agent",
        roles=[],
        raw={},
    )


def _stub_user_claims() -> TokenClaims:
    return TokenClaims(
        sub="stub-user",
        preferred_username="stub-user@example.com",
        email="stub-user@example.com",
        client_id=None,
        roles=["mission-approver"],
        raw={},
    )


async def require_agent_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> TokenClaims:
    """FastAPI dependency: require a valid Keycloak token from an agent (service account).

    In standalone mode (keycloak_enabled=False), returns a stub identity.
    """
    if not settings.keycloak_enabled:
        return _stub_agent_claims()

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_keycloak_token(credentials.credentials)
    logger.debug(f"Authenticated agent: {claims.preferred_username} ({claims.sub})")
    return claims


async def require_user_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> TokenClaims:
    """FastAPI dependency: require a valid Keycloak token from a human user.

    In standalone mode (keycloak_enabled=False), returns a stub identity.
    """
    if not settings.keycloak_enabled:
        return _stub_user_claims()

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_keycloak_token(credentials.credentials)
    logger.debug(f"Authenticated user: {claims.preferred_username} ({claims.sub})")
    return claims
