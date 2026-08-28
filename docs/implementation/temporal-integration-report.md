# Temporal integration implementation report

## 1. What was changed

AgentFactory now has an optional Temporal-backed delivery path controlled by `TEMPORAL_ENABLED`. When enabled, the existing API/application start path creates the existing SQLite run, starts a stable `AgentFactoryJobWorkflow`, records the Temporal identity, and returns without waiting for all stages. A Windows-host Worker executes side effects as Activities and reuses the existing AgentFactory registry, runtime, reviewer router, workflow contracts, SQLite artifacts, approvals, and process supervisor.

The integration includes a pinned local PostgreSQL/Temporal/UI Compose stack, idempotent namespace bootstrap, PowerShell lifecycle and health commands, centralized timeout/retry policies, structured Activity results, activity heartbeats, cancellation-aware process-tree cleanup, pause/resume/cancel Signals, status/progress/current-task Queries, a bounded repair loop, a deterministic demo Workflow, API/UI controls, and SDK plus real-Docker durability coverage.

`TEMPORAL_ENABLED=false` preserves the pre-existing synchronous `WorkflowEngine` path. Enabling Temporal is strict: backend and Worker startup fail with an actionable diagnostic if the configured server is unavailable.

## 2. Architecture before

FastAPI or the CLI called `AgentFactoryService.run_workflow()`, which called `WorkflowEngine.run()` in the same process. The engine loaded the reviewed workflow, ran stages sequentially through `AgentRuntime`, persisted artifacts and reviews in SQLite, and created a Founder gate. SQLite already provided domain persistence, mutation reservations, assignments, leases, attempts, recovery state, and audit events, but the active Python call stack was not durable across a process or Windows restart.

## 3. Architecture after

The product/domain boundary remains AgentFactory: projects, work items/backlog, agents, policies, provider gates, evidence, artifacts, approvals, and SQLite. Temporal is the durable orchestration boundary: Workflow history, completed stage sequence, Activity scheduling/retry, timers, live orchestration state, Signals, cancellation, and recovery.

`AgentFactoryJobWorkflow` contains deterministic orchestration only. The additive `AutonomousMissionWorkflow` is the stable, long-lived parent for an opt-in Autonomous Mission; its history contains identifiers and bounded summaries only. Before approval it waits without polling or side effects. After approval, when execution is enabled, it advances authorized environment phases, starts one deterministic dependency-ready child at a time, and waits for both the child result and its SQLite checkpoint reconciliation before scheduling the next item. `AgentFactoryActivities` performs workspace/config reads, SQLite reads and writes, agent execution, review routing, artifact persistence, validation, standard final-gate creation, and autonomous evidence finalization. Long-running runtime calls execute in a host thread with Temporal heartbeats and a cancellation event. CLI processes are placed in their own process group; cancellation first requests graceful group termination and then uses bounded forceful tree cleanup.

Standard-job stable IDs have the form `agentfactory-job-{jobId}`; the current application assigns `jobId=run-{runId}`. Autonomous parent IDs have the form `agentfactory-autonomous-mission-{missionId}`. Autonomous child IDs additionally bind mission, revision, execution epoch, stable item, and logical attempt. Duplicate preparation resolves the same immutable child job, and provider/stage mutation reservations remain replay-safe. The current task queue is configurable and defaults to `agentfactory-main`.

## 4. Files added

- `infra/temporal/docker-compose.yml`
- `infra/temporal/.env.example`
- `infra/temporal/README.md`
- `infra/temporal/start.ps1`
- `infra/temporal/stop.ps1`
- `infra/temporal/reset.ps1`
- `infra/temporal/status.ps1`
- `infra/temporal/health.ps1`
- `infra/temporal/dynamicconfig/development-sql.yaml`
- `infra/temporal/scripts/setup-postgres.sh`
- `infra/temporal/scripts/create-namespace.sh`
- `src/agent_factory/orchestration/__init__.py`
- `src/agent_factory/orchestration/temporal/__init__.py`
- `src/agent_factory/orchestration/temporal/settings.py`
- `src/agent_factory/orchestration/temporal/models.py`
- `src/agent_factory/orchestration/temporal/policies.py`
- `src/agent_factory/orchestration/temporal/client.py`
- `src/agent_factory/orchestration/temporal/worker.py`
- `src/agent_factory/orchestration/temporal/workflows.py`
- `src/agent_factory/orchestration/temporal/activities.py`
- `tests/test_temporal_config.py`
- `tests/test_temporal_api.py`
- `tests/test_temporal_workflows.py`
- `tests/test_temporal_docker_durability.py`
- `docs/architecture/temporal-integration-analysis.md`
- `docs/development/temporal.md`
- `docs/implementation/temporal-integration-report.md`

## 5. Files modified

- `.env.example`: Temporal feature flag, endpoint, namespace, queue, UI, timeouts, heartbeat, cancellation, and repair settings
- `.gitattributes`: LF enforcement for Linux container shell scripts
- `Dockerfile`: installs declared runtime dependencies so the image includes the required Temporal SDK
- `pyproject.toml`: pinned Temporal SDK, Worker entry point, and required web multipart dependency
- `README.md`: durable workflow quick start and documentation links
- `src/agent_factory/application.py`: prepare/start mapping, stable identity persistence, and Temporal data in run views
- `src/agent_factory/web.py`: strict startup connection, asynchronous job start, Queries, and Signals
- `src/agent_factory/static/app.js`: live status, progress, controls, Workflow ID, and UI link
- `src/agent_factory/static/index.html`: asset cache version
- `src/agent_factory/providers.py`: cancellation event support and graceful/forceful process-tree cleanup
- `src/agent_factory/runtime.py`: cancellation propagation into CLI providers
- `src/agent_factory/codex_worker.py`: shared graceful cancellation path
- `tests/test_web.py`: reviewed API surface for pause and resume

## 6. Temporal Server version

`temporalio/server:1.31.2` and matching `temporalio/admin-tools:1.31.2`.

## 7. Temporal SDK version

Official Python SDK `temporalio==1.31.0`.

## 8. PostgreSQL version

`postgres:16.14-alpine3.24`. Workflow history is stored in the named volume `agentfactory-temporal-postgresql-data`.

Temporal UI is pinned separately at `temporalio/ui:2.53.0`.

## 9. How to start Temporal

From the repository root in Windows PowerShell:

```powershell
.\infra\temporal\start.ps1
```

The command waits for PostgreSQL, Temporal gRPC, the `agentfactory` namespace, and UI before returning. Normal `stop.ps1` use preserves data. `reset.ps1` requires confirmation or `-Force` before deleting the volume.

## 10. How to start the Worker

```powershell
$env:TEMPORAL_ENABLED = "true"
& .\.venv\Scripts\agent-factory-temporal-worker.exe
```

Equivalent module command:

```powershell
& .\.venv\Scripts\python.exe -m agent_factory.orchestration.temporal.worker
```

## 11. How to run AgentFactory

Install and start the existing Local Control Center in a separate PowerShell window:

```powershell
& .\.venv\Scripts\python.exe -m pip install -e ".[web,dev]"
$env:TEMPORAL_ENABLED = "true"
& .\.venv\Scripts\agent-factory.exe --workspace . web --open
```

Start a reviewed delivery job in the UI, through `POST /api/work-items/{task_id}/runs`, or with:

```powershell
& .\.venv\Scripts\agent-factory.exe --workspace . workflow run --task-id 1 --workflow delivery --mode simulation
```

## 12. How to open Temporal UI

Open <http://localhost:8080>. AgentFactory's run detail links to the selected Workflow where the UI route is supported.

## 13. Tests executed

Syntax, patch hygiene, Compose rendering, targeted API tests, official Temporal SDK test-server tests, and the entire existing suite were exercised. Final complete-suite result: **300 tests run: 299 passed and 1 opt-in Docker test skipped by default**.

```powershell
git diff --check
& 'C:\Users\HappyDucky02\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m compileall -q src tests
docker compose --file .\infra\temporal\docker-compose.yml config
docker run --rm --entrypoint python agent-factory:local -m pip check
& 'C:\Users\HappyDucky02\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -W ignore::DeprecationWarning -m unittest discover -s tests
```

The final full-suite command completed in 100.997 seconds with `OK (skipped=1)`; the skipped case is the deliberately opt-in Compose stop/start test described below.

## 14. Durability tests executed

- **Worker restart:** SDK test server ran a two-Activity Workflow, shut down the first Worker after Activity 1, delivered a Signal while no Worker was polling, started a replacement Worker, completed Activity 2, and verified Activity 1's side-effect counter remained exactly one.
- **Temporal container restart:** the real pinned Docker stack completed the demo marker Activity, stopped the Worker and all Compose services, restarted the existing containers/PostgreSQL volume, connected a replacement Worker, resumed the same Workflow ID, and verified the marker Activity's modification time did not change.
- **Temporary Activity failure:** controlled attempts 1 and 2 raised retryable `TRANSIENT` failures; attempt 3 succeeded under the centralized policy.
- **Application failure:** a command successfully executed but exited with a failing result; the Workflow returned `repair_required`/`BUILD_ERROR` rather than causing an infrastructure retry loop.
- **Cancellation:** a long-running Python subprocess published its PID, Workflow cancellation propagated to the Activity, the process tree was terminated, and `tasklist` verified the PID was absent.
- **Normal stop persistence:** `stop.ps1` stopped the stack, `docker volume inspect agentfactory-temporal-postgresql-data` confirmed the history volume remained, and `start.ps1` returned all services to READY.
- **Reset safety:** `reset.ps1 -WhatIf` showed the destructive target and left the healthy environment unchanged.

Exact Docker durability command and result: **1 test passed**.

```powershell
$env:AGENTFACTORY_TEMPORAL_DOCKER_TESTS='1'
& 'C:\Users\HappyDucky02\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_temporal_docker_durability
```

Infrastructure verification commands:

```powershell
.\infra\temporal\start.ps1 -TimeoutSeconds 60
.\infra\temporal\health.ps1
.\infra\temporal\status.ps1
.\infra\temporal\stop.ps1
docker volume inspect agentfactory-temporal-postgresql-data --format '{{.Name}}'
.\infra\temporal\start.ps1 -TimeoutSeconds 120
.\infra\temporal\reset.ps1 -WhatIf
```

## 15. Known limitations

- Phase one durably migrates the reviewed generic delivery stage loop. Specialized engineering-loop, writable-worker, GitHub-plan, and control-plane session state machines retain their existing persistence/orchestration until migrated deliberately.
- Existing live provider and writable Codex/Claude/Hermes authorization gates remain fail-closed. Temporal does not mint approvals, bypass sandbox/worktree policy, push Git changes, or approve final evidence. The currently exposed web start command remains simulation-only.
- Git, Docker, validator, and writable-worker services are reused when reached through existing AgentFactory services; they are not exposed as a broad unrestricted Temporal command surface.
- Status is queried on demand by the Local Control Center rather than streamed. Closed Workflow details remain available in Temporal UI and SQLite domain state.
- This is a single-node localhost development deployment without production HA, TLS, authentication, Prometheus, or Grafana.
- The demo Activity bounds direct command output to 20,000 characters. Real stage output remains in AgentFactory artifacts; a future external artifact store may be appropriate for very large binary/log payloads.

## 16. Recommended next steps

1. Migrate the specialized writable coding-delivery loop one checkpoint at a time, preserving its existing one-use live-stage gates and worktree fencing.
2. Add narrow typed Activities for the exact reviewed validator, Git commit, Docker, and GitHub plan operations as those paths enter the Temporal Workflow; retain stable idempotency keys for every mutation.
3. Project closed Workflow status and retry metadata into the existing event stream for richer UI timelines without copying full Temporal history.
4. Add a manual approval wait Signal when the current Founder workflow is intentionally moved inside Temporal; do not poll for human input.
5. Add production deployment/security design separately if AgentFactory moves beyond loopback development: TLS, authentication/authorization, backup/restore, metrics, and HA sizing.
