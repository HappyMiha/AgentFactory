# Implementation audit — 2026-08-11

This audit compares the repository through the AF-049 implementation with the acceptance criteria in the [canonical implementation backlog](../examples/development-backlog.json) and the readable [development roadmap](development-roadmap.md). It records product implementation status, not just the presence of a similarly named class, table, issue, or commit.

## Audit method

- `Implemented`: all task acceptance criteria have direct code and automated-test evidence in the repository.
- `Partial`: useful precursor behavior exists, but at least one material acceptance criterion is absent. Partial work does not satisfy dependencies.
- `Not started`: no task-specific implementation exists. Schema placeholders, plans, or generic infrastructure alone do not count.
- Evidence was checked against source, migrations, tests, Git history, and the installed Hermes 0.20.0 interface.
- The full suite passed: **161 tests**, plus offline validation of `examples/development-backlog.json`.

## Result

| Status | Tasks | Count |
|---|---|---:|
| Implemented | AF-001–AF-007, AF-017, AF-036–AF-046, AF-048, AF-049, AF-055 | 22 |
| Partial precursors | AF-008, AF-010, AF-011, AF-018–AF-020, AF-023, AF-026, AF-028, AF-030, AF-032, AF-047, AF-051, AF-052, AF-056, AF-057 | 16 |
| Not started | AF-009, AF-012–AF-016, AF-021, AF-022, AF-024, AF-025, AF-027, AF-029, AF-031, AF-033–AF-035, AF-050, AF-053, AF-054 | 19 |

The product has a tested durable-data, fenced-scheduler, managed-worktree, immutable-context, concrete Hermes ACP, and local-operator foundation, but it does **not** yet have the single-node coding vertical slice. In particular, no qualified writable Codex worker runs allowlisted project validators or completes the bounded repair/recovery loop.

## Task-by-task findings

| ID | Status | Evidence already present | Material gap |
|---|---|---|---|
| AF-001 | Implemented | Versioned migrations, normalized identities, lifecycle guards; `test_storage_migrations.py` | — |
| AF-002 | Implemented | Transactional outbox, delivery keys, SHA-256 audit chain; `test_outbox_audit.py` | — |
| AF-003 | Implemented | Content-addressed evidence ledger and immutable acceptance; `test_evidence_ledger.py` | — |
| AF-004 | Implemented | Deterministic policy, exact one-use approvals, persistent emergency stop; `test_policy_plane.py` | — |
| AF-005 | Implemented | Normalized provider contract, eight health dimensions, qualification and handoff; `test_adapter_qualification.py` | — |
| AF-006 | Implemented | Version-pinned durable stages, resume and mutation reservations; `test_durable_workflow.py` | — |
| AF-007 | Implemented | Leaf-task/dependency readiness, atomic assignments and TTL leases, monotonic fencing, fenced artifact/commit boundaries, conflict serialization/escalation; `test_scheduler.py` | — |
| AF-008 | Partial | Durable stage checkpoints and existing delivery workflow | No persisted multi-iteration objective/plan/diff/critic/budget loop or repeated-failure replan rule |
| AF-009 | Not started | — | Mission intake, source authority, clarification and readiness model absent |
| AF-010 | Partial | Simple agent roles and role allowlists | No versioned provider-neutral typed role input/output/evidence contract or incompatible-duty validation |
| AF-011 | Partial | Model-independent reviewer rotation, qualification filtering, durable handoff | General router does not yet score cost, latency, load, exclusions, rationale, and fallback chain |
| AF-012 | Not started | — | Role pools, arbitration strategies and Workforce Composer absent |
| AF-013 | Not started | — | Factory Blueprint lifecycle absent |
| AF-014 | Not started | — | Blueprint-based idempotent mission bootstrap absent |
| AF-015 | Not started | — | Role/purpose context broker and governed compaction absent |
| AF-016 | Not started | — | Typed memory and invalidation model absent |
| AF-017 | Implemented | Fail-closed path policy, fenced launches, Bubblewrap/macOS backends, unsupported-host denial, audited out-of-scope writes, bounded process/time/output/network execution and preserved candidate evidence; `test_sandbox.py` | — |
| AF-018 | Partial | Guarded GitHub and Firecrawl integrations | No Tool Registry/Gateway, MCP lifecycle, normalized tool contracts, or centralized authorization boundary |
| AF-019 | Partial | Sensitive environment removal from provider subprocesses | No short-lived credential broker, scope issuance, revocation, injection firewall, or zero-exposure proof |
| AF-020 | Partial | Independent reviewer rotation and criterion evidence gates | No post-AF-052 evaluation service with versioned rubric, criterion verdict, confidence, concerns, and dissent |
| AF-021 | Not started | — | Red-team corpus, tripwires, quarantine and incidents absent |
| AF-022 | Not started | ADR document exists | No transactional ADR/Blueprint impact propagation lifecycle |
| AF-023 | Partial | Static generator/reviewer workflow and model-aware rotation | No configurable parallel, quorum, debate, generator-critic or red/blue execution patterns |
| AF-024 | Not started | — | Signed pack SDK and lifecycle manager absent |
| AF-025 | Not started | — | Installable Software Engineering reference pack absent; core worktree work moved to AF-048 |
| AF-026 | Partial | Loopback FastAPI Local Control Center | No production REST boundary, authentication, ETags/idempotency, webhooks, SDK contract, or complete resource surface |
| AF-027 | Not started | Budget fields exist | No OpenTelemetry export, metrics set, cost ledger, or threshold actions |
| AF-028 | Partial | SQLite backup, integrity checks and interrupted-attempt inspection/reconciliation | No clustered chaos suite or verified restore across storage/queue/network/host failures |
| AF-029 | Not started | — | PostgreSQL/object storage and tenant isolation deliberately deferred |
| AF-030 | Partial | Loopback dashboard, approvals, audit, routing controls | No authenticated multi-tenant Human Control Plane, incident/cost/lease controls, or production service boundary |
| AF-031 | Not started | Docker packaging exists | No qualified single-node/clustered/hybrid/air-gapped deployment definitions |
| AF-032 | Partial | Cross-platform CI, accessibility tests and checklist | No complete NFR, performance, isolation and recovery qualification suite |
| AF-033 | Not started | — | 72-hour fault-injection soak absent |
| AF-034 | Not started | — | Full heterogeneous-agent acceptance mission absent |
| AF-035 | Not started | Baseline README/security/contribution docs | No GA runbooks, clean-install/restore exercise, evidence bundle or handover |
| AF-036 | Implemented | Shared typed application services and CLI/service parity tests | — |
| AF-037 | Implemented | Loopback FastAPI host and typed bounded operations API tests | — |
| AF-038 | Implemented | Live dashboard shell and UI state tests | — |
| AF-039 | Implemented | Guarded backlog/workflow controls and tests | — |
| AF-040 | Implemented | Provider/agent/reviewer routing controls and tests | — |
| AF-041 | Implemented | Founder decision packets, separate authority and idempotency tests | — |
| AF-042 | Implemented | Audit/settings workspace and SHA-256-bound GitHub dry-run preview tests | — |
| AF-043 | Implemented | Windows launch, accessibility and fresh-state end-to-end qualification | — |
| AF-044 | Implemented | Durable lifecycle and immutable structured events, shared Direct CLI/Hermes ACP contract, typed final result, mutation-aware fallback barrier and one-shot restrictions; `test_worker_runtime.py` | — |
| AF-045 | Implemented | Exact executable/version/check/workspace qualification, ACP stdio process supervision, immutable task/run/stage/attempt/role/worktree/context/tool binding, protocol event and permission mapping, stable `session/load` restart identity, and complete process-tree cancellation; `test_hermes_acp.py` | — |
| AF-046 | Implemented | Durable live-stage waiting, exact pre-process runtime authorization, immutable gate-to-attempt consumption, rejection/expiry denial, and dependency-ready continuation; `test_live_stages.py`, `test_worker_runtime.py`, `test_hermes_acp.py` | — |
| AF-047 | Partial | AF-005 generic qualification, quarantine and handoff | No Hermes-specific ACP/version/workspace/cancellation/tool/artifact qualification or controlled runtime fallback |
| AF-048 | Implemented | Fenced deterministic Git worktree provisioning, exclusive task/lease ownership, startup reconciliation, retention and branch-preserving cleanup; `test_worktrees.py` | — |
| AF-049 | Implemented | Qualified fixed Codex exec profile, leased-worktree native sandbox boundary, immutable command/diff/exit/handoff result, forbidden authority profile, and process-tree timeout/cancel; `test_codex_worker.py` | — |
| AF-050 | Not started | Generic Claude CLI provider exists | No separately qualified writable Claude Code worker profile |
| AF-051 | Partial | Generic artifacts and approval-gated GitHub plans exist | No immutable candidate-change artifact binding base/head SHA, diff digest, files and worktree identity |
| AF-052 | Partial | Workflow validation stage and evidence contracts exist | No shell-free allowlisted command-vector runner, project pack, candidate-worktree execution, or command evidence envelope |
| AF-053 | Not started | — | No integrated claim→worktree→implement→validate→review→repair→founder→PR-plan loop |
| AF-054 | Not started | Some legacy agent roles exist | No typed software-engineering role pack or duty-separation enforcement |
| AF-055 | Implemented | Fenced canonical dispatch packages, immutable SHA-256 identity, required task/dependency/base/policy scope, explicit included/excluded/superseded sources, deterministic byte/token compaction and runtime digest binding; `test_context_packages.py`, `test_worker_runtime.py` | — |
| AF-056 | Partial | Correlation fields and budget values are stored in parts of the schema | No end-to-end correlation root, enforced token/cost/stage budgets, runtime usage ingestion, or dashboard operational state |
| AF-057 | Partial | Legacy interrupted provider-attempt reconciliation and integrity checks | No Hermes/process/worktree orphan reconciliation, fencing protection for commits, or mutation-boundary crash qualification |

## Backlog decisions from the audit

1. **AF-007 closes M1; AF-017, AF-044 through AF-046, AF-048, AF-049, and AF-055 supply isolation, runtime, concrete ACP, exact live approvals, worktree, the first writable worker, and immutable-context boundaries.** AF-052 can now add deterministic candidate validation.
2. **Use Hermes ACP for mutable sessions.** Installed Hermes 0.20.0 exposes an ACP stdio server, structured events and permission bridging. `hermes --oneshot` states that approvals are auto-bypassed, so it is limited to qualification or read-only probes.
3. **Keep worktree authority in AgentFactory.** AF-048 creates and owns the worktree; AF-045 passes it to Hermes as the working directory. Managed sessions must not invoke Hermes `--worktree`.
4. **Make context and worktree prerequisites of Hermes.** AF-045 now depends on AF-048 and AF-055, preventing an unscoped runtime session.
5. **One writable worker proves the slice.** AF-049 Codex stays P0; AF-050 Claude Code moves to P1 and is not an MVP exit dependency.
6. **Independent review is not optional for MVP.** The local criterion-verdict subset of AF-020 moves to P0 and becomes an AF-053 dependency.
7. **Separate idempotent integration from crash recovery.** AF-053 proves replay-safe logical attempts; AF-056 adds correlation/budget enforcement; AF-057 owns full local crash-boundary reconciliation.
8. **Keep platform expansion deferred.** PostgreSQL, object storage, multi-tenancy, OpenTelemetry export and clustered deployment remain downstream of AF-057 evidence.

## Rebased delivery order

```text
Done: AF-001 -> AF-002/AF-003/AF-004 -> AF-005/AF-006 -> AF-007; AF-017 + AF-044 + AF-045 + AF-046 + AF-048 + AF-049 + AF-055

Now:  AF-052 -> AF-020 + AF-051
      -> AF-008 -> AF-053 -> AF-056 -> AF-057

Then: AF-047 + AF-050 + AF-054
Later: AF-015/AF-016/AF-027/AF-028, then AF-018/AF-019/AF-026/AF-029–AF-031
```

The M1 release gate is complete at **AF-007**. The next gate is the M2 first coding worker slice; a chat response from Hermes remains environment evidence only and does not prove scoped mutation, acceptance evidence, or recovery.
