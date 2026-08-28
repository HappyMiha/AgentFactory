# Autonomous Mission planning, approval, and orchestration foundation

AF-AMM-007 through AF-AMM-014 establish the source, role-assignment, proposal-generation, verification, exact human approval boundary, durable pre-approval orchestration, and the first sequential post-approval child-delivery slice. Pre-approval operations do not authorize repository, environment, service, or Git mutation, and they do not create executable `work_items`; those records appear only after the exact approval authority has been revalidated.

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

The typed input, carry-over, and query state contain only domain identifiers, revision/epoch/checkpoint references, current item and role/model names, progress counters, phase, disposition, environment status, Temporal chain references, timestamps, and bounded activity summaries. Constructors reject oversized summaries, malformed digests, invalid counters, and cross-mission carry-over. Specifications, backlog snapshots, source trees, logs, provider output, manifests, and artifact bodies remain in SQLite or content-addressed storage rather than Workflow history.

Four queries expose mission status, progress and last activity, current role/model, and environment state. Phase and runtime disposition remain separate fields. `request_autonomous_planning` carries only a command, manifest, authorization, actor, action, and expected-version reference. The planning Activity reopens SQLite, verifies the exact mission identity and persisted owner grant, advances the version-fenced analysis/generation phases, runs the idempotent five-role pipeline, verifies the proposal, and returns only compact identifiers. An `ANALYZE` grant cannot be substituted for `REGENERATE_BACKLOG`; both remain bounded to the read-only local planning permission set.

The parent then waits in `WAITING_FOR_BACKLOG_APPROVAL` without a polling timer or environment/development Activity. `autonomous_backlog_approved` is only a wake-up hint: its claimed approval, revision, digest, and epoch values are never authoritative. A separate Activity rereads and integrity-checks the approval completion, active mission projection, immutable revision, execution epoch, local authorization, stable Workflow ID, and first run ID. A spoofed or premature Signal leaves the parent waiting. Once persisted authority is valid, bounded query state moves to `APPROVED` and retains the exact approval and execution-authorization identifiers.

## Post-approval child delivery

AF-AMM-014 makes post-approval execution explicit in the parent input. When enabled, an Activity independently revalidates the approval/authorization pair and advances `APPROVED → ENVIRONMENT_DISCOVERY → ENVIRONMENT_BOOTSTRAP → DEVELOPMENT`. Each transition is version-fenced and idempotent. Disabling post-approval execution preserves the durable phase-boundary wait used by planning-only deployments and tests.

In `DEVELOPMENT`, SQLite selects only an executable `READY` item whose dependencies are accepted. Preparing it appends an immutable child-job record and creates the existing `work_items`/`workflow_runs` transport records in one transaction. Its Temporal ID binds mission, active revision, execution epoch, stable item ID, and logical attempt. Repeating preparation with the same command or logical scope returns the same child; it cannot create a second provider attempt.

The standard `AgentFactoryJobWorkflow` remains unchanged when it has no autonomous context: successful evidence still waits at its Founder gate. An autonomous child first resolves the mission's persisted local inference authority and passes a typed `ProviderExecutionAuthorization` into the existing provider runtime. It then executes the reviewed delivery stages. Autonomous finalization requires successful terminal stage mutations plus persisted implementation, validation, policy-review, clean-Git, epoch-branch, and commit evidence. Only that opt-in path converges its transport run to `approved` without creating a per-item Founder gate.

The parent awaits the child result and then awaits reconciliation before selecting anything else. Reconciliation rereads the immutable completion, records the backlog item as `DONE`, and commits a `WORK_ITEM_ACCEPTED` mission checkpoint. The checkpoint increments the mission version, which changes the next preparation command. If the parent or Worker stops after child completion, replay recovers the same child and completion; if checkpoint completion was lost, the checkpoint command replay returns the existing record before the reconciliation ledger is appended. After all executable items are accepted, the parent advances `DEVELOPMENT → FINAL_VALIDATION → COMPLETED`.

Regeneration moves the mission from the approval wait back to generation under a distinct persisted grant. The new proposal, artifacts, verification, and revision append to history. `revision_lineage` verifies the immutable root-to-proposal parent chain, so an earlier human-visible proposal remains queryable and cannot be overwritten by a later attempt. Activity command suffixes bind every phase transition, pipeline run, verification, and revision operation, making a lost Activity completion safe to replay without another provider call.

`start_autonomous_mission_workflow` uses strict Temporal workflow-ID reuse, returns mission/run/chain correlation metadata, verifies immutable mission identity when attaching, and rejects an ID collision. The matching snapshot helper queries all four bounded projections. Initial run IDs feed the exact approval/epoch transaction, while later continue-as-new references use the existing append-only epoch run-chain ledger.
