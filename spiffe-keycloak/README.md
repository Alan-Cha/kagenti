# SPIFFE + Keycloak Federated Client Authentication

This directory contains scripts and configurations for testing SPIFFE JWT-SVID authentication with Keycloak's federated client authentication feature.

## Overview

The goal is to enable workloads with SPIFFE identities (issued by SPIRE) to authenticate to Keycloak using JWT-SVIDs as client credentials, without needing traditional client secrets.

**Status**: ⚠️ **NOT WORKING** - Configuration is correct but authentication fails (see Known Issues below)

## Authentication Flow

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
       │  (signed by SPIRE)               │                                   │
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
       │                                  │     ❌ FAILS HERE!                │
       │                                                                      │
       │  5. ❌ 401 Unauthorized                                              │
       │<─────────────────────────────────────────────────────────────────────│
```

## Prerequisites

- Keycloak 26.5.2+ with preview features enabled:
  - `client-auth-federated:v1`
  - `spiffe:v1`
- SPIRE server with OIDC Discovery Provider deployed
- Python 3.11+ with `python-keycloak` package

## Quick Start

### 1. Configure Keycloak

Run the setup script to configure Keycloak with the SPIFFE identity provider:

```bash
# From repository root
cd spiffe-keycloak
python keycloak_federated_client.py
```

This script:
- Creates the `demo` realm (if it doesn't exist)
- Creates a **SPIFFE** identity provider (NOT OIDC!)
- Registers a client configured for federated JWT authentication

### 2. Deploy Test Workload

Deploy the test pod with SPIFFE workload registration:

```bash
kubectl apply -f client_deployment.yaml
./register_workload.sh
```

### 3. Run Authentication Test

```bash
./run_test.sh test
```

## Key Configuration Details

### ⚠️ CRITICAL: Use SPIFFE Provider, Not OIDC!

**You MUST use `providerId: "spiffe"`, NOT `"oidc"`**

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

**Key Fields:**
- `trustDomain`: Must be in `spiffe://` format
- `bundleEndpoint`: NOT `jwksUrl`! This is the SPIFFE-specific field name for the Keycloak UI

### Client Configuration

```json
{
  "clientId": "federated-agent-a",
  "clientAuthenticatorType": "federated-jwt",
  "serviceAccountsEnabled": true,
  "attributes": {
    "jwt.credential.issuer": "spire-spiffe",  // References the IdP alias
    "jwt.credential.sub": "spiffe://localtest.me/ns/authbridge/sa/agent"
  }
}
```

## Known Issues

### 🔴 Issue: Authentication Fails Despite Correct Configuration

**Symptom:**
```
Response status: 401
{"error":"invalid_client","error_description":"Invalid client or Invalid client credentials"}
```

**Keycloak Log:**
```
WARN  [org.keycloak.authentication.ClientAuthenticationFlow]
Client authentication was attempted did not complete for federated-jwt
error="invalid_client_credentials"
client_assertion_issuer="http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local"
client_assertion_sub="spiffe://localtest.me/ns/authbridge/sa/agent"
```

**Root Cause:**
The JWT-SVID issued by SPIRE contains:
- `iss: http://spire-spiffe-oidc-discovery-provider.spire-server.svc.cluster.local` (HTTP URL)

But Keycloak's SPIFFE provider appears to expect the issuer to match the trust domain format:
- Expected: `iss: spiffe://localtest.me` (or derived from trust domain)

**Status**:
- ✅ Configuration is correct per Keycloak 26.5.2 documentation
- ❌ This appears to be a **compatibility gap** between SPIRE's JWT-SVID format and Keycloak's `spiffe:v1` preview feature
- ⚠️ The `spiffe:v1` feature is still in **preview** and may have incomplete SPIRE support
- Related GitHub issues:
  - https://github.com/keycloak/keycloak/issues/41907 - SPIFFE/SPIRE support request
  - https://github.com/keycloak/keycloak/issues/42634 - Federated client authentication tracking issue

### Why the `jti` Claim Doesn't Matter

Initially, we thought the missing `jti` (JWT ID) claim was the issue:
- ❌ SPIRE JWT-SVIDs don't include `jti` by design
- ✅ Keycloak's **SPIFFE provider** is designed to work **without** `jti`
- ✅ When using OIDC provider, Keycloak requires `jti` for replay protection
- ✅ The SPIFFE provider type handles this correctly

**The real issue is the issuer format, not the missing `jti`.**

## Investigation Timeline

### What We Tried

1. **❌ Used OIDC Provider** (Wrong approach)
   - Configuration: `providerId: "oidc"`
   - Error: "Issuer does not support client assertions"
   - Cause: Keycloak was checking SPIRE's discovery document for OAuth2 capabilities

2. **✅ Switched to SPIFFE Provider** (Correct approach)
   - Configuration: `providerId: "spiffe"`
   - Error changed to: "Client authentication did not complete"
   - Progress! SPIFFE provider accepts JWTs without `jti`

3. **✅ Added `bundleEndpoint` Field**
   - Required field for SPIFFE provider (not `jwksUrl`)
   - Configuration is now correct per Keycloak documentation

4. **✅ Verified All Configuration**
   - Trust domain: `spiffe://localtest.me` ✓
   - Bundle endpoint accessible ✓
   - Client configured with `federated-jwt` ✓
   - Preview features enabled ✓

5. **❌ Still Failing**
   - Issuer format mismatch between SPIRE (HTTP URL) and Keycloak expectations
   - This appears to be a limitation in Keycloak's preview implementation

## Alternative Approaches to Investigate

### Option 1: Configure SPIRE to Use SPIFFE URI as Issuer

Check if SPIRE can be configured to issue JWTs with `iss: spiffe://localtest.me` instead of the HTTP URL.

**Relevant SPIRE Configuration:**
```yaml
# In deployments/envs/dev_values.yaml
spire:
  enabled: true
  values:
    global:
      spire:
        jwtIssuer: "http://spire-spiffe-oidc-discovery-provider..."
        # Can this be changed to: "spiffe://localtest.me" ?
```

**Risks:**
- May break JWT signature validation
- JWKS endpoint expects HTTP(S) URLs in standard OIDC format
- SPIFFE spec may not allow SPIFFE URIs as issuers in JWT-SVIDs

### Option 2: Wait for Keycloak Fix

Since `spiffe:v1` is a preview feature, this might be resolved in future Keycloak releases.

**Action:**
- Monitor Keycloak GitHub issues
- Test with newer Keycloak versions when available
- File a detailed bug report if not already tracked

### Option 3: Use SPIFFE X.509 SVIDs Instead

The federated authentication feature also supports X.509 certificates. SPIFFE X.509 SVIDs might have better support.

**Pros:**
- X.509 authentication is more mature
- No issuer format issues

**Cons:**
- More complex setup (certificate management)
- Different trust model

### Option 4: Custom Keycloak Authenticator Extension

Develop a custom Keycloak authenticator SPI implementation that:
- Accepts SPIRE's HTTP issuer format
- Maps it to the SPIFFE trust domain
- Performs JWT validation directly against SPIRE's JWKS

**Effort:** High, requires Java development

### Option 5: Modify SPIRE OIDC Discovery Provider

Create a wrapper/proxy that:
- Intercepts JWT-SVID issuance
- Modifies the `iss` claim to match Keycloak expectations
- Maintains compatibility with signature validation

**Effort:** Medium, requires understanding SPIRE internals

## Files

### Core Scripts
- `keycloak_federated_client.py` - ✅ Main setup script (configures SPIFFE provider)
- `client_deployment.yaml` - Test workload deployment with SPIFFE helper
- `register_workload.sh` - Registers workload with SPIRE
- `run_test.sh` - Wrapper script for deployment and testing
- `utilties.py` - Helper functions for JWT-SVID handling

### Documentation
- `README.md` - This file
- `TEST_GUIDE.md` - Detailed testing instructions
- `SPIRE_CONCEPTS.md` - SPIFFE/SPIRE concepts reference

### Configuration (Legacy/Reference)
- `keycloak_statefulset.yaml` - Modified Keycloak deployment (if needed)
- `test_deployment.yaml` - Alternative test deployment
- `spire-oidc-httproute.yaml` - HTTPRoute for SPIRE OIDC discovery

## Troubleshooting

### Check Keycloak Logs
```bash
kubectl logs -n keycloak pod/keycloak-0 --since=5m | grep -E "CLIENT|federated|ERROR"
```

### Check SPIRE Logs
```bash
kubectl logs -n spire-server deployment/spire-server
```

### Verify JWT-SVID Claims
```bash
kubectl exec -n authbridge deployment/spiffe-keycloak-test -c test-client -- \
  python3 -c "
import jwt
with open('/opt/jwt_svid.token', 'r') as f:
    token = f.read().strip()
    claims = jwt.decode(token, options={'verify_signature': False})
    print('JWT Claims:')
    for k, v in claims.items():
        print(f'  {k}: {v}')
"
```

### Verify Keycloak Configuration
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

# Check SPIFFE IdP
idps = kc.get_idps()
spiffe_idp = next((p for p in idps if p.get('alias') == 'spire-spiffe'), None)
print('SPIFFE IdP Config:')
print(json.dumps(spiffe_idp, indent=2))
\"
"
```

## References

- [Keycloak Federated Client Authentication Blog](https://www.keycloak.org/2026/01/federated-client-authentication)
- [Keycloak Server Admin Guide - SPIFFE](https://www.keycloak.org/docs/latest/server_admin/index.html)
- [Keycloak GitHub Issue #41907](https://github.com/keycloak/keycloak/issues/41907) - SPIFFE/SPIRE support
- [Keycloak GitHub Issue #42634](https://github.com/keycloak/keycloak/issues/42634) - Federated auth tracking
- [SPIFFE Specification](https://github.com/spiffe/spiffe/blob/main/standards/SPIFFE.md)
- [SPIRE Documentation](https://spiffe.io/docs/latest/spire-about/)

## Contributing

If you find a solution or workaround, please update this README and submit a PR!

## Questions?

- Check Keycloak logs for detailed error messages
- Enable Keycloak debug logging for more details
- Review the GitHub issues linked above for updates
- Check SPIRE configuration and JWKS endpoint accessibility
