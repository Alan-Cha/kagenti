# Mission Authority — Architecture Decisions

**Status**: Living document — captures decisions and open questions from design discussions  
**Last Updated**: 2026-07-16

> **Naming note**: The Kagenti platform is being renamed to **Rosso** (see kagenti/kagenti#2207).
> AuthBridge retains its name. "RossoCortex" / "AgentCortex" refers to AuthBridge in the context of
> the Rosso platform. `rossoctl` is the new CLI. This document uses AuthBridge throughout.

---

## 1. Role Terminology (PAP / PDP / PEP / PIP)

| Component | Role | Responsibility |
|---|---|---|
| **Mission Authority** | **PAP** (Policy Administration Point) | Humans define what agents are allowed to do. Agents submit mission requests; humans approve or deny. The approved mission IS the policy. |
| **Mission Authority** | **PIP** (Policy Information Point) | Stores the authoritative data the PDP queries: mission status, usage count, valid_until, approved scopes. |
| **Mission Authority** | **PDP** (Policy Decision Point) — mission-state | At token exchange time, evaluates mission-specific policy: is the mission active? max_uses not exceeded? scope allowed? |
| **OPA + Bundle Service** | **PDP** (Policy Decision Point) — structural | Evaluates Rego policies per-request in AuthBridge: role-based rules, tool allowlists, client restrictions. Runs *before* MA in the plugin chain. |
| **AuthBridge** | **PEP** (Policy Enforcement Point) | Intercepts outbound agent requests via its plugin pipeline; runs OPA then MA PDP; enforces the decision by doing or blocking token exchange. |
| **Keycloak** | Token Issuer | Issues cryptographically signed JWTs for service-scoped access. Does not make mission-policy decisions. |

The two PDPs are complementary, not competing:
- **OPA** handles *structural* policy: who can call this agent, which MCP tools are allowed, which external services are permitted — rules that don't change per-request
- **MA** handles *mission-state* policy: is this specific mission still active, has it exceeded its usage limit, is the requested scope within the approved set — state that changes as the mission progresses

### Why Mission Authority is the right PDP for mission-state (not Keycloak)

Keycloak has Authorization Services (UMA-based) which *can* act as a PDP. However:

- Keycloak is flexible **within** the OAuth2/OIDC paradigm — not a general-purpose policy engine
- Mission-specific attributes (`max_uses`, `valid_until`, `usage_count`) do not map to Keycloak's resource/scope/client model
- "Has this mission been used more than N times?" requires a JavaScript policy that calls MA anyway — Keycloak becomes a passthrough
- OPA already handles the structural authorization Keycloak's Authorization Services would otherwise provide

**Decision**: Mission Authority is the mission-state PDP. OPA (via AuthBridge plugin + Bundle Service) is the structural PDP. Keycloak issues tokens.

---

## 2. Token Minting — Who Issues the Mission Token?

### The question

After a mission is approved, an agent needs a **mission token** (a credential that proves the mission exists and the agent is authorized to act on it). Two options:

**Option A — Mission Authority mints the mission token (current implementation, chosen long-term)**
- MA signs a JWT with RS256 using its own RSA keypair
- MA publishes its public key at `/.well-known/jwks.json`
- Keycloak is configured to trust MA as an external IdP (one-time setup)
- Token exchange: AuthBridge's token-exchange plugin presents MA token to Keycloak → Keycloak validates via MA's JWKS → Keycloak issues service-scoped token

**Option B — Keycloak mints the mission token**
- On approval, MA calls Keycloak Admin API to set session notes (`mission_id`, `scope`) on the agent's session
- A pre-configured **User Session Note protocol mapper** in Keycloak injects those notes as claims
- Advantage: single trusted issuer, automatic key rotation
- Disadvantage: Keycloak's `claim-token` RFC 8693 parameter is not implemented in Keycloak's token exchange; would require a custom Keycloak SPI extension (Java code). Session model doesn't naturally map to missions.

### Decision

**Option A (MA mints) — for Demo 1 and long-term.**

Reasons:
- Already implemented and working
- Mission token naturally contains `mission_id`, `scope`, `valid_until` — no session gymnastics
- Keycloak IdP federation (trusting MA's JWKS) is a single config step
- Mission tokens are a domain concept MA owns — Keycloak shouldn't know about missions
- Key rotation = update a Kubernetes Secret + restart MA. No rotation code needed.
- Getting Keycloak to mint tokens with arbitrary custom claims (`mission_id`) requires a custom Java SPI extension — not worth the effort when MA minting already works cleanly

**Production hardening:** Mount an RSA PEM from a Kubernetes Secret via `MISSION_AUTHORITY_MISSION_TOKEN_PRIVATE_KEY_PATH`. All replicas share the same key, JWKS is stable across restarts.

---

## 3. Token Exchange Flow (AuthBridge as PEP)

The flow reflects AuthBridge's **plugin pipeline** architecture. Each step is a plugin running in sequence on the outbound chain:

```
Agent Pod
  │
  │  HTTP request to wiki.team1.svc.cluster.local
  │  (intercepted via HTTP_PROXY=localhost:8090 or iptables)
  ▼
AuthBridge Sidecar — outbound plugin chain
  │
  ├─ 1. route-resolver plugin
  │       Determines the target service and which exchange rules apply
  │
  ├─ 2. OPA plugin (structural PDP)
  │       Evaluates Rego: is this agent allowed to call this service at all?
  │       Rejects if structural policy fails (403)
  │
  ├─ 3. mission-authority-pdp plugin (mission-state PDP)  ← TO BE BUILT
  │       POST /authorize to Mission Authority:
  │         { mission_id, agent_id, requested_scope, resource }
  │       Response: { allow: true, remaining_uses: 4 }
  │       Rejects if mission policy fails (403)
  │
  ├─ 4. token-exchange plugin (existing)
  │       Calls Keycloak RFC 8693:
  │         grant_type: token-exchange
  │         subject_token: <mission token signed by MA>
  │         audience: wiki.team1.svc.cluster.local
  │         client_id: <agent's Keycloak client>
  │       Keycloak validates mission token via MA's JWKS → issues service token
  │
  └─ 5. Forward request with fresh Keycloak-issued service token
```

**Keycloak configuration required for step 4:**
- Token exchange feature enabled (`KEYCLOAK_FEATURES=token-exchange`)
- MA registered as an Identity Provider in Keycloak realm (OIDC, pointing to MA's JWKS)
- Per-agent Keycloak client has fine-grained token exchange permission

**What Mission Authority's `/authorize` endpoint returns (to be implemented):**
```json
{
  "allow": true,
  "mission_id": "M-20260714-abc12345",
  "remaining_uses": 4,
  "expires_at": "2026-12-31T23:59:59Z"
}
```

---

## 4. AuthBridge Architecture and Mission Authority Integration

### AuthBridge is a sidecar — but it already calls centralized services

AuthBridge is a sidecar (one instance per agent pod). This initially appears to create a problem: how does MA notify "AgentCortex" about an approved mission? **The answer: MA doesn't notify AuthBridge. AuthBridge consults MA.**

AuthBridge already has plugins that call centralized external services:
- **Token Broker plugin** — calls a centralized Token Broker Service per outbound request to acquire tokens. The sidecar asks; the service decides.
- **OPA plugin** — polls a centralized Bundle Service (cluster singleton) for per-agent Rego policy bundles.

**Mission Authority is the same pattern.** It's a centralized HTTP service. AuthBridge sidecars call it at token exchange time. MA doesn't need to know which pod is asking.

### AuthBridge plugin pipeline

```
Inbound (caller → this agent):
  request phase  → jwt-validation → opa → a2a-parser → session-recorder
  response phase ← session-recorder ← a2a-parser ← opa ← jwt-validation

Outbound (this agent → target service):
  request phase  → route-resolver → opa → mission-authority-pdp → token-exchange → mcp-parser
  response phase ← mcp-parser ← token-exchange ← mission-authority-pdp ← opa
```

Plugins execute sequentially. Response phase is LIFO (reverse order). Plugins are composable and registered per-agent via configuration — `mission-authority-pdp` can be selectively enabled for mission-driven agents only.

### OPA in AuthBridge (kagenti-bundle-service)

`kagenti-bundle-service` is a cluster-wide Go service that watches `KagentiPolicy` CRDs and serves per-agent OPA bundles. AuthBridge's OPA plugin evaluates Rego policies on every request with sub-millisecond latency.

OPA policies can control:
- Inbound: who can call this agent (identity, scopes, client IDs)
- Tool access: which MCP tools a caller may invoke
- Outbound: which external services this agent can reach

**AIAC** (AI Access Control) can auto-generate initial Rego policies when a new agent is onboarded, based on the agent card, organization security policy, and registered tools. For mission-driven agents, AIAC-generated policies can include mission-scope restrictions as a structural layer on top of MA's mission-state checks.

### The remaining open question: who dispatches missions to agents?

The AuthBridge → MA consultation pattern resolves authorization at runtime. For *async* missions where an agent doesn't exist yet, the dispatch question remains open:

1. **Operator-driven**: MA emits a `mission.approved` CloudEvent → Rosso operator receives it → creates AgentRuntime CRD → pod spawns with mission token injected as env var
2. **Pull model**: A running agent polls MA for pending missions matching its `agent_id`
3. **Synchronous only (Demo 1)**: The requesting agent already exists and receives the mission token immediately in the approval response — no dispatch needed

*Agent spawning is deferred — see §5.*

---

## 5. Deferred: Agent Spawning

When a mission is approved, it may require spawning a new agent pod to fulfill it. Out of scope for the current implementation.

Notes for when this is tackled:
- AuthBridge is injection-based (Kubernetes webhook) — it cannot spawn itself
- Agent spawning would be handled by the **Rosso operator** or a new **Mission Dispatcher** component
- The mission payload needs enough information for the operator: agent template, namespace, resource limits (see §6b for agent spec design)
- The `sub_agents` field in the Mission data model was designed with this in mind
- The Rosso operator already manages `AgentRuntime` CRDs — the spawning mechanism exists; it needs a trigger

---

## 6. Pre-Authorization Problem — Identity for Agents That Don't Exist Yet

### The problem

When a mission is approved, the agent that will execute it may not exist yet. The mission needs to declare:

> "An agent of this type will be created in the future, will have these scopes, and should be permitted to act on this mission."

The challenge: standard OAuth2 assumes the client already exists in Keycloak before receiving a token. You need to pre-declare identity and bind it to the mission at approval time, then hand it to the agent at spawn time.

---

### Option A — Mission token IS the agent's bootstrap credential (simplest, Demo 1)

The mission token itself becomes the agent's identity. `agent_id` is a logical name, not a live Keycloak client. The operator injects the mission token at pod creation via env var or mounted secret. AuthBridge's `mission-authority-pdp` plugin extracts `mission_id` from the token automatically — no separate configuration per pod.

```
Mission approval
  → MA issues mission token (sub=research-agent, mission_id=M-..., scope=[...])
  → Operator spawns agent pod with MISSION_TOKEN=<token> env var
  → Agent uses token via AuthBridge proxy for all outbound calls
  → AuthBridge OPA: structural check passes
  → AuthBridge MA PDP: mission still active, scope allowed
  → AuthBridge token-exchange: Keycloak issues service token
```

**Pros:** Zero new infrastructure. Mission token carries all auth context. Already implemented.  
**Cons:** Agent's Keycloak identity is the mission token's `sub` claim — type identity, not instance identity. Audit trails show `research-agent`, not a specific pod.

---

### Option B — Kubernetes Service Account as pre-provisioned identity

Pre-create a KSA for the agent type (`sa/team1/research-agent`). The operator spawns the pod with the SA token projected as a volume. AuthBridge exchanges the SA token with Keycloak (via OIDC federation), then calls MA PDP.

**Pros:** Kubernetes-native. SA exists before the mission.  
**Cons:** Type identity only — two concurrent pods of the same type share the SA.

---

### Option C — SPIFFE/SPIRE workload identity (zero-trust, most robust)

SPIRE issues a SVID to any pod matching a registered selector. The identity is declared as a structural pattern before the pod exists. **Note**: `spiffe-helper` is now *bundled inside the AuthBridge sidecar image* — SPIFFE is not an additional sidecar, just a config flag (`SPIRE_ENABLED=true`).

```
Mission declares: agent_id=spiffe://cluster.local/ns/team1/sa/research-agent
Operator spawns pod with matching SA/labels
SPIRE issues JWT-SVID automatically to the pod
AuthBridge: SVID → Keycloak (via SPIFFE IdP) → service token
            + MA PDP: mission still active for this identity
```

**Pros:** No secrets to inject. Identity is cryptographically bound to the workload. Survives pod restarts. Already supported by AuthBridge — just requires SPIRE deployed.  
**Cons:** Requires SPIRE in the cluster.

---

### Option D — Ephemeral Keycloak client per mission (not recommended)

Create a Keycloak client per mission execution. Clean per-mission audit trail but client proliferation in Keycloak is unmanageable at scale.

---

### Recommendation

| Phase | Approach |
|---|---|
| **Demo 1** | Option A — mission token as bootstrap |
| **Production (no SPIRE)** | Option B — Kubernetes Service Account |
| **Production (with SPIRE)** | Option C — SPIFFE/SPIRE (SPIFFE-helper is already bundled in AuthBridge) |

**Key insight**: `agent_id` is a logical declaration of intent, not a reference to a live process. The binding between that declaration and a running pod happens at spawn time.

---

### 6b. Agent Specification — What Kind of Agent to Spawn?

The mission token stays small (credential only). The full agent specification — prompt, model, resources, tools — lives in MA's PostgreSQL and is fetched by the operator at spawn time via `GET /missions/{id}`.

**Three approaches:**

**Approach 1 — Template reference (Demo 1)**

```json
{
  "task": "Research AI safety and update wiki",
  "agent_id": "research-agent",
  "agent_template": "research-agent-v2",
  "scope": ["wiki_read", "wiki_write"]
}
```

`research-agent-v2` is an existing Rosso `AgentRuntime` CRD. Simple, inflexible.

**Approach 2 — Inline spec with overrides (long-term)**

```json
{
  "task": "Research AI safety and update wiki",
  "agent_id": "research-agent",
  "agent_spec": {
    "template": "research-agent-v2",
    "model": "llama3.2:3b-instruct-fp16",
    "system_prompt": "You are a research assistant...",
    "resources": { "memory": "4Gi", "cpu": "1" },
    "tools": ["web_search", "wiki_write"]
  },
  "scope": ["wiki_read", "wiki_write"]
}
```

Each mission can customize the agent. Tools map to `Tool` CRDs deployed in the cluster.

**Approach 3 — Full inline spec** — Self-contained, for programmatic use.

**What the token carries regardless of approach:**

```json
{
  "iss": "https://mission-authority...",
  "sub": "research-agent",
  "mission_id": "M-20260716-...",
  "scope": ["wiki_read", "wiki_write"],
  "exp": 1234567890
}
```

The token is the key. The mission record is the door it opens.

---

## 7. Components Not Yet Implemented

| Component | Description | Priority |
|---|---|---|
| `POST /authorize` on MA | Pure PDP endpoint — allow/deny without token issuance | High |
| MA registered as Keycloak IdP | One-time Keycloak config so token exchange works | High |
| AuthBridge `mission-authority-pdp` plugin | New outbound plugin that calls MA `/authorize` before token exchange | High |
| Agent identity binding at spawn time | Operator injects mission token / mounts SA / enables SPIFFE per §6 | Medium |
| Mission dispatch for async agents | How operator is triggered to spawn an agent for an approved mission | Medium |
| `canceled_at` / `canceled_by` in MA API response | Currently not returned in mission detail | Low |
| Mission token renewal endpoint | `POST /missions/{id}/renew-token` for long-running missions | Low |
| OPA `KagentiPolicy` for mission-driven agents | Structural policy (tool allowlists, scope restrictions) generated by AIAC | Low |
| Agent spawning on mission approval | Rosso operator creates agent pod from AgentRuntime CRD | Deferred |

---

## 8. What Mission Authority Is Not

- **Not a general-purpose authorization server** — MA is domain-specific to agent missions
- **Not an identity provider** — Keycloak handles identity; MA handles mission policy
- **Not an agent scheduler** — MA approves missions; the Rosso operator decides when/how agents run
- **Not delegating token issuance to Keycloak** — MA is the right issuer for mission tokens long-term; Keycloak minting requires a custom Java SPI extension that isn't worth building
