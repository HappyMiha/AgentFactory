# ADR-0001: Control Plane authority and Hermes execution boundary

- Status: accepted
- Date: 2026-08-11
- Decision owner: Founder / Control Plane authority

## Context

Agent Factory needs a persistent coding loop with tool use, skills, sessions, and subagents. Hermes can supply that execution behavior, but treating it as the orchestrator would create a second authority for scheduling, policy, approvals, evidence, and terminal state. That would weaken the existing one-use gates, independent evidence, founder decision, and audit model.

## Decision

The Control Plane remains authoritative for backlog and dependency readiness; policy and emergency stop; human approvals; scheduling, assignments, leases, fencing tokens, and budgets; worktree identity; evidence, acceptance criteria, terminal workflow state, and audit.

Hermes is a lifecycle-aware Worker Runtime responsible for the bounded execution loop, allowlisted tool and skill use, worker sessions, heartbeats, cancellation and resume, scoped subagent delegation, and structured execution events, tool calls, artifacts, and terminal runtime status.

Hermes receives an immutable scoped context package, exact permissions, runtime limits, worktree identity, lease, and approval reference. It cannot widen those inputs, issue a Control Plane approval, merge or push by default, or declare a task accepted. A runtime `succeeded` status means only that execution ended successfully; the Control Plane advances or accepts work only after required primary evidence, deterministic validation, independent review, and the configured human decision.

Hermes is not implemented as a regular `CLIProvider`. A `WorkerRuntime` contract owns `start`, `resume`, `heartbeat`, `cancel`, `collect_events`, and `finalize`. Direct CLI workers and Hermes implement the same contract tests. Fallback is forbidden after the first mutable action unless the Control Plane records a compatible checkpoint, terminates the old lease, and issues a new fenced assignment.

## Consequences

- Durable domain identities include worker sessions, attempts, leases, worktrees, and artifacts before Hermes integration.
- Live workflow stages gain a durable `waiting_approval` state.
- Worktree management, validator execution, evidence mapping, budgets, and recovery are P0 parts of the single-node coding loop.
- PostgreSQL, Redis, Qdrant, multi-tenancy, clustered deployment, hosted Control Plane, and broad MCP gateway work follow proof of the restart-safe single-node vertical slice.
- Existing CLI providers remain useful for advisory and qualified fallback work, but do not define the Hermes lifecycle contract.

