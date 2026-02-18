#!/bin/bash
# patch_spire_config.sh
#
# Patches SPIRE ConfigMaps to enable SPIFFE + Keycloak integration
# This script updates the existing SPIRE deployment without requiring a full reinstall.
#
# What it does:
# 1. Updates spire-server ConfigMap to set jwtIssuer to SPIFFE URI format
# 2. Updates spire-spiffe-oidc-discovery-provider ConfigMap to add set_key_use: true
# 3. Restarts SPIRE components to apply changes
#
# Usage:
#   ./spiffe-keycloak/patch_spire_config.sh [--namespace spire-server]

set -e

# Configuration
SPIRE_NAMESPACE="${1:-spire-server}"
SPIFFE_TRUST_DOMAIN="spiffe://localtest.me"

echo "=========================================="
echo "SPIRE ConfigMap Patcher for Keycloak"
echo "=========================================="
echo ""
echo "Namespace: $SPIRE_NAMESPACE"
echo "Trust Domain: $SPIFFE_TRUST_DOMAIN"
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl not found. Please install kubectl."
    exit 1
fi

# Check if namespace exists
if ! kubectl get namespace "$SPIRE_NAMESPACE" &> /dev/null; then
    echo "❌ Namespace '$SPIRE_NAMESPACE' does not exist."
    echo "   Make sure SPIRE is deployed."
    exit 1
fi

echo "🔍 Checking SPIRE ConfigMaps..."

# Check spire-server ConfigMap
if ! kubectl get configmap spire-server -n "$SPIRE_NAMESPACE" &> /dev/null; then
    echo "⚠️  Warning: spire-server ConfigMap not found. Skipping server config update."
    UPDATE_SERVER=false
else
    UPDATE_SERVER=true
fi

# Check spire-spiffe-oidc-discovery-provider ConfigMap
if ! kubectl get configmap spire-spiffe-oidc-discovery-provider -n "$SPIRE_NAMESPACE" &> /dev/null; then
    echo "❌ spire-spiffe-oidc-discovery-provider ConfigMap not found."
    echo "   This is required for Keycloak integration."
    exit 1
fi

echo ""
echo "📝 Backing up current ConfigMaps..."
kubectl get configmap spire-server -n "$SPIRE_NAMESPACE" -o yaml > /tmp/spire-server-backup.yaml 2>/dev/null || true
kubectl get configmap spire-spiffe-oidc-discovery-provider -n "$SPIRE_NAMESPACE" -o yaml > /tmp/spire-oidc-discovery-backup.yaml
echo "   Backups saved to /tmp/spire-*.yaml"

echo ""
echo "🔧 Patching SPIRE ConfigMaps..."

# Patch 1: Update spire-server jwtIssuer
if [ "$UPDATE_SERVER" = true ]; then
    echo ""
    echo "1️⃣  Updating spire-server ConfigMap..."
    echo "   Setting jwt_issuer to: $SPIFFE_TRUST_DOMAIN"

    # Get current config
    CURRENT_CONFIG=$(kubectl get configmap spire-server -n "$SPIRE_NAMESPACE" -o jsonpath='{.data.server\.conf}')

    # Check if jwt_issuer already set correctly
    if echo "$CURRENT_CONFIG" | grep -q "jwt_issuer.*$SPIFFE_TRUST_DOMAIN"; then
        echo "   ✅ jwt_issuer already set correctly"
    else
        # Patch the ConfigMap
        kubectl get configmap spire-server -n "$SPIRE_NAMESPACE" -o json | \
          jq --arg jwtIssuer "$SPIFFE_TRUST_DOMAIN" \
            '.data["server.conf"] |= (. |
              if . | contains("jwt_issuer") then
                gsub("jwt_issuer\\s*=\\s*\"[^\"]*\""; "jwt_issuer = \"\($jwtIssuer)\"")
              else
                . + "\n  jwt_issuer = \"\($jwtIssuer)\"\n"
              end
            )' | \
          kubectl apply -f -
        echo "   ✅ spire-server ConfigMap updated"
    fi
else
    echo "1️⃣  Skipping spire-server ConfigMap (not found)"
fi

# Patch 2: Update spire-spiffe-oidc-discovery-provider set_key_use
echo ""
echo "2️⃣  Updating spire-spiffe-oidc-discovery-provider ConfigMap..."
echo "   Adding set_key_use: true"

# Get current config
CURRENT_OIDC_CONFIG=$(kubectl get configmap spire-spiffe-oidc-discovery-provider -n "$SPIRE_NAMESPACE" -o jsonpath='{.data.oidc-discovery-provider\.conf}')

# Check if set_key_use already exists
if echo "$CURRENT_OIDC_CONFIG" | grep -q "set_key_use"; then
    echo "   ✅ set_key_use already configured"
else
    # Patch the ConfigMap to add set_key_use
    kubectl get configmap spire-spiffe-oidc-discovery-provider -n "$SPIRE_NAMESPACE" -o json | \
      jq '.data["oidc-discovery-provider.conf"] |= (fromjson | .set_key_use = true | tojson)' | \
      kubectl apply -f -
    echo "   ✅ spire-spiffe-oidc-discovery-provider ConfigMap updated"
fi

echo ""
echo "♻️  Restarting SPIRE components to apply changes..."

# Restart spire-server (StatefulSet)
if [ "$UPDATE_SERVER" = true ]; then
    echo "   Restarting spire-server..."
    kubectl rollout restart statefulset/spire-server -n "$SPIRE_NAMESPACE"
    echo "   Waiting for spire-server rollout..."
    kubectl rollout status statefulset/spire-server -n "$SPIRE_NAMESPACE" --timeout=2m
fi

# Restart spire-spiffe-oidc-discovery-provider (Deployment)
echo "   Restarting spire-spiffe-oidc-discovery-provider..."
kubectl rollout restart deployment/spire-spiffe-oidc-discovery-provider -n "$SPIRE_NAMESPACE"
echo "   Waiting for spire-spiffe-oidc-discovery-provider rollout..."
kubectl rollout status deployment/spire-spiffe-oidc-discovery-provider -n "$SPIRE_NAMESPACE" --timeout=2m

echo ""
echo "✅ SPIRE configuration patched successfully!"
echo ""
echo "🔍 Verification commands:"
echo ""
echo "1. Verify JWT issuer in SPIRE server:"
echo "   kubectl exec -n $SPIRE_NAMESPACE spire-server-0 -- \\"
echo "     /opt/spire/bin/spire-server token generate -spiffeID spiffe://localtest.me/test"
echo ""
echo "2. Verify JWKS has 'use' field:"
echo "   kubectl run test-curl --rm -i --image=curlimages/curl --restart=Never -- \\"
echo "     curl -s http://spire-spiffe-oidc-discovery-provider.$SPIRE_NAMESPACE.svc.cluster.local/keys"
echo "   Look for: \"use\": \"sig\" in each key"
echo ""
echo "3. Check JWT-SVID from a workload:"
echo "   kubectl exec -n authbridge deployment/spiffe-keycloak-test -c test-client -- \\"
echo "     python3 -c \"import jwt; print(jwt.decode(open('/opt/jwt_svid.token').read(), options={'verify_signature': False}))\""
echo "   Expected: iss: spiffe://localtest.me"
echo ""
echo "📋 Next steps:"
echo "1. Configure Keycloak: python spiffe-keycloak/keycloak_federated_client.py"
echo "2. Deploy test workload: kubectl apply -f spiffe-keycloak/client_deployment.yaml"
echo "3. Register workload: ./spiffe-keycloak/register_workload.sh"
echo "4. Run test: ./spiffe-keycloak/run_test.sh test"
echo ""
echo "🔙 To restore original configuration:"
echo "   kubectl apply -f /tmp/spire-server-backup.yaml"
echo "   kubectl apply -f /tmp/spire-oidc-discovery-backup.yaml"
echo "   kubectl rollout restart statefulset/spire-server -n $SPIRE_NAMESPACE"
echo "   kubectl rollout restart deployment/spire-spiffe-oidc-discovery-provider -n $SPIRE_NAMESPACE"
