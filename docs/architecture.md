# Architecture

Agent Factory is a local-first orchestration control plane. It coordinates work; it does not grant an AI provider authority to approve its own output.

## Design goals

1. Keep project policy separate from orchestration code.
2. Make provider selection replaceable at configuration boundaries.
3. Produce reviewable artifacts and evidence at every stage.
4. Require human decisions for real execution and final acceptance.
5. Fail closed when workflow contracts, approvals, or provider definitions do not match.
6. Keep the deterministic path offline and suitable for CI.
7. Preserve enough state to understand what happened after failure or interruption.

## Component map

```mermaid
flowchart TB
    CLI["CLI"] --> APP["Application services"]
    WEB["Local Control Center"] --> APP
    APP --> REG["Agent registry"]
    APP --> WF["Workflow engine"]
    APP --> GH["GitHub client"]
    APP --> DB["SQLite storage"]
    WF --> REG
    WF --> RR["Reviewer router"]
    WF --> RT["Provider runtime"]
    RT --> DET["Deterministic provider"]
    RT --> CP["CLI providers"]
    CP --> SUP["Process supervisor"]
    WF --> DB
    RT --> DB
    GH --> DB
    CFG["Packaged defaults or config override"] --> REG
    CFG --> WF
    CFG --> RT
```

### CLI

`agent_factory.cli` maps terminal arguments and presentation onto shared application operations. It does not own business-state transitions.

### Application services

`agent_factory.application.AgentFactoryService` is the operator-facing boundary shared by the CLI and Local Control Center. Its immutable dataclass query results cover projects, work items, runs, artifacts, agents, providers, reviewer assignments, every approval kind, audit events, and effective runtime settings. JSON stored in SQLite is decoded before it crosses this boundary.

Commands for workflow execution, reviews, human decisions, agent configuration, provider execution, backlog import, GitHub planning/apply, backup, and recovery call the existing registry, workflow, runtime, storage, approval, and audit implementations directly. A web handler must call this service; it must not launch a CLI subprocess or reproduce an orchestration transition.

The service is deliberately transport-neutral and has no FastAPI dependency. Contract tests run equivalent CLI and direct-service operations against separate databases and compare their final states and ordered audit event types.

### Agent registry

The registry loads agent definitions from reviewed configuration. Each agent has:

- a stable ID and display name;
- a semantic role;
- an enabled state;
- one provider assignment;
- role instructions;
- declared permissions.

Enable, disable, and provider replacement operations update the configured registry rather than changing workflow code.

### Workflow engine

The engine loads a workflow, validates its graph, then executes stages in deterministic topological order. A stage declares:

- a unique ID and name;
- an agent;
- an output artifact name;
- stage dependencies;
- acceptance criteria;
- allowed verdicts.

The default `delivery` workflow has a policy pre-check, implementation proposal, acceptance validation, and policy post-check. Guardrail stage IDs and the guardian agent are declared in configuration rather than hard-coded to a business domain.

Review stages declare a reviewer pool and one or more ancestor artifacts in
`review_of`. The reviewer router excludes producer agents and model identities,
rotates among the least-used eligible reviewers, and persists both the selection
rationale and producer/reviewer identities. This prevents a model from repeatedly
judging its own output while keeping provider assignments replaceable.

### Provider runtime

The runtime selects the configured provider for an agent. In simulation mode it may fall back to the deterministic provider. Live mode prohibits deterministic fallback.

The provider interface separates health inspection from execution. The current executable adapters are CLI-based; a future HTTP adapter can implement the same interface without changing agent definitions.

### Process supervisor

CLI providers start without a shell in a new process group. The supervisor applies:

- fixed executable resolution;
- fixed argument vectors;
- repository-scoped working directory;
- UTF-8 decoding with replacement;
- bounded execution time;
- retained-output limits;
- targeted process-tree termination on timeout.

On Windows, stable native executable candidates are tried before unreliable execution aliases. On Unix-like systems, the runtime uses a new process session and targets that process group on termination.

### SQLite storage

SQLite is the orchestration state store, not the source repository. It contains:

- projects and work items;
- workflow runs and active-run claims;
- artifacts and review notes;
- durable reviewer assignments and rotation history;
- final approval gates;
- provider execution gates and attempts;
- GitHub plans, gates, idempotency keys, and reports;
- audit events;
- schema migration history.

Foreign keys, explicit state transitions, transactions, and unique claims protect local invariants. WAL mode allows safe concurrent readers and bounded writer waiting.

## Core data flow

```mermaid
sequenceDiagram
    actor Human
    participant CLI
    participant Store as SQLite
    participant Engine
    participant Runtime
    participant Provider

    Human->>CLI: Run simulated workflow for work item
    CLI->>Engine: workflow + item + mode
    Engine->>Store: Claim active run
    loop Each dependency-ready stage
        Engine->>Runtime: agent + stage item + context
        Runtime->>Provider: Deterministic execution
        Provider-->>Runtime: Artifact candidate
        Runtime-->>Engine: Content and metadata
        Engine->>Engine: Parse verdict and evidence
        Engine->>Store: Persist artifact and event
    end
    Engine->>Store: Create final approval gate
    Store-->>Human: Awaiting decision

    Human->>CLI: Request one real provider call
    CLI->>Store: Create scoped pending gate
    Human->>CLI: Approve reviewed gate
    CLI->>Store: Atomically claim gate and create attempt
    CLI->>Runtime: Agent + work item + approval scope
    Runtime->>Provider: Bounded CLI invocation
    Provider-->>Runtime: Artifact candidate
    Runtime-->>CLI: Content and metadata
    CLI->>Store: Persist terminal attempt and digest
```

## Approval model

Agent Factory deliberately separates three concepts:

1. **Provider execution approval** authorizes one provider, agent, and work item tuple.
2. **GitHub plan approval** authorizes one immutable repository plan identified by its SHA-256 digest.
3. **Final workflow approval** accepts or rejects the accumulated delivery evidence.

No successful provider response creates any of these decisions automatically.
Proxy reviewers perform the routine evidence review, but their verdict remains an
artifact: final workflow acceptance, merge, and external closure remain separate.

Provider approval consumption is atomic. The database records an execution attempt before a subprocess starts. An interrupted attempt is reconciled to a terminal abandoned state, and retry requires a new gate.

Writable worker processes additionally cross the [local sandbox boundary](local-sandbox.md). A live fenced assignment, immutable path/limit policy, and qualified OS backend are prerequisites. Unsupported hosts fail before launch; a process group or prompt instruction is never treated as filesystem or network isolation. Teardown preserves bounded execution evidence and the candidate change manifest outside the worker's writable roots.

The [Worker Runtime contract](worker-runtime.md) owns durable start, resume, heartbeat, cancel, event collection, and finalization semantics above provider/transport drivers. Direct CLI and Hermes ACP use the same immutable session-event model. A mutable event closes the fallback boundary permanently; runtime terminal success remains subordinate to Control Plane evidence, review, and acceptance.

The [role-definition registry](role-definitions.md) separates provider-neutral responsibilities from configured agents. Immutable semantic versions type the role's inputs, outputs, evidence, tools, permissions, limits, and incompatible duties. Workflow stages bind a role/version requirement, while per-decision assignment rejects an agent occupying mutually exclusive production and final-review duties.

The [evaluation-aware agent router](agent-routing.md) resolves a role requirement against the latest durable worker qualifications and lifecycle state. Every decision preserves candidate capability, qualification, model independence, quality, risk, cost, latency, load, health, eligibility/exclusion rationale, selected worker, strategy, and ordered fallback chain. Existing least-used model-aware reviewer rotation remains the dedicated review selector.

The [software-engineering role pack](software-role-pack.md) installs eight AF-010 contracts for backlog, architecture, implementation, deterministic validation, independent code review, security review, release/integration, and policy. Its incompatible duties prevent implementer self-acceptance and validator/reviewer collapse. Release authorization is derived only from an AF-053 candidate whose Founder gate is approved and delivery is `pr_ready`.

The [mission intake boundary](mission-intake.md) normalizes intent, objectives, measures, constraints, risks, and source classifications into immutable records. Its deterministic assessment emits exactly one readiness verdict with machine-readable rationale and blocking gaps. Ambiguity, conflicting authoritative sources, infeasibility, high risk, or materially reduced scope fail closed; only the named human mission owner can resolve intent or accept reduced scope.

The [Workforce Composer](workforce-composer.md) resolves AF-010 role contracts against current AF-011 qualification and routing evidence. It records replica bounds, pool and routing strategies, explicit arbitration, qualifications, primary assignments, and fallbacks. A bounded global search rejects locally plausible combinations that violate shared agent capacity, incompatible duties, or mission budget. Independence and provider-diversity exceptions require an immutable human review.

The [Factory Blueprint service](factory-blueprints.md) binds a ready AF-009 intake and AF-012 workforce into a content-addressed operating design covering modules, workforce, tools, context, verification, budgets, policies, and recovery. Complete decision traces cover authoritative sources, mission risks, assumptions, and rejected alternatives. New execution is possible only for the latest exact version and digest after its named human mission owner signs it; amendments preserve earlier approvals and authorizations while creating a newly blocked version with exact impact analysis.

The [mission bootstrap service](mission-bootstrap.md) consumes only the latest AF-013 execution authorization. One transaction creates the mission project, root work item, version-pinned AF-006 workflow graph, queue claim, seven exact manifests, and initial recovery checkpoint. The Blueprint digest is the idempotency authority. Each attempt records its own pre-bootstrap rollback point; a failure rolls back partial resources and persists verified compensation evidence outside the reverted transaction.

AF-015 completes the [Execution Context Package](execution-context-packages.md) boundary with a role/purpose broker. Source records now carry provenance and optional freshness evidence. Active authoritative requirements and safety constraints are mandatory and cannot be silently compacted; stale mandatory sources fail closed. Governed transcript compaction stores only decisions, unresolved risks, evidence references, and next steps, with the removed transcript represented by its digest and byte count.

The [typed memory service](typed-memory.md) separates working, semantic, episodic, procedural, entity, contextual, preference, and raw-history stores with per-store write policies. Retrieval is bounded by tenant, mission, task/purpose, authority, validity, store, and result count. Invalidation appends a contradiction/staleness record without deleting the entry or its consumers. Generated skills remain draft until a curator or human binds passing versioned tests, security review, and representative evaluation threshold evidence; approved skills can later be deprecated or revoked.

The [managed worktree service](managed-worktrees.md) is the only component allowed to create task Git worktrees. It binds deterministic branch/path identity to an approved base SHA and live fenced assignment before mutation, detects dirty/missing/orphaned state without destructive adoption, and permits cleanup only after terminal state plus the persisted retention deadline.

The [Execution Context Package builder](execution-context-packages.md) snapshots task scope, acceptance criteria, dependencies, approved base, effective policy, requirements, and prior decisions before dispatch. Its canonical digest is bound to the live fenced assignment and runtime session. Source selection and compaction are deterministic and fully manifested; workers cannot widen or replace the package after launch.

The [Hermes ACP runtime](hermes-acp-runtime.md) is the concrete stdio process boundary. It binds the AF-044 session to the active workflow stage, attempt, AF-048 worktree, and AF-055 package; admits only the exactly qualified Hermes/tool version; maps JSON-RPC events and permissions; reloads the stable Hermes identity after Control Plane restart; and owns complete child-tree cancellation.

AF-047 promotes that runtime evidence into an immutable ten-check worker qualification covering executable/version/check, lifecycle, cancellation, workspace, tools, permission bridging, usage, and artifacts. A failed Hermes worker may be quarantined. Direct Codex/Claude fallback is authorized only for a compatible read-only role before any mutable event; moving mutable work between runtimes instead requires an exact stage checkpoint, release of the old fence, and a newer active lease.

The [Claude Code implementation worker](claude-code-worker.md) is the separately qualified AF-050 alternative to Codex. It uses the same `WorkerRuntime`, assignment, stage, lease, worktree, context, and approval envelope, but owns an independent file-only permission profile and immutable result ledger. Plan-only Claude roles cannot enter the writable driver.

The [live-stage approval service](live-stage-approvals.md) connects a durable `waiting_approval` checkpoint to mutable runtime launch. It reconstructs the exact task/run/stage/worker/runtime/worktree/permission scope, consumes one approved gate for one logical attempt before process creation, and advances the next dependency-ready stage after completion. A worker runtime cannot approve, widen, replay, or redirect this authority.

The [Codex implementation worker](codex-implementation-worker.md) is the first qualified writable worker. Its fixed non-interactive profile roots Codex native workspace-write isolation at the leased AF-048 worktree, streams structured JSONL events, and stores an immutable candidate result with commands, changed files, diff digest, exit state, and handoff. Merge, push, issue closure, secret access, and final approval never enter the worker authority set.

The [deterministic validator runner](deterministic-validators.md) accepts only five reviewed project-pack command vectors and invokes them without a shell in the fenced candidate worktree. Time, output, environment, command, candidate, and pack digests are persisted with exact acceptance-criterion mappings; validation success requires every category to pass.

The [candidate change service](candidate-changes.md) commits only the AF-049 changed-file set after exact 5/5 AF-052 success, preserves the base branch, and records immutable base/head/diff/worktree evidence. Its pull-request operation is an immutable dry-run plan with a separate pending GitHub gate; candidate readiness never implies push or PR authority.

The [independent evaluation service](independent-evaluation.md) reconstructs the candidate's exact five-validator snapshot before any reviewer callback, rejects the candidate-producing model, and persists a versioned rubric result plus one immutable evidence/confidence/concerns/dissent verdict per required criterion. Missing primary evidence or any failed criterion makes acceptance fail closed.

The [persistent engineering loop](persistent-engineering-loop.md) binds one objective and worker policy to a durable run, stores every plan/diff/validator/critic/budget iteration immutably, pauses at deterministic iteration/time/token/cost/tool-failure caps, and converts a repeated identical failure into the configured replan or replacement action. Database constraints restrict terminal state to evidence-backed acceptance, explicit failure, or attributable human escalation.

The [coding delivery loop](coding-delivery-loop.md) binds the persisted AF-049 implementation lineage to exact AF-052 validation, AF-051 candidate creation, AF-020 independent review, an AF-008 repair record, a separate Founder workflow gate, and finally an AF-051 pending GitHub PR gate. Completed checkpoints are replayed from immutable state, so a supported retry does not rerun the provider, reprovision the worktree, recommit the candidate, rereview evidence, or duplicate the external-mutation plan.

The [execution telemetry service](execution-telemetry.md) assigns one correlation root to task/workflow, Hermes and Codex sessions, worktree, validator, approval, candidate, evaluation, and delivery identities. Immutable samples retain duration, retries, tokens, estimated cost, tool calls, and terminal reason. Durable preflight reservations pause before token, cost, stage, retry, or tool-call caps can be exceeded, and the Local Control Center dashboard exposes live queue/session/lease/worktree/failure/budget state.

The [local recovery service](local-recovery.md) reconstructs durable stage, lease, Hermes reference, context digest, worktree, and pending approval state after restart. Provider PIDs, Hermes sessions, and filesystem worktrees are classified as separate orphan sets. Inspection is non-destructive; artifact digests, audit continuity, database integrity, and foreign keys must all verify before state is trusted, while cleanup remains an explicit human-authorized operation.

## Workflow contracts

Real providers must return structured JSON:

```json
{
  "verdict": "PASS",
  "criteria_evidence": {
    "Every criterion has evidence": "Test report artifact 12 covers all listed criteria."
  },
  "summary": "Validation passed with one documented residual risk."
}
```

The stage decides which verdicts are legal. Blocking verdicts stop the run and prevent creation of a final approval gate. Missing evidence, malformed JSON, cycles, missing dependencies, and ambiguous order also fail closed.

## Configuration resolution

Defaults ship inside the Python package:

```text
agent_factory/defaults/
  agents.json
  policy.json
  providers.json
  workflows.json
```

`AGENT_FACTORY_CONFIG_DIR` replaces the default directory with an operator-reviewed configuration set. `AGENT_FACTORY_WORKSPACE` defines the provider working directory. `AGENT_FACTORY_DB` overrides the state database path.

Configuration is JSON-compatible YAML. Runtime input cannot add executable names, switches, model IDs, profiles, paths, URLs, or environment variables to an approved provider definition.

## GitHub boundary

GitHub synchronization follows plan, review, approve, apply:

1. normalize requested operations;
2. validate the entire action allowlist;
3. persist an immutable plan and SHA-256 digest;
4. show a dry-run preview;
5. request a matching human gate;
6. verify authenticated repository access;
7. execute idempotently;
8. persist a success, partial, or failure report.

Unsupported destructive operations are rejected before any network mutation.

## Trust boundaries

Trusted configuration is code. Changes to agents, provider commands, policy, and workflows require review.

Untrusted inputs include:

- provider output;
- repository files and documentation;
- imported backlog files;
- issue bodies and comments;
- subprocess stdout and stderr;
- environment values;
- stale local state from interrupted runs.

Artifacts are evidence, not authority.

## Current limitations

- SQLite is the only implemented backend.
- CLI providers are the only live transport.
- Full multi-stage live orchestration still needs a distinct approved attempt for each real call.
- Retained output is capped after process communication; streaming byte enforcement is planned.
- Environment filtering is based on sensitive key-name markers; value-aware redaction is planned.
- The event stream is append-only through application code but not cryptographically tamper-evident.
- Windows cleanup does not yet use a Job Object.
- The Docker image intentionally supports deterministic simulation rather than host provider passthrough.
