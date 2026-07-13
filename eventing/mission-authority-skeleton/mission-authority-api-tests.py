#!/usr/bin/env -S uv run --no-project --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""Mission Authority API tests.

Exercises the README "## API" flow against a running Mission Authority service
(docker compose / docker-compose up). Mirrors the original api_test.sh logic and
output: numbered steps, pretty-printed key fields, PASS/FAIL lines, and a final
result summary. Exit code equals the number of failed checks.

Usage:
    ./mission-authority-api-tests.py
    ./mission-authority-api-tests.py --base http://localhost:8770
    BASE=http://localhost:8770 ./mission-authority-api-tests.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

_pass = 0
_fail = 0


def step(msg: str) -> None:
    print(f"\n### {msg}")


def check(desc: str, ok: bool) -> None:
    global _pass, _fail
    if ok:
        print(f"PASS: {desc}")
        _pass += 1
    else:
        print(f"FAIL: {desc}")
        _fail += 1


def show(obj, keys: list[str] | None = None) -> None:
    """Pretty-print an object, optionally projecting a subset of keys."""
    if keys is not None and isinstance(obj, dict):
        obj = {k: obj.get(k) for k in keys}
    print(json.dumps(obj, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Mission Authority API tests")
    parser.add_argument(
        "--base",
        default=os.environ.get("BASE", "http://localhost:8770"),
        help="Base URL of the running service (default: %(default)s)",
    )
    args = parser.parse_args()
    base = args.base.rstrip("/")

    client = httpx.Client(base_url=base, timeout=15.0)
    print(f"Target: {base}")

    # 1. Create a mission
    step("1. Create a mission (POST /api/v1/missions)")
    create = client.post(
        "/api/v1/missions",
        json={
            "task": "Research AI safety and update wiki",
            "agent_id": "research-agent",
            "scope": ["wiki_read", "wiki_write", "web_search"],
            "validation": {
                "type": "on_demand",
                "max_uses": 5,
                "valid_until": "2026-12-31T23:59:59Z",
            },
        },
    ).json()
    show(create)
    mid = create.get("mission_id", "")
    check(f"mission_id returned ({mid})", bool(mid))
    check("status == pending", create.get("status") == "pending")

    # 2. Get mission details
    step("2. Get mission details (GET /api/v1/missions/{id})")
    detail = client.get(f"/api/v1/missions/{mid}").json()
    show(detail, ["mission_id", "status", "agent_id", "scope"])
    check("detail status == pending", detail.get("status") == "pending")

    # 3. List missions
    step("3. List missions (GET /api/v1/missions?status=pending)")
    listing = client.get("/api/v1/missions", params={"status": "pending"}).json()
    if isinstance(listing, list):
        count = len(listing)
    else:
        count = len(listing.get("missions", []))
    print(f"count(pending)={count}")
    check("list returns >=1 pending mission", count >= 1)

    # 4. Approve the mission
    step("4. Approve the mission (POST /api/v1/missions/{id}/approve)")
    approve = client.post(f"/api/v1/missions/{mid}/approve", json={}).json()
    show(
        {
            "mission_id": approve.get("mission_id"),
            "status": approve.get("status"),
            "approved_by": approve.get("approved_by"),
            "has_token": approve.get("mission_token") is not None,
        }
    )
    mtoken = approve.get("mission_token", "") or ""
    check("status == active", approve.get("status") == "active")
    check("mission_token issued", bool(mtoken))

    # 5. Token exchange (RFC 8693)
    step("5. Token exchange (POST /api/v1/token-exchange, RFC 8693)")
    ex = client.post(
        "/api/v1/token-exchange",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": mtoken,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "resource": "wiki.team1.svc.cluster.local",
            "scope": "wiki_write",
        },
    ).json()
    show(
        {
            "token_type": ex.get("token_type"),
            "expires_in": ex.get("expires_in"),
            "scope": ex.get("scope"),
            "has_access_token": ex.get("access_token") is not None,
        }
    )
    check("access_token issued", bool(ex.get("access_token")))
    check("granted scope == wiki_write", ex.get("scope") == "wiki_write")

    # 6. Out-of-scope exchange should be rejected
    step("6. Token exchange for out-of-scope scope should be rejected")
    exbad = client.post(
        "/api/v1/token-exchange",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": mtoken,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "resource": "wiki.team1.svc.cluster.local",
            "scope": "admin_delete",
        },
    )
    print(f"http_status(out-of-scope)={exbad.status_code}")
    check(f"out-of-scope exchange rejected (status={exbad.status_code})", exbad.status_code != 200)

    # 7. Request a scope expansion
    step("7. Request a scope expansion (POST /api/v1/missions/{id}/expand-scope)")
    exp = client.post(
        f"/api/v1/missions/{mid}/expand-scope",
        json={
            "requesting_agent": "research-agent",
            "additional_scopes": ["image_optimize"],
            "justification": "Found 3 large diagrams that need compression before upload.",
        },
    ).json()
    show(exp)
    expid = exp.get("expansion_id") or exp.get("id") or ""
    check(f"expansion requested (exp_id={expid})", bool(expid))

    # 8. Approve the scope expansion
    step("8. Approve the scope expansion (POST /api/v1/missions/{id}/expansions/{exp_id}/approve)")
    if expid:
        eap = client.post(
            f"/api/v1/missions/{mid}/expansions/{expid}/approve", json={}
        ).json()
        show(eap)
        check("expansion approved", eap.get("status") == "approved")
    else:
        print("SKIP (no expansion id)")
        check("expansion approved", False)

    # 9. JWKS
    step("9. JWKS (GET /.well-known/jwks.json)")
    jwks = client.get("/.well-known/jwks.json").json()
    keys = jwks.get("keys", [])
    first = keys[0] if keys else {}
    show({"keys_count": len(keys), "kty": first.get("kty"), "alg": first.get("alg")})
    check("jwks has >=1 key", len(keys) >= 1)

    # 10. Cancel the mission (API returns "canceled" — American one-L spelling)
    step("10. Cancel the mission (POST /api/v1/missions/{id}/cancel)")
    can = client.post(f"/api/v1/missions/{mid}/cancel", json={}).json()
    show(can, ["mission_id", "status"])
    check('status == "canceled"', can.get("status") == "canceled")

    # 11. Token exchange after cancel should be rejected (revocation check)
    step("11. Token exchange after cancel should be rejected (revocation check)")
    exrev = client.post(
        "/api/v1/token-exchange",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": mtoken,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "resource": "wiki.team1.svc.cluster.local",
            "scope": "wiki_write",
        },
    )
    print(f"http_status(after cancel)={exrev.status_code}")
    check(f"exchange after cancel rejected (status={exrev.status_code})", exrev.status_code != 200)

    # 12. Probes & metrics
    step("12. Probes & metrics")
    for path, label in (
        ("/health/live", "/health/live 200"),
        ("/health/ready", "/health/ready 200"),
        ("/metrics", "/metrics 200"),
    ):
        code = client.get(path).status_code
        check(label, code == 200)

    print("\n" + "=" * 35)
    print(f"RESULT: {_pass} passed, {_fail} failed")
    print("=" * 35)
    return _fail


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.HTTPError as e:
        print(f"\nERROR: request failed: {e}", file=sys.stderr)
        print(f"  Is the service running? Try: curl {os.environ.get('BASE', 'http://localhost:8770')}/health/live", file=sys.stderr)
        sys.exit(2)
