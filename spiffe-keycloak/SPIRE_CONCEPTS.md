# SPIRE Concepts - Quick Reference

This document answers common questions about how SPIRE works.

## Do I need to exec into spire-server to register workloads?

**Short answer**: Yes, for manual registration.

**Long answer**: There are three ways to register workloads:

### Method 1: CLI via kubectl exec (Manual)
```bash
kubectl exec -n <namespace> spire-server-0 -- \
  /opt/spire/bin/spire-server entry create \
  -spiffeID spiffe://domain/workload \
  -parentID spiffe://domain/spire/agent/... \
  -selector k8s:ns:my-namespace
```

**Pros**: Direct, simple, good for testing
**Cons**: Manual, not scalable, requires cluster access

### Method 2: Kubernetes CRDs (Automated)
```yaml
apiVersion: spire.spiffe.io/v1alpha1
kind: ClusterSPIFFEID
metadata:
  name: my-workload
spec:
  spiffeIDTemplate: "spiffe://{{ .TrustDomain }}/ns/{{ .PodMeta.Namespace }}"
  podSelector:
    matchLabels:
      app: my-app
```

**Pros**: Declarative, GitOps-friendly, scalable
**Cons**: Requires SPIRE controller manager installed

### Method 3: SPIRE Registration API (Programmatic)
Use the SPIRE gRPC API to register entries programmatically.

**Pros**: Automated, can integrate with other systems
**Cons**: More complex, requires API client

## Do I need to define a SPIFFE ID? Is it not automatically created?

**Answer**: Yes, you must define every SPIFFE ID explicitly.

SPIRE follows a **zero-trust model** - no identities are issued without explicit authorization. This is intentional:

```
❌ Automatic (insecure):
Pod starts → Gets identity automatically → Can do anything

✅ Explicit (secure):
Pod starts → Requests identity → SPIRE checks registration → Identity issued only if authorized
```

### Why Manual Registration is Secure

1. **Principle of Least Privilege**: Only explicitly authorized workloads get identities
2. **Audit Trail**: Every identity must be consciously created
3. **Prevention of Identity Sprawl**: You can't accidentally expose sensitive identities
4. **Clear Authorization Model**: Registration entries serve as identity policy

### SPIFFE ID Format

A SPIFFE ID is a URI that identifies a workload:

```
spiffe://<trust-domain>/<workload-path>
```

Examples:
```
spiffe://localtest.me/ns/authbridge/sa/agent
spiffe://prod.company.com/region/us-west/service/api
spiffe://dev.example.org/k8s/namespace/team1/pod/my-app
```

**You choose** the path structure. Common patterns:
- Kubernetes: `/ns/<namespace>/sa/<service-account>`
- Microservices: `/region/<region>/service/<name>`
- Teams: `/team/<team-name>/service/<service-name>`

## What is a Parent ID and where does it come from?

### The Trust Hierarchy

```
┌─────────────────────────────────────────────────┐
│ SPIRE Server                                    │
│ - Root of trust                                 │
│ - Manages the Certificate Authority (CA)       │
│ - Issues identities to agents                   │
└─────────────┬───────────────────────────────────┘
              │ attests
              ↓
┌─────────────────────────────────────────────────┐
│ SPIRE Agent (one per node/VM)                   │
│ - Gets identity from server via attestation     │
│ - SPIFFE ID: spiffe://domain/spire/agent/...   │
│ - Issues identities to workloads on this node   │
└─────────────┬───────────────────────────────────┘
              │ issues identities (parent-child relationship)
              ↓
┌─────────────────────────────────────────────────┐
│ Workload (your application)                     │
│ - Gets identity from local agent                │
│ - SPIFFE ID: spiffe://domain/your/workload      │
└─────────────────────────────────────────────────┘
```

### What is a Parent ID?

The **Parent ID** is the SPIFFE ID of the SPIRE agent that is authorized to issue a workload's identity.

When you create a registration entry:
```bash
-spiffeID spiffe://localtest.me/my-workload    # Identity to issue
-parentID spiffe://localtest.me/spire/agent/xyz # Agent that can issue it
```

You're saying: *"The agent with ID xyz is authorized to issue identity my-workload"*

### Where Does the Agent's SPIFFE ID Come From?

SPIRE agents get their identities through **attestation** - proving their identity to the server.

Common attestation methods:

#### Kubernetes (k8s_psat)
Agent proves it's running in a specific Kubernetes cluster:
```
spiffe://localtest.me/spire/agent/k8s_psat/cluster-name/node-uid
```

#### Node (x509pop)
Agent proves it's on a specific machine:
```
spiffe://localtest.me/spire/agent/x509pop/machine-id
```

#### AWS (aws_iid)
Agent proves it's an AWS EC2 instance:
```
spiffe://localtest.me/spire/agent/aws_iid/account-id/region/instance-id
```

### Finding Parent IDs

List all agents to see their SPIFFE IDs:

```bash
kubectl exec -n <spire-namespace> spire-server-0 -- \
  /opt/spire/bin/spire-server agent list
```

Output:
```
Found 3 attested agents:

SPIFFE ID         : spiffe://localtest.me/spire/agent/k8s_psat/cluster/node-1-uid
Attestation type  : k8s_psat
Expiration time   : 2026-02-10 12:00:00 +0000 UTC
Serial number     : 123456789

SPIFFE ID         : spiffe://localtest.me/spire/agent/k8s_psat/cluster/node-2-uid
...
```

Use any of these SPIFFE IDs as the `-parentID` when registering workloads.

### Why Do We Need Parent IDs?

**Security**: Parent IDs ensure workloads can only get identities from authorized agents.

Without parent IDs:
```
❌ Any agent could issue any identity (insecure)
```

With parent IDs:
```
✅ Only agent on node-1 can issue identity for workload-A
✅ Only agent on node-2 can issue identity for workload-B
```

This prevents:
- Compromised agents from issuing arbitrary identities
- Workloads on one node from impersonating workloads on another
- Identity theft between environments

### Wildcard Parent IDs (Advanced)

You can use the server's SPIFFE ID as parent to allow **any** agent to issue an identity:

```bash
-parentID spiffe://localtest.me/spire/server
```

Use this for:
- Development/testing
- Workloads that can run on any node
- Cases where node-specific authorization isn't needed

**Production recommendation**: Use specific agent IDs when possible.

## Quick Example: Complete Registration Flow

```bash
# 1. Find SPIRE agents
kubectl exec -n spire-system spire-server-0 -- \
  /opt/spire/bin/spire-server agent list

# Output shows:
# SPIFFE ID: spiffe://localtest.me/spire/agent/k8s_psat/cluster/abc123
#            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#            This becomes your -parentID

# 2. Register a workload
kubectl exec -n spire-system spire-server-0 -- \
  /opt/spire/bin/spire-server entry create \
  -spiffeID spiffe://localtest.me/ns/default/sa/my-app \
  -parentID spiffe://localtest.me/spire/agent/k8s_psat/cluster/abc123 \
  -selector k8s:ns:default \
  -selector k8s:sa:my-app

# 3. Verify registration
kubectl exec -n spire-system spire-server-0 -- \
  /opt/spire/bin/spire-server entry show

# 4. Your workload can now request this identity
# When a pod in namespace "default" using service account "my-app" starts,
# it can request a JWT-SVID with SPIFFE ID: spiffe://localtest.me/ns/default/sa/my-app
```

## Summary

| Question | Answer |
|----------|--------|
| **Do I exec into spire-server?** | Yes, for CLI-based registration (Method 1) |
| **Are SPIFFE IDs automatic?** | No, you must register every identity explicitly |
| **What is a Parent ID?** | The SPIFFE ID of the agent authorized to issue a workload's identity |
| **Where do Parent IDs come from?** | SPIRE agents get their IDs via attestation; list them with `agent list` |
| **Why manual registration?** | Security - ensures only authorized workloads get identities |

## Next Steps

- Run the `register_workload.sh` script to see this in action
- Check out the main README.md for the full demo walkthrough
- Explore Kubernetes CRDs for automated registration at scale
