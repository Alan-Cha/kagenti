# SPIFFE + Keycloak Setup Checklist

Use this checklist to replicate the working SPIFFE + Keycloak federated authentication setup.

## ✅ Prerequisites

- [ ] Keycloak 26.5.2+ installed with preview features enabled:
  - `--features=client-auth-federated:v1,spiffe:v1`
- [ ] SPIRE 1.13.0+ deployed and running
- [ ] Python 3.11+ with `python-keycloak` package
- [ ] kubectl access to cluster

## 📋 Configuration Checklist

### Step 1: Configure SPIRE

**Why this is needed:** Keycloak's SPIFFE provider requires two specific configurations from SPIRE:

1. **JWT Issuer** must be a SPIFFE URI (`spiffe://localtest.me`) instead of an HTTP URL
   - Keycloak validates that the `iss` claim matches the trust domain format

2. **JWKS "use" field** must be present in the OIDC discovery endpoint's key metadata
   - Keycloak's code specifically looks for keys with `"use": "jwt-svid"` or `"use": "sig"`
   - Without this field, Keycloak cannot identify which keys are for JWT signature verification
   - SPIRE doesn't include this field by default - it must be enabled with `set_key_use: true`

You have **two options** to configure SPIRE:

#### Option A: Update Helm Values (Recommended for new deployments)

- [ ] **Update SPIRE deployment values** (`deployments/envs/dev_values.yaml`):
  ```yaml
  spire:
    enabled: true
    values:
      global:
        spire:
          jwtIssuer: "spiffe://localtest.me"
      spiffe-oidc-discovery-provider:
        config:
          set_key_use: true
  ```

- [ ] **Redeploy via Ansible**:
  ```bash
  deployments/ansible/run-install.sh --env dev
  ```

#### Option B: Patch Existing SPIRE ConfigMaps (For existing deployments)

- [ ] **Run the patch script**:
  ```bash
  ./spiffe-keycloak/patch_spire_config.sh
  ```

  This script:
  - Updates `spire-server` ConfigMap to set `jwt_issuer: "spiffe://localtest.me"`
  - Updates `spire-spiffe-oidc-discovery-provider` ConfigMap to add `set_key_use: true`
  - Restarts SPIRE components automatically
  - Creates backups in `/tmp/` before making changes

- [ ] **Verify JWKS has "use" field**:
  ```bash
  kubectl run test-curl --rm -i --image=curlimages/curl --restart=Never -- \
    curl -s http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys
  ```
  Look for `"use": "sig"` in each key. Example output:
  ```json
  {
    "keys": [
      {
        "use": "sig",  // ← This field must be present!
        "kty": "RSA",
        "kid": "...",
        ...
      },
      {
        "use": "sig",  // ← Multiple keys are normal (key rotation)
        "kty": "RSA",
        "kid": "...",
        ...
      }
    ]
  }
  ```

  **Note:** Multiple keys are normal - SPIRE maintains old keys during rotation to prevent downtime.

### Step 2: Configure Keycloak

- [ ] **Port-forward Keycloak** (if needed):
  ```bash
  kubectl port-forward svc/keycloak-service -n keycloak 8080:8080
  ```

- [ ] **Run Keycloak setup script**:
  ```bash
  cd /Users/alan/Documents/Work/kagenti
  python spiffe-keycloak/keycloak_federated_client.py
  ```

- [ ] **Verify SPIFFE Identity Provider created**:
  - Log into Keycloak Admin Console
  - Navigate to: `demo` realm → Identity Providers
  - Verify:
    - Alias: `spire-spiffe`
    - Type: `SPIFFE` (NOT OIDC!)
    - Trust Domain: `spiffe://localtest.me`
    - SPIFFE Bundle Endpoint: `http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local/keys`

- [ ] **Verify Client created**:
  - Navigate to: `demo` realm → Clients
  - Find client: `spiffe://localtest.me/ns/authbridge/sa/agent`
  - Verify:
    - Client ID: `spiffe://localtest.me/ns/authbridge/sa/agent` (full SPIFFE ID!)
    - Client Authenticator: `Signed JWT - Federated`
    - Credential: `federated-jwt` issuer = `spire-spiffe`

### Step 3: Deploy Test Workload

- [ ] **Create namespace**:
  ```bash
  kubectl create namespace authbridge
  ```

- [ ] **Deploy test workload**:
  ```bash
  kubectl apply -f spiffe-keycloak/client_deployment.yaml
  ```

- [ ] **Verify deployment**:
  ```bash
  kubectl get pods -n authbridge
  # Should show: spiffe-keycloak-test pod Running
  ```

### Step 4: Register Workload with SPIRE

- [ ] **Run registration script**:
  ```bash
  cd /Users/alan/Documents/Work/kagenti
  ./spiffe-keycloak/register_workload.sh
  ```

- [ ] **Verify workload registered**:
  ```bash
  kubectl exec -n spire-server spire-server-0 -- \
    /opt/spire/bin/spire-server entry show -spiffeID spiffe://localtest.me/ns/authbridge/sa/agent
  ```

### Step 5: Run Authentication Test

- [ ] **Wait for SPIRE agent to sync** (30 seconds):
  ```bash
  sleep 30
  ```

- [ ] **Run test**:
  ```bash
  cd /Users/alan/Documents/Work/kagenti
  ./spiffe-keycloak/run_test.sh test
  ```

- [ ] **Expected output**:
  ```
  Response status: 200
  ✅ Successfully authenticated!
    Access token: eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6IC...
    Token type: Bearer
    Expires in: 299 seconds
  ```

## 🔍 Verification Commands

### Check JWT-SVID Claims

```bash
kubectl exec -n authbridge deployment/spiffe-keycloak-test -c test-client -- python3 -c "
import jwt
with open('/opt/jwt_svid.token', 'r') as f:
    token = f.read().strip()
    claims = jwt.decode(token, options={'verify_signature': False})
    print('JWT-SVID Claims:')
    for k, v in claims.items():
        print(f'  {k}: {v}')
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
    "use": "sig",  // ← Must be present!
    "kty": "RSA",
    "kid": "...",
    ...
  }]
}
```

### Check Keycloak Logs

```bash
kubectl logs -n keycloak pod/keycloak-0 --tail=50 | grep -E "CLIENT|federated|ERROR"
```

**Success:** No errors, should see successful authentication logs

## ⚠️ Common Issues

### Issue 1: "Issuer does not support client assertions"
- **Cause**: Using OIDC provider instead of SPIFFE
- **Fix**: Ensure `providerId: "spiffe"` in Identity Provider config

### Issue 2: Empty "SPIFFE Bundle or OIDC JWKs endpoint" field
- **Cause**: Using `jwksUrl` instead of `bundleEndpoint`
- **Fix**: Use `bundleEndpoint` field name in SPIFFE provider config

### Issue 3: "Client authentication did not complete"
- **Cause**: SPIRE JWKS missing "use" field
- **Fix**: Add `set_key_use: true` to SPIRE OIDC discovery provider config

### Issue 4: "client_id parameter does not match sub claim"
- **Cause**: Using simple client ID instead of full SPIFFE ID
- **Fix**: Set `clientId: "spiffe://localtest.me/ns/authbridge/sa/agent"`

### Issue 5: "Invalid token audience"
- **Cause**: JWT audience is internal URL, Keycloak expects external issuer URL
- **Fix**: Set `jwt_audience="http://keycloak.localtest.me:8080/realms/demo"` in spiffe-helper.conf

### Issue 6: Wrong assertion type
- **Cause**: Using `jwt-bearer` instead of `jwt-spiffe`
- **Fix**: Use `urn:ietf:params:oauth:client-assertion-type:jwt-spiffe`

## 📚 Reference Files

All files are in `/Users/alan/Documents/Work/kagenti/spiffe-keycloak/`:

- **`README.md`** - Comprehensive documentation with detailed obstacle explanations
- **`keycloak_federated_client.py`** - Keycloak setup script (run this!)
- **`client_deployment.yaml`** - Test workload deployment
- **`register_workload.sh`** - SPIRE workload registration
- **`run_test.sh`** - Authentication test runner
- **`test_spiffe_auth.py`** - Standalone test script (alternative)
- **`utilties.py`** - Helper functions
- **`SUMMARY.md`** - Executive summary
- **`GITHUB_ISSUES_ANALYSIS.md`** - Alternative approaches analysis

## 🎯 Success Criteria

When everything is configured correctly, you should see:

✅ **Authentication Response (200 OK)**:
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6IC...",
  "token_type": "Bearer",
  "expires_in": 299
}
```

This proves that SPIFFE workload identities can successfully authenticate to Keycloak using federated client authentication!

## 🔗 External References

- [Keycloak Federated Client Authentication Blog](https://www.keycloak.org/2026/01/federated-client-authentication)
- [Keycloak PR #43656](https://github.com/keycloak/keycloak/pull/43656) - SPIFFE support
- [SPIRE PR #2634](https://github.com/spiffe/spire/pull/2634) - set_key_use configuration
- [Keycloak Issue #42634](https://github.com/keycloak/keycloak/issues/42634) - Federated auth tracking

---

**Last Updated**: 2026-02-18
**Status**: ✅ WORKING
