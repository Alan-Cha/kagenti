# Mission Authority — Architecture Decisions

**Status**: Living document — captures decisions and open questions from design discussions  
**Last Updated**: 2026-07-14

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

## 4. AgentCortex Architecture Gap — Open Question

### The problem

AgentCortex is a **sidecar** — there is no centralized "AgentCortex service". Every agent pod has its own AgentCortex sidecar instance. This creates a fundamental question:

> When a mission is approved in Mission Authority, MA needs to notify *someone* that a mission is ready. But there is no single AgentCortex endpoint to call. The agent pod may not even exist yet.

### Options being considered

| Option | How | Tradeoff |
|---|---|---|
| **Pull model** | AgentCortex polls MA for missions assigned to its agent | Simple, no dispatch needed; latency between approval and execution |
| **CloudEvent dispatch** | MA publishes `mission.approved` event; a central controller subscribes and coordinates | Decoupled; requires Knative eventing infrastructure |
| **Kagenti operator as dispatcher** | MA calls Kagenti API on approval; operator decides which agent handles it | Centralizes the routing decision in the operator |
| **HTTP call to a known agent** | MA calls a specific agent's service endpoint directly | Only works if the target agent is already running and its URL is known at approval time |

### Current state

**No implementation exists for this dispatch layer.** The current MA skeleton assumes the mission token is handed back to the requesting agent directly (synchronous request/response). For async, event-driven missions this is an open design question.

**What needs to be decided:**
1. Who assigns a mission to a specific agent instance?
2. Does the agent need to be running before approval, or does approval trigger spawning?
3. What is the protocol between MA and whatever receives the dispatch?

*Agent spawning on mission approval is deferred — see §5.*

---

## 5. Deferred: Agent Spawning

When a mission is approved, it may require spawning a new agent pod to fulfill it. This is intentionally out of scope for the current implementation. Notes for when this is tackled:

- AgentCortex is injection-based (sidecar webhook) — it cannot spawn itself
- Agent spawning would be handled by the **Kagenti operator** or a new **Mission Dispatcher** component
- The mission payload needs to include enough information for the operator to know: which agent template, what namespace, what resource limits
- The `sub_agents` field in the Mission data model was designed with this in mind

---

## 6. Components Not Yet Implemented

| Component | Description | Priority |
|---|---|---|
| `POST /authorize` on MA | Pure PDP endpoint — allow/deny without token issuance | High |
| MA registered as Keycloak IdP | One-time Keycloak config so token exchange works | High |
| AgentCortex calls MA before token exchange | PEP calls PDP before calling Keycloak | High |
| Mission dispatch mechanism | How MA notifies AgentCortex/operator on approval | Medium |
| `canceled_at` / `canceled_by` in MA API response | Currently not returned in mission detail | Low |
| Agent spawning on mission approval | Operator/dispatcher creates agent pod for mission | Deferred |
| MA token → Keycloak-minted token migration | Full Keycloak issuance via User Session Note mapper | Future |

---

## 7. What Mission Authority Is Not

To avoid scope creep, explicit non-goals:

- **Not a general-purpose authorization server** — MA is domain-specific to agent missions
- **Not an identity provider** — Keycloak handles identity; MA handles mission policy
- **Not an agent scheduler** — MA approves missions; something else decides when/how agents run
- **Not a token issuer for production** — MA mints mission tokens as a pragmatic Demo 1 shortcut; Keycloak should own token issuance long-term
