#!/bin/bash
# patch_keycloak_config.sh
#
# Patches Keycloak StatefulSet to enable SPIFFE federated authentication support
# This script updates the existing Keycloak deployment without requiring a full reinstall.
#
# What it does:
# 1. Upgrades Keycloak image to version 26.5.2 (required for SPIFFE support)
# 2. Enables preview features: client-auth-federated:v1, spiffe:v1
# 3. Restarts Keycloak to apply changes
#
# Usage:
#   ./spiffe-keycloak/patch_keycloak_config.sh [--namespace keycloak]

set -e

# Configuration
KEYCLOAK_NAMESPACE="${1:-keycloak}"
KEYCLOAK_IMAGE_TAG="26.5.2"
KEYCLOAK_FEATURES="client-auth-federated:v1,spiffe:v1"

echo "=========================================="
echo "Keycloak Patcher for SPIFFE Support"
echo "=========================================="
echo ""
echo "Namespace: $KEYCLOAK_NAMESPACE"
echo "Image Tag: $KEYCLOAK_IMAGE_TAG"
echo "Features: $KEYCLOAK_FEATURES"
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl not found. Please install kubectl."
    exit 1
fi

# Check if namespace exists
if ! kubectl get namespace "$KEYCLOAK_NAMESPACE" &> /dev/null; then
    echo "❌ Namespace '$KEYCLOAK_NAMESPACE' does not exist."
    echo "   Make sure Keycloak is deployed."
    exit 1
fi

echo "🔍 Checking Keycloak StatefulSet..."

# Check Keycloak StatefulSet
if ! kubectl get statefulset keycloak -n "$KEYCLOAK_NAMESPACE" &> /dev/null; then
    echo "❌ Keycloak StatefulSet not found."
    echo "   Make sure Keycloak is deployed in namespace '$KEYCLOAK_NAMESPACE'."
    exit 1
fi

# Get current image tag
CURRENT_IMAGE=$(kubectl get statefulset keycloak -n "$KEYCLOAK_NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}')
echo "   Current image: $CURRENT_IMAGE"

# Get current KC_FEATURES if set
CURRENT_FEATURES=$(kubectl get statefulset keycloak -n "$KEYCLOAK_NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="KC_FEATURES")].value}' || echo "")
if [ -n "$CURRENT_FEATURES" ]; then
    echo "   Current KC_FEATURES: $CURRENT_FEATURES"
else
    echo "   Current KC_FEATURES: (not set)"
fi

echo ""
echo "📝 Backing up current StatefulSet..."
kubectl get statefulset keycloak -n "$KEYCLOAK_NAMESPACE" -o yaml > /tmp/keycloak-statefulset-backup.yaml
echo "   Backup saved to /tmp/keycloak-statefulset-backup.yaml"

echo ""
echo "🔧 Patching Keycloak StatefulSet..."

# Check if image and features are already correct
IMAGE_NEEDS_UPDATE=false
FEATURES_NEED_UPDATE=false

if [[ ! "$CURRENT_IMAGE" =~ :$KEYCLOAK_IMAGE_TAG$ ]]; then
    IMAGE_NEEDS_UPDATE=true
fi

if [ "$CURRENT_FEATURES" != "$KEYCLOAK_FEATURES" ]; then
    FEATURES_NEED_UPDATE=true
fi

if [ "$IMAGE_NEEDS_UPDATE" = false ] && [ "$FEATURES_NEED_UPDATE" = false ]; then
    echo "   ✅ Keycloak already configured correctly"
    echo "   - Image: $(echo $CURRENT_IMAGE | grep -o '[^:]*$')"
    echo "   - Features: $CURRENT_FEATURES"
    exit 0
fi

# Prepare patch operations
PATCH_OPS="["

# Update image tag if needed
if [ "$IMAGE_NEEDS_UPDATE" = true ]; then
    echo "   Updating image to: quay.io/keycloak/keycloak:$KEYCLOAK_IMAGE_TAG"
    IMAGE_PATCH='{"op":"replace","path":"/spec/template/spec/containers/0/image","value":"quay.io/keycloak/keycloak:'$KEYCLOAK_IMAGE_TAG'"}'
    PATCH_OPS="$PATCH_OPS$IMAGE_PATCH"
fi

# Update KC_FEATURES if needed
if [ "$FEATURES_NEED_UPDATE" = true ]; then
    echo "   Updating KC_FEATURES to: $KEYCLOAK_FEATURES"

    # Check if KC_FEATURES env var exists
    if [ -n "$CURRENT_FEATURES" ]; then
        # Update existing KC_FEATURES
        ENV_INDEX=$(kubectl get statefulset keycloak -n "$KEYCLOAK_NAMESPACE" -o json | jq '.spec.template.spec.containers[0].env | map(.name == "KC_FEATURES") | index(true)')
        FEATURES_PATCH='{"op":"replace","path":"/spec/template/spec/containers/0/env/'$ENV_INDEX'/value","value":"'$KEYCLOAK_FEATURES'"}'
    else
        # Add new KC_FEATURES env var
        FEATURES_PATCH='{"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"KC_FEATURES","value":"'$KEYCLOAK_FEATURES'"}}'
    fi

    if [ "$IMAGE_NEEDS_UPDATE" = true ]; then
        PATCH_OPS="$PATCH_OPS,$FEATURES_PATCH"
    else
        PATCH_OPS="$PATCH_OPS$FEATURES_PATCH"
    fi
fi

PATCH_OPS="$PATCH_OPS]"

# Apply patch
kubectl patch statefulset keycloak -n "$KEYCLOAK_NAMESPACE" --type='json' -p="$PATCH_OPS"
echo "   ✅ Keycloak StatefulSet patched"

echo ""
echo "♻️  Waiting for Keycloak to restart..."
kubectl rollout status statefulset/keycloak -n "$KEYCLOAK_NAMESPACE" --timeout=5m

# Wait for Keycloak pod to be ready
echo "   Waiting for Keycloak pod to be ready..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=keycloak -n "$KEYCLOAK_NAMESPACE" --timeout=5m

echo ""
echo "✅ Keycloak patched successfully!"
echo ""
echo "🔍 Verification commands:"
echo ""
echo "1. Check Keycloak pod status:"
echo "   kubectl get pods -n $KEYCLOAK_NAMESPACE"
echo "   Should show: keycloak-0 pod Running with READY 1/1"
echo ""
echo "2. Check Keycloak logs for feature enablement:"
echo "   kubectl logs -n $KEYCLOAK_NAMESPACE pod/keycloak-0 | grep -E \"Preview.*enabled\""
echo "   Should show: Preview feature enabled: client-auth-federated:v1"
echo "   Should show: Preview feature enabled: spiffe:v1"
echo ""
echo "3. Verify Keycloak version:"
echo "   kubectl get statefulset keycloak -n $KEYCLOAK_NAMESPACE -o jsonpath='{.spec.template.spec.containers[0].image}'"
echo "   Should show: quay.io/keycloak/keycloak:$KEYCLOAK_IMAGE_TAG"
echo ""
echo "📋 Next steps:"
echo "1. Port-forward Keycloak (if needed):"
echo "   kubectl port-forward svc/keycloak-service -n $KEYCLOAK_NAMESPACE 8080:8080"
echo ""
echo "2. Run Keycloak setup script:"
echo "   python spiffe-keycloak/keycloak_federated_client.py"
echo ""
echo "3. Verify SPIFFE Identity Provider in Keycloak Admin Console:"
echo "   - Navigate to: demo realm → Identity Providers"
echo "   - Verify: Alias=spire-spiffe, Type=SPIFFE"
echo ""
echo "4. Verify Client created:"
echo "   - Navigate to: demo realm → Clients"
echo "   - Find: spiffe://localtest.me/ns/authbridge/sa/agent"
echo "   - Verify: Client Authenticator = Signed JWT - Federated"
echo ""
echo "🔙 To restore original configuration:"
echo "   kubectl apply -f /tmp/keycloak-statefulset-backup.yaml"
echo "   kubectl rollout status statefulset/keycloak -n $KEYCLOAK_NAMESPACE"
