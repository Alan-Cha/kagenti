#!/usr/bin/env python3
import requests, sys, json

KC_BASE = "http://keycloak.localtest.me:8080"
ADMIN_USER = "admin"
ADMIN_PWD  = "admin"
REALM      = "demo"

# SPIRE OIDC DP issuer (cluster-local HTTP per our OIDC DP config)
SPIRE_ISSUER = "http://spire-oidc.spire.svc.cluster.local"

def token():
    data = {
        "client_id": "admin-cli",
        "username": ADMIN_USER,
        "password": ADMIN_PWD,
        "grant_type": "password",
    }
    r = requests.post(
        f"{KC_BASE}/realms/master/protocol/openid-connect/token",
        data=data, timeout=30
    )
    r.raise_for_status()
    return r.json()["access_token"]

def create_realm(at):
    # Idempotent: ignore if exists
    realms = requests.get(f"{KC_BASE}/admin/realms", headers={"Authorization": f"Bearer {at}"}, timeout=30).json()
    if any(r.get("realm")==REALM for r in realms):
        return
    body = {"realm": REALM, "enabled": True}
    r = requests.post(f"{KC_BASE}/admin/realms",
                      headers={"Authorization": f"Bearer {at}", "Content-Type":"application/json"},
                      data=json.dumps(body), timeout=30)
    if r.status_code not in (201, 409):
        r.raise_for_status()

def add_spire_oidc_idp(at):
    # Adds an OIDC Identity Provider using SPIRE issuer discovery
    body = {
        "alias": "spire-oidc",
        "providerId": "oidc",
        "enabled": True,
        "config": {
            "issuer": SPIRE_ISSUER,     # Keycloak will auto-discover JWKS via /.well-known
            "useJwksUrl": "true",
            "validateSignature": "true"
        }
    }
    r = requests.post(f"{KC_BASE}/admin/realms/{REALM}/identity-provider/instances",
                      headers={"Authorization": f"Bearer {at}", "Content-Type":"application/json"},
                      data=json.dumps(body), timeout=30)
    if r.status_code not in (201, 409):
        r.raise_for_status()

def create_client(at):
    body = {
        "clientId": "agent-a",
        "protocol": "openid-connect",
        "publicClient": False,
        "serviceAccountsEnabled": True,
        # We'll switch this client to "Federated client auth" in the UI to map external subject
    }
    r = requests.post(f"{KC_BASE}/admin/realms/{REALM}/clients",
                      headers={"Authorization": f"Bearer {at}", "Content-Type":"application/json"},
                      data=json.dumps(body), timeout=30)
    if r.status_code not in (201, 409):
        r.raise_for_status()

if __name__ == "__main__":
    at = token()
    create_realm(at)
    add_spire_oidc_idp(at)
    create_client(at)
    print("\nCreated realm 'demo', IdP 'spire-oidc', and client 'agent-a'.")
    print("Now, in the Admin Console:")
    print("  • Go to demo → Clients → agent-a → Credentials (or 'Federated client authentication').")
    print("  • Enable Federated client authentication, pick IdP = 'spire-oidc'.")
    print("  • Set External subject to your SPIFFE ID (e.g., spiffe://example.org/ns/default/sa/default).")
    print("Save changes.")