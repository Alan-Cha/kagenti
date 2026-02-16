# SPIFFE + Keycloak Federated Authentication Demo

This demo demonstrates how to use SPIFFE identities from SPIRE for OAuth 2.0 authentication with Keycloak using the **federated-jwt client authenticator**.

## Overview

The integration allows workloads with SPIFFE identities to authenticate to Keycloak without traditional client secrets. Instead, the workload presents a JWT-SVID (issued by SPIRE) as proof of identity.

### Authentication Flow

```
┌─────────────┐                    ┌─────────────┐                    ┌──────────────┐
│  Workload   │                    │    SPIRE    │                    │   Keycloak   │
│   (Client)  │                    │   Agent     │                    │              │
└──────┬──────┘                    └──────┬──────┘                    └──────┬───────┘
       │                                  │                                   │
       │  1. Request JWT-SVID             │                                   │
       │─────────────────────────────────>│                                   │
       │                                  │                                   │
       │  2. Return JWT-SVID              │                                   │
       │  (signed by SPIRE, contains      │                                   │
       │   SPIFFE ID as subject)          │                                   │
       │<─────────────────────────────────│                                   │
       │                                                                      │
       │  3. Token request with JWT-SVID as client_assertion                  │
       │  POST /realms/demo/protocol/openid-connect/token                     │
       │  - grant_type=client_credentials                                     │
       │  - client_id=federated-agent-a                                       │
       │  - client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
       │  - client_assertion=<JWT-SVID>                                       │
       │─────────────────────────────────────────────────────────────────────>│
       │                                                                      │
       │                                  │  4. Keycloak validates JWT-SVID  │
       │                                  │     against SPIRE OIDC Discovery │
       │                                  │     Provider (jwks_uri)          │
       │                                                                      │
       │  5. Return access token                                              │
       │<─────────────────────────────────────────────────────────────────────│
       │                                                                      │
```

## Prerequisites

1. **Kagenti deployed** with SPIRE and Keycloak installed
2. **Keycloak version 26.5.2+** with features `client-auth-federated:v1,spiffe:v1` enabled
3. **Python 3.11+** for running setup and test scripts

## Files

- `keycloak_statefulset.yaml` - Modified Keycloak deployment with required features enabled
- `keycloak_federated_client.py` - Provisions Keycloak realm, OIDC IdP, and federated client
- `test_spiffe_auth.py` - Test script demonstrating the authentication flow
- `register_workload.sh` - Helper script to register the test workload in SPIRE
- `requirements.txt` - Python dependencies

## Setup Instructions

### Step 1: Ensure Keycloak is Running with Correct Features

The Kagenti Helm chart ([charts/kagenti-deps/templates/keycloak-k8s.yaml](../charts/kagenti-deps/templates/keycloak-k8s.yaml)) already includes the necessary configuration:
- Keycloak version 26.5.2
- Features: `client-auth-federated:v1,spiffe:v1`

If you need to update:

```bash
helm upgrade kagenti-deps charts/kagenti-deps -n kagenti-system
```

Wait for Keycloak to be ready:

```bash
kubectl wait --for=condition=ready pod -l app=keycloak -n keycloak --timeout=300s
```

### Step 2: Install Python Dependencies

```bash
cd spiffe-keycloak
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3: Run Keycloak Setup

This creates the demo realm, SPIRE OIDC Identity Provider, and federated client:

```bash
python setup3.py
```

Expected output:
```
============================================================
SPIFFE Federated Client Auth - Keycloak Setup
============================================================

Keycloak:          http://keycloak.localtest.me:8080
Realm:             demo
SPIRE Issuer:      http://spire-oidc.spire.svc.cluster.local
IdP Alias:         spire-oidc
Client:            federated-agent-a
Federated Subject: spiffe://localtest.me/ns/authbridge/sa/agent

--- Realm ---
Realm 'demo' already exists.

--- Identity Provider ---
Identity Provider "spire-oidc" already exists.

--- Client ---
Created client "federated-agent-a" with Signed JWT - Federated.

============================================================
Setup complete.
============================================================
```

### Step 4: Register Workload in SPIRE

The test script expects a workload with SPIFFE ID `spiffe://localtest.me/ns/authbridge/sa/agent`.

**Option A: Use the helper script (recommended)**:

```bash
chmod +x register_workload.sh
./register_workload.sh
```

The script will:
1. Find your SPIRE installation and agents
2. Determine the correct parent ID automatically
3. Create a registration entry with `unix:uid` selector for local testing
4. Verify the registration

**Option B: Manual registration**:

If you prefer to register manually or need to customize the selectors:

```bash
# First, find the parent agent SPIFFE ID
kubectl exec -n zero-trust-workload-identity-manager spire-server-0 -- \
  /opt/spire/bin/spire-server agent list

# Then create the entry (replace PARENT_ID with the actual agent SPIFFE ID)
kubectl exec -n zero-trust-workload-identity-manager spire-server-0 -- \
  /opt/spire/bin/spire-server entry create \
  -spiffeID spiffe://localtest.me/ns/authbridge/sa/agent \
  -parentID <PARENT_ID_FROM_ABOVE> \
  -selector unix:uid:$(id -u)

# Verify the entry
kubectl exec -n zero-trust-workload-identity-manager spire-server-0 -- \
  /opt/spire/bin/spire-server entry show
```

**Note**: The selector `unix:uid:$(id -u)` allows your local user to obtain this identity. For Kubernetes pods, you'd use `k8s:ns:authbridge` and `k8s:sa:agent` selectors instead.

### Step 5: Set Up SPIRE Agent Socket

The test script needs access to the SPIRE Workload API socket. For local testing:

```bash
# Port-forward the SPIRE agent socket
kubectl port-forward -n zero-trust-workload-identity-manager daemonset/spire-agent 8081:8081 &

# Set environment variable
export SPIFFE_ENDPOINT_SOCKET="unix:///var/run/spire/sockets/agent.sock"
```

**For testing in a pod**: Mount the socket volume from the SPIRE agent DaemonSet.

### Step 6: Run the Test Script

```bash
python test_spiffe_auth.py
```

Expected output:

```
======================================================================
SPIFFE + Keycloak Federated Authentication Test
======================================================================

Configuration:
  Keycloak:         http://keycloak.localtest.me:8080
  Realm:            demo
  Client ID:        federated-agent-a
  Expected SPIFFE:  spiffe://localtest.me/ns/authbridge/sa/agent
  Workload Socket:  unix:///var/run/spire/sockets/agent.sock

======================================================================
Step 1: Fetch JWT-SVID from SPIRE
======================================================================
Fetching JWT-SVID from SPIRE...
  Expected SPIFFE ID: spiffe://localtest.me/ns/authbridge/sa/agent
  Audience: http://keycloak.localtest.me:8080/realms/demo
[OK] SPIFFE ID matches: spiffe://localtest.me/ns/authbridge/sa/agent
[OK] JWT-SVID retrieved (XXX bytes)

======================================================================
Step 2: Authenticate to Keycloak
======================================================================
Authenticating to Keycloak...
  Token endpoint: http://keycloak.localtest.me:8080/realms/demo/protocol/openid-connect/token
  Client ID: federated-agent-a
  Response status: 200
[OK] Successfully authenticated!
  Access token: eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA...
  Token type: Bearer
  Expires in: 300 seconds

======================================================================
Step 3: Verify Access Token
======================================================================
Verifying access token...
[OK] Token is valid!

======================================================================
SUCCESS! SPIFFE + Keycloak Integration Working
======================================================================

The following flow was demonstrated:
  1. ✓ Workload retrieved JWT-SVID from SPIRE
  2. ✓ Used JWT-SVID to authenticate to Keycloak
  3. ✓ Received valid access token from Keycloak
  4. ✓ Verified token with Keycloak userinfo endpoint

This proves that SPIFFE identity can be used for OAuth 2.0
authentication with Keycloak's federated-jwt client authenticator.
```

## Configuration Details

### Keycloak Client Configuration

The client `federated-agent-a` is configured with:

- **Client Authenticator Type**: `federated-jwt`
- **JWT Credential Issuer**: `spire-oidc` (the OIDC IdP alias)
- **JWT Credential Subject**: `spiffe://localtest.me/ns/authbridge/sa/agent`

This tells Keycloak to:
1. Accept JWTs from the SPIRE OIDC Discovery Provider
2. Match the JWT's `sub` claim against the configured SPIFFE ID
3. Grant access if validation succeeds

### SPIRE OIDC Discovery Provider

The OIDC IdP in Keycloak points to:
- **Issuer**: `http://spire-oidc.spire.svc.cluster.local`
- **JWKS URL**: `https://spire-oidc.spire.svc.cluster.local/keys`

**Note**: The protocol mismatch (http → https in jwksUrl) is intentional based on Keycloak OIDC IdP requirements.

## Troubleshooting

### "No JWT-SVIDs returned from SPIRE"

- Verify SPIRE agent is running: `kubectl get pods -n zero-trust-workload-identity-manager`
- Check workload API socket: `ls -la /var/run/spire/sockets/agent.sock`
- Verify registration entry exists: `kubectl exec ... spire-server entry show`

### "Authentication failed"

- Ensure `setup3.py` ran successfully
- Verify Keycloak is accessible: `curl http://keycloak.localtest.me:8080/health`
- Check Keycloak logs: `kubectl logs -n keycloak keycloak-0`
- Verify client exists in Keycloak UI at `http://keycloak.localtest.me:8080/admin`

### "SPIFFE ID mismatch"

The registration entry in SPIRE doesn't match the expected SPIFFE ID. Update either:
- The registration entry in SPIRE, OR
- The `AGENT_SPIFFE_ID` constant in `setup3.py` and `test_spiffe_auth.py`

## Next Steps

1. **Create a Kubernetes pod deployment** that demonstrates the flow in-cluster
2. **Add RBAC policies** to limit which workloads can authenticate as specific clients
3. **Integrate with Kagenti agents** to use SPIFFE identities for agent-to-agent authentication
4. **Add mTLS** between workload and Keycloak using X.509-SVIDs

## References

- [Keycloak Client Authentication with Federated IdP](https://www.keycloak.org/docs/latest/securing_apps/#_client_credentials_grant)
- [SPIFFE Workload API](https://github.com/spiffe/spiffe/blob/main/standards/SPIFFE_Workload_API.md)
- [SPIRE OIDC Discovery Provider](https://spiffe.io/docs/latest/keyless/oidc-federation-spec/)
- [OAuth 2.0 JWT Bearer Token Profiles](https://datatracker.ietf.org/doc/html/rfc7523)
