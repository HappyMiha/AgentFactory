# Implementation release notes — 2026-08-11

These notes describe the implemented, tested repository state through the AF-050 Claude-worker slice and AF-057 local recovery. This is an **unreleased development snapshot**, not a published SemVer tag. The source of truth for remaining work is the [implementation backlog](../examples/development-backlog.json), with readable sequencing in the [development roadmap](development-roadmap.md) and evidence status in the [implementation audit](implementation-audit-2026-08-11.md).

## Release summary

- Completed **31 of 57** backlog tasks: AF-001–AF-008, AF-017, AF-020, AF-036–AF-053, and AF-055–AF-057.
- Established the durable SQLite authority, transactional audit/outbox, criterion evidence, deterministic Control Plane policy, provider qualification, resumable stage checkpoints, and fenced dependency scheduling.
- Completed the loopback Local Control Center with guarded workflow/routing/founder/audit/GitHub-preview operations.
- Verified **191 automated tests** and the offline backlog manifest validation on Python 3.11.15.
- The qualified restart-safe two-worker single-node coding vertical slice is implemented but not released; AF-054 retains the typed role-pack work.

## Implemented backlog items and implementation commits

### Durable Safe Core

| Backlog item | Implemented outcome | Committed | Implementation commit |
|---|---|---|---|
| AF-001 | Versioned domain identities, compatibility migration and lifecycle state machines | 2026-08-11 10:01 CEST | [`0bad182`](https://github.com/HappyMiha/AgentFactory/commit/0bad182727a302b4dcbbbc4d6b7002eb454a16ad) |
| AF-002 | Transactional outbox, stable delivery keys and tamper-evident audit chain | 2026-08-11 10:08 CEST | [`2436960`](https://github.com/HappyMiha/AgentFactory/commit/24369600e7031024797fb907cc5019671d106041) |
| AF-003 | Content-addressed artifact and criterion-evidence ledger | 2026-08-11 10:14 CEST | [`2acbaee`](https://github.com/HappyMiha/AgentFactory/commit/2acbaeef834e94fc5f0a85a40602731a9eb763bd) |
| AF-004 | Deterministic policy plane, exact approvals and persistent emergency stop | 2026-08-11 10:20 CEST | [`376bb0b`](https://github.com/HappyMiha/AgentFactory/commit/376bb0ba6434dc0a19f01c4236017ce0f0ca815f) |
| AF-005 | Normalized adapters, multidimensional health, qualification, quarantine and handoff | 2026-08-11 10:25 CEST | [`4d1877a`](https://github.com/HappyMiha/AgentFactory/commit/4d1877ab79d329cb9ed72dd7fd87c386bf8fd6de) |
| AF-006 | Version-pinned durable workflow stages, resume and mutation reservations | 2026-08-11 10:29 CEST | [`b466073`](https://github.com/HappyMiha/AgentFactory/commit/b466073950eac3d99402a00acd21a28ebfdad9e1) |
| AF-007 | Dependency-ready claims, TTL/fenced leases and hierarchical conflict domains | 2026-08-11 21:59 CEST | This AF-007 task commit |
| AF-008 | Persistent bounded repair loop and deterministic no-progress control | 2026-08-11 23:58 CEST | This AF-008 task commit |
| AF-044 | Shared lifecycle-aware Direct CLI/Hermes ACP runtime contract | 2026-08-11 22:27 CEST | This AF-044 task commit |
| AF-045 | Version-qualified Hermes ACP stdio lifecycle, durable scope and restart identity | 2026-08-11 23:05 CEST | This AF-045 task commit |
| AF-046 | Exact durable live-stage gates, one-attempt consumption and automatic dependency-ready continuation | 2026-08-11 23:18 CEST | This AF-046 task commit |
| AF-047 | Immutable Hermes qualification, quarantine, and controlled runtime fallback/transfer | 2026-08-12 00:42 CEST | This AF-047 task commit |
| AF-048 | Fenced deterministic Git worktrees, reconciliation, retention and branch-preserving cleanup | 2026-08-11 22:35 CEST | This AF-048 task commit |
| AF-055 | Immutable bounded execution context packages and runtime digest enforcement | 2026-08-11 22:46 CEST | This AF-055 task commit |
| AF-056 | Correlated execution telemetry, enforced budgets, and dashboard operational state | 2026-08-12 00:16 CEST | This AF-056 task commit |
| AF-057 | Restart reconstruction, separate orphan detection, and evidence-ledger restore verification | 2026-08-12 00:23 CEST | This AF-057 task commit |

### Safe Extensibility

| Backlog item | Implemented outcome | Committed | Implementation commit |
|---|---|---|---|
| AF-017 | Fail-closed writable-worker sandbox and preserved teardown evidence | 2026-08-11 22:17 CEST | This AF-017 task commit |
| AF-020 | Deterministic-first independent criterion verdicts with primary-evidence closure | 2026-08-11 23:46 CEST | This AF-020 task commit |
| AF-049 | Qualified fixed-profile Codex worker, immutable candidate handoff and process-tree termination | 2026-08-11 23:32 CEST | This AF-049 task commit |
| AF-050 | Separately qualified file-only Claude Code worker and compatible routing | 2026-08-12 00:52 CEST | This AF-050 task commit |
| AF-051 | Validated immutable candidate commit and separately gated PR plan | 2026-08-11 23:43 CEST | This AF-051 task commit |
| AF-052 | Five-category shell-free validator packs and criterion-mapped bounded evidence | 2026-08-11 23:37 CEST | This AF-052 task commit |
| AF-053 | Replay-safe end-to-end coding delivery with separate Founder and PR gates | 2026-08-12 00:07 CEST | This AF-053 task commit |

### Local Control Center MVP

| Backlog item | Implemented outcome | Committed | Implementation commit |
|---|---|---|---|
| AF-036 | Shared typed application-service boundary for CLI and web | 2026-08-10 23:38 CEST | [`5696028`](https://github.com/HappyMiha/AgentFactory/commit/56960283172aebea67336a969bb94ff0ebc02b4e) |
| AF-037 | Loopback FastAPI host and bounded operations API | 2026-08-10 23:46 CEST | [`74cea39`](https://github.com/HappyMiha/AgentFactory/commit/74cea39924348ed13ab242f776d1935303d040e5) |
| AF-038 | Live dashboard shell, navigation and explicit UI states | 2026-08-11 00:03 CEST | [`0f11833`](https://github.com/HappyMiha/AgentFactory/commit/0f11833951eb71b312535725621b3e45dcaffca7) |
| AF-039 | Guarded backlog and workflow controls | 2026-08-11 00:13 CEST | [`6fa3c03`](https://github.com/HappyMiha/AgentFactory/commit/6fa3c036d09f760d37ad397fea115f1c80b0ec4a) |
| AF-040 | Agent/provider controls and independent reviewer routing | 2026-08-11 00:23 CEST | [`03d6c2f`](https://github.com/HappyMiha/AgentFactory/commit/03d6c2f04d56c49d405faa545536c1b84e80e364) |
| AF-041 | Founder review workspace and idempotent separate authority | 2026-08-11 00:38 CEST | [`3f9eab7`](https://github.com/HappyMiha/AgentFactory/commit/3f9eab7ddaf77e2c356226e2416ff709eddc6e0e) |
| AF-042 | Audit/settings workspace and SHA-256-bound GitHub sync preview | 2026-08-11 00:32 CEST | [`b80fc10`](https://github.com/HappyMiha/AgentFactory/commit/b80fc102a35c8d614f6d597c467f60885772af77) |
| AF-043 | Windows launch flow, accessibility and fresh-state qualification | 2026-08-11 00:47 CEST | [`89ac833`](https://github.com/HappyMiha/AgentFactory/commit/89ac8335527ae32b8cfae42ba3d6da8e68a66e23) |

Commit times above are author timestamps from Git in the repository timezone (`+02:00`). AF-042 was authored before AF-041 and is its parent in repository ancestry; the table is ordered by stable task ID rather than commit chronology.

## AF-046 implementation detail

Mutable Direct CLI and Hermes ACP launches now reconstruct the complete project/task/run/stage/worker/runtime/worktree/permission scope before any worker session or child process exists. The approved gate is consumed once and immutably tied to one assignment attempt; rejected, expired, replayed, or redirected envelopes fail closed. Stage completion also checkpoints success and starts the first dependency-ready pending stage, preserving the durable workflow instead of requiring operator-driven continuation.

## AF-049 implementation detail

The first writable implementation worker now qualifies the installed Codex CLI and launches a fixed non-interactive `workspace-write` profile rooted at the leased AF-048 worktree. It consumes only the AF-046-authorized attempt, records JSONL command execution plus the final handoff, and stores immutable changed-file, canonical diff-digest, version, invocation, exit, and evidence metadata. The profile has no extra write directory or bypass flag, explicitly excludes merge/push/issue/final-approval authority, and complete process-tree termination is exercised for both deadline and operator cancellation.

## AF-047 implementation detail

Hermes qualification now persists one immutable matrix covering executable discovery, version constraints, `hermes-acp --check`, complete session lifecycle, process-tree cancellation, workspace confinement, exact tool restrictions, permission bridging, usage reporting, and normalized candidate artifacts. A failed Hermes runtime can quarantine its worker. Controlled direct fallback targets only an actively qualified Codex or Claude profile with compatible read-only capabilities, only after Hermes failure, and only before any mutable event. Mutable work cannot use that path: its separate transfer authorization requires an exact source-stage checkpoint, release of the old fencing authority, and a newer active lease for the target runtime.

## AF-052 implementation detail

Validation is now driven by reviewed project packs with required test, lint, type-check, build, and security-scan vectors; workers cannot submit a shell string or replace a vector at runtime. Every command runs through the fenced AF-017 boundary with the candidate worktree as cwd, denied network, and bounded time/output. Immutable records bind candidate and pack digests to command/exit/environment evidence and exact declared acceptance criteria, so a generic green process can no longer masquerade as criterion-complete validation.

## AF-050 implementation detail

Claude Code now has its own qualified `claude-cli` Worker Runtime rather than reusing the plan-only provider command. The fixed non-interactive profile accepts only `Read`, `Edit`, `Write`, `Glob`, and `Grep`, roots its permission rules at the leased worktree, loads no setting source or MCP server, and excludes Bash, web, extra directories, permission bypass, push, merge, issue, and acceptance authority. Stream-JSON tool, usage, handoff, changed-file, diff, version, invocation, and evidence identities are immutable. A successful exact-profile result creates the role/capability qualification used for Codex/Claude compatibility routing; planning roles remain incompatible, and timeout/cancel terminate the full process tree.

## AF-051 implementation detail

Only the exact AF-049 diff with five successful AF-052 categories can now become a committed candidate artifact. Agent Factory stages the worker-declared file set on the deterministic task branch, requires an `AF-NNN` commit prefix, verifies the base branch SHA did not move, and records immutable base/head/worktree/diff/validation identity. The pull request remains an immutable GitHub dry-run operation behind its own pending gate; failed or candidate-mutating validation produces neither a candidate artifact nor PR-ready plan.

## AF-020 implementation detail

Independent evaluation now reconstructs and verifies the exact five-result AF-052 snapshot before a reviewer callback is allowed to run. The candidate-producing model identity is persisted on AF-049 output and cannot be selected as reviewer. Agent Factory—not the model—binds primary validator evidence to every required acceptance criterion, then stores the rubric version and one immutable pass/fail verdict with confidence, concerns, and dissent per criterion. Missing evidence, failed deterministic checks, or any failed criterion rejects acceptance; replay of the same rubric version returns the stored result without another model call.

## AF-008 implementation detail

The engineering loop now persists the objective, structured plan, diff digest, validator and critic results, per-iteration usage, cumulative budget, failure signature, and outcome for every attempt. Iteration, time, token, cost, and tool-failure caps deterministically pause work; two identical consecutive failures force the configured replan or worker-replacement action. Evidence-backed acceptance, explicit failed iteration, and attributable human escalation are the only terminal paths, enforced by SQLite triggers. Raising a paused loop's limits requires an immutable human approval record and cannot reduce any cap or undercut already consumed budget.

## AF-053 implementation detail

The first coding-delivery integration now binds an immutable Codex result back to its claimed assignment and managed worktree, consumes its exact validator snapshot, creates one replay-safe candidate commit, runs one independent evidence review, and records success or repair in the bounded engineering loop. Validation failure returns to the same worker unless a policy selector supplies a compatible replacement, and the configured repair cap fails exhausted delivery deterministically. Accepted review evidence opens a separate Founder gate; only Founder approval creates a PR-ready dry-run plan with another pending GitHub gate. Supported replay creates no additional worker result, worktree, commit, review, Founder gate, PR plan, provider call, or live GitHub mutation.

## AF-056 implementation detail

Every workflow can now own one immutable correlation root and exact budget scope. Hydration links the task, workflow, Hermes session when present, Codex process, worktree, validator results, candidate, evaluation, delivery, and distinct stage/Founder/GitHub approvals. Idempotent samples retain duration, retries, tokens, estimated cost, tool calls, metadata, and terminal reason across restart. Stage preflight records and blocks token, cost, stage, and tool-call overages; retry overages and actual usage crossings pause the trace too. The Local Control Center dashboard now reports active sessions, queued tasks, leases, worktrees, failures, and recent budget state without waiting for the later OpenTelemetry export.

## AF-057 implementation detail

Local restart recovery now reconstructs the authoritative stage, fenced lease, Hermes session reference, context digest, managed worktree, and pending approvals from SQLite without inventing replacement identity. Provider processes, Hermes sessions, and worktrees are reported as separate orphan classes; inspection is deliberately non-destructive, leaving termination and cleanup under human authorization. Restore qualification verifies SQLite integrity, foreign keys, every stored artifact digest, and audit-chain continuity. Crash-boundary replay tests also prove that a newer fencing token rejects stale commits, an exact commit completed immediately before termination is adopted rather than repeated, and supported checkpoints do not duplicate approvals, provider calls, PR plans, or external GitHub operations.

## What is explicitly not in this snapshot

- PostgreSQL, object storage, Redis/Qdrant-style production services, multi-tenancy and clustered deployment.

## Backlog changes made by this release audit

- Selected Hermes ACP stdio as the mutable session transport; one-shot mode is read-only/qualification-only because Hermes documents approval bypass in that mode.
- Made AF-048 and AF-055 prerequisites of AF-045 so Hermes cannot start without a Control-Plane-owned worktree and immutable scoped context.
- Promoted the MVP subset of AF-020 independent evaluation to P0.
- Kept AF-049 Codex at P0 and moved AF-050 Claude Code to P1; one qualified writable worker is sufficient to prove the MVP slice.
- Assigned replay-safe integration to AF-053 and full crash-boundary reconciliation to AF-057.
- Kept platform expansion downstream of the single-node coding-loop evidence.

## Next release target

M1, AF-008, AF-017, AF-020, AF-044 through AF-053, and AF-055 through AF-057 are complete. AF-054 is the next typed role-pack slice.
