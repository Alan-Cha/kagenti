"""Shared test fixtures.

Uses SQLite (in-memory) for the database and fakeredis for the token registry,
so the test suite runs without any external infrastructure.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from mission_authority.main import app
from mission_authority.database import Base, get_db
from mission_authority.auth.keycloak import require_agent_token, require_user_token, TokenClaims

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_engine):
    """HTTP test client with SQLite DB. No external infrastructure required."""
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    stub_agent = TokenClaims(sub="test-agent", preferred_username="test-agent",
                             email=None, client_id="test-agent", roles=[], raw={})
    stub_user = TokenClaims(sub="test-user", preferred_username="operator@example.com",
                            email="operator@example.com", client_id=None, roles=["mission-approver"], raw={})

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_agent_token] = lambda: stub_agent
    app.dependency_overrides[require_user_token] = lambda: stub_user

    # Ensure the RSA keypair is initialised before tests run
    from mission_authority.services.token_service import get_private_key
    get_private_key()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# --- Mission factory helpers ---

def on_demand_validation(max_uses=5, valid_until_offset_hours=2):
    """Build an on_demand validation policy dict."""
    from datetime import datetime, timedelta, timezone
    valid_until = (
        datetime.now(timezone.utc) + timedelta(hours=valid_until_offset_hours)
    ).isoformat()
    policy = {"type": "on_demand", "max_uses": max_uses, "valid_until": valid_until}
    return policy


def scheduled_validation(duration_days=30):
    """Build a scheduled validation policy dict."""
    return {
        "type": "scheduled",
        "schedule": "0 9 * * *",
        "timezone": "UTC",
        "window_minutes": 30,
        "duration_days": duration_days,
    }


async def create_and_approve_mission(
    client: AsyncClient,
    *,
    agent_id: str = "test-agent",
    scope: list = None,
    validation: dict = None,
    task: str = "Test task for the agent",
):
    """Helper: create a mission and immediately approve it. Returns (mission_id, mission_token)."""
    if scope is None:
        scope = ["wiki_read", "wiki_write"]
    if validation is None:
        validation = on_demand_validation()

    resp = await client.post(
        "/api/v1/missions",
        json={
            "task": task,
            "agent_id": agent_id,
            "scope": scope,
            "validation": validation,
        },
    )
    assert resp.status_code == 201, resp.text
    mission_id = resp.json()["mission_id"]

    approve_resp = await client.post(
        f"/api/v1/missions/{mission_id}/approve",
        json={},
    )
    assert approve_resp.status_code == 200, approve_resp.text
    mission_token = approve_resp.json()["mission_token"]

    return mission_id, mission_token


TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
TOKEN_TYPE_JWT = "urn:ietf:params:oauth:token-type:jwt"


async def do_token_exchange(
    client: AsyncClient,
    *,
    mission_token: str,
    resource: str = "wiki.team1.svc.cluster.local",
    scope: str = None,
):
    """Helper: perform a token exchange request."""
    data = {
        "grant_type": TOKEN_EXCHANGE_GRANT,
        "subject_token": mission_token,
        "subject_token_type": TOKEN_TYPE_JWT,
        "resource": resource,
    }
    if scope:
        data["scope"] = scope
    return await client.post("/api/v1/token-exchange", data=data)
