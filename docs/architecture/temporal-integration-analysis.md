# Temporal integration analysis

## Current AgentFactory execution model

AgentFactory is a Python 3.11+ package. Its operator backend is FastAPI (`agent_factory.web`) and the same `AgentFactoryService` application layer is also used by the argparse CLI. The browser UI is a small static HTML/CSS/JavaScript Local Control Center served by FastAPI.

The domain model is already established: SQLite stores projects, `WorkItem` backlog records, workflow runs, stages, artifacts, reviews, approval gates, assignments, fenced leases, attempts, worker sessions, worktrees, engineering-loop iterations, audit events, and idempotency records. `WorkflowEngine.run()` currently loads the reviewed workflow JSON, iterates its stages synchronously, selects agents/reviewers, invokes `AgentRuntime`, persists artifacts, and finally creates a Founder approval gate. Consequently an HTTP workflow-start request blocks until that loop finishes and the Python process owns the in-memory call stack.

Agent providers implement a common `Provider` abstraction. Configured CLI providers include Codex, Claude, Gemini, Antigravity, Ollama, and Firecrawl; only configured adapters are used. The newer lifecycle-aware `WorkerRuntime` abstraction adds durable start/resume/heartbeat/cancel/event/finalize operations. Writable Codex and Claude drivers run fixed, reviewed command lines in leased Git worktrees, capture bounded evidence, and terminate process trees through `ProcessSupervisor`. Hermes ACP has a separate persistent runtime driver. Generic provider execution uses `subprocess.Popen`, bounded concurrent stdout/stderr capture, timeouts, and Windows `taskkill /T /F` cleanup.

There is no separate message broker. SQLite active-workflow claims, assignment leases, fencing tokens, and runnable-task queries form the current local scheduler/queue boundary. Retry and recovery are domain-specific: provider attempts, durable stage checkpoints, workflow mutation reservations, bounded engineering repair iterations, expired leases, and local orphan inspection are persisted. Pause/resume exists for engineering loops and worker sessions; cancellation endpoints currently mark runs failed or cancel runtime sessions. Git/GitHub, Docker-like command execution, validators, filesystem worktrees, and provider CLIs remain ordinary local side effects guarded by existing services.

Configuration resolves from an explicit config directory, workspace `.agent-factory/config`, checked-in workspace config, then packaged JSON defaults. Environment variables choose the workspace and SQLite database. Tests use `unittest`, temporary workspaces/databases, FastAPI/httpx where available, and extensive deterministic recovery/idempotency coverage. Normal development commands are `python -m pip install -e ".[web]"`, `python -m agent_factory --workspace . web --open`, `python -m agent_factory demo`, and `python -m unittest discover -s tests`.

## Integration points

- FastAPI `POST /api/work-items/{task_id}/runs` and `AgentFactoryService.run_workflow()` are the existing start entry points.
- `WorkItem`, workflow JSON, `AgentRegistry`, `ReviewerRouter`, `AgentRuntime`, `WorkerRuntime`, and SQLite artifacts remain the execution inputs and domain stores.
- `ProcessSupervisor` and the existing CLI/worker drivers remain the process-containment boundary. Temporal activities add heartbeat and cancellation coordination around them.
- Existing workflow mutation reservations, stable run/task IDs, GitHub idempotency keys, candidate commits, and durable delivery checkpoints remain the side-effect deduplication layer.
- FastAPI run/detail/execution endpoints and the Local Control Center are extended with Temporal status and control data; they are not redesigned.

## Proposed Temporal execution model

With `TEMPORAL_ENABLED=true`, the API creates the existing SQLite workflow run, assigns job ID `run-{run_id}`, then starts one `AgentFactoryJobWorkflow` using stable ID `agentfactory-job-{job_id}` and returns immediately. Temporal is authoritative for the live orchestration state: current phase/stage, retries, pause/resume, cancellation, timers, and completed activity sequence. SQLite remains authoritative for AgentFactory domain state, artifacts, large logs, approvals, backlog, and audit history.

The workflow loads project/workflow context through an activity, then schedules one activity per reviewed stage. Workflow code performs only deterministic branching, repair-limit accounting, pause waits, signal handling, and status/query updates. Provider calls, subprocesses, filesystem access, SQLite writes, validation, and final approval creation occur only in activities. Activity payloads contain identifiers and bounded summaries; full provider output stays in the existing artifact/evidence stores.

The Temporal Worker runs on the Windows host so it can use local PowerShell, Codex, Claude/Hermes, Git, Docker, and project folders. Temporal Server, PostgreSQL, and Temporal UI run in Docker. The `agentfactory` namespace and `agentfactory-main` task queue are configurable and initialized idempotently.

The migration feature flag is strict: disabled preserves the synchronous engine; enabled requires a reachable Temporal Server and never silently falls back. Central policies distinguish transient infrastructure/provider failures from successful tool execution that reports a build/test failure. Long-running activities heartbeat, use conservative retry policies, and terminate subprocess trees when cancellation is observed.

## Components that remain unchanged

- Projects, backlog/work items, agents, roles, workflow definitions, approvals, evidence, artifacts, and SQLite persistence.
- Existing provider, Codex, Claude, Hermes, Git/GitHub, validator, worktree, sandbox, policy, credential, telemetry, and logging/audit services.
- Human authority boundaries: Temporal completion does not approve evidence, push Git changes, merge, or create uncontrolled external mutations.
- Existing synchronous execution when `TEMPORAL_ENABLED=false`.

## Components that will be replaced or wrapped

- The in-process `WorkflowEngine.run()` stage loop is wrapped by `AgentFactoryJobWorkflow` when Temporal is enabled.
- The blocking HTTP start path becomes an asynchronous Temporal start and immediate response.
- External execution is wrapped in activities with structured results, centralized timeouts/retries, heartbeat reporting, cancellation cleanup, and correlation identifiers.
- The existing run UI/API is augmented with Temporal workflow ID, status, current phase/task, attempt, progress, controls, and a Temporal UI link.
- Local Docker development gains a pinned PostgreSQL-backed Temporal stack and PowerShell lifecycle/health scripts.

Temporal does not replace SQLite or the AgentFactory backlog. It replaces the continuously running Python call stack as the durable orchestration backbone.
