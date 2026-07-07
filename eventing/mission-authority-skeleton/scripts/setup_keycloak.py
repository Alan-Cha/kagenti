#!/usr/bin/env python3
"""Set up Mission Authority as a Keycloak client.

Reads a YAML config file and uses the Keycloak Admin REST API to create
(or update) the Mission Authority confidential client in the target realm.

Usage:
    python scripts/setup_keycloak.py --config scripts/keycloak_config.yaml
    python scripts/setup_keycloak.py --config scripts/keycloak_config.yaml --dry-run
    python scripts/setup_keycloak.py --config scripts/keycloak_config.yaml \\
        --admin-password $KC_ADMIN_PASSWORD

Output:
    Prints the client secret and ready-to-use env var block for .env / Helm values.
"""

import argparse
import json
import sys
from typing import Optional

import httpx
import yaml


def load_config(path: str, admin_password: Optional[str] = None) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    if admin_password:
        cfg["keycloak"]["admin_password"] = admin_password
    return cfg


def get_admin_token(kc_url: str, realm: str, username: str, password: str) -> str:
    resp = httpx.post(
        f"{kc_url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": username,
            "password": password,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"ERROR: Failed to authenticate as admin: {resp.text}", file=sys.stderr)
        sys.exit(1)
    return resp.json()["access_token"]


def find_client(kc_url: str, realm: str, client_id: str, token: str) -> Optional[dict]:
    resp = httpx.get(
        f"{kc_url}/admin/realms/{realm}/clients",
        params={"clientId": client_id},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    clients = resp.json()
    return clients[0] if clients else None


def create_or_update_client(
    kc_url: str,
    realm: str,
    client_cfg: dict,
    token: str,
    dry_run: bool,
) -> str:
    """Create or update the client. Returns the internal Keycloak client UUID."""
    client_id = client_cfg["client_id"]

    representation = {
        "clientId": client_id,
        "name": client_cfg.get("client_name", client_id),
        "description": client_cfg.get("description", ""),
        "protocol": "openid-connect",
        "publicClient": False,
        "serviceAccountsEnabled": client_cfg.get("service_accounts_enabled", True),
        "standardFlowEnabled": client_cfg.get("standard_flow_enabled", False),
        "directAccessGrantsEnabled": client_cfg.get("direct_access_grants_enabled", False),
        "authorizationServicesEnabled": False,
        "enabled": True,
    }

    existing = find_client(kc_url, realm, client_id, token)

    if dry_run:
        action = "UPDATE" if existing else "CREATE"
        print(f"[dry-run] Would {action} client '{client_id}':")
        print(json.dumps(representation, indent=2))
        return "dry-run-uuid"

    if existing:
        uuid = existing["id"]
        resp = httpx.put(
            f"{kc_url}/admin/realms/{realm}/clients/{uuid}",
            json=representation,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        print(f"Updated client '{client_id}' (id={uuid})")
    else:
        resp = httpx.post(
            f"{kc_url}/admin/realms/{realm}/clients",
            json=representation,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        # Location header contains the new client URL
        location = resp.headers.get("Location", "")
        uuid = location.rstrip("/").split("/")[-1]
        print(f"Created client '{client_id}' (id={uuid})")

    return uuid


def get_client_secret(kc_url: str, realm: str, uuid: str, token: str) -> str:
    resp = httpx.get(
        f"{kc_url}/admin/realms/{realm}/clients/{uuid}/client-secret",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["value"]


def add_protocol_mappers(
    kc_url: str,
    realm: str,
    uuid: str,
    mappers: list,
    token: str,
    dry_run: bool,
):
    for mapper in mappers:
        representation = {
            "name": mapper["name"],
            "protocol": mapper.get("protocol", "openid-connect"),
            "protocolMapper": mapper["protocolMapper"],
            "consentRequired": False,
            "config": mapper.get("config", {}),
        }

        if dry_run:
            print(f"[dry-run] Would add protocol mapper '{mapper['name']}':")
            print(json.dumps(representation, indent=2))
            continue

        resp = httpx.post(
            f"{kc_url}/admin/realms/{realm}/clients/{uuid}/protocol-mappers/models",
            json=representation,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 409:
            print(f"  Protocol mapper '{mapper['name']}' already exists, skipping")
        else:
            resp.raise_for_status()
            print(f"  Added protocol mapper '{mapper['name']}'")


def print_env_block(realm: str, kc_url: str, client_id: str, secret: str):
    print("\n" + "=" * 60)
    print("Add these to your .env or Helm values:")
    print("=" * 60)
    print(f"MISSION_AUTHORITY_KEYCLOAK_ENABLED=true")
    print(f"MISSION_AUTHORITY_KEYCLOAK_URL={kc_url}")
    print(f"MISSION_AUTHORITY_KEYCLOAK_REALM={realm}")
    print(f"MISSION_AUTHORITY_KEYCLOAK_CLIENT_ID={client_id}")
    print(f"MISSION_AUTHORITY_KEYCLOAK_CLIENT_SECRET={secret}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Set up Mission Authority in Keycloak")
    parser.add_argument("--config", required=True, help="Path to keycloak_config.yaml")
    parser.add_argument("--admin-password", help="Override admin password from config")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done, make no changes")
    args = parser.parse_args()

    cfg = load_config(args.config, args.admin_password)
    kc = cfg["keycloak"]
    ma = cfg["mission_authority"]

    kc_url = kc["url"].rstrip("/")
    realm = kc["realm"]

    print(f"Keycloak: {kc_url}  realm: {realm}")
    if args.dry_run:
        print("[dry-run mode — no changes will be made]\n")

    # Authenticate
    admin_token = get_admin_token(kc_url, realm, kc["admin_username"], kc["admin_password"])
    print("Authenticated as admin")

    # Create/update client
    uuid = create_or_update_client(kc_url, realm, ma, admin_token, args.dry_run)

    # Add protocol mappers if configured
    mappers = ma.get("protocol_mappers", [])
    if mappers:
        add_protocol_mappers(kc_url, realm, uuid, mappers, admin_token, args.dry_run)

    # Fetch and print client secret
    if args.dry_run:
        print("\n[dry-run] Would retrieve client secret")
        return

    secret = get_client_secret(kc_url, realm, uuid, admin_token)
    print_env_block(realm, kc_url, ma["client_id"], secret)


if __name__ == "__main__":
    main()
