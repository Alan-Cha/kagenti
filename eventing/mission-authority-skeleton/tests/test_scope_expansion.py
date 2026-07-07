"""Tests for the scope expansion workflow."""

import pytest
from httpx import AsyncClient

from tests.conftest import create_and_approve_mission, on_demand_validation


class TestRequestScopeExpansion:
    async def test_request_expansion_on_active_mission(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(
            client, scope=["wiki_read", "wiki_write"]
        )
        resp = await client.post(
            f"/api/v1/missions/{mission_id}/expand-scope",
            json={
                "requesting_agent": "research-agent",
                "additional_scopes": ["image_optimize"],
                "justification": "Found 3 large diagrams that need compression before upload.",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert body["mission_id"] == mission_id
        assert "image_optimize" in body["additional_scopes"]
        assert body["expansion_id"].startswith("EXP-")

    async def test_request_expansion_on_pending_mission_rejected(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/v1/missions",
            json={
                "task": "Pending task",
                "agent_id": "agent-1",
                "scope": ["read"],
                "validation": on_demand_validation(),
            },
        )
        mission_id = create_resp.json()["mission_id"]

        resp = await client.post(
            f"/api/v1/missions/{mission_id}/expand-scope",
            json={
                "requesting_agent": "agent-1",
                "additional_scopes": ["write"],
                "justification": "Need write access for the task.",
            },
        )
        assert resp.status_code == 400
        assert "pending" in resp.json()["detail"].lower()

    async def test_request_expansion_short_justification_rejected(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(client)

        resp = await client.post(
            f"/api/v1/missions/{mission_id}/expand-scope",
            json={
                "requesting_agent": "agent-1",
                "additional_scopes": ["write"],
                "justification": "Need it",  # Too short (< 10 chars)
            },
        )
        assert resp.status_code == 422

    async def test_request_expansion_nonexistent_mission_returns_404(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/missions/M-00000000-fake/expand-scope",
            json={
                "requesting_agent": "agent-1",
                "additional_scopes": ["write"],
                "justification": "Need write access to complete the task.",
            },
        )
        assert resp.status_code == 404


class TestApproveScopeExpansion:
    async def test_approve_expansion_merges_scopes(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(
            client, scope=["wiki_read", "wiki_write"]
        )

        # Request expansion
        exp_resp = await client.post(
            f"/api/v1/missions/{mission_id}/expand-scope",
            json={
                "requesting_agent": "research-agent",
                "additional_scopes": ["image_optimize", "doc_export"],
                "justification": "Need image optimization and document export for final report.",
            },
        )
        expansion_id = exp_resp.json()["expansion_id"]

        # Approve it
        approve_resp = await client.post(
            f"/api/v1/missions/{mission_id}/expansions/{expansion_id}/approve",
            json={"approved_by": "operator@example.com"},
        )
        assert approve_resp.status_code == 200
        body = approve_resp.json()
        assert body["status"] == "approved"
        assert body["approved_by"] == "operator@example.com"

        # Mission scope should now include the new scopes
        mission_resp = await client.get(f"/api/v1/missions/{mission_id}")
        scope = mission_resp.json()["scope"]
        assert "wiki_read" in scope
        assert "wiki_write" in scope
        assert "image_optimize" in scope
        assert "doc_export" in scope

    async def test_approve_already_approved_expansion_rejected(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(client, scope=["read"])

        exp_resp = await client.post(
            f"/api/v1/missions/{mission_id}/expand-scope",
            json={
                "requesting_agent": "agent-1",
                "additional_scopes": ["write"],
                "justification": "Need write access for the final step of the task.",
            },
        )
        expansion_id = exp_resp.json()["expansion_id"]

        await client.post(
            f"/api/v1/missions/{mission_id}/expansions/{expansion_id}/approve",
            json={"approved_by": "operator@example.com"},
        )

        # Second approve should fail
        resp = await client.post(
            f"/api/v1/missions/{mission_id}/expansions/{expansion_id}/approve",
            json={"approved_by": "operator@example.com"},
        )
        assert resp.status_code == 400

    async def test_approve_nonexistent_expansion_returns_404(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(client)
        resp = await client.post(
            f"/api/v1/missions/{mission_id}/expansions/EXP-00000000-fake/approve",
            json={"approved_by": "operator@example.com"},
        )
        assert resp.status_code == 404


class TestDenyScopeExpansion:
    async def test_deny_expansion(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(client, scope=["read"])

        exp_resp = await client.post(
            f"/api/v1/missions/{mission_id}/expand-scope",
            json={
                "requesting_agent": "agent-1",
                "additional_scopes": ["admin_delete"],
                "justification": "Requesting admin access to clean up test data.",
            },
        )
        expansion_id = exp_resp.json()["expansion_id"]

        deny_resp = await client.post(
            f"/api/v1/missions/{mission_id}/expansions/{expansion_id}/deny",
            json={"denied_by": "security@example.com", "reason": "Admin scopes not permitted"},
        )
        assert deny_resp.status_code == 200
        assert deny_resp.json()["status"] == "denied"

        # Mission scope must NOT have changed
        mission_resp = await client.get(f"/api/v1/missions/{mission_id}")
        assert "admin_delete" not in mission_resp.json()["scope"]

    async def test_deny_already_denied_expansion_rejected(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(client, scope=["read"])

        exp_resp = await client.post(
            f"/api/v1/missions/{mission_id}/expand-scope",
            json={
                "requesting_agent": "agent-1",
                "additional_scopes": ["write"],
                "justification": "Need write for the next phase of the task.",
            },
        )
        expansion_id = exp_resp.json()["expansion_id"]

        await client.post(
            f"/api/v1/missions/{mission_id}/expansions/{expansion_id}/deny",
            json={"denied_by": "operator@example.com"},
        )

        resp = await client.post(
            f"/api/v1/missions/{mission_id}/expansions/{expansion_id}/deny",
            json={"denied_by": "operator@example.com"},
        )
        assert resp.status_code == 400
