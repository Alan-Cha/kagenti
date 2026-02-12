"""
client_registration.py

Registers a Keycloak client and stores its secret in a file.
Idempotent:
- Creates the client if it does not exist.
- If the client already exists, reuses it.
- Always retrieves and stores the client secret.
"""

import os
from typing import Any
import jwt
from keycloak import KeycloakAdmin, KeycloakPostError


def get_env_var(name: str, default: str | None = None) -> str:
    """
    Fetch an environment variable or return default if provided.
    Raise ValueError if missing and no default is set.
    """
    value = os.environ.get(name)
    if value is not None and value != "":
        return value
    if default is not None:
        return default
    raise ValueError(f"Missing required environment variable: {name}")


def write_client_secret(
    keycloak_admin: KeycloakAdmin,
    internal_client_id: str,
    client_name: str,
    secret_file_path: str = "secret.txt",
) -> None:
    """
    Retrieve the secret for a Keycloak client and write it to a file.
    """
    try:
        # There will be a value field if client authentication is enabled
        # client authentication is enabled if "publicClient" is False
        secret = keycloak_admin.get_client_secrets(internal_client_id)["value"]
        print(f'Successfully retrieved secret for client "{client_name}".')
    except KeycloakPostError as e:
        print(f"Could not retrieve secret for client '{client_name}': {e}")
        return

    try:
        with open(secret_file_path, "w") as f:
            f.write(secret)
        print(f'Secret written to file: "{secret_file_path}"')
    except OSError as ose:
        print(f"Error writing secret to file: {ose}")


# TODO: refactor this function so kagenti-client-registration image can use it
def register_client(keycloak_admin: KeycloakAdmin, client_id: str, client_payload: dict[str, Any]) -> str:
    """
    Ensure a Keycloak client exists.
    Returns the internal client ID.
    """
    internal_client_id = keycloak_admin.get_client_id(client_id)
    if internal_client_id:
        print(f'Client "{client_id}" already exists with ID: {internal_client_id}')
        return internal_client_id

    # Create client
    try:
        internal_client_id = keycloak_admin.create_client(client_payload)

        print(f'Created Keycloak client "{client_id}": {internal_client_id}')
        return internal_client_id
    except KeycloakPostError as e:
        print(f'Could not create client "{client_id}": {e}')
        raise


def get_client_id() -> str:
    """
    Read the SVID JWT from file and extract the client ID from the "sub" claim.
    """
    # Read SVID JWT from file to get client ID
    jwt_file_path = "/opt/jwt_svid.token"
    content = None
    try:
        with open(jwt_file_path, "r") as file:
            content = file.read()

    except FileNotFoundError:
        print(f"Error: The file {jwt_file_path} was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

    if content is None or content.strip() == "":
        raise Exception("No content read from SVID JWT.")

    # Decode JWT to get client ID
    decoded = jwt.decode(content, options={"verify_signature": False})
    if "sub" not in decoded:
        raise Exception('SVID JWT does not contain a "sub" claim.')
    return decoded["sub"]

client_name = get_env_var("CLIENT_NAME")

# If SPIFFE is enabled, use the client ID from the SVID JWT.
# Otherwise, use the client name as the client ID.
if get_env_var("SPIRE_ENABLED", "false").lower() == "true":
    client_id = get_client_id()
else:
    client_id = client_name

try:
    KEYCLOAK_URL = get_env_var("KEYCLOAK_URL")
    KEYCLOAK_TOKEN_EXCHANGE_ENABLED = (
        get_env_var("KEYCLOAK_TOKEN_EXCHANGE_ENABLED", "true").lower() == "true"
    )
    KEYCLOAK_CLIENT_REGISTRATION_ENABLED = (
        get_env_var("KEYCLOAK_CLIENT_REGISTRATION_ENABLED", "true").lower() == "true"
    )
except ValueError as e:
    print(
        f"Expected environment variable missing. Skipping client registration of {client_id}."
    )
    print(e)
    exit(1)

if not KEYCLOAK_CLIENT_REGISTRATION_ENABLED:
    print(
        f"Client registration (KEYCLOAK_CLIENT_REGISTRATION_ENABLED=false) disabled. Skipping registration of {client_id}."
    )
    exit(0)

keycloak_admin = KeycloakAdmin(
    server_url=KEYCLOAK_URL,
    username=get_env_var("KEYCLOAK_ADMIN_USERNAME"),
    password=get_env_var("KEYCLOAK_ADMIN_PASSWORD"),
    realm_name=get_env_var("KEYCLOAK_REALM"),
    user_realm_name="master",
)

internal_client_id = register_client(
    keycloak_admin,
    client_id,
    {
        "name": client_name,
        "clientId": client_id,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": True,
        "serviceAccountsEnabled": True,  # Required for client_credentials grant
        "fullScopeAllowed": False,
        "publicClient": False,  # Enable client authentication
        # Enable token exchange for this client.
        # Token exchange allows this client to exchange tokens for other tokens, potentially across different clients.
        # Use case: [EXPLAIN THE SPECIFIC USE CASE HERE, e.g., "Required for service-to-service authentication in microservices architecture."]
        # Security considerations: Ensure only trusted clients have this capability, restrict scopes and permissions as needed,
        # and audit usage to prevent privilege escalation or unauthorized access.
        "attributes": {
            "standard.token.exchange.enabled": str(
                KEYCLOAK_TOKEN_EXCHANGE_ENABLED
            ).lower(),  # Enable token exchange
        },
    },
)

# try:
#     secret_file_path = get_env_var("SECRET_FILE_PATH")
# except ValueError:
#     secret_file_path = "/shared/secret.txt"
# print(
#     f'Writing secret for client ID: "{client_id}" (internal client ID: "{internal_client_id}") to file: "{secret_file_path}"'
# )
# write_client_secret(
#     keycloak_admin,
#     internal_client_id,
#     client_name,
#     secret_file_path=secret_file_path,
# )

# print("Client registration complete.")




#!/usr/bin/env python3
"""
configure_keycloak.py

Provision Keycloak for SPIFFE / Federated Client Authentication:

- Ensures the target realm exists.
- Ensures an OIDC Identity Provider pointing to the SPIRE OIDC Discovery Provider exists.
- Registers (or reuses) a client, leveraging the helper functions you already wrote.
- Prints a final 1-click instruction to enable Federated Client Authentication for that client
  and map External Subject (the SPIFFE ID = JWT-SVID `sub`).

This script is idempotent.

Environment variables (required):
  KEYCLOAK_URL                  e.g., http://keycloak.keycloak.svc:8080
  KEYCLOAK_ADMIN_USERNAME       e.g., admin
  KEYCLOAK_ADMIN_PASSWORD       e.g., admin
  KEYCLOAK_REALM                e.g., demo          (realm to create/use)
  CLIENT_NAME                   e.g., agent-a       (a friendly label)
  SPIRE_ISSUER                  e.g., http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local

Optional:
  IDP_ALIAS                     default: spire-oidc
  SPIRE_ENABLED                 default: "true" (if true, client_id = JWT-SVID `sub`; else client_id = CLIENT_NAME)
  SECRET_FILE_PATH              where to write client secret if you still need it (legacy/hybrid use)
  KEYCLOAK_TOKEN_EXCHANGE_ENABLED     default: "false" (generally not needed with federated client auth)
  KEYCLOAK_CLIENT_REGISTRATION_ENABLED default: "true"  (disable to no-op)

Notes:
- For Keycloak 26.5.2 you do NOT need any special startup flags for SPIFFE federated client auth.
  Start normally (start or start-dev) and configure at Realm/IdP/Client level. 
- The SPIRE OIDC Discovery Provider must serve OIDC Discovery and JWKS (/.well-known/openid-configuration and /keys),
  which Keycloak will use to validate SPIFFE JWT-SVIDs. 
"""

import sys
from typing import Any
from keycloak import KeycloakAdmin, KeycloakPostError, KeycloakGetError

# # Reuse your helpers
# from client_registration import (
#     get_env_var,
#     register_client,
#     write_client_secret,
#     get_client_id,
# )


def ensure_realm(kc: KeycloakAdmin, realm_name: str) -> None:
    """
    Create the realm if it doesn't exist.
    Uses the master realm privileges (kc.realm_name should be 'master').
    """
    try:
        realms = kc.get_realms()  # list of realm reps
        if any(r.get("realm") == realm_name for r in realms):
            print(f'Realm "{realm_name}" already exists.')
            return
    except Exception as e:
        print(f"Warning: could not list realms via get_realms(): {e}. Attempting create anyway.")

    try:
        kc.create_realm(payload={"realm": realm_name, "enabled": True})
        print(f'Created realm "{realm_name}".')
    except KeycloakPostError as e:
        if e.response_code == 409:
            print(f'Realm "{realm_name}" already exists (409).')
            return
        print(f'Could not create realm "{realm_name}": {e}')
        raise


def ensure_oidc_idp(kc: KeycloakAdmin, alias: str, issuer: str) -> None:
    """
    Create (or verify) an OIDC Identity Provider pointing at the SPIRE OIDC Discovery Provider.
    Idempotent: if alias exists, it is left as-is.
    """
    try:
        idps = kc.get_idps()  # list of identity providers
        if any(p.get("alias") == alias for p in idps):
            print(f'Identity Provider "{alias}" already exists.')
            return
    except KeycloakGetError as e:
        print(f"Warning: could not list IdPs: {e}. Attempting to create IdP.")

    idp_payload = {
        "alias": alias,
        "providerId": "oidc",
        "enabled": True,
        "config": {
            # Keycloak will auto-discover JWKS from /.well-known/openid-configuration
            "issuer": issuer,
            "useJwksUrl": "true",
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
        print(f'Could not create Identity Provider "{alias}": {e}')
        raise


def main() -> int:
    # --- Read env ---
    try:
        KEYCLOAK_URL = get_env_var("KEYCLOAK_URL")
        ADMIN_USER = get_env_var("KEYCLOAK_ADMIN_USERNAME")
        ADMIN_PWD = get_env_var("KEYCLOAK_ADMIN_PASSWORD")
        TARGET_REALM = get_env_var("KEYCLOAK_REALM")

        CLIENT_NAME = get_env_var("CLIENT_NAME")
        SPIRE_ISSUER = get_env_var("SPIRE_ISSUER")  # OIDC DP issuer URL (cluster-local is fine for demos) 

        IDP_ALIAS = get_env_var("IDP_ALIAS", "spire-oidc")

        SPIRE_ENABLED = get_env_var("SPIRE_ENABLED", "true").lower() == "true"
        KEYCLOAK_CLIENT_REGISTRATION_ENABLED = get_env_var(
            "KEYCLOAK_CLIENT_REGISTRATION_ENABLED", "true"
        ).lower() == "true"
        KEYCLOAK_TOKEN_EXCHANGE_ENABLED = get_env_var(
            "KEYCLOAK_TOKEN_EXCHANGE_ENABLED", "false"
        ).lower() == "true"
    except ValueError as e:
        print(f"[FATAL] Missing environment variable: {e}")
        return 1

    if not KEYCLOAK_CLIENT_REGISTRATION_ENABLED:
        print("Client registration disabled by KEYCLOAK_CLIENT_REGISTRATION_ENABLED=false. Exiting.")
        return 0

    # Compute client_id:
    # - For SPIFFE flow, we generally map External Subject = SPIFFE ID (= JWT-SVID sub).
    # - Using the SPIFFE ID directly as the client_id keeps things explicit for demos.
    if SPIRE_ENABLED:
        try:
            client_id = get_client_id()  # reads /opt/jwt_svid.token and returns its `sub`
            print(f'Using SPIFFE ID as client_id: "{client_id}"')
        except Exception as e:
            print(f"[FATAL] Could not extract client_id from JWT-SVID: {e}")
            return 1
    else:
        client_id = CLIENT_NAME
        print(f'Using CLIENT_NAME as client_id: "{client_id}"')

    # --- Connect to Keycloak as master to ensure realm exists ---
    try:
        kc = KeycloakAdmin(
            server_url=KEYCLOAK_URL,
            username=ADMIN_USER,
            password=ADMIN_PWD,
            realm_name="master",        # operate as master to create realm
            user_realm_name="master",
            verify=True,
        )
    except Exception as e:
        print(f"[FATAL] Could not initialize KeycloakAdmin: {e}")
        return 1

    # Ensure target realm
    ensure_realm(kc, TARGET_REALM)

    # Switch the admin client to operate against the target realm
    kc.realm_name = TARGET_REALM

    # Ensure SPIRE OIDC Identity Provider
    ensure_oidc_idp(kc, alias=IDP_ALIAS, issuer=SPIRE_ISSUER)

    # Register (or reuse) client using your helper
    client_payload: dict[str, Any] = {
        "name": CLIENT_NAME,
        "clientId": client_id,
        "protocol": "openid-connect",
        "publicClient": False,              # confidential → can still be used for hybrid/legacy flows
        "serviceAccountsEnabled": True,     # client_credentials if needed (non-federated)
        "standardFlowEnabled": False,       # not needed for this demo
        "directAccessGrantsEnabled": False,
        "fullScopeAllowed": False,
        # Token-exchange not required for SPIFFE federated client auth; leave disabled unless you need it.
        "attributes": {
            "standard.token.exchange.enabled": str(KEYCLOAK_TOKEN_EXCHANGE_ENABLED).lower()
        },
    }

    try:
        internal_client_id = register_client(kc, client_id, client_payload)
    except Exception as e:
        print(f"[FATAL] Could not register client: {e}")
        return 1

    # (Optional) If you still want to persist a client secret for a legacy/hybrid path:
    secret_path = get_env_var("SECRET_FILE_PATH", "/shared/secret.txt")
    print(
        f'Writing client secret for "{client_id}" (internal ID: {internal_client_id}) to: {secret_path}'
    )
    try:
        write_client_secret(kc, internal_client_id, CLIENT_NAME, secret_file_path=secret_path)
    except Exception as e:
        print(f"Warning: could not write client secret: {e}")

    # Final instructions: flip the client to Federated Client Authentication
    realm_issuer = f"{KEYCLOAK_URL.rstrip('/')}/realms/{TARGET_REALM}"
    print("\nNEXT STEP (one-time, in Admin Console):")
    print(f"  1) Realm: {TARGET_REALM} → Identity Providers → confirm IdP '{IDP_ALIAS}' has issuer '{SPIRE_ISSUER}'")
    print(f"  2) Clients → {client_id} → Credentials (or 'Federated client authentication'):")
    print(f"     • Enable Federated client authentication")
    print(f"     • Identity Provider = {IDP_ALIAS}")
    print(f"     • External subject  = <your SPIFFE ID> (should match JWT-SVID 'sub'), e.g., {client_id}")
    print("  3) Save.")
    print("\nRUNTIME:")
    print(f"  • Workload fetches a JWT-SVID (audience MUST target the realm issuer): {realm_issuer}")
    print("  • Call the token endpoint with client_assertion (the JWT-SVID):")
    print(f"      POST {realm_issuer}/protocol/openid-connect/token")
    print("        grant_type=client_credentials")
    print("        client_id=<local client id> (e.g., your SPIFFE ID)")
    print("        client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer")
    print("        client_assertion=<JWT-SVID>")
    print("\nSUCCESS indicates Keycloak validated the SPIRE-issued JWT-SVID via OIDC Discovery & JWKS.")

    return 0


if __name__ == "__main__":
    sys.exit(main())