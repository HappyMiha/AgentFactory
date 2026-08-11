# Changelog

All notable changes to Agent Factory are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Shared typed application-service boundary for CLI and Local Control Center queries and guarded commands.
- Contract tests proving equivalent CLI and service state transitions and audit events.
- Loopback-only FastAPI host with typed, bounded, read-only Local Control Center endpoints and structured failures.
- Live Local Control Center dashboard shell with delivery counts, workflow, approval, provider, and failure status that refreshes without navigation.
- Guarded backlog and workflow workspace with six work-item filters, contract and artifact inspection, simulation-only execution, artifact review, and ordered run evidence.
- Workspace-local agent controls with role-compatible provider replacement, audited impact records, detailed provider health, assignment usage, and explainable independent-review routing.
- Correlated audit explorer, immutable allowlisted runtime-setting history, and workspace-contained GitHub dry-run planning with SHA-256-bound approval gates.
- Founder review inbox with complete decision packets, separate guarded authority, idempotent same-decision replay, conflicting-decision protection, and attributable audit receipts.
- Windows `web --open` launch flow, guarded workspace backlog import, documented accessibility checklist, automated semantic/contrast checks, and fresh-state R0.2 end-to-end qualification.
- Durable proxy-reviewer pools with model-aware author exclusion, least-used rotation, assignment history, and audit events.
- Independent rotating policy post-checks that cannot reuse the implementation or validation producer models.
- Guarded Antigravity CLI adapter with native Windows and Unix executable discovery, plan mode, OS sandboxing, and a replaceable implementation worker.
- Immutable approval snapshots that bind each provider gate to the full work item, agent definition, provider catalog, and execution policy.
- Guarded Firecrawl CLI integration with a least-privilege `Web Researcher` role, source-oriented instructions, fixed five-credit ceiling, and one-use execution approval.
- Accepted Control Plane/Hermes authority boundary and expanded the implementation backlog through AF-057 around the restart-safe single-node coding loop.
- AF-001 versioned SQLite domain model with immutable identities for work items, runs, stages, assignments, sessions, attempts, leases, worktrees, and artifacts; normalized WorkItem authority; compatibility backfill; and lifecycle state-machine enforcement.
- AF-002 transactional event outbox with stable delivery keys and guarded claims, complete correlation envelopes, concurrent-safe SHA-256 audit chaining, immutable audit records, and integrated tamper verification.
- AF-003 evidence ledger with SHA-256 artifact envelopes, typed criterion mappings, explicit verifier decisions, primary-evidence closure gates, immutable accepted evidence, and integrity verification.
- AF-004 durable Control Plane policy with allow/deny/require-approval decisions, exact one-use execution approvals, immutable decision records, persistent emergency stop, dispatch blocking, and mutable-session cancellation.
- AF-005 normalized provider adapter contract, eight-dimensional health evidence, immutable worker qualifications, lifecycle quarantine/draining, compatible replacement routing, and durable recovery handoffs.
- AF-006 version-pinned durable workflow runs, dependency-aware stage checkpoints, restart resume, durable waiting-approval state, and generic provider/worktree/GitHub mutation idempotency reservations.
- AF-007 dependency readiness scheduler with atomic durable assignments, TTL leases, monotonic fencing tokens, fenced artifact/commit boundaries, and serialized or escalated hierarchical conflict domains.
- AF-017 fail-closed writable-worker sandbox policies, Bubblewrap and macOS enforcement backends, audited path denials, external process/time/output/network controls, and preserved teardown evidence.
- AF-044 lifecycle-aware Worker Runtime contract with durable sessions/events, shared Direct CLI and Hermes ACP adapters, structured results, immutable external identities, and a durable post-mutation fallback barrier.
- AF-048 Control-Plane-owned Git worktree manager with deterministic fenced branches/paths, immutable authority metadata, crash-safe replay, non-destructive reconciliation, and terminal retention cleanup.
- AF-055 immutable Execution Context Packages with fenced dispatch scope, canonical SHA-256 identity, explicit source inclusion/exclusion/supersession, deterministic byte/token compaction, and runtime digest enforcement.
- AF-045 concrete Hermes ACP stdio driver with exact version/check qualification, durable task/run/stage/attempt/worktree/context bindings, normalized protocol events, permission bridging, stable restart reattachment, and process-tree cancellation.
- AF-046 durable per-stage live execution approvals with exact runtime scope, immutable gate-to-attempt consumption, pre-process rejection/expiry enforcement, and automatic dependency-ready continuation.
- AF-049 qualified writable Codex CLI worker with a fixed workspace-write profile, leased-worktree scope, JSONL command/handoff evidence, immutable candidate results, and complete process-tree timeout/cancellation.
- AF-052 deterministic validator packs with five required shell-free command categories, candidate-worktree execution, bounded output/environment evidence, and exact acceptance-criterion mappings.
- AF-051 immutable validated candidate commits with stable task IDs, base-branch preservation, failed-validation denial, and separately gated pull-request plans.
- AF-020 evidence-first independent evaluation with producer-model exclusion, versioned rubrics, immutable criterion verdicts, confidence, concerns, dissent, and primary-evidence closure.
- AF-008 durable bounded engineering loops with complete iteration snapshots, deterministic iteration/time/token/cost/tool-failure caps, repeated-failure replan or replacement, evidence-only acceptance, and human-approved limit increases.
- Evidence-based implementation audit and release notes covering all AF-001–AF-057 statuses, completed-task dates, implementation commits, and current test evidence.

### Changed

- Agent definitions now carry a stable model identity, and provider replacement clears or explicitly updates that identity.
- Roadmap tasks AF-011, AF-020, and AF-023 now require model-independent review routing and recorded rotation evidence.
- Provider launch now falls through to the next reviewed executable only when process creation fails before a provider starts, including Windows access-denied aliases.
- Provider stdout and stderr are drained through a hard combined limit; overflowing processes are terminated and audited.
- The test matrix now covers Python 3.11 and 3.12 on Windows, Ubuntu, and macOS.
- The critical path now uses Hermes ACP for mutable sessions, keeps worktree ownership in the Control Plane, makes context and worktrees prerequisites of the Hermes adapter, promotes the MVP independent-review subset of AF-020 to P0, and moves the optional Claude worker AF-050 to P1.

### Planned

- Native HTTP provider interface.
- Streaming output limits and value-aware secret redaction.
- PostgreSQL storage adapter.
- Hosted control interface.

## [0.1.0] - 2026-08-02

### Added

- Project-neutral work items, agent roles, provider definitions, artifacts, and approval gates.
- Deterministic offline provider for safe demonstrations and CI.
- Guarded CLI adapters for Codex, Claude, Gemini, and Ollama.
- Health-only OpenClaw integration with execution disabled by default.
- Dependency-aware workflows with typed verdict and acceptance-evidence contracts.
- SQLite migrations, WAL mode, online backups, integrity checks, and interrupted-attempt reconciliation.
- One-use human approval gates for real provider calls.
- Separate final acceptance decisions for completed workflows.
- GitHub dry-run planning, mutation allowlists, plan hashing, idempotency, and durable reports.
- Cross-platform process-group supervision and bounded execution.
- Windows, Ubuntu, and macOS CI plus wheel and Docker build checks.
