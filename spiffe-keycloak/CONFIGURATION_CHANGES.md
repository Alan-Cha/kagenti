# Configuration Changes Summary

This document shows the exact configuration changes needed to make SPIFFE + Keycloak federated authentication work.

## 1. SPIRE JWT Issuer Configuration

### File: `deployments/envs/dev_values.yaml`

**Before:**
```yaml
spire:
  enabled: true
  values:
    global:
      spire:
        jwtIssuer: "http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local"
```

**After:**
```yaml
spire:
  enabled: true
  values:
    global:
      spire:
        jwtIssuer: "spiffe://localtest.me"  # ← Changed to SPIFFE URI format
```

**Why:** Keycloak's SPIFFE provider expects JWT issuer to match the trust domain format.

---

## 2. SPIRE OIDC Discovery Provider Configuration

### ConfigMap: `spire-spiffe-oidc-discovery-provider` (namespace: `spire-server`)

**Before:**
```json
{
  "allow_insecure_scheme": true,
  "domains": [...],
  "workload_api": {
    "socket_path": "/spiffe-workload-api/spire-agent.sock",
    "trust_domain": "localtest.me"
  }
}
```

**After:**
```json
{
  "set_key_use": true,  // ← ADDED: Required for Keycloak JWKS compatibility
  "allow_insecure_scheme": true,
  "domains": [...],
  "workload_api": {
    "socket_path": "/spiffe-workload-api/spire-agent.sock",
    "trust_domain": "localtest.me"
  }
}
```

**Why:** Keycloak's `SpiffeBundleEndpointLoader` filters JWKS keys by the "use" field. Without this field, Keycloak finds no keys to validate JWTs.

**Result in JWKS:**
```json
{
  "keys": [{
    "use": "sig",  // ← Now present
    "kty": "RSA",
    "kid": "...",
    "alg": "RS256",
    ...
  }]
}
```

---

## 3. Keycloak Identity Provider Configuration

### File: `spiffe-keycloak/keycloak_federated_client.py`

**Before (OIDC Provider):**
```python
idp_payload = {
    "alias": "spire-oidc",
    "providerId": "oidc",  # ❌ Wrong!
    "enabled": True,
    "config": {
        "issuer": "http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local",
        "jwksUrl": "http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys",
        "validateSignature": "true",
        "clientAuthMethod": "client_secret_jwt"
    },
}
```

**After (SPIFFE Provider):**
```python
idp_payload = {
    "alias": "spire-spiffe",
    "providerId": "spiffe",  # ✅ Changed to SPIFFE
    "enabled": True,
    "config": {
        "trustDomain": "spiffe://localtest.me",  # ✅ Changed field name and value
        "bundleEndpoint": "http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys",  # ✅ Changed field name
        "validateSignature": "true",
    },
}
```

**Why:**
- OIDC providers require full OAuth2 discovery document with token endpoints
- SPIRE only provides minimal OIDC discovery (no token endpoints)
- SPIFFE provider is designed specifically for SPIFFE JWT-SVIDs
- Different field names: `trustDomain`/`bundleEndpoint` vs `issuer`/`jwksUrl`

---

## 4. Keycloak Client Configuration

### File: `spiffe-keycloak/keycloak_federated_client.py`

**Before:**
```python
AGENT_SPIFFE_ID = "spiffe://localtest.me/ns/authbridge/sa/agent"
CLIENT_ID = "federated-agent-a"  # ❌ Simple name

client_payload = {
    "name": "Federated Agent",
    "clientId": CLIENT_ID,  # ❌ "federated-agent-a"
    "protocol": "openid-connect",
    "publicClient": False,
    "serviceAccountsEnabled": True,
    "clientAuthenticatorType": "federated-jwt",
    "attributes": {
        "jwt.credential.issuer": "spire-oidc",
        "jwt.credential.sub": AGENT_SPIFFE_ID,
    },
}
```

**After:**
```python
AGENT_SPIFFE_ID = "spiffe://localtest.me/ns/authbridge/sa/agent"
CLIENT_ID = AGENT_SPIFFE_ID  # ✅ Use SPIFFE ID as client ID!

client_payload = {
    "name": "SPIFFE Agent",  # Display name only
    "clientId": CLIENT_ID,  # ✅ Full SPIFFE ID
    "protocol": "openid-connect",
    "publicClient": False,
    "serviceAccountsEnabled": True,
    "clientAuthenticatorType": "federated-jwt",
    "attributes": {
        "jwt.credential.issuer": "spire-spiffe",  # ✅ Updated alias
        "jwt.credential.sub": AGENT_SPIFFE_ID,
    },
}
```

**Why:** For SPIFFE authentication, the `clientId` must match the JWT `sub` claim exactly. The `sub` claim is the SPIFFE ID, so `clientId` must also be the SPIFFE ID.

---

## 5. Workload JWT-SVID Request Configuration

### File: `spiffe-keycloak/client_deployment.yaml`

**ConfigMap: `spiffe-helper-config`**

**Before:**
```hcl
jwt_svids = [{
  jwt_audience="http://keycloak-service.keycloak.svc:8080/realms/demo",  # ❌ Internal service URL
  jwt_svid_file_name="/opt/jwt_svid.token"
}]
```

**After:**
```hcl
jwt_svids = [{
  jwt_audience="http://keycloak.localtest.me:8080/realms/demo",  # ✅ External issuer URL
  jwt_svid_file_name="/opt/jwt_svid.token"
}]
```

**Why:** Keycloak validates the JWT `aud` claim against its configured issuer URL. The issuer is the external URL, not the internal Kubernetes service URL.

---

## 6. Authentication Request Configuration

### File: `spiffe-keycloak/client_deployment.yaml`

**ConfigMap: `test-scripts` (test.py)**

**Before:**
```python
CLIENT_ID = "federated-agent-a"  # ❌ Simple name

payload = {
    "grant_type": "client_credentials",
    "client_id": CLIENT_ID,
    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",  # ❌ jwt-bearer
    "client_assertion": jwt_svid,
}
```

**After:**
```python
CLIENT_ID = os.getenv("CLIENT_ID", "spiffe://localtest.me/ns/authbridge/sa/agent")  # ✅ Full SPIFFE ID

payload = {
    "grant_type": "client_credentials",
    "client_id": CLIENT_ID,  # ✅ Full SPIFFE ID
    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-spiffe",  # ✅ jwt-spiffe
    "client_assertion": jwt_svid,
}
```

**Why:**
- `client_id` must match the JWT `sub` claim (the SPIFFE ID)
- `client_assertion_type` must be `jwt-spiffe` for SPIFFE provider (not standard `jwt-bearer`)

---

## Summary Table

| Configuration Item | Before | After | Why Changed |
|-------------------|--------|-------|-------------|
| **SPIRE JWT Issuer** | HTTP URL | `spiffe://localtest.me` | Match trust domain format |
| **SPIRE JWKS "use" field** | Missing | `"use": "sig"` | Required by Keycloak's key loader |
| **Keycloak IdP Type** | `oidc` | `spiffe` | SPIFFE provider handles JWT-SVIDs correctly |
| **IdP Config Field** | `jwksUrl` | `bundleEndpoint` | SPIFFE provider uses different field names |
| **IdP Trust Field** | `issuer` (HTTP URL) | `trustDomain` (SPIFFE URI) | SPIFFE provider expects trust domain |
| **Client ID** | Simple name | Full SPIFFE ID | Must match JWT `sub` claim |
| **JWT Audience** | Internal K8s service URL | External issuer URL | Must match Keycloak's issuer |
| **Client Assertion Type** | `jwt-bearer` | `jwt-spiffe` | SPIFFE provider requires specific type |

---

## Quick Apply Commands

After making the configuration changes:

```bash
# 1. Apply SPIRE changes
helm upgrade spire-charts -n spire-server -f deployments/envs/dev_values.yaml
kubectl rollout restart statefulset/spire-server -n spire-server
kubectl rollout restart deployment/spire-spiffe-oidc-discovery-provider -n spire-server

# 2. Update Keycloak
python spiffe-keycloak/keycloak_federated_client.py

# 3. Deploy test workload
kubectl apply -f spiffe-keycloak/client_deployment.yaml
./spiffe-keycloak/register_workload.sh

# 4. Wait for sync and test
sleep 30
./spiffe-keycloak/run_test.sh test
```

---

## References

- **SPIRE Configuration**: [SPIRE PR #2634](https://github.com/spiffe/spire/pull/2634) - Added `set_key_use`
- **Keycloak SPIFFE Support**: [Keycloak PR #43656](https://github.com/keycloak/keycloak/pull/43656)
- **Keycloak Source**: `SpiffeBundleEndpointLoader.java`, `SpiffeConstants.java`

---

**Last Updated**: 2026-02-18
**Status**: ✅ All changes tested and working
