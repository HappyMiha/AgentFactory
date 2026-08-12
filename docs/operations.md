# Operations

This runbook covers health checks, state, backup, recovery, updates, and common failures.

For GitHub Actions failures, use the [CI troubleshooting runbook](ci-troubleshooting.md) to distinguish a repository failure from a runner/account billing block.

## Environment and provider health

```bash
agent-factory env check
agent-factory providers status
agent-factory agents list
```

Environment results distinguish required core components from optional provider tools. Provider health is a version probe, not proof that authentication or a real request will succeed.

## State location

The default state database is:

```text
<workspace>/.agent-factory/state.db
```

Override it with:

```bash
export AGENT_FACTORY_DB=/absolute/path/state.db
```

PowerShell:

```powershell
$env:AGENT_FACTORY_DB = "C:\absolute\path\state.db"
```

Docker uses `/data/agent-factory.db` in the `agent-factory-data` volume.

SQLite may create `-wal` and `-shm` companions while the database is open. Do not copy only the main file during active writes.

## Online backup

Use the built-in online backup so a running WAL database is captured consistently. The destination must not already exist:

```bash
agent-factory state backup --to /absolute/path/backup.db
```

The equivalent Python SQLite operation for recovery environments without the CLI is:

```bash
python -c "import sqlite3; s=sqlite3.connect('state.db'); d=sqlite3.connect('backup.db'); s.backup(d); d.close(); s.close()"
```

The destination should not exist, should be stored outside the live state directory, and should receive the same access protection as the source.

Verify a backup:

```bash
python -c "import sqlite3; d=sqlite3.connect('backup.db'); print(d.execute('PRAGMA integrity_check').fetchone()[0]); d.close()"
```

Expected output is `ok`.

## Restore

1. Stop all Agent Factory processes using the database.
2. Preserve the failed database and its WAL companions for investigation.
3. Verify the backup with `PRAGMA integrity_check`.
4. Copy the verified backup to a new state path.
5. Set `AGENT_FACTORY_DB` to that path.
6. Run `agent-factory project list` and `agent-factory approvals list`.
7. Reconcile interrupted provider attempts before requesting new gates.

Never overwrite the only copy of a damaged database.

## Reconcile interrupted attempts

```bash
agent-factory providers reconcile
agent-factory providers gates
```

An interrupted claimed or running attempt becomes abandoned when the original process identity cannot be proven. Its gate remains consumed. Request a new gate for retry.

Reconciliation never launches a provider automatically.

## Inspect orchestration state

High-level CLI views:

```bash
agent-factory project list
agent-factory work-item list
agent-factory providers gates
agent-factory approvals list
agent-factory audit list --limit 100
agent-factory state check
agent-factory state stale --older-than 3600
```

For deeper inspection, use a read-only SQLite connection or a copied backup. Useful tables include projects, work items, workflow runs, artifacts, provider execution attempts, approval gates, GitHub mutation reports, and events.

Avoid editing state manually. Application transitions combine state and audit events in transactions; direct edits can break those invariants.

## Update from source

```bash
git fetch --all --prune
git switch main
git pull --ff-only
python -m pip install -e .
python -m unittest discover -s tests -v
agent-factory env check
agent-factory demo
```

Back up the database before running a version that introduces new migrations. Released migrations are forward-only.

## Build and clean-install check

```bash
python -m pip install build
python -m build
python -m venv /tmp/agent-factory-smoke
/tmp/agent-factory-smoke/bin/python -m pip install dist/agent_factory_orchestrator-0.1.0-py3-none-any.whl
cd /tmp
/tmp/agent-factory-smoke/bin/agent-factory --help
```

On Windows, create the smoke environment under `$env:TEMP` and use its `Scripts\python.exe` and `Scripts\agent-factory.exe` executables.

The clean-install test must run outside the checkout so it proves packaged default configuration is present.

## Docker operations

Build and run the deterministic demo:

```bash
docker compose build
docker compose run --rm agent-factory demo
```

List volumes:

```bash
docker volume ls
```

Back up the named volume by stopping writes and copying `/data` through a temporary utility container appropriate to your environment.

Removing the volume destroys local orchestration state:

```bash
docker compose down --volumes
```

Run that command only after verifying a recoverable backup and the exact Compose project.

## Common failures

### `agent-factory` is not found

Use the virtual environment's Python directly:

```bash
python -m agent_factory --help
```

Then confirm the editable installation completed and the environment's executable directory is on `PATH`.

### Optional provider is missing

Install it using its official instructions, restart the terminal, and run its own `--version` command before checking factory health.

### Windows `WinError 5`

The resolved path may be an inaccessible application execution alias. Add the stable native executable as an earlier `executable_candidates` entry. Never work around the problem by enabling a shell or broad elevation.

### PowerShell blocks an npm command

Call the fixed `npm.cmd` launcher:

```powershell
& "C:\Program Files\nodejs\npm.cmd" --version
```

This avoids changing machine-wide execution policy.

### Workflow reports an active-run conflict

Another run for the same work item and workflow is still active or awaiting a decision. Inspect approvals and finish the existing run. If the process crashed, preserve state and investigate before manual intervention.

### Provider approval mismatch

Provider, agent, and work item must match the approved tuple. Provider reassignment or task changes require a new gate.

### Provider output is rejected

The subprocess may have succeeded but returned malformed JSON, an illegal verdict, or incomplete criterion evidence. Keep the artifact for diagnosis, improve task scope or provider instructions through reviewed configuration, then request a new attempt.

### GitHub apply is blocked

Verify the target, authenticated account permission, plan ID, gate ID, and digest. Generate a new plan instead of altering persisted plan data.

## Production-readiness checklist

- [ ] Dedicated unprivileged operating-system account.
- [ ] Workspace limited to intended repositories.
- [ ] State and config permissions reviewed.
- [ ] Backups tested with an actual restore.
- [ ] Provider versions and argument contracts pinned and reviewed.
- [ ] Provider auth uses least authority.
- [ ] Simulation used in CI and untrusted branches.
- [ ] External mutations require human approval.
- [ ] Default branch protection configured independently.
- [ ] Logs and artifacts reviewed for sensitive content.
- [ ] Alpha limitations accepted for the deployment.
