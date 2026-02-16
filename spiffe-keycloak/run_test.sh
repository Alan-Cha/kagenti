#!/bin/bash
set -e

NAMESPACE="authbridge"
POD_LABEL="app.kubernetes.io/name=spiffe-keycloak-test"

echo "=================================================="
echo "SPIFFE + Keycloak Federated Auth Test Runner"
echo "=================================================="

# Function to wait for pod to be ready
wait_for_pod() {
    echo "Waiting for pod to be ready..."
    kubectl wait --for=condition=ready pod -l "$POD_LABEL" -n "$NAMESPACE" --timeout=60s
    echo "✅ Pod is ready"
}

# Function to wait for JWT-SVID to be available
wait_for_jwt() {
    echo "Waiting for JWT-SVID to be available..."
    local max_attempts=30
    local attempt=0

    while [ $attempt -lt $max_attempts ]; do
        if kubectl exec -n "$NAMESPACE" deployment/spiffe-keycloak-test -c test-client -- test -f /opt/jwt_svid.token 2>/dev/null; then
            echo "✅ JWT-SVID file found"
            return 0
        fi
        attempt=$((attempt + 1))
        echo "  Attempt $attempt/$max_attempts - JWT-SVID not ready yet..."
        sleep 2
    done

    echo "❌ JWT-SVID file not found after $max_attempts attempts"
    return 1
}

case "${1:-deploy}" in
    deploy)
        echo ""
        echo "Step 1: Deploying test workload..."
        echo "--------------------------------------------------"
        kubectl apply -f client_deployment.yaml

        echo ""
        echo "Step 2: Waiting for pod to be ready..."
        echo "--------------------------------------------------"
        wait_for_pod

        echo ""
        echo "Step 3: Waiting for JWT-SVID to be available..."
        echo "--------------------------------------------------"
        wait_for_jwt

        echo ""
        echo "✅ Deployment complete!"
        echo ""
        echo "To run the test, execute:"
        echo "  ./run_test.sh test"
        ;;

    test)
        echo ""
        echo "Installing dependencies..."
        echo "--------------------------------------------------"
        kubectl exec -n "$NAMESPACE" deployment/spiffe-keycloak-test -c test-client -- \
            pip install --quiet PyJWT requests

        echo ""
        echo "Running authentication test..."
        echo "--------------------------------------------------"
        kubectl exec -n "$NAMESPACE" deployment/spiffe-keycloak-test -c test-client -- \
            python3 test_auth.py

        exit_code=$?

        echo ""
        if [ $exit_code -eq 0 ]; then
            echo "✅ Test passed successfully!"
        else
            echo "❌ Test failed with exit code $exit_code"
        fi

        exit $exit_code
        ;;

    logs)
        echo ""
        echo "Test client logs:"
        echo "--------------------------------------------------"
        kubectl logs -n "$NAMESPACE" deployment/spiffe-keycloak-test -c test-client --tail=50

        echo ""
        echo "SPIFFE helper logs:"
        echo "--------------------------------------------------"
        kubectl logs -n "$NAMESPACE" deployment/spiffe-keycloak-test -c spiffe-helper --tail=50
        ;;

    debug)
        echo ""
        echo "Debugging information:"
        echo "--------------------------------------------------"

        echo ""
        echo "Pod status:"
        kubectl get pods -n "$NAMESPACE" -l "$POD_LABEL"

        echo ""
        echo "JWT-SVID file check:"
        kubectl exec -n "$NAMESPACE" deployment/spiffe-keycloak-test -c test-client -- \
            ls -lh /opt/ || echo "❌ Could not list /opt/"

        echo ""
        echo "JWT-SVID content (first 100 chars):"
        kubectl exec -n "$NAMESPACE" deployment/spiffe-keycloak-test -c test-client -- \
            cat /opt/jwt_svid.token 2>/dev/null | head -c 100 || echo "❌ Could not read JWT-SVID"

        echo ""
        echo "Environment variables:"
        kubectl exec -n "$NAMESPACE" deployment/spiffe-keycloak-test -c test-client -- \
            env | grep -E "(KEYCLOAK|CLIENT)" || echo "No relevant env vars"
        ;;

    shell)
        echo ""
        echo "Opening shell in test-client container..."
        echo "--------------------------------------------------"
        kubectl exec -it -n "$NAMESPACE" deployment/spiffe-keycloak-test -c test-client -- /bin/bash
        ;;

    delete)
        echo ""
        echo "Deleting test deployment..."
        echo "--------------------------------------------------"
        kubectl delete -f client_deployment.yaml
        echo "✅ Deployment deleted"
        ;;

    *)
        echo "Usage: $0 {deploy|test|logs|debug|shell|delete}"
        echo ""
        echo "Commands:"
        echo "  deploy  - Deploy the test workload"
        echo "  test    - Run the authentication test"
        echo "  logs    - Show logs from both containers"
        echo "  debug   - Show debugging information"
        echo "  shell   - Open a shell in the test container"
        echo "  delete  - Delete the test deployment"
        exit 1
        ;;
esac
