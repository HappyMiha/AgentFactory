# Autonomous Mission planning and proposal generation

AF-AMM-007 through AF-AMM-009 establish the pre-approval source, role-assignment, and proposal-generation boundary. They do not authorize repository, environment, service, or Git mutation, and they do not create executable `work_items`.

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

AF-AMM-011 supplies the exact human approval and mission-start transaction.
