# Implementation audit — 2026-08-11

This audit compares the repository through the AF-015 Context-Broker, AF-050 Claude-worker, and AF-057 local-recovery slices with the acceptance criteria in the [canonical implementation backlog](../examples/development-backlog.json) and the readable [development roadmap](development-roadmap.md). It records product implementation status, not just the presence of a similarly named class, table, issue, or commit.

## Audit method

- `Implemented`: all task acceptance criteria have direct code and automated-test evidence in the repository.
- `Partial`: useful precursor behavior exists, but at least one material acceptance criterion is absent. Partial work does not satisfy dependencies.
- `Not started`: no task-specific implementation exists. Schema placeholders, plans, or generic infrastructure alone do not count.
- Evidence was checked against source, migrations, tests, Git history, and the installed Hermes 0.20.0 interface.
- The full suite passed: **219 tests**, plus offline validation of `examples/development-backlog.json`.

## Result

| Status | Tasks | Count |
|---|---|---:|
| Implemented | AF-001–AF-015, AF-017, AF-020, AF-036–AF-057 | 39 |
| Partial precursors | AF-018, AF-019, AF-023, AF-026, AF-028, AF-030, AF-032 | 7 |
| Not started | AF-016, AF-021, AF-022, AF-024, AF-025, AF-027, AF-029, AF-031, AF-033–AF-035 | 11 |

The product now has a tested, correlated, budget-enforced, restart-qualified single-node coding vertical slice plus fail-closed mission intake, justified workforce composition, exact owner-signed Factory Blueprints, and recoverable idempotent mission bootstrap across durable data, source authority, role contracts, qualification-aware routing, bounded role pools, immutable operating-design versions, exact manifests, managed worktrees, controlled fallback, deterministic validation, independent evaluation, and gated PR planning. Full context brokerage and platform expansion remain downstream work.

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
| AF-008 | Implemented | Restart-persistent immutable iteration snapshots, five deterministic caps, repeated-failure replan/replacement, evidence/failure/escalation terminal guards, and approved limit revisions; `test_engineering_loop.py` | — |
| AF-009 | Implemented | Immutable normalized intake, source authority/version/provenance/conflict records, typed clarification/review requests, owner-only resolutions, and fail-closed readiness assessments; `test_mission_intake.py` | — |
| AF-010 | Implemented | Immutable provider-neutral semantic role versions, typed input/output/evidence validation, tool/permission/limit contracts, workflow role requirements, independent resolution, and per-decision incompatible-duty rejection; `test_roles.py` | — |
| AF-011 | Implemented | Latest-qualification/lifecycle/capability/provider and independence filtering; complete quality/risk/cost/latency/load/health candidate envelopes; immutable rationale and fallback chains; deterministic pinned/best/cost/latency/diversity/canary/tournament/fallback strategies; preserved reviewer rotation; `test_agent_router.py`, `test_reviewer_routing.py` | — |
| AF-012 | Implemented | Immutable qualified role pools, replica bounds, deterministic routing/fallbacks, strengthened heterogeneous arbitration, global capacity/budget allocation, typed gaps, and human-reviewed diversity exceptions; `test_workforce.py` | — |
| AF-013 | Implemented | Eight-section immutable Blueprint versions, complete source/risk/assumption/alternative traces, exact latest-digest owner signatures, execution authorization, and owner-only impact-analyzed amendments preserving history; `test_blueprint.py` | — |
| AF-014 | Implemented | Authorized-digest idempotency, one durable project/task/workflow graph, seven exact manifests, initial recovery checkpoint, per-attempt rollback snapshots, verified compensation, and clean retry; `test_mission_bootstrap.py` | — |
| AF-015 | Implemented | Immutable role/purpose broker dispatches, provenance/freshness enforcement, mandatory authoritative/safety retention, explicit source outcomes, and governed transcript compaction retaining decisions, risks, evidence, and next steps; `test_context_packages.py` | — |
| AF-016 | Not started | — | Typed memory and invalidation model absent |
| AF-017 | Implemented | Fail-closed path policy, fenced launches, Bubblewrap/macOS backends, unsupported-host denial, audited out-of-scope writes, bounded process/time/output/network execution and preserved candidate evidence; `test_sandbox.py` | — |
| AF-018 | Partial | Guarded GitHub and Firecrawl integrations | No Tool Registry/Gateway, MCP lifecycle, normalized tool contracts, or centralized authorization boundary |
| AF-019 | Partial | Sensitive environment removal from provider subprocesses | No short-lived credential broker, scope issuance, revocation, injection firewall, or zero-exposure proof |
| AF-020 | Implemented | Deterministic-first independent model review, exact primary evidence closure, versioned rubric, immutable criterion verdicts, confidence, concerns, dissent, and replay safety; `test_codex_worker.py` | — |
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
| AF-047 | Implemented | Immutable ten-check Hermes matrix for executable/version/check/lifecycle/cancellation/workspace/tools/permission/usage/artifact evidence, failed-runtime quarantine, compatible read-only Codex/Claude fallback, and checkpoint-plus-new-lease mutable transfer; `test_hermes_qualification.py`, `test_hermes_acp.py`, `test_worker_runtime.py` | — |
| AF-048 | Implemented | Fenced deterministic Git worktree provisioning, exclusive task/lease ownership, startup reconciliation, retention and branch-preserving cleanup; `test_worktrees.py` | — |
| AF-049 | Implemented | Qualified fixed Codex exec profile, leased-worktree native sandbox boundary, immutable command/diff/exit/handoff result, forbidden authority profile, and process-tree timeout/cancel; `test_codex_worker.py` | — |
| AF-050 | Implemented | Separately qualified file-only Claude Code stream-JSON profile, exact implementation-role boundary, shared task/run/stage/worktree/context approval contract, immutable candidate evidence, compatible qualification routing, and process-tree timeout/cancel; `test_claude_worker.py` | — |
| AF-051 | Implemented | 5/5-validated immutable candidate artifact, stable-ID task-branch commit, base-ref preservation, failed-validation denial, and separately gated PR plan; `test_codex_worker.py`, `test_github.py` | — |
| AF-052 | Implemented | Five-category project packs, fixed shell-free argv, candidate-worktree sandbox execution, bounded command/environment evidence, immutable results, and exact criterion mappings; `test_validators.py` | — |
| AF-053 | Implemented | Replay-safe worker/worktree lineage through validation, candidate, independent review, bounded repair, separate Founder decision, and pending PR gate; same/replacement worker policy and deterministic repair exhaustion; `test_codex_worker.py` | — |
| AF-054 | Implemented | Immutable eight-role software-engineering manifest, typed contracts, separate deterministic validator and independent reviewer, implementer self-acceptance denial, and AF-053 Founder-approved PR-ready release authorization; `test_software_roles.py`, `test_codex_worker.py` | — |
| AF-055 | Implemented | Fenced canonical dispatch packages, immutable SHA-256 identity, required task/dependency/base/policy scope, explicit included/excluded/superseded sources, deterministic byte/token compaction and runtime digest binding; `test_context_packages.py`, `test_worker_runtime.py` | — |
| AF-056 | Implemented | One correlation root across delivery entities, immutable duration/retry/token/cost/tool/terminal telemetry, enforced token/cost/stage/retry/tool caps, and dashboard queue/session/lease/worktree/failure/budget state; `test_execution_telemetry.py`, `test_codex_worker.py`, `test_web.py` | — |
| AF-057 | Implemented | Restart snapshots for stage/lease/Hermes/context/worktree/approval identity, separate provider/Hermes/worktree orphan sets, stale-fence denial, replay qualification, and artifact/audit/foreign-key restore verification; `test_local_recovery.py`, `test_hermes_acp.py`, `test_worktrees.py`, `test_codex_worker.py`, `test_scheduler.py` | — |

## Backlog decisions from the audit

1. **AF-047 and AF-057 complete runtime and restart qualification for the correlated, budgeted AF-053 coding loop.** The qualified restart-safe single-node critical path is complete.
2. **Use Hermes ACP for mutable sessions.** Installed Hermes 0.20.0 exposes an ACP stdio server, structured events and permission bridging. `hermes --oneshot` states that approvals are auto-bypassed, so it is limited to qualification or read-only probes.
3. **Keep worktree authority in AgentFactory.** AF-048 creates and owns the worktree; AF-045 passes it to Hermes as the working directory. Managed sessions must not invoke Hermes `--worktree`.
4. **Make context and worktree prerequisites of Hermes.** AF-045 now depends on AF-048 and AF-055, preventing an unscoped runtime session.
5. **Two writable workers now share the contract.** AF-049 Codex remains the P0 default; AF-050 supplies a separately qualified compatible Claude alternative without widening planning roles.
6. **Independent review is not optional for MVP.** The local criterion-verdict subset of AF-020 moves to P0 and becomes an AF-053 dependency.
7. **Separate idempotent integration from crash recovery.** AF-053 proves replay-safe logical attempts; AF-056 adds correlation/budget enforcement; AF-057 owns full local crash-boundary reconciliation.
8. **Keep platform expansion deferred.** PostgreSQL, object storage, multi-tenancy, OpenTelemetry export and clustered deployment remain downstream of AF-057 evidence.

## Rebased delivery order

```text
Done: AF-001 -> AF-002/AF-003/AF-004 -> AF-005/AF-006 -> AF-007 -> AF-008; AF-010 + AF-011 + AF-017 + AF-020 + AF-044 + AF-045 + AF-046 + AF-047 + AF-048 + AF-049 + AF-050 + AF-051 + AF-052 + AF-053 + AF-054 + AF-055 + AF-056 + AF-057

Done: AF-009, AF-010, AF-011, AF-012, AF-013, AF-014, AF-015

Now:  AF-016
Then: AF-018
Later: AF-015/AF-016/AF-027/AF-028, then AF-018/AF-019/AF-026/AF-029–AF-031
```

The M1 release gate is complete at **AF-007**. The next gate is the M2 first coding worker slice; a chat response from Hermes remains environment evidence only and does not prove scoped mutation, acceptance evidence, or recovery.
