"""Tests for mission lifecycle: create, approve, get, list, cancel."""

import pytest
from httpx import AsyncClient

from tests.conftest import on_demand_validation, scheduled_validation, create_and_approve_mission


class TestCreateMission:
    async def test_create_on_demand_mission(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/missions",
            json={
                "task": "Research AI safety literature and update wiki",
                "agent_id": "research-agent",
                "scope": ["wiki_read", "wiki_write", "web_search"],
                "validation": on_demand_validation(max_uses=3),
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert body["mission_id"].startswith("M-")
        assert "approval_url" in body
        assert "expires_at" in body

    async def test_create_scheduled_mission(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/missions",
            json={
                "task": "Daily metrics report",
                "agent_id": "metrics-agent",
                "scope": ["metrics_read"],
                "validation": scheduled_validation(duration_days=30),
            },
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "pending"

    async def test_create_mission_empty_scope_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/missions",
            json={
                "task": "Some task",
                "agent_id": "agent-1",
                "scope": [],
                "validation": on_demand_validation(),
            },
        )
        assert resp.status_code == 422

    async def test_create_mission_missing_task_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/missions",
            json={
                "agent_id": "agent-1",
                "scope": ["read"],
                "validation": on_demand_validation(),
            },
        )
        assert resp.status_code == 422

    async def test_create_mission_with_labels(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/missions",
            json={
                "task": "Tagged task",
                "agent_id": "agent-1",
                "scope": ["read"],
                "validation": on_demand_validation(),
                "labels": {"env": "test", "team": "research"},
            },
        )
        assert resp.status_code == 201


class TestApproveMission:
    async def test_approve_pending_mission_issues_token(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/v1/missions",
            json={
                "task": "Summarize documents",
                "agent_id": "summarizer",
                "scope": ["doc_read"],
                "validation": on_demand_validation(),
            },
        )
        mission_id = create_resp.json()["mission_id"]

        approve_resp = await client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={},
        )
        assert approve_resp.status_code == 200
        body = approve_resp.json()
        assert body["status"] == "active"
        assert body["approved_by"] == "operator@example.com"  # from stub user token
        assert "mission_token" in body
        assert len(body["mission_token"]) > 20

    async def test_approve_nonexistent_mission_returns_404(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/missions/M-99999999-notreal/approve",
            json={"approved_by": "admin@example.com"},
        )
        assert resp.status_code == 404

    async def test_approve_already_active_mission_returns_400(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(client)

        second_approve = await client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={"approved_by": "admin@example.com"},
        )
        assert second_approve.status_code == 400
        assert "active" in second_approve.json()["detail"]

    async def test_approve_canceled_mission_returns_400(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/v1/missions",
            json={
                "task": "Task to cancel",
                "agent_id": "agent-1",
                "scope": ["read"],
                "validation": on_demand_validation(),
            },
        )
        mission_id = create_resp.json()["mission_id"]

        await client.post(
            f"/api/v1/missions/{mission_id}/cancel",
            json={"reason": "No longer needed"},
        )

        resp = await client.post(
            f"/api/v1/missions/{mission_id}/approve",
            json={"approved_by": "admin@example.com"},
        )
        assert resp.status_code == 400


class TestGetMission:
    async def test_get_existing_mission(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(
            client, agent_id="getter-agent", scope=["read", "write"]
        )
        resp = await client.get(f"/api/v1/missions/{mission_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mission_id"] == mission_id
        assert body["status"] == "active"
        assert body["agent_id"] == "getter-agent"
        assert "read" in body["scope"]

    async def test_get_nonexistent_mission_returns_404(self, client: AsyncClient):
        resp = await client.get("/api/v1/missions/M-00000000-missing")
        assert resp.status_code == 404

    async def test_get_mission_shows_usage_count(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(client)
        resp = await client.get(f"/api/v1/missions/{mission_id}")
        assert resp.json()["usage_count"] == 0


class TestListMissions:
    async def test_list_all_missions(self, client: AsyncClient):
        await create_and_approve_mission(client, agent_id="a1")
        await create_and_approve_mission(client, agent_id="a2")

        resp = await client.get("/api/v1/missions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 2
        assert len(body["missions"]) >= 2

    async def test_list_filter_by_status(self, client: AsyncClient):
        # Create a pending mission (not approved)
        await client.post(
            "/api/v1/missions",
            json={
                "task": "Pending task",
                "agent_id": "pending-agent",
                "scope": ["read"],
                "validation": on_demand_validation(),
            },
        )
        await create_and_approve_mission(client, agent_id="active-agent")

        pending_resp = await client.get("/api/v1/missions?status=pending")
        assert pending_resp.status_code == 200
        for m in pending_resp.json()["missions"]:
            assert m["status"] == "pending"

        active_resp = await client.get("/api/v1/missions?status=active")
        for m in active_resp.json()["missions"]:
            assert m["status"] == "active"

    async def test_list_filter_by_agent_id(self, client: AsyncClient):
        await create_and_approve_mission(client, agent_id="special-agent")
        await create_and_approve_mission(client, agent_id="other-agent")

        resp = await client.get("/api/v1/missions?agent_id=special-agent")
        assert resp.status_code == 200
        for m in resp.json()["missions"]:
            assert m["agent_id"] == "special-agent"

    async def test_list_invalid_status_returns_400(self, client: AsyncClient):
        resp = await client.get("/api/v1/missions?status=not_a_status")
        assert resp.status_code == 400

    async def test_list_pagination(self, client: AsyncClient):
        for i in range(3):
            await create_and_approve_mission(client, agent_id=f"page-agent-{i}")

        page1 = await client.get("/api/v1/missions?page=1&page_size=2")
        assert page1.status_code == 200
        assert len(page1.json()["missions"]) <= 2


class TestCancelMission:
    async def test_cancel_pending_mission(self, client: AsyncClient):
        create_resp = await client.post(
            "/api/v1/missions",
            json={
                "task": "Will be canceled",
                "agent_id": "agent-c",
                "scope": ["read"],
                "validation": on_demand_validation(),
            },
        )
        mission_id = create_resp.json()["mission_id"]

        cancel_resp = await client.post(
            f"/api/v1/missions/{mission_id}/cancel",
            json={"reason": "Not needed"},
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "canceled"

        # Confirm status in GET
        get_resp = await client.get(f"/api/v1/missions/{mission_id}")
        assert get_resp.json()["status"] == "canceled"

    async def test_cancel_active_mission(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(client)

        cancel_resp = await client.post(
            f"/api/v1/missions/{mission_id}/cancel",
            json={"reason": "Task obsolete"},
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "canceled"

    async def test_cancel_already_canceled_mission_returns_400(self, client: AsyncClient):
        mission_id, _ = await create_and_approve_mission(client)

        await client.post(
            f"/api/v1/missions/{mission_id}/cancel",
            json={"reason": "First cancel"},
        )

        resp = await client.post(
            f"/api/v1/missions/{mission_id}/cancel",
            json={"reason": "Second cancel"},
        )
        assert resp.status_code == 400

    async def test_cancel_nonexistent_mission_returns_404(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/missions/M-00000000-fake/cancel",
            json={},
        )
        assert resp.status_code == 404
