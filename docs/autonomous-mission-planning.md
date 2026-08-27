# Autonomous Mission planning intake

AF-AMM-007 and AF-AMM-008 establish the pre-approval source and role-assignment boundary. They do not authorize repository, environment, service, or Git mutation, and they do not create executable `work_items`.

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

AF-AMM-009 adds schema-validated role invocation and artifact production on top of these records; AF-AMM-010 verifies proposal completeness; AF-AMM-011 supplies the exact human approval boundary.
