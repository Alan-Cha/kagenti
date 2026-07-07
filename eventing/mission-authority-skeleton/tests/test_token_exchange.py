"""Tests for RFC 8693 token exchange flow."""

import pytest
import jwt
from cryptography.hazmat.primitives import serialization
from httpx import AsyncClient

from mission_authority.services.token_service import get_private_key
from tests.conftest import (
    create_and_approve_mission,
    do_token_exchange,
    on_demand_validation,
    TOKEN_EXCHANGE_GRANT,
    TOKEN_TYPE_JWT,
)


class TestTokenExchangeHappyPath:
    async def test_exchange_returns_access_token(self, client: AsyncClient):
        _, mission_token = await create_and_approve_mission(
            client, scope=["wiki_read", "wiki_write"]
        )
        resp = await do_token_exchange(client, mission_token=mission_token)

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] > 0
        assert body["expires_in"] <= 15 * 60 + 5  # ≤ 15 min + small clock tolerance
        assert body["resource"] == "wiki.team1.svc.cluster.local"

    async def test_exchange_access_token_is_valid_jwt(self, client: AsyncClient):
        from mission_authority.config import settings

        _, mission_token = await create_and_approve_mission(
            client, scope=["wiki_read", "wiki_write"]
        )
        resp = await do_token_exchange(client, mission_token=mission_token)
        access_token = resp.json()["access_token"]

        public_key_pem = get_private_key().public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        payload = jwt.decode(
            access_token,
            public_key_pem,
            algorithms=["RS256"],
            audience="wiki.team1.svc.cluster.local",
        )
        assert payload["iss"] == settings.jwt_issuer
        assert "exp" in payload
        assert "scope" in payload

    async def test_exchange_with_specific_scope(self, client: AsyncClient):
        _, mission_token = await create_and_approve_mission(
            client, scope=["wiki_read", "wiki_write", "web_search"]
        )
        resp = await do_token_exchange(
            client, mission_token=mission_token, scope="wiki_read"
        )
        assert resp.status_code == 200
        assert resp.json()["scope"] == "wiki_read"

    async def test_exchange_increments_usage_count(self, client: AsyncClient):
        mission_id, mission_token = await create_and_approve_mission(client)

        await do_token_exchange(client, mission_token=mission_token)
        await do_token_exchange(client, mission_token=mission_token)

        get_resp = await client.get(f"/api/v1/missions/{mission_id}")
        assert get_resp.json()["usage_count"] == 2

    async def test_exchange_different_resources(self, client: AsyncClient):
        _, mission_token = await create_and_approve_mission(
            client, scope=["read"]
        )
        for resource in ["svc-a.team1.svc.cluster.local", "svc-b.team2.svc.cluster.local"]:
            resp = await do_token_exchange(
                client, mission_token=mission_token, resource=resource
            )
            assert resp.status_code == 200
            assert resp.json()["resource"] == resource


class TestTokenExchangeRejections:
    async def test_wrong_grant_type_rejected(self, client: AsyncClient):
        _, mission_token = await create_and_approve_mission(client)
        resp = await client.post(
            "/api/v1/token-exchange",
            data={
                "grant_type": "authorization_code",
                "subject_token": mission_token,
                "subject_token_type": TOKEN_TYPE_JWT,
                "resource": "some-service",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "unsupported_grant_type"

    async def test_wrong_token_type_rejected(self, client: AsyncClient):
        _, mission_token = await create_and_approve_mission(client)
        resp = await client.post(
            "/api/v1/token-exchange",
            data={
                "grant_type": TOKEN_EXCHANGE_GRANT,
                "subject_token": mission_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:saml2",
                "resource": "some-service",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "invalid_request"

    async def test_invalid_jwt_rejected(self, client: AsyncClient):
        resp = await do_token_exchange(client, mission_token="not.a.jwt")
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "invalid_grant"

    async def test_out_of_scope_request_rejected(self, client: AsyncClient):
        _, mission_token = await create_and_approve_mission(
            client, scope=["wiki_read"]
        )
        resp = await do_token_exchange(
            client, mission_token=mission_token, scope="admin_write"
        )
        assert resp.status_code == 403
        assert "scope" in resp.json()["detail"]["error_description"].lower()

    async def test_canceled_mission_token_rejected(self, client: AsyncClient):
        mission_id, mission_token = await create_and_approve_mission(client)

        await client.post(
            f"/api/v1/missions/{mission_id}/cancel",
            json={"reason": "Revoked"},
        )

        resp = await do_token_exchange(client, mission_token=mission_token)
        assert resp.status_code == 403

    async def test_expired_jwt_rejected(self, client: AsyncClient):
        """A JWT whose exp is in the past should be rejected."""
        import time
        from mission_authority.config import settings

        now = int(time.time())
        payload = {
            "iss": settings.jwt_issuer,
            "sub": "test-agent",
            "aud": "mission-authority",
            "mission_id": "M-20200101-expired",
            "scope": ["read"],
            "exp": now - 3600,
            "nbf": now - 7200,
            "iat": now - 7200,
        }
        private_key_pem = get_private_key().private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        expired_token = jwt.encode(payload, private_key_pem, algorithm="RS256")

        resp = await do_token_exchange(client, mission_token=expired_token)
        assert resp.status_code == 403
        assert "expired" in resp.json()["detail"]["error_description"].lower()
