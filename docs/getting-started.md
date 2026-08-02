# Getting started

This guide takes a new operator from an empty machine to a deterministic workflow, then to one explicitly approved provider call.

## 1. Requirements

Required:

- Git 2.40 or newer;
- Python 3.11 or newer;
- a terminal with permission to create a virtual environment.

Optional:

- GitHub CLI for repository synchronization;
- one or more supported provider CLIs;
- Docker Desktop, Docker Engine, or a compatible container runtime for the simulation image.

Provider subscriptions and API billing are external to Agent Factory.

## 2. Install on Windows

Open PowerShell in a directory where you keep source repositories.

```powershell
git clone https://github.com/<owner>/agent-factory.git
Set-Location agent-factory

py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e .

& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe -m agent_factory --help
```

If the `py` launcher is unavailable, replace `py -3.11` with the full path to a Python 3.11+ executable.

PowerShell activation is unnecessary. Calling `.venv\Scripts\python.exe` directly also avoids local script-execution-policy issues.

## 3. Install on macOS or Linux

```bash
git clone https://github.com/<owner>/agent-factory.git
cd agent-factory

python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .

.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m agent_factory --help
```

If your system names the interpreter `python3`, confirm that `python3 --version` reports 3.11 or newer before using it.

## 4. Check the environment

From here onward, `agent-factory` means the virtual-environment entry point. You may always substitute `python -m agent_factory` using the environment-specific Python path above.

```bash
agent-factory env check
agent-factory providers status
```

Only Git and Python are required for the deterministic demo. Missing optional providers are reported without blocking simulation.

## 5. Run the offline demo

```bash
agent-factory demo
```

The demo:

1. seeds a generic project and work item;
2. executes the `delivery` workflow in simulation mode;
3. produces deterministic artifacts for every stage;
4. records events and artifacts in SQLite;
5. stops at a pending human approval gate.

It does not invoke an external provider or change GitHub.

`agent-factory init` and `agent-factory bootstrap` are equivalent generic seeding shortcuts.

## 6. Create a project

Run the following commands from the repository or directory provider processes may inspect. The current directory anchors the default state path at `<workspace>/.agent-factory/state.db`.

```bash
agent-factory project init --name "Example Product" --description "A small, measurable delivery"
agent-factory project list
```

For automation from another directory, pass the same absolute `--workspace PATH` option to every command or set `AGENT_FACTORY_WORKSPACE` once in the process environment.

## 7. Create a work item

```bash
agent-factory work-item create \
  --project-id 1 \
  --title "First capability" \
  --description "Deliver one independently reviewable capability" \
  --kind task \
  --acceptance "Criterion one" \
  --acceptance "Criterion two"

agent-factory work-item list --project-id 1
```

On PowerShell, either place the command on one line or use the PowerShell backtick as the continuation character instead of `\`.

Run all work items across projects with:

```bash
agent-factory work-item list
```

## 8. Import a backlog

Review [the example backlog](../examples/backlog.json), then validate before importing:

```bash
agent-factory backlog validate --path examples/backlog.json
agent-factory backlog import --path examples/backlog.json --project-id 1
```

Validation is read-only. Import persists work items locally; it does not contact GitHub.

## 9. Run a workflow

```bash
agent-factory workflow run --task-id 1 --workflow delivery --mode simulation
agent-factory approvals list
```

Review generated artifacts before deciding:

```bash
agent-factory approvals approve 1 --note "Evidence reviewed"
```

Use `reject` instead of `approve` when evidence is insufficient. A decision is terminal.

## 10. Enable one real provider call

Install and authenticate a supported provider as described in [providers.md](providers.md). Verify it first:

```bash
agent-factory providers status
agent-factory agents list
```

The following example uses local Ollama:

```bash
ollama pull qwen2.5-coder:7b
agent-factory providers request ollama --agent coding-worker-ollama --task-id 1
agent-factory providers gates
agent-factory providers approve 1 --note "One local, bounded artifact"
agent-factory providers invoke 1
```

The gate authorizes exactly one logical attempt. Failure, timeout, or interruption does not make the gate reusable.

## 11. Docker simulation

```bash
docker compose build
docker compose run --rm agent-factory env check
docker compose run --rm agent-factory demo
```

The image:

- runs as an unprivileged user;
- writes persistent state only under `/data`;
- uses a read-only container filesystem plus temporary `/tmp`;
- drops Linux capabilities;
- includes no external provider CLI or provider credentials.

Docker is therefore simulation-only by default. Run real providers on the host or build a separately reviewed private image.

## 12. Configuration overrides

The package ships defaults under `agent_factory/defaults`. To customize them in a source checkout:

```bash
mkdir config
cp src/agent_factory/defaults/*.json config/
export AGENT_FACTORY_CONFIG_DIR="$PWD/config"
```

PowerShell equivalent:

```powershell
New-Item -ItemType Directory -Force config | Out-Null
Copy-Item src\agent_factory\defaults\*.json config\
$env:AGENT_FACTORY_CONFIG_DIR = (Resolve-Path config).Path
```

Review and commit non-secret configuration. Never commit provider authentication files or the SQLite state directory.

## Next steps

- Learn the trust boundaries in [architecture.md](architecture.md).
- Configure providers in [providers.md](providers.md).
- Customize stages in [workflows.md](workflows.md).
- Connect a repository using [github-integration.md](github-integration.md).
- Prepare backups and recovery using [operations.md](operations.md).
