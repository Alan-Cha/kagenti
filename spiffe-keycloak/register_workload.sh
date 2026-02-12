#!/bin/bash
# register_workload.sh
#
# Helper script to register a SPIFFE ID in SPIRE for the Keycloak demo.
# This simplifies the registration process and explains each step.

set -e

# Configuration
SPIRE_NAMESPACE="spire-server"
SPIRE_SERVER_POD="spire-server-0"
TRUST_DOMAIN="localtest.me"

# SPIFFE ID for the test workload
WORKLOAD_SPIFFE_ID="spiffe://${TRUST_DOMAIN}/ns/authbridge/sa/agent"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "============================================================"
echo "SPIRE Workload Registration Helper"
echo "============================================================"
echo ""
echo "This script will register a SPIFFE ID for the Keycloak demo:"
echo "  SPIFFE ID: ${WORKLOAD_SPIFFE_ID}"
echo ""

# Check if SPIRE namespace exists
echo "Checking SPIRE installation..."
if ! kubectl get namespace "${SPIRE_NAMESPACE}" &>/dev/null; then
    echo -e "${RED}[ERROR]${NC} SPIRE namespace '${SPIRE_NAMESPACE}' not found"
    echo ""
    echo "Available namespaces:"
    kubectl get namespaces | grep -i spire || echo "  No SPIRE namespaces found"
    echo ""
    echo "Please update SPIRE_NAMESPACE in this script to match your environment."
    exit 1
fi

# Check if SPIRE server pod exists
if ! kubectl get pod -n "${SPIRE_NAMESPACE}" "${SPIRE_SERVER_POD}" &>/dev/null; then
    echo -e "${RED}[ERROR]${NC} SPIRE server pod '${SPIRE_SERVER_POD}' not found"
    echo ""
    echo "Available SPIRE server pods:"
    kubectl get pods -n "${SPIRE_NAMESPACE}" | grep spire-server || echo "  No SPIRE server pods found"
    echo ""
    echo "Please update SPIRE_SERVER_POD in this script to match your environment."
    exit 1
fi

echo -e "${GREEN}[OK]${NC} SPIRE installation found"
echo ""

# List existing agents to help determine parent ID
echo "============================================================"
echo "Step 1: Finding SPIRE Agents"
echo "============================================================"
echo ""
echo "SPIRE agents running in your cluster:"
echo ""

AGENT_LIST=$(kubectl exec -n "${SPIRE_NAMESPACE}" "${SPIRE_SERVER_POD}" -- \
    /opt/spire/bin/spire-server agent list 2>/dev/null || echo "")

if [ -z "$AGENT_LIST" ]; then
    echo -e "${RED}[ERROR]${NC} Could not list SPIRE agents"
    exit 1
fi

echo "$AGENT_LIST"
echo ""

# Extract the first agent's SPIFFE ID as parent
PARENT_ID=$(echo "$AGENT_LIST" | grep "SPIFFE ID" | head -1 | awk '{print $4}')

if [ -z "$PARENT_ID" ]; then
    echo -e "${RED}[ERROR]${NC} Could not determine parent agent SPIFFE ID"
    echo "Please check that SPIRE agents are running:"
    echo "  kubectl get pods -n ${SPIRE_NAMESPACE} -l app=spire-agent"
    exit 1
fi

echo -e "${GREEN}[OK]${NC} Using parent agent: ${PARENT_ID}"
echo ""

# Check if entry already exists
echo "============================================================"
echo "Step 2: Checking Existing Registrations"
echo "============================================================"
echo ""

EXISTING_ENTRIES=$(kubectl exec -n "${SPIRE_NAMESPACE}" "${SPIRE_SERVER_POD}" -- \
    /opt/spire/bin/spire-server entry show 2>/dev/null || echo "")

if echo "$EXISTING_ENTRIES" | grep -q "$WORKLOAD_SPIFFE_ID"; then
    echo -e "${YELLOW}[WARNING]${NC} Entry for ${WORKLOAD_SPIFFE_ID} already exists"
    echo ""
    echo "Existing entry details:"
    echo "$EXISTING_ENTRIES" | grep -A 10 "$WORKLOAD_SPIFFE_ID"
    echo ""
    read -p "Do you want to delete and recreate it? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ENTRY_ID=$(echo "$EXISTING_ENTRIES" | grep -B 5 "$WORKLOAD_SPIFFE_ID" | grep "Entry ID" | awk '{print $4}')
        if [ -n "$ENTRY_ID" ]; then
            echo "Deleting existing entry..."
            kubectl exec -n "${SPIRE_NAMESPACE}" "${SPIRE_SERVER_POD}" -- \
                /opt/spire/bin/spire-server entry delete -entryID "$ENTRY_ID"
            echo -e "${GREEN}[OK]${NC} Deleted existing entry"
            echo ""
        fi
    else
        echo "Keeping existing entry. Exiting."
        exit 0
    fi
fi

# Create the registration entry
echo "============================================================"
echo "Step 3: Creating Registration Entry"
echo "============================================================"
echo ""
echo "Creating entry with:"
echo "  SPIFFE ID:  ${WORKLOAD_SPIFFE_ID}"
echo "  Parent ID:  ${PARENT_ID}"
echo "  Selector:   unix:uid:$(id -u) (for local testing)"
echo ""
echo "NOTE: For Kubernetes pods, you would use selectors like:"
echo "  -selector k8s:ns:authbridge"
echo "  -selector k8s:sa:agent"
echo ""

kubectl exec -n "${SPIRE_NAMESPACE}" "${SPIRE_SERVER_POD}" -- \
    /opt/spire/bin/spire-server entry create \
    -spiffeID "${WORKLOAD_SPIFFE_ID}" \
    -parentID "${PARENT_ID}" \
    -selector "unix:uid:$(id -u)"

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}[SUCCESS]${NC} Registration entry created!"
else
    echo ""
    echo -e "${RED}[ERROR]${NC} Failed to create registration entry"
    exit 1
fi

# Verify the entry
echo ""
echo "============================================================"
echo "Step 4: Verifying Registration"
echo "============================================================"
echo ""

kubectl exec -n "${SPIRE_NAMESPACE}" "${SPIRE_SERVER_POD}" -- \
    /opt/spire/bin/spire-server entry show -spiffeID "${WORKLOAD_SPIFFE_ID}"

echo ""
echo "============================================================"
echo "Registration Complete!"
echo "============================================================"
echo ""
echo "What just happened:"
echo ""
echo "1. We found the SPIRE agent running on your node"
echo "2. We created a registration entry that tells SPIRE:"
echo "   'When a process running as uid $(id -u) on this node requests"
echo "   an identity, issue it the SPIFFE ID:"
echo "   ${WORKLOAD_SPIFFE_ID}'"
echo ""
echo "Now you can run the test script:"
echo "  python test_spiffe_auth.py"
echo ""
echo "The script will:"
echo "1. Connect to the SPIRE agent's Workload API socket"
echo "2. Request a JWT-SVID for the registered SPIFFE ID"
echo "3. Use that JWT-SVID to authenticate to Keycloak"
echo ""
