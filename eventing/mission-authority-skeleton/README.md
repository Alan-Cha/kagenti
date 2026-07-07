# Mission Authority

**Status**: MVP  
**Version**: 0.1.0  
**Role**: Policy Administration Point (PAP) — manages human approval of agent missions

Mission Authority is a FastAPI service that implements a human-in-the-loop approval workflow for AI agents. Before an agent can act, a human approves a mission (task + scopes). The resulting mission token can be exchanged for short-lived service access tokens via RFC 8693.

See [design docs](../docs/design/) for architecture context, ADRs, and the PAP/PDP/PEP/PIP breakdown.

---

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- uv

### With Docker Compose (recommended)

```bash
# Start PostgreSQL and the service
docker compose up

# Service is available at http://localhost:8000
# API docs at http://localhost:8000/docs
```

### Without Docker

```bash
# Install dependencies
uv sync --extra dev

# Create the database
createdb missions

# Start the service (creates tables automatically on first run)
MISSION_AUTHORITY_DATABASE_URL=postgresql+asyncpg://localhost/missions \
  uv run uvicorn mission_authority.main:app --reload
```

---

## Keycloak Setup

When `MISSION_AUTHORITY_KEYCLOAK_ENABLED=false` (the default), the service runs in standalone mode — all endpoints work without authentication and use stub identities. This is suitable for demos and local development.

To connect to a live Keycloak instance:

```bash
# Create the Mission Authority client in Keycloak
python scripts/setup_keycloak.py --config scripts/keycloak_config.yaml

# Set the output env vars, then start with Keycloak enabled
MISSION_AUTHORITY_KEYCLOAK_ENABLED=true \
MISSION_AUTHORITY_KEYCLOAK_URL=http://keycloak.keycloak.svc.cluster.local:8080 \
MISSION_AUTHORITY_KEYCLOAK_CLIENT_ID=mission-authority \
MISSION_AUTHORITY_KEYCLOAK_CLIENT_SECRET=<from setup script> \
  uv run uvicorn mission_authority.main:app
```

When Keycloak is enabled:
- `POST /missions` requires a Bearer token from the agent (Keycloak service account)
- `POST /missions/{id}/approve` and `/cancel` require a Bearer token from a human user
- Identity is derived from the verified token — not from request body fields

---

## API

### Create a mission

```bash
curl -X POST http://localhost:8000/api/v1/missions \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Research AI safety and update wiki",
    "agent_id": "research-agent",
    "scope": ["wiki_read", "wiki_write", "web_search"],
    "validation": {
      "type": "on_demand",
      "max_uses": 5,
      "valid_until": "2026-12-31T23:59:59Z"
    }
  }'
```

```json
{
  "mission_id": "M-20260701-abc12345",
  "status": "pending",
  "created_at": "2026-07-01T10:00:00Z",
  "expires_at": "2026-12-31T23:59:59Z",
  "approval_url": "/missions/M-20260701-abc12345/approve"
}
```

### Approve a mission

```bash
curl -X POST http://localhost:8000/api/v1/missions/M-20260701-abc12345/approve \
  -H "Content-Type: application/json" \
  -d '{}'
```

```json
{
  "mission_id": "M-20260701-abc12345",
  "status": "active",
  "approved_by": "alice@example.com",
  "mission_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

### Exchange mission token for a service access token (RFC 8693)

```bash
curl -X POST http://localhost:8000/api/v1/token-exchange \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
  -d "subject_token=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -d "subject_token_type=urn:ietf:params:oauth:token-type:jwt" \
  -d "resource=wiki.team1.svc.cluster.local" \
  -d "scope=wiki_write"
```

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 900,
  "scope": "wiki_write"
}
```

The token exchange validates:
- JWT signature against Mission Authority's public key (`/.well-known/jwks.json`)
- Mission status is `active` (revocation by cancellation is a DB status check)
- Requested scope is within the mission's approved scopes
- `on_demand` policy: `max_uses` not exceeded, `valid_until` not passed

### Request a scope expansion

```bash
curl -X POST http://localhost:8000/api/v1/missions/M-20260701-abc12345/expand-scope \
  -H "Content-Type: application/json" \
  -d '{
    "requesting_agent": "research-agent",
    "additional_scopes": ["image_optimize"],
    "justification": "Found 3 large diagrams that need compression before upload."
  }'
```

A human then approves or denies via `POST /missions/{id}/expansions/{exp_id}/approve` or `.../deny`.

### Other endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/missions` | List missions (filter by `status`, `agent_id`) |
| GET | `/api/v1/missions/{id}` | Get mission details |
| POST | `/api/v1/missions/{id}/cancel` | Cancel a mission |
| GET | `/.well-known/jwks.json` | Public key for mission token validation |
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe (checks DB) |
| GET | `/metrics` | Prometheus metrics |
| GET | `/docs` | OpenAPI / Swagger UI |

---

## Configuration

All settings use the `MISSION_AUTHORITY_` prefix:

```bash
# Database (required)
MISSION_AUTHORITY_DATABASE_URL=postgresql+asyncpg://user:pass@host/missions

# Token lifetimes
MISSION_AUTHORITY_MISSION_TOKEN_TTL_HOURS=24
MISSION_AUTHORITY_ACCESS_TOKEN_TTL_MINUTES=15

# Mission token signing key (RS256)
# Leave empty to auto-generate an in-memory keypair on startup (dev/demo).
# In production: mount a PEM secret and set this path.
MISSION_AUTHORITY_MISSION_TOKEN_PRIVATE_KEY_PATH=/run/secrets/mission-authority.key

# Keycloak (disabled by default)
MISSION_AUTHORITY_KEYCLOAK_ENABLED=false
MISSION_AUTHORITY_KEYCLOAK_URL=http://keycloak.keycloak.svc.cluster.local:8080
MISSION_AUTHORITY_KEYCLOAK_REALM=kagenti
MISSION_AUTHORITY_KEYCLOAK_CLIENT_ID=mission-authority
MISSION_AUTHORITY_KEYCLOAK_CLIENT_SECRET=<from setup_keycloak.py>
```

---

## Structure

```
mission-authority-skeleton/
├── mission_authority/
│   ├── main.py                 # FastAPI app, lifespan, routes
│   ├── config.py               # Settings (pydantic-settings)
│   ├── database.py             # SQLAlchemy async engine and session
│   ├── auth/
│   │   └── keycloak.py         # JWKS validation, require_agent_token / require_user_token
│   ├── models/
│   │   └── mission.py          # Mission and ScopeExpansion SQLAlchemy models
│   ├── schemas/
│   │   └── mission.py          # Pydantic request/response schemas
│   ├── api/v1/
│   │   ├── missions.py         # Mission CRUD and scope expansion endpoints
│   │   └── token_exchange.py   # RFC 8693 token exchange endpoint
│   └── services/
│       ├── token_service.py    # RS256 token generation and exchange
│       └── keycloak_client.py  # Keycloak client credentials service
├── scripts/
│   ├── setup_keycloak.py       # Creates Mission Authority client in Keycloak
│   └── keycloak_config.yaml    # Configuration template for setup script
├── tests/
│   ├── conftest.py             # SQLite + stub auth fixtures (no infra needed)
│   ├── test_missions.py
│   ├── test_token_exchange.py
│   ├── test_scope_expansion.py
│   └── test_validation.py
├── docker-compose.yml          # PostgreSQL + service
├── Dockerfile
└── pyproject.toml
```

---

## Tests

The test suite runs entirely against SQLite (in-memory) with stubbed auth — no PostgreSQL or Keycloak needed:

```bash
uv run pytest
uv run pytest --cov=mission_authority --cov-report=html
```

---

## Token signing

Mission tokens are signed with an RSA private key (RS256). In dev/standalone mode, a keypair is generated in memory on startup. The corresponding public key is available at `/.well-known/jwks.json` for downstream services to validate tokens.

In production, mount a stable RSA private key and set `MISSION_AUTHORITY_MISSION_TOKEN_PRIVATE_KEY_PATH` — otherwise each restart generates a new keypair, invalidating any previously issued tokens.

**Note on Keycloak-issued mission tokens**: migrating to Keycloak as the token issuer requires a custom User Session Note protocol mapper in Keycloak so that `mission_id` and `scope` can be injected as claims at exchange time. The configuration for this is documented (but commented out) in `scripts/keycloak_config.yaml`.
