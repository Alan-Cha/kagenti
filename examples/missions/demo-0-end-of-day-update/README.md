# Demo 0: Mission-Based Authorization - End-of-Day Update

**Mission Authorization Proof-of-Concept for KubeCon + CloudNativeCon NA 2026**

This demo shows mission-based authorization solving the "temporal uncertainty gap" in event-driven AI agent architectures.

---

## What This Demo Shows

**Scenario**: User asks an AI agent (Claude Code) for an end-of-day update from wiki articles.

**The Problem**: In traditional event-driven systems, credentials embedded at event publish time may expire before processing. Long-lived credentials are insecure; short-lived credentials expire too quickly.

**The Solution**: Mission-based authorization provides time-bounded, task-specific authorization with human oversight:
1. Agent requests a "mission" (natural language task description)
2. Human approves the mission
3. Mission Authority issues long-lived mission token
4. Agent exchanges mission token for short-lived service tokens (RFC 8693)
5. Agent performs task
6. Human can cancel mission mid-flight if needed

---

## Architecture

```
User → Claude Code → Mission Authority → Wiki Service
         ↓              ↓                    ↓
    Request Mission   Approve & Issue   Validate Token
                      Mission Token     Return Content
```

**Key Components**:
- **Mission Authority**: Issues and validates mission tokens
- **Token Exchange (RFC 8693)**: Mission token → service-specific access token
- **Claude Code Skill**: Enables Claude to request/use missions
- **Mock Wiki Service**: Simulates protected resource

---

## Quick Start

### Prerequisites

```bash
# Install dependencies
pip install click

# Set working directory
cd examples/missions/demo-0-end-of-day-update
```

### Step 1: Start Mock Services

**Terminal 1: Mission Authority**
```bash
python3 mock_mission_authority.py
```

**Terminal 2: Mock Wiki Service**
```bash
python3 mock_wiki_service.py
```

### Step 2: Install Mission Skill

```bash
# Install to Claude Code
cp -r claude-code-skill ~/.claude/skills/mission/
```

### Step 3: Run Demo

See the two demo paths below for different presentation approaches.

---

## Demo Path A: Manual CLI (Technical Audience)

**Best for**: Technical deep dive, showing API flow

**Duration**: 5-7 minutes

### 1. Request Mission
```bash
cd ~/.claude/skills/mission
python3 skill.py request \
  --task "Read AI safety wiki for end-of-day update" \
  --scope wiki_read \
  --duration-hours 8
```

**Output**: Mission ID (e.g., M-20260624-abc)

### 2. Check Status (Pending)
```bash
python3 skill.py status
```

**Output**: Status is "pending", awaiting approval

### 3. Approve Mission (Human)
```bash
cd examples/missions/demo-0-end-of-day-update
python3 mock_mission_authority.py approve M-20260624-abc
```

**Output**: Mission approved, token saved

### 4. Check Status (Active)
```bash
cd ~/.claude/skills/mission
python3 skill.py status
```

**Output**: Status is "active", ready to use

### 5. Exchange Token (RFC 8693)
```bash
python3 skill.py exchange --resource wiki --scope wiki_read
```

**Output**: Access token obtained (4 hour expiry)

### 6. Read Wiki
```bash
python3 skill.py read-wiki --topic ai-safety
```

**Output**: 5 articles retrieved, saved to cache

---

## Demo Path B: Claude Code Integration (Mixed Audience)

**Best for**: Natural agent behavior, showing user experience

**Duration**: 3-5 minutes

### User asks Claude:
```
Can you give me an end-of-day update on AI safety? Check the wiki for the latest articles.
```

### Claude responds:
```
I'll need to request a mission to access the wiki.

[Requests mission via Bash tool]

Mission M-20260624-xyz requested. This needs your approval.
```

### User approves:
```bash
# In another terminal
python3 mock_mission_authority.py approve M-20260624-xyz
```

Then tells Claude: "I've approved it. Please continue."

### Claude proceeds:
```
[Exchanges token]
[Reads wiki]

I've read 5 articles from the AI safety wiki. Here's your update:

1. Scalable Oversight for Advanced AI Systems
2. Constitutional AI: Safety through Natural Language
3. Mechanistic Interpretability of LLMs
4. AI Alignment Research Overview
5. Safety Considerations for Large Language Models

[Compiles summary]
```

---

## Cleanup

```bash
# Stop services (Ctrl+C in terminals)

# Clean mission data
rm -rf ~/.claude/missions/*.token
rm -rf ~/.claude/missions/*.txt
rm -rf ~/.claude/cache/wiki-*.json
rm -rf ~/.claude/mock_mission_authority/
```

---

## Key Concepts

### Mission
Time-bounded, human-readable authorization context with natural language task description.

**Example**:
```json
{
  "mission_id": "M-20260624-001",
  "mission_text": "Read AI safety wiki for end-of-day update",
  "agent_id": "spiffe://cluster.local/ns/default/sa/claude-code",
  "scope": ["wiki_read"],
  "status": "active",
  "duration_hours": 8
}
```

### Token Exchange (RFC 8693)
Mission tokens are long-lived but never used directly. They're exchanged for short-lived, service-specific access tokens:

1. **Mission Token** (8 hours) - Used only for exchange
2. **Access Token** (4 hours) - Used for service calls

If mission is canceled, exchange fails → agent loses access immediately.

### Temporal Uncertainty Gap
The problem that credentials valid at event publish time (T₀) may be expired/revoked at processing time (T₁). Missions solve this by:
- Long-lived authorization (mission token)
- Short-lived access (service tokens)
- Mid-flight cancellation capability

---

## Production Differences

This demo uses mocks. In production:

- **Mission Authority**: Real service with database, SPIFFE validation, audit logging
- **Wiki Service**: Real Kagenti Wiki Memory Tool
- **Approval**: Web UI or mobile app (not CLI)
- **Events**: Missions embedded in CloudEvents, validated by Event Bridge Proxy
- **Multi-Agent**: Multiple agents sharing mission tokens in events

---

## Related Kagenti Work

This demo builds on:
- **Epic #1460**: Authorization and Identity for Event-Driven Agents
- **Issue #1918-1920**: Mission Framework tracks
- **Event Bridge Proxy**: CloudEvent signing and validation (Phase 0)
- **AuthBridge**: SPIFFE integration for agent identity

---

## Files

- `mock_mission_authority.py` - Mock Mission Authority (port 8001)
- `mock_wiki_service.py` - Mock Wiki Service (port 8002)
- `claude-code-skill/` - Mission skill for Claude Code
  - `skill.py` - Implementation (Click CLI)
  - `skill.json` - Metadata

---

## Next Steps

### After Demo Validation
1. Build real Mission Authority service (Go/FastAPI)
2. Add mission commands to kosh CLI
3. Integrate with Event Bridge Proxy for mission validation
4. Define Mission CRDs (Mission, ScheduledMission, MissionAuthority)
5. Add mission tokens to CloudEvents

### Future Demos
- Demo 1: Recurring missions (90-day duration)
- Demo 2: Multi-agent orchestration with shared missions
- Demo 3: Cross-cluster missions

---

## Troubleshooting

**"Address already in use" error**:
```bash
# Stop any running services
lsof -ti:8001 -ti:8002 | xargs kill 2>/dev/null
```

**"Mission token not found" error**:
```bash
# Make sure mission was approved
python3 mock_mission_authority.py approve <mission_id>

# Check token file exists
ls ~/.claude/missions/<mission_id>.token
```

**"Connection refused" error**:
- Make sure Mission Authority is running on port 8001
- Make sure Wiki Service is running on port 8002

---

## Contributing

This is a proof-of-concept demo for KubeCon 2026. For questions or contributions:
- Epic #1460: Authorization and Identity for Event-Driven Agents
- Contact: Alan Cha (@Alan-Cha)

---

## License

[Same as Kagenti project]
