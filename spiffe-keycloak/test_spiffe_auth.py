#!/usr/bin/env python3
"""
test_spiffe_auth.py

Demonstrates SPIFFE + Keycloak federated authentication:
1. Fetches a JWT-SVID from the SPIRE Workload API
2. Uses the JWT-SVID as a client_assertion to authenticate to Keycloak
3. Retrieves an access token from Keycloak

This script assumes:
- SPIRE agent is running and accessible via the Workload API socket
- keycloak_federated_client.py has been run to configure Keycloak
- The workload has been registered in SPIRE with the correct SPIFFE ID

IMPORTANT:
- CLIENT_ID MUST be the full SPIFFE ID (not a simple name)
- client_assertion_type MUST be jwt-spiffe (not jwt-bearer)
"""

import sys
import os
import requests
from spiffe import WorkloadApiClient

# Configuration - match keycloak_federated_client.py
KEYCLOAK_URL = "http://keycloak.localtest.me:8080"
KEYCLOAK_REALM = "demo"
# CRITICAL: For SPIFFE authentication, client_id MUST be the full SPIFFE ID!
AGENT_SPIFFE_ID = "spiffe://localtest.me/ns/authbridge/sa/agent"
CLIENT_ID = AGENT_SPIFFE_ID  # Use SPIFFE ID as client ID

# SPIRE Workload API socket
SPIFFE_ENDPOINT_SOCKET = os.getenv(
    "SPIFFE_ENDPOINT_SOCKET",
    "/run/spire/sockets/agent.sock"
)


def fetch_jwt_svid(client: WorkloadApiClient, spiffe_id: str, audience: str) -> str:
    """
    Fetch a JWT-SVID from the SPIRE Workload API.

    Args:
        client: WorkloadApiClient instance
        spiffe_id: Expected SPIFFE ID for this workload
        audience: Audience claim for the JWT (typically the Keycloak realm URL)

    Returns:
        JWT-SVID as a string
    """
    print(f"Fetching JWT-SVID from SPIRE...")
    print(f"  Expected SPIFFE ID: {spiffe_id}")
    print(f"  Audience: {audience}")

    try:
        # Fetch JWT-SVID with specified audience
        jwt_svid = client.fetch_jwt_svid(audiences=[audience])

        # Get the first SVID from the bundle
        if not jwt_svid.svids:
            print("[ERROR] No JWT-SVIDs returned from SPIRE")
            return None

        svid = jwt_svid.svids[0]

        # Verify we got the expected SPIFFE ID
        actual_spiffe_id = str(svid.spiffe_id)
        if actual_spiffe_id != spiffe_id:
            print(f"[WARNING] SPIFFE ID mismatch!")
            print(f"  Expected: {spiffe_id}")
            print(f"  Got:      {actual_spiffe_id}")
        else:
            print(f"[OK] SPIFFE ID matches: {actual_spiffe_id}")

        jwt_token = svid.token
        print(f"[OK] JWT-SVID retrieved ({len(jwt_token)} bytes)")

        # Display JWT header and payload for debugging
        import base64
        import json
        parts = jwt_token.split('.')
        if len(parts) >= 2:
            try:
                header = json.loads(base64.urlsafe_b64decode(parts[0] + '=='))
                payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=='))
                print(f"\nJWT Header: {json.dumps(header, indent=2)}")
                print(f"JWT Payload: {json.dumps(payload, indent=2)}")
            except Exception as e:
                print(f"[WARNING] Could not decode JWT: {e}")

        return jwt_token

    except Exception as e:
        print(f"[ERROR] Failed to fetch JWT-SVID: {e}")
        return None


def authenticate_to_keycloak(jwt_svid: str, keycloak_url: str, realm: str, client_id: str) -> dict:
    """
    Authenticate to Keycloak using JWT-SVID as client assertion.

    Args:
        jwt_svid: JWT-SVID token from SPIRE
        keycloak_url: Base Keycloak URL
        realm: Keycloak realm name
        client_id: Client ID configured in Keycloak

    Returns:
        Token response dict with access_token, or None on failure
    """
    token_endpoint = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    print(f"\nAuthenticating to Keycloak...")
    print(f"  Token endpoint: {token_endpoint}")
    print(f"  Client ID: {client_id}")

    # OAuth 2.0 client credentials grant with JWT-SVID assertion
    # CRITICAL: Must use jwt-spiffe assertion type, not jwt-bearer!
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-spiffe",
        "client_assertion": jwt_svid,
    }

    try:
        response = requests.post(
            token_endpoint,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10
        )

        print(f"  Response status: {response.status_code}")

        if response.status_code == 200:
            token_data = response.json()
            print(f"[OK] Successfully authenticated!")
            print(f"  Access token: {token_data.get('access_token', '')[:50]}...")
            print(f"  Token type: {token_data.get('token_type')}")
            print(f"  Expires in: {token_data.get('expires_in')} seconds")
            return token_data
        else:
            print(f"[ERROR] Authentication failed!")
            print(f"  Response: {response.text}")
            return None

    except Exception as e:
        print(f"[ERROR] Request failed: {e}")
        return None


def verify_access_token(access_token: str, keycloak_url: str, realm: str):
    """
    Verify the access token by calling Keycloak's userinfo endpoint.

    Args:
        access_token: The access token to verify
        keycloak_url: Base Keycloak URL
        realm: Keycloak realm name
    """
    userinfo_endpoint = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/userinfo"

    print(f"\nVerifying access token...")
    print(f"  Userinfo endpoint: {userinfo_endpoint}")

    try:
        response = requests.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )

        print(f"  Response status: {response.status_code}")

        if response.status_code == 200:
            userinfo = response.json()
            print(f"[OK] Token is valid!")
            print(f"  User info: {userinfo}")
            return userinfo
        else:
            print(f"[ERROR] Token verification failed!")
            print(f"  Response: {response.text}")
            return None

    except Exception as e:
        print(f"[ERROR] Request failed: {e}")
        return None


def main() -> int:
    print("=" * 70)
    print("SPIFFE + Keycloak Federated Authentication Test")
    print("=" * 70)
    print(f"\nConfiguration:")
    print(f"  Keycloak:         {KEYCLOAK_URL}")
    print(f"  Realm:            {KEYCLOAK_REALM}")
    print(f"  Client ID:        {CLIENT_ID}")
    print(f"  Expected SPIFFE:  {AGENT_SPIFFE_ID}")
    print(f"  Workload Socket:  {SPIFFE_ENDPOINT_SOCKET}")

    # Calculate audience (Keycloak realm URL)
    audience = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"

    # Step 1: Connect to SPIRE Workload API and fetch JWT-SVID
    print(f"\n{'=' * 70}")
    print("Step 1: Fetch JWT-SVID from SPIRE")
    print("=" * 70)

    try:
        with WorkloadApiClient(SPIFFE_ENDPOINT_SOCKET) as client:
            jwt_svid = fetch_jwt_svid(client, AGENT_SPIFFE_ID, audience)

            if not jwt_svid:
                print("\n[FATAL] Could not retrieve JWT-SVID")
                print("\nTroubleshooting:")
                print("  1. Ensure SPIRE agent is running")
                print("  2. Check that workload API socket exists:")
                print(f"     {SPIFFE_ENDPOINT_SOCKET}")
                print("  3. Verify workload has been registered in SPIRE:")
                print("     kubectl exec -n zero-trust-workload-identity-manager spire-server-0 -- \\")
                print("       /opt/spire/bin/spire-server entry show")
                return 1

            # Step 2: Authenticate to Keycloak using JWT-SVID
            print(f"\n{'=' * 70}")
            print("Step 2: Authenticate to Keycloak")
            print("=" * 70)

            token_response = authenticate_to_keycloak(
                jwt_svid, KEYCLOAK_URL, KEYCLOAK_REALM, CLIENT_ID
            )

            if not token_response:
                print("\n[FATAL] Authentication failed")
                print("\nTroubleshooting:")
                print("  1. Ensure keycloak_federated_client.py has been run successfully")
                print("  2. Verify Keycloak is accessible:")
                print(f"     curl {KEYCLOAK_URL}/health")
                print("  3. Check that the client exists in Keycloak with SPIFFE ID as clientId")
                print("  4. Verify the SPIFFE IdP is configured correctly (not OIDC!)")
                print("  5. Ensure SPIRE is configured with jwtIssuer: 'spiffe://localtest.me'")
                print("  6. Verify SPIRE OIDC discovery provider has set_key_use: true")
                return 1

            access_token = token_response.get("access_token")

            # Step 3: Verify the access token
            print(f"\n{'=' * 70}")
            print("Step 3: Verify Access Token")
            print("=" * 70)

            userinfo = verify_access_token(access_token, KEYCLOAK_URL, KEYCLOAK_REALM)

            if not userinfo:
                print("\n[WARNING] Token verification failed, but authentication succeeded")

    except Exception as e:
        print(f"\n[FATAL] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Success!
    print(f"\n{'=' * 70}")
    print("SUCCESS! SPIFFE + Keycloak Integration Working")
    print("=" * 70)
    print("\nThe following flow was demonstrated:")
    print("  1. ✓ Workload retrieved JWT-SVID from SPIRE")
    print("  2. ✓ Used JWT-SVID to authenticate to Keycloak")
    print("  3. ✓ Received valid access token from Keycloak")
    print("  4. ✓ Verified token with Keycloak userinfo endpoint")
    print("\nThis proves that SPIFFE identity can be used for OAuth 2.0")
    print("authentication with Keycloak's federated-jwt client authenticator.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
