# Mission-Based Authorization Examples

Examples demonstrating mission-based authorization for event-driven AI agents in Kagenti.

## Overview

Missions solve the "temporal uncertainty gap" in event-driven architectures by providing time-bounded, task-specific authorization with human oversight. This is particularly important for long-running AI agents where credentials might expire between event publication and processing.

## Problem

Traditional approaches fail for event-driven agents:
- **Long-lived credentials**: Security risk
- **Short-lived credentials**: Expire before processing
- **Refresh tokens**: No human oversight for long delays

## Solution

**Mission-based authorization**:
1. Agent requests mission (natural language task description)
2. Human approves mission
3. Mission Authority issues long-lived mission token
4. Agent exchanges for short-lived service tokens (RFC 8693)
5. Agent performs task with oversight
6. Human can cancel mission mid-flight

## Demos

### [Demo 0: End-of-Day Update](./demo-0-end-of-day-update/)

**Status**: ✅ Working proof-of-concept

**Scenario**: AI agent requests mission to read wiki for end-of-day update

**Components**:
- Mock Mission Authority
- Mock Wiki Service
- Claude Code mission skill

**Time**: 5-7 minutes (manual) or 3-5 minutes (integrated)

**Best for**: Understanding the basic mission flow

---

### Demo 1: Recurring Updates (Future)

**Status**: 🔲 Planned

**Scenario**: Agent gets 90-day mission for daily wiki updates

**Shows**: Long-duration missions, recurring execution, cancellation

---

### Demo 2: Multi-Agent Orchestration (Future)

**Status**: 🔲 Planned

**Scenario**: Multiple agents share mission token via CloudEvents

**Shows**: Event-driven patterns, mission token in events, Event Bridge Proxy validation

---

## Key Concepts

### Mission
Human-approved, time-bounded authorization with natural language description.

### Token Exchange (RFC 8693)
Mission token → service-specific access token. Separates authorization from access.

### Temporal Uncertainty Gap
Credentials valid at T₀ (publish) may be invalid at T₁ (process). Missions bridge this gap.

---

## Production Architecture

```
User → Agent → Mission Authority → Event Bridge Proxy → Services
         ↓         ↓                      ↓                ↓
    Request    Approve/Issue        Validate           Access
    Mission    Mission Token        in Events         Resources
```

**Components**:
- **Mission Authority**: Issues/validates missions, handles token exchange
- **Event Bridge Proxy**: Validates mission tokens in CloudEvents
- **Kosh CLI**: User interface for mission approval
- **SPIFFE/SPIRE**: Agent identity and authentication

---

## Related Kagenti Work

- **Epic #1460**: Authorization and Identity for Event-Driven Agents
- **Issues #1918-1920**: Mission Framework implementation tracks
- **Event Bridge Proxy**: CloudEvent signing (Phase 0 - in progress)
- **AuthBridge**: SPIFFE integration foundation

---

## Getting Started

1. Choose a demo (start with Demo 0)
2. Follow the demo's README
3. Run the demo locally
4. Adapt for your use case

---

## Contributing

These examples support the mission authorization framework being built in Kagenti. For questions or contributions, see Epic #1460 or contact the team.

---

## License

[Same as Kagenti project]
