"""
setup3.py

Provision Keycloak for SPIFFE Federated Client Authentication:

- Ensures the target realm exists.
- Ensures an OIDC Identity Provider pointing to the SPIRE OIDC Discovery Provider exists.
- Registers (or reuses) a client configured with the "federated-jwt" authenticator,
  mapping the SPIFFE ID as the federated subject.

This script is idempotent.

NOTE: Federated client auth is a preview feature in Keycloak 26.5.2.
Keycloak must be started with:  --features=preview  (or --features=federated-client-auth)
"""

from keycloak import KeycloakAdmin, KeycloakPostError, KeycloakGetError
from typing import Any
import sys

KEYCLOAK_URL = "http://keycloak.localtest.me:8080"
KEYCLOAK_REALM = "demo"
KEYCLOAK_ADMIN_USERNAME = "admin"
KEYCLOAK_ADMIN_PASSWORD = "admin"

# SPIRE OIDC Discovery Provider issuer (cluster-local)
SPIRE_ISSUER = "http://spire-oidc.spire.svc.cluster.local"
IDP_ALIAS = "spire-oidc"

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


def ensure_oidc_idp(kc: KeycloakAdmin, alias: str, issuer: str) -> None:
    """
    Create (or verify) an OIDC Identity Provider pointing at the
    SPIRE OIDC Discovery Provider. Idempotent.
    """
    try:
        idps = kc.get_idps()
        if any(p.get("alias") == alias for p in idps):
            print(f'Identity Provider "{alias}" already exists.')
            return
    except KeycloakGetError as e:
        print(f"Warning: could not list IdPs: {e}. Attempting to create.")

    idp_payload = {
        "alias": alias,
        "providerId": "oidc",
        "enabled": True,
        "config": {
            "issuer": issuer,
            "useJwksUrl": "true",
            "jwksUrl": issuer.replace("http://", "https://") + "/keys",
            "validateSignature": "true",
        },
    }

    try:
        kc.create_idp(idp_payload)
        print(f'Created OIDC Identity Provider "{alias}" with issuer "{issuer}".')
    except KeycloakPostError as e:
        if e.response_code == 409:
            print(f'Identity Provider "{alias}" already exists (409).')
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
    print(f"\nKeycloak:          {KEYCLOAK_URL}")
    print(f"Realm:             {KEYCLOAK_REALM}")
    print(f"SPIRE Issuer:      {SPIRE_ISSUER}")
    print(f"IdP Alias:         {IDP_ALIAS}")
    print(f"Client:            {CLIENT_NAME}")
    print(f"Federated Subject: {AGENT_SPIFFE_ID}")

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

    # Create SPIRE OIDC Identity Provider
    print(f"\n--- Identity Provider ---")
    ensure_oidc_idp(kc, alias=IDP_ALIAS, issuer=SPIRE_ISSUER)

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
