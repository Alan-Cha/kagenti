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
| **Mission Authority** | **PDP** (Policy Decision Point) — *current implementation* | At token exchange time, evaluates whether the exchange is permitted: is the mission active? max_uses not exceeded? scope allowed? |
| **AgentCortex** | **PEP** (Policy Enforcement Point) | Intercepts outbound agent requests, calls the PDP, enforces the decision by doing or blocking the token exchange. |
| **Keycloak** | Token Issuer | Issues cryptographically signed JWTs. Does not make mission-policy decisions. |

### Why Mission Authority is the right PDP (not Keycloak)

Keycloak has Authorization Services (UMA-based) which *can* act as a PDP. However:

- Keycloak is flexible **within** the OAuth2/OIDC paradigm. It is not a general-purpose policy engine.
- Mission-specific policy attributes (`max_uses`, `valid_until`, `usage_count`, `mission_id`) do not map naturally to Keycloak's resource/scope/client model.
- Keycloak can evaluate role-based, time-based, and JavaScript policies — but "has this mission been used more than N times?" requires either a JavaScript policy with an external HTTP call, or a Remote Policy that calls Mission Authority anyway.
- At that point Keycloak is a passthrough, not the real PDP.

**Decision**: Mission Authority is the PDP. Keycloak is the token issuer. These are distinct responsibilities.

> **Note on Keycloak flexibility**: Keycloak is not "locked in" to a rigid flow — it supports custom JavaScript policies, Remote Policy providers, protocol mappers, and IdP federation. But it is opinionated around OAuth2/OIDC as the authorization framework. If your authorization logic exceeds what OAuth2 scopes and client permissions can express, use an external PDP (Mission Authority, OPA, etc.) and have Keycloak delegate to it.

---

## 2. Token Minting — Who Issues the Mission Token?

### The question

After a mission is approved, an agent needs a **mission token** (a credential that proves the mission exists and the agent is authorized to act on it). Two options:

**Option A — Mission Authority mints the mission token (current implementation)**
- MA signs a JWT with RS256 using its own RSA keypair
- MA publishes its public key at `/.well-known/jwks.json`
- Keycloak is configured to trust MA as an external IdP (one-time setup)
- Token exchange: AgentCortex presents MA token → Keycloak validates via MA's JWKS → Keycloak issues service-scoped token

**Option B — Keycloak mints the mission token**
- On approval, MA calls Keycloak Admin API to set session notes (`mission_id`, `scope`) on the agent's session
- A pre-configured **User Session Note protocol mapper** in Keycloak reads those notes and injects them as claims
- Keycloak issues the mission token directly
- Advantage: single trusted issuer, automatic key rotation
- Disadvantage: requires the "set session note then immediately request token" dance; the mapper is static config (not per-token); Keycloak's session model doesn't naturally map to missions

### Decision

**Option A (MA mints) for Demo 1 and the foreseeable future.**

Reasons:
- Already implemented and working
- Mission token naturally contains `mission_id`, `scope`, `valid_until` — no session model gymnastics
- Keycloak IdP federation (trusting MA's JWKS) is a single config step — not complex
- Key rotation is a production concern, not a demo concern; MA's in-memory keypair is acceptable for now

**Migration path to Option B**: When ready, configure a User Session Note mapper in Keycloak and update the approval flow in MA. The `scripts/keycloak_config.yaml` already has the mapper configuration commented out for this purpose.

---

## 3. Token Exchange Flow (with AgentCortex as PEP)

```
Agent Pod
  │
  │  HTTP request to wiki.team1.svc.cluster.local
  │  (via HTTP_PROXY=localhost:8090)
  ▼
AgentCortex Sidecar (PEP)
  │
  ├─ 1. AUTHORIZE: POST /authorize to Mission Authority (PDP)
  │       body: { mission_id, agent_id, requested_scope, resource }
  │       response: { allow: true, remaining_uses: 4 }
  │
  ├─ 2. If denied → reject request (403)
  │
  ├─ 3. If allowed → TOKEN EXCHANGE: POST to Keycloak RFC 8693
  │       grant_type: urn:ietf:params:oauth:grant-type:token-exchange
  │       subject_token: <mission token signed by MA>
  │       subject_token_type: urn:ietf:params:oauth:token-type:jwt
  │       audience: wiki.team1.svc.cluster.local
  │       client_id: <agent's Keycloak client>
  │       client_secret: <from Kubernetes Secret>
  │   Keycloak validates mission token via MA's JWKS → issues service token
  │
  └─ 4. Forward request with fresh Keycloak-issued service token
```

**Keycloak configuration required for token exchange:**
- Token exchange feature enabled (`KEYCLOAK_FEATURES=token-exchange`)
- MA registered as an Identity Provider in Keycloak realm (OIDC, pointing to MA's JWKS)
- Per-agent Keycloak client has permission to perform token exchange (fine-grained permissions)

**What Mission Authority's `/authorize` endpoint returns (to be implemented):**
```json
{
  "allow": true,
  "mission_id": "M-20260714-abc12345",
  "remaining_uses": 4,
  "expires_at": "2026-12-31T23:59:59Z"
}
```
This is a pure policy decision — no token issuance. MA checks: status=active, usage_count < max_uses, valid_until not passed, requested_scope in mission scopes.

---

## 4. AuthBridge Architecture and Mission Authority Integration

### AuthBridge is a sidecar — but it already calls centralized services

AuthBridge is indeed a sidecar (one instance per agent pod), not a centralized service. This initially appears to create a fundamental problem: how does MA notify "AgentCortex" about an approved mission when there is no single endpoint to call?

**The answer is already in AuthBridge's architecture.** AuthBridge has a plugin pipeline with two chains — inbound and outbound — and plugins can call external centralized services. Two existing plugins demonstrate this exact pattern:

- **Token Broker plugin** — Each AuthBridge sidecar calls a centralized `Token Broker Service` (HTTP) to acquire tokens for outbound requests. The broker manages the token lifecycle; the sidecar just asks.
- **OPA plugin** — Each AuthBridge sidecar polls a centralized `Bundle Service` (cluster singleton) for its policy bundle. Policies are managed centrally; sidecars pull them.

**Mission Authority fits the same pattern.** MA is a centralized HTTP service. AuthBridge sidecars call it at token exchange time — not the other way around.

### The corrected flow

MA does not notify AuthBridge. AuthBridge consults MA:

```
Agent makes outbound request
  → AuthBridge outbound pipeline intercepts
  → Mission Authority plugin calls MA PDP:
      POST /authorize { mission_id, agent_id, requested_scope, resource }
      ← { allow: true, remaining_uses: 4 }
  → If allowed: token exchange with Keycloak
  → Forward request with fresh token
```

This resolves the centralization question entirely. The sidecar calls the central MA service on every token exchange — MA doesn't need to know which pod is asking.

### AuthBridge plugin pipeline

AuthBridge processes requests through sequential plugin chains:

```
Inbound (caller → this agent):
  request phase  → jwt-validation → a2a-parser → session-recorder
  response phase ← a2a-parser ← jwt-validation

Outbound (this agent → target service):
  request phase  → route-resolver → token-exchange → mcp-parser
  response phase ← mcp-parser ← token-exchange
```

Mission Authority integration is an **outbound plugin** that runs before token exchange:

```
Outbound request phase:
  → route-resolver
  → mission-authority-pdp  ← NEW: calls MA /authorize, rejects if denied
  → token-exchange          (only reached if MA says allow)
  → mcp-parser
```

Plugins are composable and registered per agent via configuration. The `mission-authority-pdp` plugin can be selectively enabled for mission-driven agents without affecting others.

### OPA in AuthBridge (kagenti-bundle-service)

AuthBridge already has an **OPA plugin** that evaluates Rego policies per-request using bundles served by `kagenti-bundle-service` (a cluster singleton). This provides:

- **Inbound control**: who can call this agent (identity, scopes, client IDs)
- **Tool-level access**: which MCP tools a caller may invoke
- **Outbound control**: what external services this agent can use

OPA policy and Mission Authority PDP are **complementary**, not competing:
- OPA evaluates *structural* policy: role-based rules, tool allowlists, client restrictions
- Mission Authority evaluates *mission-state* policy: is this mission still active, usage limits, time windows

Both can run in the same outbound pipeline. OPA fires first (structural check), then MA (mission-state check).

### The remaining open question: who dispatches missions to agents?

The token-exchange-time consultation pattern (AuthBridge → MA) solves authorization. But there is still an open question for *async* missions where an agent doesn't exist yet:

> Mission is approved → who spawns the agent?

Options (to be decided):
1. **Operator-driven**: MA emits a CloudEvent → Kagenti/Rosso operator receives it → operator creates the AgentRuntime CRD → pod spawns with mission token injected
2. **Pull model**: A running agent polls MA for pending missions matching its `agent_id`
3. **Synchronous only (Demo 1)**: The requesting agent already exists and receives the mission token immediately in the approval response — no dispatch needed

*Agent spawning is deferred — see §5.*

---

## 5. Deferred: Agent Spawning

When a mission is approved, it may require spawning a new agent pod to fulfill it. This is intentionally out of scope for the current implementation. Notes for when this is tackled:

- AgentCortex is injection-based (sidecar webhook) — it cannot spawn itself
- Agent spawning would be handled by the **Kagenti operator** or a new **Mission Dispatcher** component
- The mission payload needs to include enough information for the operator to know: which agent template, what namespace, what resource limits
- The `sub_agents` field in the Mission data model was designed with this in mind

---

## 7. Pre-Authorization Problem — Identity for Agents That Don't Exist Yet

### The problem

When a mission is approved, the agent that will execute it may not exist yet. AgentCortex (or the Kagenti operator) will spawn it later. But the mission needs to say something like:

> "An agent that will be created in the future will have these roles and these scopes, and it should be permitted to act on this mission."

The challenge: you cannot issue credentials to an entity that has no identity yet. Standard OAuth2 assumes the client already exists in Keycloak before it can receive a token. You need a mechanism to pre-declare identity and bind it to the mission at approval time, then hand it to the agent at spawn time.

---

### Option A — Mission token IS the agent's bootstrap credential (simplest)

The mission token itself becomes the agent's identity for all mission-scoped operations. The `agent_id` field in the mission is a logical name (e.g. `research-agent`), not a reference to a live Keycloak client. AgentCortex injects the mission token into the spawned agent pod as an environment variable or mounted secret. The agent presents that token for all outbound calls; AgentCortex validates it against MA before exchanging it with Keycloak.

```
Mission approval
  → MA issues mission token (sub=research-agent, mission_id=M-..., scope=[...])
  → Operator spawns agent pod with MISSION_TOKEN env var
  → Agent uses MISSION_TOKEN for all calls via AgentCortex proxy
  → AgentCortex calls MA PDP: "is this mission token still valid for this scope?"
  → MA says yes → AgentCortex calls Keycloak to get a service-scoped token
```

**Pros:** No pre-provisioning of Keycloak clients per agent instance. The mission token carries all the authorization context. Already partially implemented.  
**Cons:** The agent's Keycloak identity is inherited from the mission token's `sub` claim rather than a distinct workload identity. Makes audit trails at the service level show `research-agent` rather than a specific pod/instance.

---

### Option B — Kubernetes Service Account as pre-provisioned identity

Pre-create a Kubernetes Service Account (KSA) for the agent type (e.g. `sa/research-agent` in `team1`). KSA tokens are issued by the cluster's OIDC provider and bound to the SA. The mission references the SA name; when the operator spawns the pod it mounts the SA token as a projected volume. AgentCortex exchanges the SA token with Keycloak (using the existing OIDC federation between the cluster and Keycloak) to get a Keycloak token, then calls MA PDP to validate the mission.

```
Mission references: agent_id=research-agent → maps to sa/team1/research-agent
Operator spawns pod with SA token mounted
AgentCortex: SA token → Keycloak token exchange → service token
             + MA PDP check: is mission M-... active for scope wiki_write?
```

**Pros:** Clean workload identity using Kubernetes primitives. SA exists before the mission; no per-mission credential generation. Standard pattern used broadly in Kubernetes.  
**Cons:** Requires pre-creating SAs for all agent types. SA is a type identity, not an instance identity — if two pods of the same type run concurrently, they share the same SA and can't be distinguished in audit logs.

---

### Option C — SPIFFE/SPIRE workload identity (zero-trust, most robust)

SPIRE issues a SPIFFE SVID to any pod matching a registered selector (namespace, service account, labels). The SPIFFE ID is declared in the mission: `spiffe://cluster.local/ns/team1/sa/research-agent`. This identity exists as a *policy* before the pod exists — SPIRE will issue a matching SVID as soon as a pod with the right attributes is spawned.

```
Mission approval: declares agent_id=spiffe://cluster.local/ns/team1/sa/research-agent
Operator spawns pod with matching labels/SA
SPIRE issues JWT-SVID to the pod automatically
AgentCortex: SVID → Keycloak (via SPIFFE IdP) → Keycloak token
             + MA PDP check: is mission M-... active for this SPIFFE identity?
```

**Pros:** Identity is cryptographically bound to the workload, not a secret. Survives pod restarts. No credentials to inject at spawn time. The "future agent" identity is declared structurally (via SPIFFE selector patterns), not by pre-issuing credentials.  
**Cons:** Requires SPIRE deployed and configured (already supported by AgentCortex/AuthBridge in `spiffe` mode, but not always enabled). More operational complexity.

---

### Option D — Ephemeral Keycloak client per mission

On mission approval, MA (or the operator) creates a new Keycloak client specifically for this mission execution: `client_id: mission-exec-M-20260716-abc12345`. The client is granted exactly the approved scopes. The operator spawns the agent pod with these credentials injected. The client is deleted when the mission completes or is canceled.

**Pros:** Per-mission identity — fully traceable in Keycloak audit logs. Scopes are enforced at the Keycloak level.  
**Cons:** Client proliferation in Keycloak (one client per mission). Requires Keycloak Admin API calls on every mission approval/completion. Keycloak's client list can grow unbounded without aggressive cleanup.

---

### Recommendation

| Phase | Approach | Reason |
|---|---|---|
| **Demo 1** | Option A — mission token as bootstrap | Already implemented, zero new infrastructure |
| **Production (no SPIRE)** | Option B — Kubernetes Service Account | Clean, Kubernetes-native, no custom code |
| **Production (with SPIRE)** | Option C — SPIFFE/SPIRE workload identity | Zero-trust, no secrets to manage, matches AgentCortex's existing SPIFFE mode |

Option D (ephemeral Keycloak clients) is not recommended — the operational overhead of client lifecycle management outweighs the benefits.

The key insight for all options: **the `agent_id` field in a mission is a logical declaration of intent** ("an agent of this type will execute this mission"), not a reference to a live process. The binding between that logical identity and a running pod happens at spawn time, via whichever mechanism the operator uses.

---

### 7b. Agent Specification — What Kind of Agent to Spawn?

A related open question: when a mission is approved and an agent needs to be spawned, the operator needs to know *what kind of agent* to create — its prompt/system instructions, model, memory/storage requirements, skills and tools, resource limits. None of this belongs in the JWT token (tokens are credentials, not configuration manifests). The token stays small.

**Separation of concerns:**

| What | Where it lives | Why |
|---|---|---|
| Authorization credential | Mission token (JWT) | Small, signed, `mission_id` + `scope` + `exp` only |
| Full agent specification | Mission record in MA's PostgreSQL | Arbitrarily large, mutable, operator fetches at spawn time |

At spawn time, the operator receives a `mission_id` (via dispatch), calls `GET /missions/{id}` on MA to fetch the full spec, then creates the agent pod.

**Three approaches for defining the agent spec within a mission:**

**Approach 1 — Template reference**

The mission names an existing agent template, and the operator looks it up:

```json
{
  "task": "Research AI safety and update wiki",
  "agent_id": "research-agent",
  "agent_template": "research-agent-v2",
  "scope": ["wiki_read", "wiki_write"]
}
```

`research-agent-v2` is a pre-registered Kagenti `AgentRuntime` CRD that defines prompt, model, resources, and tools. The mission only names the template; defaults come from the CRD. Simple, but inflexible — missions can't customize individual agents.

**Approach 2 — Inline agent spec with overrides**

The mission carries a partial agent spec that overrides template defaults:

```json
{
  "task": "Research AI safety and update wiki",
  "agent_id": "research-agent",
  "agent_spec": {
    "template": "research-agent-v2",
    "model": "llama3.2:3b-instruct-fp16",
    "system_prompt": "You are a research assistant focused on AI safety...",
    "resources": { "memory": "4Gi", "cpu": "1" },
    "tools": ["web_search", "wiki_write"]
  },
  "scope": ["wiki_read", "wiki_write"]
}
```

More flexible — each mission can customize the agent. The `tools` list maps to Kagenti `Tool` CRDs already deployed in the cluster.

**Approach 3 — Full inline spec (no template)**

The mission is fully self-contained. The operator needs no external lookup for the agent definition. Maximum flexibility, maximum verbosity. Suitable if missions are always created programmatically (e.g. by an orchestrator).

**Recommendation for Demo 1:** Approach 1 (template reference). The `agent_id` field already exists and maps to an existing AgentRuntime. No schema changes needed. Approach 2 is the right long-term design once missions are being created through the UI and need per-mission customization.

**What the mission token carries regardless of approach:**

```
{
  "iss": "https://mission-authority...",
  "sub": "research-agent",       ← logical agent type, not instance
  "mission_id": "M-20260716-...",
  "scope": ["wiki_read", "wiki_write"],
  "exp": ...,
  "iat": ...
}
```

The full spec — prompt, model, resources — lives in the mission record, not the token. The token is the key; the mission record is the door it opens.

---

## 8. Components Not Yet Implemented

| Component | Description | Priority |
|---|---|---|
| `POST /authorize` on MA | Pure PDP endpoint — allow/deny without token issuance | High |
| MA registered as Keycloak IdP | One-time Keycloak config so token exchange works | High |
| AgentCortex calls MA before token exchange | PEP calls PDP before calling Keycloak | High |
| Mission dispatch mechanism | How MA notifies AgentCortex/operator on approval | Medium |
| Agent identity binding at spawn time | Operator injects mission token / mounts SA / configures SPIFFE per §7 | Medium |
| `canceled_at` / `canceled_by` in MA API response | Currently not returned in mission detail | Low |
| Mission token renewal endpoint | `POST /missions/{id}/renew-token` for long-running missions | Low |
| Agent spawning on mission approval | Operator/dispatcher creates agent pod for mission | Deferred |
| MA token → Keycloak-minted token migration | Full Keycloak issuance via User Session Note mapper | Future |

---

## 9. What Mission Authority Is Not

To avoid scope creep, explicit non-goals:

- **Not a general-purpose authorization server** — MA is domain-specific to agent missions
- **Not an identity provider** — Keycloak handles identity; MA handles mission policy
- **Not an agent scheduler** — MA approves missions; something else decides when/how agents run
- **Not a token issuer for production** — MA mints mission tokens as a pragmatic Demo 1 shortcut; Keycloak should own token issuance long-term
