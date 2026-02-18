# File Index - spiffe-keycloak Directory

Complete index of all files in this directory, organized by purpose.

## 📖 Documentation Files (Read These First!)

### **README.md** ⭐ START HERE
- **Purpose**: Comprehensive guide to SPIFFE + Keycloak integration
- **Contents**:
  - Complete obstacle documentation (6 obstacles with explanations)
  - Configuration requirements
  - Authentication flow diagram
  - Troubleshooting commands
  - Success criteria
- **When to read**: First file to read for understanding the integration

### **SETUP_CHECKLIST.md** 📋 STEP-BY-STEP GUIDE
- **Purpose**: Actionable checklist for replicating the setup
- **Contents**:
  - Prerequisites checklist
  - Configuration steps with verification
  - Common issues and fixes
  - Success criteria
- **When to read**: When you want to replicate the setup from scratch

### **CONFIGURATION_CHANGES.md** 🔄 BEFORE/AFTER REFERENCE
- **Purpose**: Quick reference showing exact configuration changes
- **Contents**:
  - Before/after comparisons for each config file
  - Why each change was needed
  - Summary table of all changes
- **When to read**: When you want to see exactly what changed and why

### **SUMMARY.md** 📝 EXECUTIVE SUMMARY
- **Purpose**: High-level summary of the work
- **Contents**:
  - What we accomplished
  - The problem encountered
  - Key learnings
  - Alternative approaches
  - Next steps
- **When to read**: For quick overview or to share with others

### **GITHUB_ISSUES_ANALYSIS.md** 🔍 COMMUNITY RESEARCH
- **Purpose**: Analysis of relevant GitHub issues and community work
- **Contents**:
  - Key Keycloak issues (#41907, #42634)
  - Working examples from other projects
  - Alternative approaches (X.509 SVIDs, Curity Identity Server, etc.)
  - Recommended next steps
- **When to read**: When considering alternatives or contributing upstream

### **FILES_INDEX.md** 📑 THIS FILE
- **Purpose**: Index of all files in the directory
- **When to read**: When navigating the directory

---

## 🔧 Core Implementation Files

### **keycloak_federated_client.py** ✅ SETUP SCRIPT
- **Purpose**: Configure Keycloak with SPIFFE identity provider and client
- **What it does**:
  - Creates `demo` realm (if needed)
  - Creates SPIFFE identity provider (NOT OIDC!)
  - Registers client with SPIFFE ID as clientId
- **Usage**:
  ```bash
  python spiffe-keycloak/keycloak_federated_client.py
  ```
- **Key configuration**:
  - `providerId: "spiffe"`
  - `bundleEndpoint` (not `jwksUrl`)
  - `CLIENT_ID = AGENT_SPIFFE_ID` (full SPIFFE ID)

### **client_deployment.yaml** 🚀 TEST WORKLOAD
- **Purpose**: Kubernetes deployment for testing SPIFFE authentication
- **What it creates**:
  - Namespace: `authbridge`
  - ServiceAccount: `agent`
  - Deployment: `spiffe-keycloak-test` with SPIFFE helper sidecar
  - ConfigMaps: Configuration and test scripts
- **Key configuration**:
  - JWT audience: External Keycloak issuer URL
  - Client ID: Full SPIFFE ID
  - Assertion type: `jwt-spiffe`
- **Usage**:
  ```bash
  kubectl apply -f spiffe-keycloak/client_deployment.yaml
  ```

### **register_workload.sh** 📝 SPIRE REGISTRATION
- **Purpose**: Register the test workload with SPIRE server
- **What it does**:
  - Creates SPIRE entry for `spiffe://localtest.me/ns/authbridge/sa/agent`
  - Maps to Kubernetes service account selector
- **Usage**:
  ```bash
  ./spiffe-keycloak/register_workload.sh
  ```

### **run_test.sh** 🧪 TEST RUNNER
- **Purpose**: Execute authentication test
- **What it does**:
  - Runs test script in the test pod
  - Shows JWT-SVID claims
  - Attempts Keycloak authentication
  - Displays results
- **Usage**:
  ```bash
  ./spiffe-keycloak/run_test.sh test
  ```
- **Expected output**: 200 OK with access token

### **utilties.py** 🔨 HELPER FUNCTIONS
- **Purpose**: Python utility functions for JWT handling
- **Functions**:
  - `get_client_id()`: Extract SPIFFE ID from JWT `sub` claim
  - `get_jwt_svid()`: Read JWT-SVID token from file
- **Used by**: Test scripts in `client_deployment.yaml`

### **patch_spire_config.sh** 🔧 SPIRE CONFIG PATCHER
- **Purpose**: Patch existing SPIRE ConfigMaps without full redeployment
- **What it does**:
  - Backs up current ConfigMaps to `/tmp/`
  - Updates `spire-server` ConfigMap: Sets `jwt_issuer` to SPIFFE URI
  - Updates `spire-spiffe-oidc-discovery-provider` ConfigMap: Adds `set_key_use: true`
  - Restarts SPIRE components automatically
  - Provides verification commands
- **Usage**:
  ```bash
  ./spiffe-keycloak/patch_spire_config.sh
  # Or specify namespace:
  ./spiffe-keycloak/patch_spire_config.sh --namespace spire-server
  ```
- **When to use**: For existing SPIRE deployments; alternative to updating Helm values and redeploying

---

## 🧪 Alternative Test Scripts

### **test_spiffe_auth.py** 🔬 STANDALONE TEST
- **Purpose**: Standalone Python script for testing authentication
- **What it does**:
  - Connects directly to SPIRE Workload API
  - Fetches JWT-SVID programmatically
  - Authenticates to Keycloak
  - Verifies access token
- **Usage**:
  ```bash
  python spiffe-keycloak/test_spiffe_auth.py
  ```
- **Note**: Alternative to the containerized test in `client_deployment.yaml`
- **Requirements**: `spiffe` Python package, access to SPIRE socket

---

## 📚 Reference Files

### **TEST_GUIDE.md** 📖 DETAILED TESTING INSTRUCTIONS
- **Purpose**: Comprehensive testing guide
- **Contents**:
  - Detailed test scenarios
  - Debugging steps
  - Expected outputs
- **When to read**: When troubleshooting test failures

### **SPIRE_CONCEPTS.md** 🎓 SPIFFE/SPIRE CONCEPTS
- **Purpose**: Educational reference for SPIFFE/SPIRE
- **Contents**:
  - SPIFFE ID format
  - Trust domains
  - JWT-SVID structure
  - Workload API concepts
- **When to read**: When learning about SPIFFE/SPIRE fundamentals

### **test_deployment.yaml** 📦 ALTERNATIVE DEPLOYMENT
- **Purpose**: Alternative Kubernetes deployment configuration
- **Note**: Not actively used; `client_deployment.yaml` is the primary test deployment

### **keycloak_statefulset.yaml** 🏢 KEYCLOAK REFERENCE
- **Purpose**: Reference Keycloak StatefulSet configuration
- **Contents**:
  - Keycloak deployment with preview features enabled
  - Required feature flags: `client-auth-federated:v1`, `spiffe:v1`
- **Note**: Reference only; production deployments may differ

### **spire-oidc-httproute.yaml** 🌐 INGRESS ROUTE
- **Purpose**: HTTPRoute for external access to SPIRE OIDC discovery
- **What it does**:
  - Exposes SPIRE OIDC provider at `oidc-discovery.localtest.me`
  - Routes to `spire-spiffe-oidc-discovery-provider` service
- **Usage**:
  ```bash
  kubectl apply -f spiffe-keycloak/spire-oidc-httproute.yaml
  ```
- **Note**: Useful for debugging JWKS from outside the cluster

---

## 📦 Dependency Files

### **requirements.txt** 📋 PYTHON DEPENDENCIES
- **Purpose**: Python package dependencies
- **Contents**:
  - `python-keycloak` - Keycloak Admin API client
  - `PyJWT` - JWT decoding (for testing)
  - `requests` - HTTP client
  - `spiffe` - SPIRE Workload API client
- **Usage**:
  ```bash
  pip install -r spiffe-keycloak/requirements.txt
  ```

### **venv/** 🐍 VIRTUAL ENVIRONMENT
- **Purpose**: Python virtual environment
- **Note**: Created locally, not committed to git
- **Usage**:
  ```bash
  python -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```

---

## 📁 File Organization by Use Case

### 🚀 Quick Start (Minimal Files)
1. **README.md** - Understand the setup
2. **SETUP_CHECKLIST.md** - Follow the checklist
3. **patch_spire_config.sh** - Update SPIRE configuration (if already deployed)
4. **keycloak_federated_client.py** - Configure Keycloak
5. **client_deployment.yaml** - Deploy test workload
6. **register_workload.sh** - Register with SPIRE
7. **run_test.sh** - Run the test

### 🔍 Troubleshooting
1. **README.md** - Troubleshooting section
2. **TEST_GUIDE.md** - Detailed debugging steps
3. **CONFIGURATION_CHANGES.md** - Verify configurations

### 🎓 Learning & Understanding
1. **README.md** - Obstacles and solutions
2. **SUMMARY.md** - High-level overview
3. **SPIRE_CONCEPTS.md** - SPIFFE/SPIRE fundamentals
4. **GITHUB_ISSUES_ANALYSIS.md** - Community research

### 🔧 Development & Customization
1. **CONFIGURATION_CHANGES.md** - See what to change
2. **keycloak_federated_client.py** - Modify Keycloak setup
3. **client_deployment.yaml** - Customize test deployment
4. **test_spiffe_auth.py** - Adapt test script

---

## 🎯 File Status

| File | Status | Last Modified | Purpose |
|------|--------|---------------|---------|
| README.md | ✅ Up-to-date | 2026-02-18 | Main documentation |
| SETUP_CHECKLIST.md | ✅ Up-to-date | 2026-02-18 | Step-by-step guide |
| CONFIGURATION_CHANGES.md | ✅ Up-to-date | 2026-02-18 | Before/after reference |
| FILES_INDEX.md | ✅ Up-to-date | 2026-02-18 | This file |
| SUMMARY.md | ✅ Up-to-date | 2026-02-17 | Executive summary |
| GITHUB_ISSUES_ANALYSIS.md | ✅ Up-to-date | 2026-02-17 | Community analysis |
| keycloak_federated_client.py | ✅ Up-to-date | 2026-02-18 | Uses SPIFFE provider |
| client_deployment.yaml | ✅ Up-to-date | 2026-02-18 | Correct assertion type & client ID |
| test_spiffe_auth.py | ✅ Up-to-date | 2026-02-18 | Updated with correct config |
| utilties.py | ✅ Up-to-date | 2026-02-17 | Helper functions |
| patch_spire_config.sh | ✅ Up-to-date | 2026-02-18 | SPIRE ConfigMap patcher |
| register_workload.sh | ✅ Up-to-date | 2026-02-17 | SPIRE registration |
| run_test.sh | ✅ Up-to-date | 2026-02-17 | Test runner |
| TEST_GUIDE.md | 📖 Reference | 2026-02-17 | Detailed testing |
| SPIRE_CONCEPTS.md | 📖 Reference | 2026-02-17 | Educational |
| test_deployment.yaml | 📦 Archive | 2026-02-17 | Alternative deployment |
| keycloak_statefulset.yaml | 📖 Reference | 2026-02-17 | Deployment example |
| spire-oidc-httproute.yaml | ✅ Up-to-date | 2026-02-17 | Ingress route |
| requirements.txt | ✅ Up-to-date | 2026-02-17 | Python dependencies |

**Legend:**
- ✅ Up-to-date: Current and tested
- 📖 Reference: Documentation, no code changes needed
- 📦 Archive: Kept for reference, not actively used

---

## 🔗 External Dependencies

### SPIRE Configuration Files (Outside This Directory)

1. **`deployments/envs/dev_values.yaml`** ✅ Updated
   - Location: `/Users/alan/Documents/Work/kagenti/deployments/envs/dev_values.yaml`
   - Changes made:
     - Set `jwtIssuer: "spiffe://localtest.me"`
     - Added `spiffe-oidc-discovery-provider.config.set_key_use: true`

2. **SPIRE ConfigMaps (in cluster)** - Can be patched with `patch_spire_config.sh`
   - `spire-server` ConfigMap - Namespace: `spire-server`
     - Set `jwt_issuer: "spiffe://localtest.me"`
   - `spire-spiffe-oidc-discovery-provider` ConfigMap - Namespace: `spire-server`
     - Add `"set_key_use": true`

### Keycloak Configuration (In Cluster)

- Keycloak must be deployed with preview features:
  - `--features=client-auth-federated:v1,spiffe:v1`
- Created by `keycloak_federated_client.py`:
  - SPIFFE Identity Provider in `demo` realm
  - Client with SPIFFE ID as clientId

---

## 💡 Quick Tips

### Which file should I read first?
→ **README.md** - Start here for complete understanding

### How do I replicate this setup?
→ **SETUP_CHECKLIST.md** - Follow the checklist step-by-step

### What exactly changed?
→ **CONFIGURATION_CHANGES.md** - See before/after comparisons

### Why did authentication fail?
→ **README.md** - "Obstacles Encountered and Solutions" section

### How do I run the test?
→ **run_test.sh** - Just execute `./spiffe-keycloak/run_test.sh test`

### Can I use a different approach?
→ **GITHUB_ISSUES_ANALYSIS.md** - See alternative approaches

---

**Last Updated**: 2026-02-18
**Directory Status**: ✅ Complete and working
