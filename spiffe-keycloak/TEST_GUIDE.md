# SPIFFE + Keycloak Federated Authentication Test

This test demonstrates SPIFFE workload identity being used for OAuth 2.0 client authentication with Keycloak's federated-jwt authenticator.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Kubernetes Pod (authbridge/spiffe-keycloak-test)      │
│                                                         │
│  ┌──────────────────┐   ┌──────────────────────────┐  │
│  │  test-client     │   │  spiffe-helper           │  │
│  │  (Python)        │   │  (Fetches JWT-SVID)      │  │
│  │                  │   │                          │  │
│  │  test_auth.py    │   │  /opt/jwt_svid.token ────┼──┤
│  │  utilities.py    │◄──┤  /opt/svid.pem           │  │
│  └──────────────────┘   │  /opt/svid_key.pem       │  │
│                         └──────────┬───────────────┘  │
│                                    │                   │
└────────────────────────────────────┼───────────────────┘
                                     │
                    Unix Socket: /run/spire/agent-sockets/
                                     │
                         ┌───────────▼───────────┐
                         │   SPIRE Agent         │
                         │   (DaemonSet)         │
                         └───────────┬───────────┘
                                     │
                         ┌───────────▼───────────┐
                         │   SPIRE Server        │
                         └───────────────────────┘
```

## Test Flow

1. **spiffe-helper** fetches JWT-SVID from SPIRE Agent
   - SPIFFE ID: `spiffe://localtest.me/ns/authbridge/sa/agent`
   - Audience: `http://keycloak.localtest.me:8080/realms/demo`
   - Written to: `/opt/jwt_svid.token`

2. **test_auth.py** reads the JWT-SVID and authenticates to Keycloak
   - Uses JWT-SVID as `client_assertion`
   - Grant type: `client_credentials`
   - Client ID: `federated-agent-a`

3. **Keycloak** validates the JWT-SVID
   - Verifies signature against SPIRE OIDC Discovery Provider
   - Checks issuer and subject match federated client configuration
   - Issues access token

4. **test_auth.py** verifies the access token
   - Calls Keycloak userinfo endpoint
   - Confirms token is valid

## Prerequisites

1. **Kagenti cluster with SPIRE installed**
   - SPIRE Agent running (DaemonSet)
   - SPIRE Server running
   - SPIFFE Controller Manager installed (auto-registers pods)

2. **Keycloak configured** (run `keycloak_federated_client.py`):
   - Realm: `demo`
   - OIDC Identity Provider: `spire-oidc` pointing to SPIRE
   - Client: `federated-agent-a` with federated-jwt authenticator

3. **Namespace and Service Account**:
   - Namespace: `authbridge`
   - ServiceAccount: `agent`
   - These match the expected SPIFFE ID: `spiffe://localtest.me/ns/authbridge/sa/agent`

## Quick Start

### 1. Deploy the test workload

```bash
cd spiffe-keycloak
./run_test.sh deploy
```

This will:
- Create the `authbridge` namespace
- Create the `agent` service account
- Deploy the test pod with spiffe-helper sidecar
- Wait for the pod to be ready
- Wait for JWT-SVID to be available

### 2. Run the authentication test

```bash
./run_test.sh test
```

Expected output:
```
======================================================================
SPIFFE + Keycloak Federated Authentication Test
======================================================================

Configuration:
  Keycloak URL:  http://keycloak.localtest.me:8080
  Realm:         demo
  Client ID:     federated-agent-a

======================================================================
Step 1: Read JWT-SVID from SPIFFE
======================================================================
✅ SPIFFE ID: spiffe://localtest.me/ns/authbridge/sa/agent
✅ JWT-SVID retrieved (XXX bytes)

JWT Claims:
  Issuer (iss): http://spire-oidc.spire.svc.cluster.local
  Subject (sub): spiffe://localtest.me/ns/authbridge/sa/agent
  Audience (aud): http://keycloak.localtest.me:8080/realms/demo
  Expiration (exp): 1234567890

======================================================================
Step 2: Authenticate to Keycloak
======================================================================
Authenticating to Keycloak...
  Token endpoint: http://keycloak.localtest.me:8080/realms/demo/protocol/openid-connect/token
  Client ID: federated-agent-a
  Response status: 200
✅ Successfully authenticated!
  Access token: eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
  Token type: Bearer
  Expires in: 3600 seconds

======================================================================
Step 3: Verify Access Token
======================================================================
Verifying access token...
  Userinfo endpoint: http://keycloak.localtest.me:8080/realms/demo/protocol/openid-connect/userinfo
  Response status: 200
✅ Token is valid!
  User info: {...}

======================================================================
✅ SUCCESS! SPIFFE + Keycloak Integration Working
======================================================================

The following flow was demonstrated:
  1. ✅ Workload retrieved JWT-SVID from SPIRE
  2. ✅ Used JWT-SVID to authenticate to Keycloak
  3. ✅ Received valid access token from Keycloak
  4. ✅ Verified token with Keycloak

This proves that SPIFFE identity can be used for OAuth 2.0
authentication with Keycloak's federated-jwt client authenticator.
```

## Additional Commands

### View logs

```bash
./run_test.sh logs
```

Shows logs from both containers (test-client and spiffe-helper).

### Debug information

```bash
./run_test.sh debug
```

Shows:
- Pod status
- JWT-SVID file presence
- JWT-SVID content preview
- Environment variables

### Open shell

```bash
./run_test.sh shell
```

Opens an interactive shell in the test-client container for manual debugging.

### Delete deployment

```bash
./run_test.sh delete
```

Removes the test deployment from the cluster.

## Files

- **client_deployment.yaml**: Kubernetes deployment with test pod
  - `test-client` container: Python 3.11 with test scripts
  - `spiffe-helper` container: Fetches JWT-SVID from SPIRE
  - ConfigMaps: test-config, spiffe-helper-config, test-scripts

- **utilities.py**: Helper functions
  - `get_client_id()`: Extract SPIFFE ID from JWT-SVID
  - `get_jwt_svid()`: Read JWT-SVID token

- **test_auth.py**: Main test script
  - Authenticates to Keycloak using JWT-SVID
  - Verifies access token

- **run_test.sh**: Helper script for deploying and testing

## Troubleshooting

### JWT-SVID file not found

```bash
# Check if spiffe-helper is running
kubectl logs -n authbridge deployment/spiffe-keycloak-test -c spiffe-helper

# Check if SPIRE Agent socket is accessible
kubectl exec -n authbridge deployment/spiffe-keycloak-test -c spiffe-helper -- \
  ls -l /spiffe-workload-api/
```

### Authentication fails (401)

```bash
# Verify Keycloak configuration
python3 keycloak_federated_client.py

# Check if client exists
curl http://keycloak.localtest.me:8080/admin/realms/demo/clients \
  -H "Authorization: Bearer <admin-token>"
```

### Pod not scheduled

```bash
# Check if SPIRE Agent is running
kubectl get pods -n spire -l app=spire-agent

# Check node taints
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

### SPIFFE ID mismatch

The SPIFFE ID is automatically generated based on:
- Namespace: `authbridge`
- ServiceAccount: `agent`
- Trust domain: `localtest.me`

Resulting in: `spiffe://localtest.me/ns/authbridge/sa/agent`

If you change namespace or service account, update:
1. Keycloak client configuration (federated subject)
2. JWT audience in spiffe-helper-config

## Understanding the Code

### How spiffe-helper works

```
spiffe-helper configuration:
agent_address = "/spiffe-workload-api/spire-agent.sock"  ← Unix socket
jwt_svids = [{
  jwt_audience = "http://keycloak.localtest.me:8080/realms/demo",
  jwt_svid_file_name = "/opt/jwt_svid.token"
}]

1. Connects to SPIRE Agent via Unix socket
2. Requests JWT-SVID with specific audience
3. SPIRE Agent attests workload (checks namespace, SA, etc.)
4. SPIRE Agent fetches JWT-SVID from SPIRE Server
5. spiffe-helper writes JWT to /opt/jwt_svid.token
6. Automatically rotates before expiration
```

### How federated-jwt authentication works

```
POST /realms/demo/protocol/openid-connect/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
client_id=federated-agent-a
client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
client_assertion=<JWT-SVID>

Keycloak:
1. Receives client_assertion (JWT-SVID)
2. Extracts issuer claim: "http://spire-oidc.spire.svc.cluster.local"
3. Matches to OIDC Identity Provider: "spire-oidc"
4. Fetches JWKS from SPIRE: http://spire-oidc.spire.svc.cluster.local/keys
5. Verifies JWT signature
6. Checks subject matches client config: "spiffe://localtest.me/ns/authbridge/sa/agent"
7. Issues access token
```

## References

- [SPIFFE Workload API](https://github.com/spiffe/spiffe/blob/main/standards/SPIFFE_Workload_API.md)
- [Keycloak Federated Client Authentication](https://www.keycloak.org/docs/latest/server_admin/#_federated-client-auth)
- [OAuth 2.0 JWT Bearer Assertion](https://datatracker.ietf.org/doc/html/rfc7523)
