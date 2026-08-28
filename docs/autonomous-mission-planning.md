# Autonomous Mission planning, approval, and orchestration foundation

AF-AMM-007 through AF-AMM-017 establish the source, role-assignment, proposal-generation, verification, exact human approval boundary, durable pre-approval orchestration, sequential post-approval child delivery, its mission-wide control fence, owner-authorized checkpoint/revision epoch handoff, and bounded history across Worker releases. Pre-approval operations do not authorize repository, environment, service, or Git mutation, and they do not create executable `work_items`; those records appear only after the exact approval authority has been revalidated.

## Specification source contract

`AutonomousMissionIntakeService` creates a project/intake shell, a `DRAFT` Autonomous Mission, and an immutable version-one specification source. Text is preserved exactly. Supported uploads are UTF-8 plain text, Markdown, JSON with an object or array root, and readable non-encrypted PDF files. Upload processing rejects mismatched media types, binary controls, duplicate JSON keys, malformed or active PDF content, unsupported formats, and inputs over the reviewed bounds before mission state is created.

Every source records its mission and source version, media type, filename, provenance, actor, extracted content digest, original-byte digest, metadata, idempotency request, and a digest of the complete binding. A durable head projection identifies the current source. A pre-approval edit appends a new source and supersession; it never rewrites history. Backlog revisions whose `source_sha256` no longer matches the new authoritative bytes receive immutable invalidation records and cannot later be activated or bound to a planning manifest.

The application boundary exposes typed create, update, and query methods for both text and upload inputs. REST, CLI, and Control Center resources remain part of the later operator-surface slice.

## Planning role and model contract

The `autonomous-planning@1.0.0` role pack installs five logical roles in a fixed order:

| Role | Output authority |
|---|---|
| Mission Analyst | Source-traceable mission analysis |
| Product/Requirements Analyst | Normalized measurable requirements |
| Software Architect | Architecture, infrastructure, interfaces, and prerequisite ordering |
| Backlog Planner | Rich dependency-aware proposal only |
| Backlog Reviewer | Independent findings and readiness evidence |

Each immutable role definition declares typed inputs, outputs, evidence, tools, permissions, limits, and incompatible duties. A mission may use one default model for all roles or explicit provider/model overrides for every role. Provider names do not prove locality: an assignment is accepted only when the provider is in the mission allowlist and its typed capabilities explicitly declare eligible local text generation. Remote, undeclared, missing, or name-masquerading providers fail closed.

A content-addressed manifest binds the exact specification source digest, role-pack digest, role contract digests, provider capability snapshots, logical-agent identities, model assignments, and context policy for one proposal. A separate immutable binding joins that exact manifest digest to an exact backlog revision digest.

## Context isolation

Each role invocation receives a newly persisted context envelope with a unique sequence, context key, and digest. It contains only the exact specification, the selected logical role contract, and explicitly supplied upstream artifact references. It has no parent session or prior transcript, carries read-only tool authority, denies repository/environment/external mutation, and fails if mandatory content exceeds the manifest byte or token limits. A specification update makes earlier manifests stale, preventing new contexts or revision bindings.

## Proposal generation pipeline

`AutonomousPlanningPipelineService` invokes the five manifest assignments in their fixed order through typed `BOUNDED_LOCAL_PLANNING` authority. Every attempt gets a fresh persisted context. A strict JSON envelope, the role contract, and deterministic nested semantics are validated before a content-addressed artifact can enter the next role's context. Invalid or partial output is retained as evidence and may be repaired only in another fresh invocation with bounded validation feedback.

The deterministic validator requires measurable requirements and task acceptance criteria, complete schema-v2 execution fields, requirement coverage, an acyclic canonical dependency order, and explicit bootstrap tasks ahead of every dependent use of bootstrap-required infrastructure. A successful run appends an `AGENT_MATERIAL` backlog revision and binds it to the exact source/role/model manifest. It deliberately leaves the revision proposed and creates no executable `work_items`.

Runs, attempts, artifacts, failures, completions, and regeneration history are append-only and idempotency-bound. Provider failures or exhausted repair attempts close the one-request planning authority and cannot leave a partial proposal that looks complete. A new proposal key produces a new manifest, run, artifact chain, and revision rather than overwriting prior planning evidence.

## Deterministic readiness verification

`AutonomousProposalVerificationService` has no provider-invocation authority. It independently replays the canonical revision, completion, source, manifest, role/model, artifact, reviewer-evidence, and proposal digests. Its document verifier rejects malformed rich fields, duplicates, orphaned references, dependency cycles, non-canonical order, non-measurable acceptance criteria, uncovered requirements, unsafe infrastructure ordering, and references outside the authoritative source scope.

Reviewer findings remain part of the immutable report. Resolved findings may remain hidden; unresolved findings must be explicitly displayed, and open `BLOCKER` or `HIGH` findings still block readiness. The human presentation packet contains the exact canonical revision digest, complete backlog, normalized requirements, architecture, manifest assignments, checks, and visible findings.

A `READY` verification record and the mission transition to `WAITING_FOR_BACKLOG_APPROVAL` commit atomically. A database fence prevents a completed planning mission from entering that phase by calling the generic transition service directly. `BLOCKED` reports retain their evidence without changing mission state, and source/version races fail closed. No revision is activated and no executable work is created at this boundary.

## Exact approval and bounded mission start

`AutonomousBacklogApprovalService.approve_and_start` consumes one authenticated mission-owner command. It requires the current `READY` verification, exact latest revision ID and canonical digest, unchanged source and planning manifest, current mission version, a clean reviewed Git base, an explicitly local provider set, and explicit execution role/model bindings. A mismatched digest, stale version or source, invalid actor context, blocked report, emergency stop, dirty repository, duplicate conflicting command, or superseded proposal fails before any durable start record is committed.

One `BEGIN IMMEDIATE` transaction appends the approval and completion evidence, initial execution epoch and Temporal run-chain metadata, policy/tool/planning/execution model manifests, and the bounded Autonomous Local authorization. The same commit changes the mission from `WAITING_FOR_BACKLOG_APPROVAL` to `APPROVED` and binds its active revision and epoch. SQLite fences reject a direct phase or revision activation that lacks the exact completion evidence. The transaction records control metadata only: it does not dispatch a workflow, bootstrap an environment, invoke a development provider, or create a standard `work_item`.

The resulting capability is reusable for ordinary local calls inside the exact mission/revision/epoch/provider/role/model/repository/tool/permission scope. The resolver still checks the current policy and scheduling fence before every operation; remote inference, protected integration, external mutation, secrets, and machine-global writes retain their existing gates.

Later immutable revisions use an origin-specific authority ledger:

- `HUMAN` is applied only by the authenticated mission owner at apply time;
- `TECHNICAL_SUBTASK` must name and digest-bind an executable item in the active authorized parent revision;
- `AGENT_MATERIAL` cannot activate itself and atomically routes the mission back to `WAITING_FOR_BACKLOG_APPROVAL` while retaining the previously active revision.

Every authority action is append-only, digest-bound, version-fenced, idempotent, and audit-attributed. The durable parent Workflow contract below supplies the Temporal identity and run-chain metadata consumed by the start boundary.

## Durable parent Workflow contract

`AutonomousMissionWorkflow` is registered additively beside the unchanged `AgentFactoryJobWorkflow` and `TemporalDemoWorkflow`. Its logical ID is `agentfactory-autonomous-mission-{mission_id}` (with a validated deployment prefix), so repeated client starts attach to the one existing parent instead of launching a second mission.

The typed input and bounded query state contain domain identifiers, revision/epoch/checkpoint references, current item and role/model display names, progress counters, phase, disposition, environment status, Temporal chain references, timestamps, and bounded activity summaries. Continue-as-new carry-over schema v2 is stricter: it carries only mission/revision/epoch/checkpoint/work-item/control identities, chain/build evidence, and bounded counters. Role/model display values and activity text are reconstructed in the next run and are never copied across the boundary. Constructors reject oversized values, malformed digests, invalid counters, and cross-mission carry-over. Specifications, backlog snapshots, source trees, logs, provider output, manifests, and artifact bodies remain in SQLite or content-addressed storage rather than Workflow history. Schema v1 remains decodable solely for historical replay.

Four queries expose mission status, progress and last activity, current role/model, and environment state. Phase and runtime disposition remain separate fields. `request_autonomous_planning` carries only a command, manifest, authorization, actor, action, and expected-version reference. The planning Activity reopens SQLite, verifies the exact mission identity and persisted owner grant, advances the version-fenced analysis/generation phases, runs the idempotent five-role pipeline, verifies the proposal, and returns only compact identifiers. An `ANALYZE` grant cannot be substituted for `REGENERATE_BACKLOG`; both remain bounded to the read-only local planning permission set.

The parent then waits in `WAITING_FOR_BACKLOG_APPROVAL` without a polling timer or environment/development Activity. `autonomous_backlog_approved` is only a wake-up hint: its claimed approval, revision, digest, and epoch values are never authoritative. A separate Activity rereads and integrity-checks the approval completion, active mission projection, immutable revision, execution epoch, local authorization, stable Workflow ID, and first run ID. A spoofed or premature Signal leaves the parent waiting. Once persisted authority is valid, bounded query state moves to `APPROVED` and retains the exact approval and execution-authorization identifiers.

## Post-approval child delivery

AF-AMM-014 makes post-approval execution explicit in the parent input. When enabled, an Activity independently revalidates the approval/authorization pair and advances `APPROVED → ENVIRONMENT_DISCOVERY → ENVIRONMENT_BOOTSTRAP → DEVELOPMENT`. Each transition is version-fenced and idempotent. Disabling post-approval execution preserves the durable phase-boundary wait used by planning-only deployments and tests.

In `DEVELOPMENT`, SQLite selects only an executable `READY` item whose dependencies are accepted. Preparing it appends an immutable child-job record and creates the existing `work_items`/`workflow_runs` transport records in one transaction. Its Temporal ID binds mission, active revision, execution epoch, stable item ID, and logical attempt. Repeating preparation with the same command or logical scope returns the same child; it cannot create a second provider attempt.

The standard `AgentFactoryJobWorkflow` remains unchanged when it has no autonomous context: successful evidence still waits at its Founder gate. An autonomous child first resolves the mission's persisted local inference authority and passes a typed `ProviderExecutionAuthorization` into the existing provider runtime. It then executes the reviewed delivery stages. Autonomous finalization requires successful terminal stage mutations plus persisted implementation, validation, policy-review, clean-Git, epoch-branch, and commit evidence. Only that opt-in path converges its transport run to `approved` without creating a per-item Founder gate.

The parent awaits the child result and then awaits reconciliation before selecting anything else. Reconciliation rereads the immutable completion, records the backlog item as `DONE`, and commits a `WORK_ITEM_ACCEPTED` mission checkpoint. The checkpoint increments the mission version, which changes the next preparation command. If the parent or Worker stops after child completion, replay recovers the same child and completion; if checkpoint completion was lost, the checkpoint command replay returns the existing record before the reconciliation ledger is appended. After all executable items are accepted, the parent advances `DEVELOPMENT → FINAL_VALIDATION → COMPLETED`.

## Mission-wide scheduling fence

AF-AMM-015 separates phase from control disposition. `PAUSED` and `STOPPED` retain the exact planning/development phase and latest checkpoint; neither is translated into cancellation or failure. The typed control payload binds command ID, actor, reason, expected mission version, fencing token, active revision/epoch, and current child. A Signal has no direct authority: its Activity rereads the mission, validates exact owner and scope, commits the disposition plus an immutable command result, and only then updates the parent and active child Workflow state.

The SQLite control projection monotonically advances its fencing token whenever disposition or execution epoch changes. New planning or delivery inference, runtime command, installation, service operation, next-work-item reservation, and individual multi-tool worker turn must acquire an operation lease with the current token. A stale token fails even when the operation ID already exists, closing replay-based fence bypasses. Pause permits an already admitted atomic operation to finish but blocks every later admission. Stop marks active leases as releasing; resume is rejected until each reaches its terminal safe boundary, after which the same child/checkpoint remains continuable under the new token.

`RETRY_CURRENT_TASK` is distinct from stop and cancellation. It accepts only the current uncompleted child, increments the fence, makes its active operations release, and persists one requested next logical attempt. At the safe boundary, settlement appends `RUNNING -> FAILED -> READY` backlog evidence and retires the old transport run. The next child ID includes the higher logical attempt and current fence token. Duplicate retry Signals reuse the immutable request/settlement, while an accepted completed item cannot be retried.

## Checkpoint and revision epoch handoff

AF-AMM-016 adds separate typed `restart_from_checkpoint` and `apply_backlog_revision` Signals. Before either Signal is sent, the authenticated mission owner persists an immutable command binding the exact mission version, fence token, active revision and epoch, current child, selected approved checkpoint, target already-authorized revision, destination epoch branch, reason, and authentication context. The Signal carries only a command reference and claims. Its preparation Activity reloads that record and rejects a spoofed, stale, or conflicting payload; a Signal never grants checkpoint or revision authority.

Preparation derives one idempotent STOP command and prevents new Activity/runtime admission. An active child finishes its already-admitted atomic operation and returns `SUPERSEDED`; an Activity that raced ahead but did not acquire a lease detects the persisted handoff and retires immediately. Completion refuses to replace the epoch while any lease remains `ACTIVE` or `RELEASING`. It then appends one superseding epoch from the selected checkpoint, renews bounded execution authority for the new epoch, reconciles the fence, resumes the mission, and appends an immutable result. Replaying after any partial boundary reuses the STOP, epoch, authorization, resume, and result identities, so exactly one replacement epoch exists.

The parent carries the resulting revision ID/digest, execution epoch, checkpoint, authorization, mission version, and fencing token before it schedules another child. Historical epochs, children, transport runs, checkpoints, and Temporal metadata remain queryable and are never rewritten. AF-AMM-021 remains responsible for materializing/restoring the Git checkpoint and destination branch; AF-AMM-022 remains responsible for the full revision-impact and restart transaction. AF-AMM-016 defines and proves the authority, safe-boundary, and durable orchestration contract those tasks consume.

## Bounded history and Worker replacement

AF-AMM-017 evaluates continue-as-new only after an accepted mutation has reached a persisted safe boundary. It never rolls over while an Activity mutation, child Workflow, Signal/Update handler, queued planning or approval command, retry settlement, or epoch handoff is active. A run becomes eligible when its configurable safe-boundary or event threshold is reached, when Temporal recommends rollover, or when an enabled Worker Deployment target changes. Reason priority and the patch ID `af-amm-017-safe-rollover-v1` are deterministic.

Every run starts by appending its exact run ID, predecessor, first run ID, mission scope, build ID, rollover evidence, counters, and digest to the immutable `autonomous_mission_temporal_runs` table. Sequence, predecessor, scope, and monotonic mutation-count triggers reject forks or rewrites. Temporal Search Attributes (`AgentFactoryMissionId`, `AgentFactoryProjectId`, `AgentFactoryMissionIdentity`, `AgentFactoryMissionKey`, `AgentFactoryChainSequence`, `AgentFactoryMissionPhase`, and `AgentFactoryMissionDisposition`) support retained-run discovery. A compact memo supplies the same stable identity when the lightweight test server has no visibility service, and ledger run IDs provide direct discovery after visibility retention.

The namespace defaults to seven-day Temporal retention. This is operational history, not the domain audit boundary: migration 69's SQLite chain and normal mission audit events are retained under AgentFactory's data policy and survive Temporal visibility expiry. Initial static details identify the logical mission and stable Workflow ID; memo and Search Attributes are written again on each continuation. Worker builds are explicit, and opt-in Worker Deployment mode uses `PINNED` behavior with `AUTO_UPGRADE` only for a safe continued run. The required release procedure is in [Temporal Worker versioning](development/temporal-worker-versioning.md).

## Authoritative operation recovery

AF-AMM-018 generalizes mutation reservations into typed operation classes for provider calls, commands, installations, services, model lifecycle, worktrees, Git/GitHub integration, checkpoints, and revision/epoch transitions. A stable key binds canonical request digest, reconciliation policy, exact pre-operation mission/revision/epoch/checkpoint/child scope, and control token. Append-only events distinguish `reserved`, `running`, `unknown`, `retry_ready`, and terminal outcomes and bind every result and observation to canonical evidence digests.

An operation may touch external state only after its `running` event is durable. A restart changes `running` to `unknown` and invokes a typed read-only observer. Present state is adopted as `reconciled`; proven absence permits `retry_ready` only under the stored policy; conflict, indeterminate state, or a missing observer becomes `needs_attention`. Completed or reconciled work never becomes executable again.

Mission recovery reconstructs the active revision, epoch, running child, last verified checkpoint, Git branch/commit authority, inference lease, service requirements, and latest Temporal run alongside database, foreign-key, artifact, audit, and journal integrity. One immutable recovery record and its ordered decision ledger persist `RESUME_SAFE`, `PAUSED`, `STOPPED`, `COMPLETED`, or `NEEDS_ATTENTION`. Reusing its recovery key returns the same evidence rather than observing or mutating again. The operational contract and kill-point matrix are in [Autonomous Mission operation journal and recovery](development/autonomous-mission-recovery.md).

## Mission epoch Git authority

AF-AMM-019 extends the sole `WorktreeManager` boundary with deterministic `autonomous/<normalized-mission>/epoch-<n>` branches and workspace-contained epoch worktrees. Migration 71 persists an immutable repository/branch/path/base/checkpoint reservation and its first `RESERVED` observation before `git worktree add` can execute; later `PROVISIONING`, `READY`, `DIRTY`, `MISSING`, and `CONFLICT` observations are append-only and content-digested.

Epoch 1 starts at the exact approved base commit. A later epoch starts at the exact commit from its verified checkpoint, while previous epoch refs and worktrees remain intact. Reconciliation accepts only the epoch base or a clean checkpointed descendant from that epoch, distinguishes filtered content from Git stat-cache noise, and never resets, prunes, removes, or adopts a conflicting ref/path. Standard task worktree reconciliation excludes the reserved autonomous namespace. The naming policy and recovery procedure are in [Mission epoch branches and worktrees](development/mission-epoch-worktrees.md).

Regeneration moves the mission from the approval wait back to generation under a distinct persisted grant. The new proposal, artifacts, verification, and revision append to history. `revision_lineage` verifies the immutable root-to-proposal parent chain, so an earlier human-visible proposal remains queryable and cannot be overwritten by a later attempt. Activity command suffixes bind every phase transition, pipeline run, verification, and revision operation, making a lost Activity completion safe to replay without another provider call.

`start_autonomous_mission_workflow` uses strict Temporal workflow-ID reuse, returns mission/run/chain correlation metadata, verifies immutable mission identity when attaching, and rejects an ID collision. The matching snapshot helper queries all four bounded projections. Initial run IDs feed the exact approval/epoch transaction; every run also enters the mission-wide immutable Temporal chain, while execution-epoch-specific run metadata remains separate.
