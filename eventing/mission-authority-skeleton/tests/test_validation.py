"""Tests for on_demand validation policy enforcement during token exchange."""

import pytest
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient

from tests.conftest import create_and_approve_mission, do_token_exchange


class TestOnDemandMaxUses:
    async def test_exchange_succeeds_up_to_max_uses(self, client: AsyncClient):
        mission_id, mission_token = await create_and_approve_mission(
            client,
            scope=["read"],
            validation={"type": "on_demand", "max_uses": 3, "valid_until": _future()},
        )

        for _ in range(3):
            resp = await do_token_exchange(client, mission_token=mission_token)
            assert resp.status_code == 200

    async def test_exchange_rejected_after_max_uses(self, client: AsyncClient):
        mission_id, mission_token = await create_and_approve_mission(
            client,
            scope=["read"],
            validation={"type": "on_demand", "max_uses": 2, "valid_until": _future()},
        )

        await do_token_exchange(client, mission_token=mission_token)
        await do_token_exchange(client, mission_token=mission_token)

        # Third exchange must be rejected
        resp = await do_token_exchange(client, mission_token=mission_token)
        assert resp.status_code == 403
        assert "usage limit" in resp.json()["detail"]["error_description"].lower()

    async def test_exchange_with_no_max_uses_limit_succeeds_repeatedly(
        self, client: AsyncClient
    ):
        _, mission_token = await create_and_approve_mission(
            client,
            scope=["read"],
            validation={"type": "on_demand", "valid_until": _future()},
        )

        # No max_uses set — should succeed many times
        for _ in range(5):
            resp = await do_token_exchange(client, mission_token=mission_token)
            assert resp.status_code == 200


class TestOnDemandValidUntil:
    async def test_exchange_rejected_when_valid_until_passed(self, client: AsyncClient):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        mission_id, mission_token = await create_and_approve_mission(
            client,
            scope=["read"],
            # valid_until in the past — exchange should fail immediately
            validation={"type": "on_demand", "max_uses": 10, "valid_until": past},
        )

        resp = await do_token_exchange(client, mission_token=mission_token)
        assert resp.status_code == 403
        # Either the JWT itself has expired, or the valid_until check fires
        desc = resp.json()["detail"]["error_description"].lower()
        assert "expired" in desc or "valid_until" in desc

    async def test_exchange_succeeds_when_within_valid_until(self, client: AsyncClient):
        _, mission_token = await create_and_approve_mission(
            client,
            scope=["read"],
            validation={"type": "on_demand", "max_uses": 5, "valid_until": _future(hours=4)},
        )

        resp = await do_token_exchange(client, mission_token=mission_token)
        assert resp.status_code == 200


class TestScheduledValidation:
    async def test_scheduled_mission_exchange_succeeds(self, client: AsyncClient):
        """Scheduled missions have no max_uses or valid_until checks — just duration."""
        _, mission_token = await create_and_approve_mission(
            client,
            scope=["read"],
            validation={
                "type": "scheduled",
                "schedule": "0 9 * * *",
                "timezone": "UTC",
                "window_minutes": 30,
                "duration_days": 30,
            },
        )

        resp = await do_token_exchange(client, mission_token=mission_token)
        assert resp.status_code == 200


# --- helpers ---

def _future(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
