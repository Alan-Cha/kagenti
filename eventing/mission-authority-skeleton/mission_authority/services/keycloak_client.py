"""Keycloak client for Mission Authority's own service account interactions.

Mission Authority authenticates to Keycloak using the client credentials grant,
then uses that service token to call Keycloak admin or token APIs.

Note on mission token issuance:
  Keycloak's standard token exchange (RFC 8693) cannot inject arbitrary custom
  claims like mission_id without a custom protocol mapper. Mission tokens are
  therefore signed by Mission Authority's own RSA key (see token_service.py).
  The path to full Keycloak issuance requires configuring a User Session Note
  mapper in Keycloak and injecting session notes at exchange time — documented
  in scripts/setup_keycloak.py for when that migration is ready.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

from mission_authority.config import settings

logger = logging.getLogger(__name__)

_cached_token: Optional[str] = None
_token_expires_at: Optional[datetime] = None


async def get_service_token() -> str:
    """Obtain a service account token for Mission Authority from Keycloak.

    Uses the client credentials grant. Result is cached until 30 seconds
    before expiry to avoid unnecessary round-trips.

    Returns:
        Bearer token string

    Raises:
        RuntimeError: If Keycloak is unreachable or returns an error
    """
    global _cached_token, _token_expires_at

    now = datetime.utcnow()
    if _cached_token and _token_expires_at and now < _token_expires_at:
        return _cached_token

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                settings.keycloak_token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.keycloak_client_id,
                    "client_secret": settings.keycloak_client_secret,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(f"Failed to obtain service token from Keycloak: {e}")

    body = resp.json()
    _cached_token = body["access_token"]
    expires_in = body.get("expires_in", 300)
    _token_expires_at = now + timedelta(seconds=expires_in - 30)

    logger.debug(f"Obtained Keycloak service token (expires_in={expires_in}s)")
    return _cached_token


def invalidate_service_token():
    """Force re-fetch of service token on next call (e.g. after 401)."""
    global _cached_token, _token_expires_at
    _cached_token = None
    _token_expires_at = None
