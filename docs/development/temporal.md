# Temporal development guide

AgentFactory uses Temporal as an optional durable execution backbone. With `TEMPORAL_ENABLED=true`, starting a delivery run creates an `AgentFactoryJobWorkflow` and returns immediately. The Windows-host Worker performs the real AgentFactory activities, so it retains access to local PowerShell, Git, Docker, Codex, Claude, Hermes, and project folders. With the flag set to `false`, the existing synchronous workflow engine remains available during migration.

## Prerequisites

- Windows 10 or 11 with PowerShell 5.1 or newer
- Docker Desktop using Linux containers
- Python 3.11 or newer and the existing AgentFactory prerequisites
- Enough free local Docker storage for PostgreSQL, Temporal Server/Admin Tools, and Temporal UI images

Install AgentFactory and its web dependencies from the repository root:

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[web,dev]"
```

## Start Temporal

```powershell
.\infra\temporal\start.ps1
```

The script checks Docker, starts the pinned stack, waits for PostgreSQL, Temporal, the `agentfactory` namespace, and Temporal UI, then prints the endpoints:

- Temporal gRPC: `localhost:7233`
- Temporal UI: <http://localhost:8080>
- Namespace: `agentfactory`
- Task queue: `agentfactory-main`

Set the rollout flag for the PowerShell sessions that run the backend and Worker:

```powershell
$env:TEMPORAL_ENABLED = "true"
```

Other defaults are documented in the repository `.env.example`. Environment variables override them. Secret provider credentials must stay in the existing provider CLI profile, OS keyring, or AgentFactory secret mechanism; never put secrets in Workflow input.

Autonomous Mission parents use the stable ID prefix `agentfactory-autonomous-mission` by default. A deployment may set `TEMPORAL_AUTONOMOUS_WORKFLOW_ID_PREFIX` before its first mission starts, but must then keep that value stable so later clients attach to the same logical parents.

After exact backlog approval, an execution-enabled Autonomous Mission parent advances the authorized environment phases and starts one dependency-ready `AgentFactoryJobWorkflow` child at a time. Child IDs are deterministic across replay and bind the mission/revision/epoch/item/logical-attempt scope. The parent does not schedule another item until the prior child has persisted accepted validation, review, and clean-Git integration evidence and the reconciliation Activity has committed its mission checkpoint. Standard jobs still create the normal Founder gate; only a child carrying the persisted autonomous context uses mission authority and skips that per-item gate.

Autonomous controls use typed `PAUSE`, `RESUME`, `STOP`, and `RETRY_CURRENT_TASK` Signals. Each Signal carries an idempotent command ID plus the expected mission version, active revision/epoch, current child, and fencing token; an Activity revalidates those claims against SQLite before changing state. Pause and stop retain the mission phase, let an already admitted atomic operation reach its boundary, and reject every later inference, command-class operation, installation, service action, next-item reservation, or worker tool turn. Resume requires the newest token and waits for releasing stop/retry leases. Retry retires the active strategy and creates exactly one higher logical attempt without replaying an accepted completion. `STOPPED` is a resumable disposition, not Temporal cancellation or mission failure.

## Start AgentFactory

Start the Local Control Center in one PowerShell window:

```powershell
$env:TEMPORAL_ENABLED = "true"
& .\.venv\Scripts\agent-factory.exe --workspace . web --open
```

Startup fails with a direct `start.ps1` diagnostic if Temporal is enabled but unreachable. It does not silently fall back to synchronous execution.

## Start the Worker

Start the Windows-host Worker in a second PowerShell window:

```powershell
$env:TEMPORAL_ENABLED = "true"
& .\.venv\Scripts\agent-factory-temporal-worker.exe
```

The backend may start a Workflow before the Worker is running. Temporal keeps the Workflow task pending until a Worker polls `agentfactory-main`.

Start a job through the existing UI or CLI:

```powershell
& .\.venv\Scripts\agent-factory.exe --workspace . workflow run --task-id 1 --workflow delivery --mode simulation
```

The API equivalent is `POST /api/work-items/{task_id}/runs`. It creates the existing SQLite run, starts the stable Temporal Workflow ID `agentfactory-job-run-{runId}`, records the mapping, and returns the running job rather than waiting for all stages.

## Inspect and control a Workflow

Open <http://localhost:8080> to inspect Workflow history, activity attempts and retries, timers, failures, and payloads. The AgentFactory run detail shows the Workflow ID, current phase/progress while running, and a direct UI link. Pause, resume, and cancel controls send Temporal Signals.

Pause is a safe scheduling boundary: the current atomic Activity finishes, then the Workflow schedules no new Activity until resume. Cancellation propagates into a running provider/command Activity, requests graceful process-tree termination, and forces cleanup after the configured grace period.

## Stop and restart

Stop the local stack without deleting history:

```powershell
.\infra\temporal\stop.ps1
```

Restart it with:

```powershell
.\infra\temporal\start.ps1
```

The named volume `agentfactory-temporal-postgresql-data` preserves namespace and Workflow history across `stop`, `start`, container recreation, and a Windows restart once Docker Desktop and the Worker are started again.

Display status or use the machine-readable health exit code:

```powershell
.\infra\temporal\status.ps1
.\infra\temporal\health.ps1
if ($LASTEXITCODE -ne 0) { throw "Temporal is unhealthy" }
```

Delete local Temporal history only when intentionally resetting the development environment:

```powershell
.\infra\temporal\reset.ps1
# or, for non-interactive local automation:
.\infra\temporal\reset.ps1 -Force
```

## Tests

Run unit, API, SDK test-server, retry, repair, Worker-restart, and cancellation coverage:

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests
```

The Docker restart test is opt-in because it deliberately stops and restarts this repository's local Temporal Compose project:

```powershell
$env:AGENTFACTORY_TEMPORAL_DOCKER_TESTS = "1"
& .\.venv\Scripts\python.exe -m unittest tests.test_temporal_docker_durability
```

## Troubleshooting

### Port 7233 is occupied

Use `Get-NetTCPConnection -LocalPort 7233` to identify the listener. Stop the conflicting local service. Do not change only the Compose port: update `TEMPORAL_ADDRESS` consistently for AgentFactory and the Worker.

### Port 8080 is occupied

Use `Get-NetTCPConnection -LocalPort 8080`. Stop the conflict, or change the loopback UI mapping and `TEMPORAL_UI_URL` together. The gRPC endpoint can remain unchanged.

### Docker Desktop is not running

Start Docker Desktop and wait until `docker info` succeeds. Then rerun `start.ps1`.

### PostgreSQL is unhealthy

Run `docker compose --file .\infra\temporal\docker-compose.yml logs postgresql temporal-schema`. A normal stop preserves data. Use `reset.ps1` only if losing all local Temporal history is acceptable.

### Worker cannot connect

Run `health.ps1`, confirm the Worker uses the same `TEMPORAL_ADDRESS` and `TEMPORAL_NAMESPACE`, and verify no proxy or security tool is blocking loopback gRPC. The error names the address and tells you to run `start.ps1`.

### Namespace is missing

Run `start.ps1` again. Compose namespace initialization and SDK startup initialization are both idempotent. `status.ps1` reports `agentfactory (READY)` when registration is complete.

### Workflow already exists

AgentFactory intentionally uses stable job IDs and rejects a second independent execution. Continue, query, signal, or inspect the existing Workflow. Only failed terminal executions may reuse an ID under the configured reuse policy.

### Activity timeout or heartbeat timeout

Inspect the Activity attempt in Temporal UI and the referenced AgentFactory artifact/log. Increase the documented timeout environment variable only after confirming the Activity is healthy. Long-running agent/command Activities heartbeat and detect cancellation; a missing heartbeat indicates a stuck Worker or process.

### Tests failed but the Activity is shown as successful

That is intentional. `run_tests`-style execution succeeded as infrastructure, but `passed=false` is application input. The Workflow enters its bounded repair loop instead of asking Temporal to retry the same test command as a transient infrastructure failure.
