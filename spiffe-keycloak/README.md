# SPIFFE + Keycloak Federated Client Authentication

This directory contains scripts and configurations for SPIFFE JWT-SVID authentication with Keycloak's federated client authentication feature.

## Overview

Enables workloads with SPIFFE identities (issued by SPIRE) to authenticate to Keycloak using JWT-SVIDs as client credentials, without traditional client secrets.

**Status**: ✅ **WORKING** (as of 2026-02-18)

## Prerequisites

- **Keycloak 26.5.2+** with preview features enabled:
  - `client-auth-federated:v1`
  - `spiffe:v1`
- **SPIRE 1.13.0+** with proper JWT issuer configuration
- **Python 3.11+** with `python-keycloak` package
- **kubectl** access to Kubernetes cluster

## Quick Start

### 1. Configure SPIRE

Update your SPIRE deployment values to use SPIFFE URI as JWT issuer:

```yaml
# In deployments/envs/dev_values.yaml
spire:
  enabled: true
  values:
    global:
      spire:
        jwtIssuer: "spiffe://localtest.me"  # Must be SPIFFE URI, not HTTP URL!
```

Then ensure SPIRE OIDC discovery provider includes "use" field in JWKS:

```bash
# Add set_key_use to SPIRE OIDC discovery provider config
kubectl get configmap spire-spiffe-oidc-discovery-provider -n spire-server -o yaml | \
  # ... add "set_key_use": true to the JSON config ...
kubectl apply -f -

# Restart SPIRE components
kubectl rollout restart statefulset/spire-server -n spire-server
kubectl rollout restart deployment/spire-spiffe-oidc-discovery-provider -n spire-server
```

### 2. Configure Keycloak

Run the setup script to configure Keycloak with the SPIFFE identity provider:

```bash
# Ensure port-forward is running (if needed)
kubectl port-forward svc/keycloak-service -n keycloak 8080:8080

# Run setup
python spiffe-keycloak/keycloak_federated_client.py
```

This script:
- Creates the `demo` realm (if it doesn't exist)
- Creates a **SPIFFE** identity provider (NOT OIDC!)
- Registers a client with the SPIFFE ID as the client ID

### 3. Deploy Test Workload

```bash
kubectl apply -f spiffe-keycloak/client_deployment.yaml
./spiffe-keycloak/register_workload.sh
```

### 4. Run Authentication Test

```bash
./spiffe-keycloak/run_test.sh test
```

Expected output:
```
✅ Successfully authenticated!
  Access token: eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6IC...
  Token type: Bearer
  Expires in: 299 seconds
```

## Critical Configuration Requirements

### ⚠️ MUST Use SPIFFE Provider, Not OIDC!

```json
{
  "alias": "spire-spiffe",
  "providerId": "spiffe",  // NOT "oidc"!
  "enabled": true,
  "config": {
    "trustDomain": "spiffe://localtest.me",
    "bundleEndpoint": "http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys",
    "validateSignature": "true"
  }
}
```

### ⚠️ Client ID MUST Be the SPIFFE ID

```json
{
  "clientId": "spiffe://localtest.me/ns/authbridge/sa/agent",  // Full SPIFFE ID, not simple name!
  "clientAuthenticatorType": "federated-jwt",
  "attributes": {
    "jwt.credential.issuer": "spire-spiffe",
    "jwt.credential.sub": "spiffe://localtest.me/ns/authbridge/sa/agent"
  }
}
```

### ⚠️ Authentication Request Must Use jwt-spiffe Assertion Type

```python
payload = {
    "grant_type": "client_credentials",
    "client_id": "spiffe://localtest.me/ns/authbridge/sa/agent",  // Full SPIFFE ID
    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-spiffe",  // NOT jwt-bearer!
    "client_assertion": jwt_svid,
}
```

## Obstacles Encountered and Solutions

During development, we encountered multiple configuration issues that prevented authentication from working. Here's the complete journey:

### Obstacle 1: Used OIDC Provider Instead of SPIFFE

**Symptom:**
```
java.lang.RuntimeException: Issuer does not support client assertions
```

**Why It Failed:**
- Configured `providerId: "oidc"` instead of `providerId: "spiffe"`
- OIDC providers require the external IdP to advertise OAuth2 capabilities in its OIDC discovery document
- SPIRE's discovery document is minimal (no `token_endpoint`, no `token_endpoint_auth_methods_supported`)
- Keycloak rejected authentication because SPIRE doesn't look like a full OAuth2 authorization server

**Solution:**
✅ Use `providerId: "spiffe"`
- SPIFFE provider is specifically designed for SPIFFE JWT-SVIDs
- Doesn't require OAuth2 discovery document capabilities
- Handles JWT-SVIDs without `jti` claim (which SPIRE doesn't issue)

**Configuration Change:**
```json
{
  "providerId": "spiffe",  // Changed from "oidc"
  "config": {
    "trustDomain": "spiffe://localtest.me",  // Not "issuer"
    "bundleEndpoint": "...",  // Not "jwksUrl"
  }
}
```

---

### Obstacle 2: Wrong Configuration Field Names

**Symptom:**
- SPIFFE Identity Provider in Keycloak UI showed "SPIFFE Bundle or OIDC JWKs endpoint" as empty

**Why It Failed:**
- Used `jwksUrl` field (correct for OIDC providers)
- SPIFFE providers use different field name: `bundleEndpoint`
- Without the bundle endpoint, Keycloak couldn't fetch keys to validate JWT signatures

**Solution:**
✅ Use `bundleEndpoint` instead of `jwksUrl`

**Configuration Change:**
```json
{
  "config": {
    "bundleEndpoint": "http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys",  // Not "jwksUrl"
  }
}
```

---

### Obstacle 3: SPIRE JWKS Missing "use" Field

**Symptom:**
```
WARN  [org.keycloak.authentication.ClientAuthenticationFlow]
Client authentication was attempted did not complete for federated-jwt
```

**Why It Failed:**
- SPIRE's JWKS response didn't include the `"use"` field:
  ```json
  {
    "keys": [{
      "kty": "RSA",
      "kid": "...",
      "alg": "RS256",
      // ❌ Missing "use" field
    }]
  }
  ```
- Keycloak's `SpiffeBundleEndpointLoader` tries to find keys with `use: "jwt-svid"` first, then falls back to `use: "sig"`
- When neither is present, Keycloak has no keys to validate the JWT!

**Solution:**
✅ Configure SPIRE OIDC discovery provider to include "use" field

**Configuration Change:**
```json
// In spire-spiffe-oidc-discovery-provider ConfigMap
{
  "set_key_use": true,  // ← Add this!
  "allow_insecure_scheme": true,
  "domains": [...],
  ...
}
```

**Result:**
```json
{
  "keys": [{
    "use": "sig",  // ✅ Now present!
    "kty": "RSA",
    "kid": "...",
    "alg": "RS256",
    ...
  }]
}
```

**Source:** [SPIRE PR #2634](https://github.com/spiffe/spire/pull/2634) - Added `set_key_use` configuration option

---

### Obstacle 4: Wrong Client Assertion Type

**Symptom:**
```
{"error":"invalid_client","error_description":"client_id parameter does not match sub claim"}
```

**Why It Failed:**
- Used standard OAuth2 assertion type: `urn:ietf:params:oauth:client-assertion-type:jwt-bearer`
- SPIFFE has its own assertion type: `urn:ietf:params:oauth:client-assertion-type:jwt-spiffe`
- Keycloak's SPIFFE provider only accepts `jwt-spiffe` assertions

**Solution:**
✅ Use `jwt-spiffe` assertion type

**Code Change:**
```python
# Before
"client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

# After
"client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-spiffe"
```

**Source:** [Keycloak SpiffeConstants.java](https://github.com/keycloak/keycloak/blob/main/services/src/main/java/org/keycloak/broker/spiffe/SpiffeConstants.java)

---

### Obstacle 5: Client ID Mismatch

**Symptom:**
```
{"error":"invalid_client","error_description":"client_id parameter does not match sub claim"}
```

**Why It Failed:**
- Registered client with simple name: `clientId: "federated-agent-a"`
- JWT-SVID has: `sub: "spiffe://localtest.me/ns/authbridge/sa/agent"`
- For SPIFFE authentication, `client_id` parameter in request MUST match JWT `sub` claim exactly
- Traditional OAuth uses simple client IDs like "myclient"
- SPIFFE uses full SPIFFE IDs as client IDs

**Solution:**
✅ Use the full SPIFFE ID as the client ID

**Configuration Change:**
```json
{
  "clientId": "spiffe://localtest.me/ns/authbridge/sa/agent",  // Full SPIFFE ID
  "attributes": {
    "jwt.credential.sub": "spiffe://localtest.me/ns/authbridge/sa/agent"  // Must match
  }
}
```

**Code Change:**
```python
# Before
client_id = "federated-agent-a"

# After
client_id = "spiffe://localtest.me/ns/authbridge/sa/agent"  # Full SPIFFE ID
```

---

### Obstacle 6: Wrong JWT Audience

**Symptom:**
```
{"error":"invalid_client","error_description":"Invalid token audience"}
```

**Why It Failed:**
- JWT-SVID had: `aud: ["http://keycloak-service.keycloak.svc:8080/realms/demo"]` (internal service URL)
- Keycloak expects: `aud: "http://keycloak.localtest.me:8080/realms/demo"` (external issuer URL)
- The audience must match Keycloak's configured realm issuer

**Solution:**
✅ Set JWT audience to Keycloak's external issuer URL

**Configuration Change:**
```hcl
# In spiffe-helper.conf
jwt_svids = [{
  jwt_audience="http://keycloak.localtest.me:8080/realms/demo",  // External URL, not internal service
  jwt_svid_file_name="/opt/jwt_svid.token"
}]
```

---

### Obstacle 7: Multiple Clients with Same Federated Attributes

**Symptom:**
```
WARN [org.keycloak.authentication.authenticators.client.FederatedJWTClientAuthenticator]
Authentication failed: java.lang.RuntimeException: Multiple clients matches attributes
```

**Why It Failed:**
- Multiple clients in Keycloak have the same `jwt.credential.issuer` and `jwt.credential.sub` attributes
- This typically happens when:
  - An old client (e.g., `federated-agent-a`) exists from previous testing
  - A new client with the SPIFFE ID as clientId was created
  - Both have the same federated attributes
- Keycloak cannot determine which client to authenticate

**Solution:**
✅ Delete duplicate clients, keeping only the one with the SPIFFE ID as clientId

**How to Fix:**
```bash
# Run the setup script again - it now includes automatic cleanup
python spiffe-keycloak/keycloak_federated_client.py
```

**Prevention:** The `keycloak_federated_client.py` script now automatically detects and removes duplicate clients.

---

### Obstacle 8: Stale JWT-SVID (Token Issued Too Long Ago)

**Symptom:**
```
{"error":"invalid_client","error_description":"Token was issued too far in the past to be used now"}
```

**Why It Failed:**
- The JWT-SVID cached by SPIFFE helper was issued too long ago
- Keycloak validates the `iat` (issued at) claim and rejects tokens older than a certain threshold
- This can happen if:
  - The test pod has been running for a while
  - The SPIFFE helper hasn't refreshed the token
  - There's clock skew between SPIRE and Keycloak

**Solution:**
✅ Refresh the JWT-SVID by restarting the workload

**How to Fix:**
```bash
# Restart the test pod to get a fresh JWT-SVID
kubectl rollout restart deployment/spiffe-keycloak-test -n authbridge
kubectl rollout status deployment/spiffe-keycloak-test -n authbridge

# Wait for the pod to get a new JWT-SVID
sleep 10

# Run the test again
./spiffe-keycloak/run_test.sh test
```

**Note:** The SPIFFE helper automatically refreshes JWT-SVIDs before they expire, but if the pod has been idle for a long time, the cached token might be stale.

---

### Bonus: JWT Issuer Format (Initially Suspected Issue)

**Investigation:**
We initially thought the problem was SPIRE using HTTP URL as issuer:
- SPIRE default: `iss: "http://spire-spiffe-oidc-discovery-provider..."`
- Expected by SPIFFE providers: `iss: "spiffe://localtest.me"`

**Solution:**
✅ Configure SPIRE to use SPIFFE URI as JWT issuer

**Configuration Change:**
```yaml
# In deployments/envs/dev_values.yaml
spire:
  values:
    global:
      spire:
        jwtIssuer: "spiffe://localtest.me"  // Changed from HTTP URL
```

**Note:** While this change was part of getting it working, it alone wasn't sufficient. All 8 obstacles needed to be fixed.

---

## Complete Configuration Summary

### SPIRE Configuration

**File:** `deployments/envs/dev_values.yaml`
```yaml
spire:
  enabled: true
  values:
    global:
      spire:
        jwtIssuer: "spiffe://localtest.me"  # ← SPIFFE URI format
```

**File:** `spire-spiffe-oidc-discovery-provider` ConfigMap
```json
{
  "set_key_use": true,  // ← Required for Keycloak compatibility
  "allow_insecure_scheme": true,
  "domains": [...],
  "workload_api": {
    "socket_path": "/spiffe-workload-api/spire-agent.sock",
    "trust_domain": "localtest.me"
  }
}
```

### Keycloak Configuration

**Identity Provider:**
```json
{
  "alias": "spire-spiffe",
  "providerId": "spiffe",  // NOT "oidc"
  "enabled": true,
  "config": {
    "trustDomain": "spiffe://localtest.me",
    "bundleEndpoint": "http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys",
    "validateSignature": "true"
  }
}
```

**Client:**
```json
{
  "clientId": "spiffe://localtest.me/ns/authbridge/sa/agent",  // Full SPIFFE ID
  "clientAuthenticatorType": "federated-jwt",
  "serviceAccountsEnabled": true,
  "attributes": {
    "jwt.credential.issuer": "spire-spiffe",
    "jwt.credential.sub": "spiffe://localtest.me/ns/authbridge/sa/agent"
  }
}
```

### Workload Configuration

**JWT-SVID Request:**
```hcl
# spiffe-helper.conf
jwt_svids = [{
  jwt_audience="http://keycloak.localtest.me:8080/realms/demo",  // Keycloak's external issuer
  jwt_svid_file_name="/opt/jwt_svid.token"
}]
```

**Authentication Request:**
```python
POST http://keycloak.localtest.me:8080/realms/demo/protocol/openid-connect/token

grant_type=client_credentials
client_id=spiffe://localtest.me/ns/authbridge/sa/agent  # Full SPIFFE ID
client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-spiffe  # jwt-spiffe!
client_assertion=<JWT-SVID>
```

## Authentication Flow

```
┌─────────────┐         ┌─────────────┐         ┌──────────────┐
│  Workload   │         │    SPIRE    │         │   Keycloak   │
└──────┬──────┘         └──────┬──────┘         └──────┬───────┘
       │                       │                        │
       │ 1. Request JWT-SVID   │                        │
       │   aud=keycloak issuer │                        │
       │──────────────────────>│                        │
       │                       │                        │
       │ 2. JWT-SVID           │                        │
       │   iss=spiffe://...    │                        │
       │   sub=spiffe://...    │                        │
       │   aud=keycloak issuer │                        │
       │<──────────────────────│                        │
       │                                                │
       │ 3. POST /token                                 │
       │   client_id=<SPIFFE ID>                        │
       │   client_assertion_type=jwt-spiffe             │
       │   client_assertion=<JWT-SVID>                  │
       │───────────────────────────────────────────────>│
       │                                                │
       │                       │ 4. Fetch JWKS from     │
       │                       │    bundleEndpoint      │
       │                       │<───────────────────────│
       │                       │                        │
       │                       │ 5. Validate JWT-SVID   │
       │                       │    - Check issuer      │
       │                       │    - Verify signature  │
       │                       │    - Match trust domain│
       │                       │    - Match sub claim   │
       │                                                │
       │ 6. ✅ Access Token                             │
       │<───────────────────────────────────────────────│
```

## Key Learnings

### Why SPIFFE Provider, Not OIDC?

| Aspect | OIDC Provider | SPIFFE Provider |
|--------|---------------|-----------------|
| Provider ID | `"oidc"` | `"spiffe"` |
| Requires `jti` claim | ✅ Yes | ❌ No (SPIRE doesn't issue it) |
| Discovery validation | Checks for OAuth2 endpoints | Trust domain based |
| Configuration field | `jwksUrl` | `bundleEndpoint` |
| Client ID format | Simple names | Full SPIFFE IDs |
| Assertion type | `jwt-bearer` | `jwt-spiffe` |

### Why "use" Field in JWKS Matters

Keycloak's code (`SpiffeBundleEndpointLoader.java`):
```java
PublicKeysWrapper keysWrapper = JWKSUtils.getKeyWrappersForUse(jwks, JWK.Use.JWT_SVID, true);
if (keysWrapper.getKeys().isEmpty()) {
    keysWrapper = JWKSUtils.getKeyWrappersForUse(jwks, JWK.Use.SIG, true);
}
```

- First tries to find keys with `"use": "jwt-svid"`
- Falls back to keys with `"use": "sig"`
- If both return empty (no "use" field), Keycloak has no keys → authentication fails

SPIRE added `set_key_use` configuration in version 1.1.2 (PR #2634) specifically for clients that require the "use" field.

### Why Client ID Must Be SPIFFE ID

From Keycloak's validation logic:
1. Extracts `sub` claim from JWT-SVID: `"spiffe://localtest.me/ns/authbridge/sa/agent"`
2. Looks up client by `client_id` parameter in request
3. Verifies `sub` claim matches client's configured `jwt.credential.sub`

If `client_id` is a simple name like "federated-agent-a" but `sub` is the SPIFFE ID, Keycloak can't find the matching client.

**The test shows the pattern:**
```java
static final String INTERNAL_CLIENT_ID = "myclient";  // Display name
static final String EXTERNAL_CLIENT_ID = "spiffe://mytrust-domain/myclient";  // Actual client_id
```

### Why jwt-spiffe Assertion Type

Keycloak has a dedicated constant (`SpiffeConstants.java`):
```java
String CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-spiffe";
```

The SPIFFE provider specifically looks for this assertion type, not the standard `jwt-bearer` type.

## Files

### Core Scripts
- **`keycloak_federated_client.py`** - ✅ Setup script (configures SPIFFE provider)
- **`client_deployment.yaml`** - ✅ Test workload deployment (with correct config)
- **`register_workload.sh`** - Registers workload with SPIRE
- **`run_test.sh`** - Test runner script
- **`utilties.py`** - Helper functions for JWT-SVID handling

### Documentation
- **`README.md`** - This file (comprehensive guide)
- **`SUMMARY.md`** - Executive summary
- **`GITHUB_ISSUES_ANALYSIS.md`** - Community discussion and alternatives
- **`TEST_GUIDE.md`** - Detailed testing instructions
- **`SPIRE_CONCEPTS.md`** - SPIFFE/SPIRE concepts reference

### Configuration
- **`spire-oidc-httproute.yaml`** - HTTPRoute for external SPIRE OIDC access
- **`keycloak_statefulset.yaml`** - Reference Keycloak deployment

## Troubleshooting

### Check JWT-SVID Claims
```bash
kubectl exec -n authbridge deployment/spiffe-keycloak-test -c test-client -- python3 -c "
import jwt
with open('/opt/jwt_svid.token', 'r') as f:
    token = f.read().strip()
    claims = jwt.decode(token, options={'verify_signature': False})
    for k, v in claims.items():
        print(f'{k}: {v}')
"
```

**Expected:**
```
iss: spiffe://localtest.me
sub: spiffe://localtest.me/ns/authbridge/sa/agent
aud: ['http://keycloak.localtest.me:8080/realms/demo']
```

### Check SPIRE JWKS
```bash
kubectl run test-curl --rm -i --image=curlimages/curl --restart=Never -- \
  curl -s http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys
```

**Expected:**
```json
{
  "keys": [{
    "use": "sig",  ← Must be present!
    "kty": "RSA",
    ...
  }]
}
```

### Check Keycloak Configuration
```bash
kubectl run keycloak-client --rm -i --image=python:3.11-slim --restart=Never -- bash -c "
pip install -q python-keycloak && python3 -c \"
from keycloak import KeycloakAdmin
import json

kc = KeycloakAdmin(
    server_url='http://keycloak-service.keycloak.svc:8080',
    username='admin',
    password='admin',
    realm_name='demo',
    user_realm_name='master'
)

idps = kc.get_idps()
spiffe_idp = next((p for p in idps if p.get('alias') == 'spire-spiffe'), None)
print(json.dumps(spiffe_idp, indent=2))
\"
"
```

### Check Keycloak Logs
```bash
kubectl logs -n keycloak pod/keycloak-0 --since=5m | grep -E "CLIENT|federated|ERROR"
```

## References

- [Keycloak Federated Client Authentication Blog](https://www.keycloak.org/2026/01/federated-client-authentication)
- [Keycloak PR #43656](https://github.com/keycloak/keycloak/pull/43656) - SPIFFE OIDC JWK endpoint support
- [Keycloak GitHub Issue #42634](https://github.com/keycloak/keycloak/issues/42634) - Federated auth tracking
- [SPIRE PR #2634](https://github.com/spiffe/spire/pull/2634) - Added set_key_use configuration
- [SPIFFE Trust Domain and Bundle Spec](https://github.com/spiffe/spiffe/blob/main/standards/SPIFFE_Trust_Domain_and_Bundle.md)
- [SPIRE Documentation](https://spiffe.io/docs/latest/spire-about/)

## Contributing

This integration is now working! If you encounter issues or have improvements, please submit a PR.

## Success Criteria

When properly configured, you should see:

```
✅ Successfully authenticated!
  Access token: eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6IC...
  Token type: Bearer
  Expires in: 299 seconds
```

This proves that SPIFFE workload identities can successfully authenticate to Keycloak for OAuth 2.0 client credentials flow!
