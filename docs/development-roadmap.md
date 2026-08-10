# Development roadmap

This roadmap converts the remaining requirements in *Agent Factory Technical Specification v1.0* (2 August 2026) into an ordered delivery backlog. It is deliberately based on the current repository rather than treating the specification as a greenfield design.

The importable source of the issue list is [`examples/development-backlog.json`](../examples/development-backlog.json). Stable IDs in that file are permanent. Titles, descriptions, and implementation choices may evolve without changing those IDs.

## Current baseline

| Capability | Assessment | Roadmap treatment |
|---|---|---|
| Configured agents and provider adapters | Implemented alpha | Preserve; normalize the adapter contract and add qualification/lifecycle. |
| One-use provider and GitHub approvals | Implemented alpha | Generalize into a deterministic policy plane without weakening existing gates. |
| Static workflow DAG and typed stage evidence | Implemented alpha | Migrate to a versioned durable workflow and criterion-level evidence ledger. |
| SQLite migrations, audit events, backup, and interrupted-attempt reconciliation | Implemented alpha | Preserve data while adding the full domain model, outbox, checkpoints, and recovery. |
| GitHub plan/review/approve/apply | Implemented alpha | Route it through the future tool gateway as the first protected connector. |
| Local web operator experience | Foundation implemented | AF-036 provides shared typed application services; deliver the loopback host and UI in the remaining R0.2 tasks, then evolve it in R4. |
| Mission intake, Blueprint, role pools, and Workforce Composer | Missing | Deliver in Release 2 after the durable core exists. |
| Persistent loops, scheduling leases, immutable context, and typed memory | Missing | Deliver on the critical path before broader autonomy. |
| Sandbox manager, MCP manager, evaluation service, and red-team harness | Missing | Deliver before enabling bounded autonomous mutation. |
| REST API, web control plane, PostgreSQL, multi-tenancy, and clustered deployment | Missing | Deliver after the local durable runtime is proven. |
| Pack SDK, production qualification, soak test, and acceptance mission | Missing | GA work; explicitly downstream of the operating platform. |

## Delivery rules

- Preserve project neutrality: no product-specific workflow or source document belongs in factory core.
- Repeat the read-only Phase 0 environment/access audit from Appendix K for every target deployment; that environment-specific report is an entry gate, not a portable product feature.
- Keep the deterministic offline path working in every release.
- Migrate existing `0.1.x` state forward; do not replace the current safety gates with an incompatible prototype.
- Every accepted task maps each acceptance criterion to stored evidence produced or verified independently of the implementing worker.
- External mutation stays deny-by-default, idempotent, auditable, and approval-gated at the configured risk tier.
- A release is complete only when its executable tasks meet the task Definition of Done below.
- Review risks R-01 through R-20 at every release gate and after any critical incident, provider, tool class, pack, or production architecture change.

## Dependency path

```mermaid
flowchart LR
    R02["R0.2 Local Control Center MVP"] --> R4["R4 Operable Platform"]
    R1["R1 Durable Safe Core"] --> R2["R2 Mission Factory"]
    R1 --> R3["R3 Safe Extensibility"]
    R2 --> R3
    R3 --> R4["R4 Operable Platform"]
    R4 --> R5["R5 Production Qualification"]
```

The immediate operator-experience sequence is `AF-036 → AF-037 → AF-038/AF-039/AF-040/AF-042 → AF-041 → AF-043`. In parallel, the first durable-core sequence is `AF-001 → AF-002/AF-003 → AF-004 → AF-005/AF-006 → AF-007 → AF-008`. Work on `AF-009` and `AF-010` may begin once `AF-001` and `AF-004` are stable. Release names are outcome groupings, not implicit global barriers: the explicit dependencies in the issue manifest are authoritative and permit reviewed overlap between releases.

## R0.2 — Local Control Center MVP

**Target:** make the current local Agent Factory observable and operable from one lightweight Windows web interface while preserving the existing CLI behavior, provider gates, independent reviews, founder approval, and GitHub dry-run defaults.

| ID | Priority | Deliverable | Depends on | Specification trace |
|---|---:|---|---|---|
| AF-036 | P0 | Shared application-service boundary for CLI and web | — | Operator request; foundation for §27 |
| AF-037 | P0 | Local FastAPI host and read-only operations API | AF-036 | Operator request; precursor to §32 |
| AF-038 | P0 | Live development dashboard and navigation shell | AF-037 | Operator request; precursor to §27 |
| AF-039 | P0 | Backlog, work-item, and workflow run controls | AF-037 | Operator request; precursor to §27 |
| AF-040 | P0 | Agent, provider, and reviewer routing controls | AF-037 | Operator request; AC-03 precursor |
| AF-041 | P0 | Review inbox and founder approval workspace | AF-037, AF-040 | Operator request; AC-42 precursor |
| AF-042 | P0 | Audit explorer, runtime settings, and GitHub sync preview | AF-037 | Operator request; §§27, 30 precursor |
| AF-043 | P0 | Windows launch experience, accessibility, and end-to-end qualification | AF-038, AF-039, AF-040, AF-041, AF-042 | Operator request; §36 precursor |

**Exit evidence:** from a fresh local state, the operator opens the dashboard, imports or inspects work, runs a deterministic workflow, sees independent reviewer routing, makes the explicit founder decision, reviews the complete audit trail, and previews GitHub synchronization without an unintended external mutation.

This MVP is intentionally loopback-only and single-operator. It uses current SQLite state and shared Python application services rather than becoming a second orchestration implementation. `AF-026`, `AF-029`, and `AF-030` later add the authenticated, multi-tenant, production service boundary without discarding this UI.

**Progress:** AF-036 is complete. CLI commands now use the shared typed service boundary, and contract tests prove matching state transitions and audit events. AF-037 is unblocked.

## R1 — Durable Safe Core

**Target:** a restart-safe local orchestrator with versioned authority, independent evidence, normalized agents, leases, and bounded persistent loops.

| ID | Priority | Deliverable | Depends on | Specification trace |
|---|---:|---|---|---|
| AF-001 | P0 | Versioned tenant-aware domain model and compatibility migration | — | §§3, 33, 35; AC-02 |
| AF-002 | P0 | Transactional event outbox and tamper-evident audit chain | AF-001 | §§30, 32–33; AC-34, AC-37 |
| AF-003 | P0 | Content-addressed artifact and criterion-evidence ledger | AF-001 | §§3, 24, 29; AC-26, AC-31, AC-33 |
| AF-004 | P0 | Deterministic policy plane, autonomy modes, and emergency stop | AF-001, AF-002 | §§5, 27–28; AC-27–30, AC-42 |
| AF-005 | P0 | Normalized adapter contract, qualification, and agent lifecycle | AF-001, AF-004 | §§8–9; AC-01–03 |
| AF-006 | P0 | Versioned durable workflow DSL, signals, timers, and resume | AF-002, AF-003, AF-004 | §15; AC-12, AC-36–37 |
| AF-007 | P0 | Dependency scheduler, TTL/fenced leases, and conflict domains | AF-005, AF-006 | §17; AC-15 |
| AF-008 | P0 | Persistent nested Loop Engineering and no-progress control | AF-003, AF-006, AF-007 | §16; AC-13–14 |

**Exit evidence:** upgrade test from the current SQLite schema, restart/replay test, duplicate-mutation fault injection, lifecycle handoff test, criterion-complete evidence manifest, authenticated tenant/RBAC/MFA policy tests, and two-person P4 approval enforcement. Full checkpoint replacement is completed by `AF-028`.

## R2 — Mission Factory

**Target:** analyze a free-form mission, compose a justified workforce, approve a versioned Factory Blueprint, and bootstrap a resumable mission.

| ID | Priority | Deliverable | Depends on | Specification trace |
|---|---:|---|---|---|
| AF-009 | P1 | Mission intake, source authority, clarifications, and readiness verdict | AF-001, AF-004 | §12; AC-08–09 |
| AF-010 | P1 | Versioned Role Definition catalog and compatibility contracts | AF-001, AF-004 | §10; AC-05 |
| AF-011 | P1 | Evaluation-aware Agent Router, independent reviewer rotation, and qualification history | AF-005, AF-010 | §§9, 23; AC-01, AC-03 |
| AF-012 | P1 | Role pools, arbitration strategies, and Workforce Composer | AF-010, AF-011 | §§10–11; AC-06–07 |
| AF-013 | P1 | Factory Blueprint generation, alternatives, approval, and amendments | AF-009, AF-010, AF-012 | §13; AC-10–11, AC-16 |
| AF-014 | P1 | Idempotent mission bootstrap, manifests, and rollback point | AF-006, AF-007, AF-013 | §14 |
| AF-015 | P1 | Immutable Context Packages, provenance, broker, and compaction | AF-003, AF-009, AF-013 | §20; AC-17–18 |
| AF-016 | P1 | Typed memory, bounded retrieval, invalidation, and governed skills | AF-015 | §21; AC-19–21 |

**Exit evidence:** one natural-language mission reaches `READY_FOR_BLUEPRINT`, exposes rejected alternatives and uncertainties, composes a two-agent strengthened role, receives human Blueprint approval, and bootstraps without hard-coded project logic.

## R3 — Safe Extensibility

**Target:** execute untrusted work inside narrow environments, broker tools and secrets, verify independently, govern architecture changes, and install capabilities without editing core.

| ID | Priority | Deliverable | Depends on | Specification trace |
|---|---:|---|---|---|
| AF-017 | P1 | Resource- and network-restricted sandbox manager | AF-003, AF-004 | §24; AC-25 |
| AF-018 | P1 | Tool Registry, Tool Gateway, MCP manager, and connector lifecycle | AF-002, AF-004, AF-017 | §22; AC-22–23 |
| AF-019 | P1 | Short-lived scoped credential broker with zero prompt/log exposure | AF-004, AF-017, AF-018 | §§22, 28; AC-24 |
| AF-020 | P1 | Evaluation, quality gates, model-independent judges, and signed verdicts | AF-003, AF-015, AF-018 | §29; AC-31–33 |
| AF-021 | P1 | Prompt-injection red team, tripwires, quarantine, and incidents | AF-004, AF-017, AF-018, AF-020 | §§28–29; AC-29–30 |
| AF-022 | P1 | ADR governance and transactional Blueprint impact propagation | AF-006, AF-013, AF-015 | §18; AC-16 |
| AF-023 | P1 | Audited parallel, generator-critic, quorum, debate, and red/blue patterns | AF-008, AF-012, AF-020 | §19; AC-06 |
| AF-024 | P1 | Signed pack SDK and install/upgrade/disable/rollback manager | AF-004, AF-018, AF-020 | §25; AC-41 |
| AF-025 | P1 | Software Engineering reference pack with isolated worktrees and release evidence | AF-014, AF-017, AF-020, AF-024 | §26; AC-40 |

**Exit evidence:** an allowlisted MCP tool runs through policy and sandbox boundaries; an injected instruction cannot widen authority; a pack is installed and rolled back without core changes; an implementation task is independently verified.

## R4 — Operable Platform

**Target:** expose one governed service boundary, make missions observable and recoverable, isolate tenants, and provide a usable human control plane.

| ID | Priority | Deliverable | Depends on | Specification trace |
|---|---:|---|---|---|
| AF-026 | P2 | REST operations API, idempotency/ETags, webhooks, and SDK contracts | AF-002, AF-004, AF-006 | §32 |
| AF-027 | P2 | OpenTelemetry traces, metrics, cost ledger, forecasts, and budget actions | AF-002, AF-006, AF-018 | §30; AC-34–35 |
| AF-028 | P2 | Checkpoints, reconciliation, chaos recovery, and verified restore | AF-002, AF-006, AF-007, AF-017 | §31; AC-04, AC-36–38 |
| AF-029 | P2 | PostgreSQL/object storage migration and end-to-end tenant isolation | AF-002, AF-016, AF-026, AF-027, AF-028 | §§33, 35; AC-39 |
| AF-030 | P2 | Human Control Plane for evidence, approvals, incidents, cost, and intervention | AF-004, AF-005, AF-012, AF-026, AF-027, AF-029, AF-043 | §27; AC-03, AC-42 |
| AF-031 | P2 | Single-node, clustered, hybrid, and air-gapped deployment definitions | AF-027, AF-028, AF-029 | §34 |

**Exit evidence:** the CLI and UI use the same API contracts; one root trace connects mission-to-evidence; a worker restart resumes without duplicate mutation; adversarial tenant tests observe no foreign data or side effects; classification, residency, retention, legal hold, quota, export, and deletion policies produce auditable evidence.

## R5 — Production Qualification

**Target:** prove the product against its measurable SLOs and the reusable reference acceptance mission, then hand it over with recovery evidence.

| ID | Priority | Deliverable | Depends on | Specification trace |
|---|---:|---|---|---|
| AF-032 | P3 | NFR, performance, accessibility, isolation, and recovery qualification suite | AF-020, AF-027, AF-030, AF-031 | §§36, 38; AC-38–39 |
| AF-033 | P3 | 72-hour fault-injection soak with bounded resource growth | AF-028, AF-031, AF-032 | §38.5; AC-43 |
| AF-034 | P3 | Full heterogeneous-agent reference acceptance mission | AF-013, AF-023, AF-025, AF-030, AF-033 | §39; AC-44–45 |
| AF-035 | P3 | Runbooks, clean install, restore exercise, GA evidence, and handover | AF-031, AF-034 | §§40–43; AC-38, AC-44–45 |

**Exit evidence:** all 45 final acceptance criteria are mapped to stored evidence, the 72-hour run loses no accepted state, and a second unrelated mission starts without core workflow changes.

## Definition of Ready

An executable task is ready only when it has:

- a stable ID, priority, owning role, versioned inputs, and satisfied dependencies;
- measurable acceptance criteria plus the required evidence type;
- tool, data, environment, permission, timeout, iteration, and budget limits;
- expected artifact/output contracts and independent reviewers;
- applicable requirement, Blueprint, architecture, and risk references.

The initial issue manifest intentionally supplies product outcome, dependencies, specification trace, and acceptance criteria. The Backlog Steward must add release-specific owner, estimate, and operational limits before changing an item to `ready`.

## Definition of Done

An executable task is done only when:

- required deterministic gates and independent reviews pass;
- each acceptance criterion points to immutable stored evidence;
- findings are resolved or explicitly accepted by the configured human authority;
- task journal, handoff, traceability, cost, and resource usage are complete;
- leases, temporary environments, and scoped credentials are released;
- downstream contracts are updated; and
- the workflow transitions the item to `ACCEPTED`; the implementing agent never self-declares completion.

## Using the issue manifest

Validate locally without network access:

```bash
agent-factory backlog validate --path examples/development-backlog.json
```

Preview GitHub changes without applying them:

```bash
agent-factory backlog sync --path examples/development-backlog.json --repo OWNER/REPOSITORY
```

The sync command remains dry-run by default. Review the immutable plan and its digest before separately approving any apply operation. The roadmap commit does not create, close, merge, or reprioritize GitHub Issues automatically.
