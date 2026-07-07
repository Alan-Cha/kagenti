"""Token generation and exchange service (RFC 8693).

Mission tokens are signed with Mission Authority's own RSA private key (RS256).
The corresponding public key is published at /.well-known/jwks.json so that
downstream services can verify the tokens without contacting Mission Authority.

Revocation is handled entirely through mission status in PostgreSQL — a canceled
or expired mission is rejected at token exchange time by the endpoint's DB lookup,
so no separate revocation store is needed.

Why not Keycloak-signed mission tokens?
  Keycloak's token exchange cannot inject arbitrary custom claims (e.g. mission_id)
  without a custom protocol mapper. Using Mission Authority's own keypair is the
  pragmatic approach; migrating to full Keycloak issuance requires:
    1. A "User Session Note" protocol mapper configured in Keycloak
    2. Session note injection in the token exchange request
  See scripts/setup_keycloak.py for notes on that migration path.
"""

import base64
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple
import logging

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

from mission_authority.config import settings
from mission_authority.models.mission import Mission

logger = logging.getLogger(__name__)

_private_key = None
_public_key = None


def _load_or_generate_keypair():
    global _private_key, _public_key

    if settings.mission_token_private_key_path:
        with open(settings.mission_token_private_key_path, "rb") as f:
            _private_key = serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )
        logger.info(f"Loaded RSA private key from {settings.mission_token_private_key_path}")
    else:
        _private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        logger.info("Generated in-memory RSA keypair for mission token signing")

    _public_key = _private_key.public_key()


def get_private_key():
    if _private_key is None:
        _load_or_generate_keypair()
    return _private_key


def get_public_key():
    if _public_key is None:
        _load_or_generate_keypair()
    return _public_key


def get_jwks() -> dict:
    """Return the public key as a JWKS document for /.well-known/jwks.json."""
    pub = get_public_key()
    pub_numbers = pub.public_numbers()

    def _b64(n: int, length: int) -> str:
        return base64.urlsafe_b64encode(
            n.to_bytes(length, byteorder="big")
        ).rstrip(b"=").decode()

    key_size_bytes = (pub_numbers.n.bit_length() + 7) // 8
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "mission-authority-1",
                "n": _b64(pub_numbers.n, key_size_bytes),
                "e": _b64(pub_numbers.e, 4),
            }
        ]
    }


class TokenService:
    """Token generation and exchange.

    Handles:
    - Mission token generation (RS256, signed by Mission Authority's RSA key)
    - Access token generation for RFC 8693 exchange
    """

    def generate_mission_token(self, mission: Mission) -> str:
        """Generate a mission token signed with Mission Authority's RSA key (RS256).

        Token claims:
          iss: Mission Authority's own issuer URL
          sub: Agent ID (from verified Keycloak token)
          aud: "mission-authority"
          mission_id, scope, exp, nbf, iat
        """
        now = datetime.utcnow()
        expires_at = min(
            now + timedelta(hours=settings.mission_token_ttl_hours),
            mission.expires_at,
        )

        now_ts = int(time.time())
        ttl_seconds = int((expires_at - now).total_seconds())

        payload = {
            "iss": settings.jwt_issuer,
            "sub": mission.agent_id,
            "aud": "mission-authority",
            "mission_id": mission.mission_id,
            "scope": mission.scope,
            "exp": now_ts + ttl_seconds,
            "nbf": now_ts,
            "iat": now_ts,
        }

        private_key_pem = get_private_key().private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        token = jwt.encode(
            payload,
            private_key_pem,
            algorithm="RS256",
            headers={"kid": "mission-authority-1"},
        )

        logger.info(f"Generated RS256 mission token for {mission.mission_id}")
        return token

    def exchange_token(
        self,
        mission_token: str,
        resource: str,
        scope: Optional[str] = None,
    ) -> Tuple[str, datetime]:
        """Exchange a mission token for a short-lived service access token (RFC 8693).

        Validates JWT signature and requested scope. Mission status (active/canceled)
        is validated by the calling endpoint before this method is invoked.
        """
        public_key_pem = get_public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        try:
            payload = jwt.decode(
                mission_token,
                public_key_pem,
                algorithms=["RS256"],
                audience="mission-authority",
            )
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid mission token: {e}")
            raise ValueError(f"Invalid mission token: {e}")

        mission_scopes = payload["scope"]
        if scope and scope not in mission_scopes:
            logger.warning(f"Scope {scope} not in mission scopes {mission_scopes}")
            raise ValueError(f"Scope '{scope}' not in mission scopes: {mission_scopes}")

        now_ts = int(time.time())
        access_ttl = settings.access_token_ttl_minutes * 60
        expires_at = datetime.utcnow() + timedelta(minutes=settings.access_token_ttl_minutes)

        access_payload = {
            "iss": settings.jwt_issuer,
            "sub": payload["sub"],
            "aud": resource,
            "resource": resource,
            "scope": scope or mission_scopes[0],
            "mission_id": payload["mission_id"],
            "exp": now_ts + access_ttl,
            "iat": now_ts,
        }

        private_key_pem = get_private_key().private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        access_token = jwt.encode(
            access_payload,
            private_key_pem,
            algorithm="RS256",
            headers={"kid": "mission-authority-1"},
        )

        logger.info(
            f"Exchanged mission token {payload['mission_id']} for access token "
            f"(resource={resource}, scope={scope or mission_scopes[0]})"
        )
        return access_token, expires_at
