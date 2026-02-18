"""
keycloak_federated_client.py

Provision Keycloak for SPIFFE Federated Client Authentication:

- Ensures the target realm exists.
- Creates a SPIFFE Identity Provider (not OIDC!) pointing to SPIRE.
- Registers a client configured with the "federated-jwt" authenticator,
  mapping the SPIFFE ID as the federated subject.

This script is idempotent.

IMPORTANT:
- Uses SPIFFE provider type (providerId="spiffe"), not OIDC
- Requires Keycloak 26+ with preview features enabled
- Keycloak must be started with: --features=client-auth-federated:v1,spiffe:v1

Known Issue:
- As of Keycloak 26.5.2, authentication still fails with "Client authentication did not complete"
- This appears to be an issuer format mismatch between SPIRE (HTTP URL) and Keycloak expectations
"""

from keycloak import KeycloakAdmin, KeycloakPostError, KeycloakGetError
from typing import Any
import sys

KEYCLOAK_URL = "http://keycloak.localtest.me:8080"
KEYCLOAK_REALM = "demo"
KEYCLOAK_ADMIN_USERNAME = "admin"
KEYCLOAK_ADMIN_PASSWORD = "admin"

# SPIFFE Trust Domain (matches SPIRE configuration)
SPIFFE_TRUST_DOMAIN = "spiffe://localtest.me"

# SPIFFE Bundle Endpoint - JWKS URL for validating JWT-SVIDs
# Must be accessible from inside the Kubernetes cluster
SPIFFE_BUNDLE_ENDPOINT = "http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys"

IDP_ALIAS = "spire-spiffe"

# SPIFFE ID for the agent pod
AGENT_SPIFFE_ID = "spiffe://localtest.me/ns/authbridge/sa/agent"

CLIENT_NAME = "federated-agent-a"


def get_or_create_realm(keycloak_admin: KeycloakAdmin, realm_name: str) -> None:
    """Create realm if it doesn't exist."""
    try:
        realms = keycloak_admin.get_realms()
        if any(r["realm"] == realm_name for r in realms):
            print(f"Realm '{realm_name}' already exists.")
            return
    except Exception as e:
        print(f"Warning: could not list realms: {e}. Attempting create anyway.")

    try:
        keycloak_admin.create_realm(payload={"realm": realm_name, "enabled": True})
        print(f"Created realm '{realm_name}'.")
    except KeycloakPostError as e:
        if e.response_code == 409:
            print(f"Realm '{realm_name}' already exists (409).")
            return
        raise


def ensure_spiffe_idp(kc: KeycloakAdmin, alias: str, trust_domain: str, bundle_endpoint: str) -> None:
    """
    Create or update a SPIFFE Identity Provider. Idempotent.

    IMPORTANT: Uses providerId="spiffe", NOT "oidc"!
    This is critical for SPIFFE JWT-SVID authentication.

    Args:
        kc: KeycloakAdmin instance
        alias: Identity Provider alias (e.g., "spire-spiffe")
        trust_domain: SPIFFE trust domain (e.g., "spiffe://localtest.me")
        bundle_endpoint: URL to SPIFFE bundle/JWKS endpoint
    """
    idp_payload = {
        "alias": alias,
        "providerId": "spiffe",  # Must be "spiffe", not "oidc"!
        "enabled": True,
        "config": {
            "trustDomain": trust_domain,  # Must be in spiffe:// format
            "bundleEndpoint": bundle_endpoint,  # Key field for SPIFFE provider
            "validateSignature": "true",
        },
    }

    try:
        idps = kc.get_idps()
        existing_idp = next((p for p in idps if p.get("alias") == alias), None)

        if existing_idp:
            # Check if configuration needs updating
            existing_trust_domain = existing_idp.get("config", {}).get("trustDomain")
            existing_bundle_endpoint = existing_idp.get("config", {}).get("bundleEndpoint")

            if (existing_trust_domain == trust_domain and
                existing_bundle_endpoint == bundle_endpoint):
                print(f'SPIFFE Identity Provider "{alias}" already exists with correct configuration.')
                return
            else:
                print(f'Updating SPIFFE Identity Provider "{alias}":')
                if existing_trust_domain != trust_domain:
                    print(f'  Trust Domain - Old: {existing_trust_domain}')
                    print(f'                 New: {trust_domain}')
                if existing_bundle_endpoint != bundle_endpoint:
                    print(f'  Bundle Endpoint - Old: {existing_bundle_endpoint}')
                    print(f'                    New: {bundle_endpoint}')
                kc.update_idp(alias, idp_payload)
                print(f'SPIFFE Identity Provider "{alias}" updated.')
                return
    except KeycloakGetError as e:
        print(f"Warning: could not list IdPs: {e}. Attempting to create.")

    try:
        kc.create_idp(idp_payload)
        print(f'Created SPIFFE Identity Provider "{alias}" with trust domain "{trust_domain}".')
    except KeycloakPostError as e:
        if e.response_code == 409:
            print(f'Identity Provider "{alias}" already exists (409).')
            # Try to update it
            try:
                kc.update_idp(alias, idp_payload)
                print(f'Updated SPIFFE Identity Provider "{alias}".')
            except Exception as update_err:
                print(f'Could not update IdP: {update_err}')
            return
        raise


def register_federated_client(
    kc: KeycloakAdmin,
    client_id: str,
    client_name: str,
    idp_alias: str,
    federated_subject: str,
) -> str:
    """
    Ensure a Keycloak client exists with Signed JWT - Federated authentication.

    If the client doesn't exist, creates it with the federated authenticator
    configured. If it already exists, updates it to ensure the federated
    settings are applied.

    Returns the internal client UUID.
    """
    client_payload: dict[str, Any] = {
        "name": client_name,
        "clientId": client_id,
        "protocol": "openid-connect",
        "publicClient": False,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "fullScopeAllowed": False,
        "clientAuthenticatorType": "federated-jwt",
        "attributes": {
            "jwt.credential.issuer": idp_alias,
            "jwt.credential.sub": federated_subject,
        },
    }

    internal_id = kc.get_client_id(client_id)
    if internal_id:
        print(f'Client "{client_id}" already exists (ID: {internal_id}), updating federated auth settings.')
        kc.update_client(internal_id, client_payload)
        print(f'Client "{client_id}" updated to Signed JWT - Federated.')
        return internal_id

    try:
        internal_id = kc.create_client(client_payload)
        print(f'Created client "{client_id}" (ID: {internal_id}) with Signed JWT - Federated.')
        return internal_id
    except KeycloakPostError as e:
        print(f'Could not create client "{client_id}": {e}')
        raise


def main() -> int:
    print("=" * 60)
    print("SPIFFE Federated Client Auth - Keycloak Setup")
    print("=" * 60)
    print(f"\nKeycloak:           {KEYCLOAK_URL}")
    print(f"Realm:              {KEYCLOAK_REALM}")
    print(f"Trust Domain:       {SPIFFE_TRUST_DOMAIN}")
    print(f"Bundle Endpoint:    {SPIFFE_BUNDLE_ENDPOINT}")
    print(f"IdP Alias:          {IDP_ALIAS}")
    print(f"IdP Type:           spiffe (NOT oidc)")
    print(f"Client:             {CLIENT_NAME}")
    print(f"Federated Subject:  {AGENT_SPIFFE_ID}")

    # Connect to master realm
    print(f"\nConnecting to Keycloak...")
    try:
        master_admin = KeycloakAdmin(
            server_url=KEYCLOAK_URL,
            username=KEYCLOAK_ADMIN_USERNAME,
            password=KEYCLOAK_ADMIN_PASSWORD,
            realm_name="master",
            user_realm_name="master",
        )
    except Exception as e:
        print(f"Failed to connect to Keycloak: {e}")
        print("\nMake sure Keycloak is running and accessible at:")
        print(f"  {KEYCLOAK_URL}")
        print("\nIf running in Kubernetes, you may need port-forwarding:")
        print(f"  kubectl port-forward svc/keycloak-service -n keycloak 8080:8080")
        return 1

    # Create realm
    print(f"\n--- Realm ---")
    get_or_create_realm(master_admin, KEYCLOAK_REALM)

    # Switch to target realm
    kc = KeycloakAdmin(
        server_url=KEYCLOAK_URL,
        username=KEYCLOAK_ADMIN_USERNAME,
        password=KEYCLOAK_ADMIN_PASSWORD,
        realm_name=KEYCLOAK_REALM,
        user_realm_name="master",
    )

    # Create SPIFFE Identity Provider (NOT OIDC!)
    print(f"\n--- SPIFFE Identity Provider ---")
    ensure_spiffe_idp(
        kc,
        alias=IDP_ALIAS,
        trust_domain=SPIFFE_TRUST_DOMAIN,
        bundle_endpoint=SPIFFE_BUNDLE_ENDPOINT
    )

    # Register client with federated auth configured
    print(f"\n--- Client ---")
    try:
        register_federated_client(
            kc,
            client_id=CLIENT_NAME,
            client_name=CLIENT_NAME,
            idp_alias=IDP_ALIAS,
            federated_subject=AGENT_SPIFFE_ID,
        )
    except Exception as e:
        print(f"[FATAL] Could not register client: {e}")
        return 1

    # Print runtime instructions
    realm_issuer = f"{KEYCLOAK_URL.rstrip('/')}/realms/{KEYCLOAK_REALM}"
    print(f"\n{'=' * 60}")
    print("Setup complete. Runtime usage:")
    print(f"{'=' * 60}")
    print(f"\nThe client '{CLIENT_NAME}' is configured with:")
    print(f"  clientAuthenticatorType:  federated-jwt")
    print(f"  jwt.credential.issuer:   {IDP_ALIAS}")
    print(f"  jwt.credential.sub:      {AGENT_SPIFFE_ID}")
    print(f"\nTo authenticate, the workload sends its JWT-SVID as a client_assertion:")
    print(f"  POST {realm_issuer}/protocol/openid-connect/token")
    print(f"    grant_type=client_credentials")
    print(f"    client_id={CLIENT_NAME}")
    print(f"    client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer")
    print(f"    client_assertion=<JWT-SVID>")

    return 0


if __name__ == "__main__":
    sys.exit(main())
