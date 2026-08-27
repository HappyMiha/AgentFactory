# N0DRA

> LOCAL AI SWITCHBOARD // one task in, one coder at a time

![A late-1990s hacker workstation glowing beside the N0DRA console](src/agent_factory/static/n0dra-terminal-hero.png)

N0DRA is a local control room for AI-assisted coding. You give it a concrete work item, it sends that item through a bounded delivery workflow, and it keeps the prompts, artifacts, reviews, approvals, costs, and failures in one inspectable trail.

It is deliberately not an autonomous swarm. Workers cannot invent or delegate extra tasks. Codex coordinates the run; one coding model works at a time; a human still decides what is accepted or allowed to touch an external system.

```text
┌─ CODING LINE ───────────────────────────────────────────────┐
│  GEMINI 3.1 PRO  ──quota empty──>  CLAUDE SONNET 5          │
│         └────────────────both empty────────────────> CODEX   │
│                                                            │
│  ordinary failure = stop and explain, not silent failover  │
└────────────────────────────────────────────────────────────┘
```

The Python package and command remain named `agent_factory` / `agent-factory` for compatibility. N0DRA is the product and interface name.

## What works today

- A loopback-only web control room and a full CLI over the same application service.
- A deterministic offline demo that spends no provider tokens.
- Work items with dependencies, acceptance criteria, artifacts, independent reviews, and final human approval.
- Gemini 3.1 Pro as the first coding worker, pinned to the high-capability tier. Claude Sonnet 5 takes over only when Gemini reports token or quota exhaustion. Codex codes only when both external coding quotas are exhausted.
- Durable Temporal execution, local SQLite state, restart recovery, budgets, audit history, and emergency controls.
- Guarded provider calls and GitHub dry-run plans. A preview is never permission to apply a change.

This is still an alpha. The local workflow is usable; unattended live execution and a hosted multi-user control plane are not the product being promised here.

## Five-minute start

Python 3.11 or newer and Git are required. On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[web]"
& .\.venv\Scripts\agent-factory.exe env check
& .\.venv\Scripts\agent-factory.exe demo
& .\.venv\Scripts\agent-factory.exe --workspace . web --open
```

The control room opens at `http://127.0.0.1:8765/`. Press `Ctrl+C` in the terminal to stop it. It does not require a PowerShell execution-policy change.

On macOS or Linux, use `.venv/bin/python` and `.venv/bin/agent-factory` instead.

## A normal run

1. Write a small work item with acceptance criteria.
2. Inspect the proposed route and budget.
3. Start in simulation mode.
4. Read the implementation, validation evidence, and independent reviews.
5. Approve or reject the final result yourself.

Import the small working example when you want something concrete:

```powershell
& .\.venv\Scripts\agent-factory.exe backlog validate --path examples/backlog.json
& .\.venv\Scripts\agent-factory.exe project init --name "N0DRA field test" --description "First bounded repository run"
& .\.venv\Scripts\agent-factory.exe backlog import --path examples/backlog.json --project-id 1
```

The older 57-task implementation manifest is kept at [`examples/development-backlog.json`](examples/development-backlog.json). It is a historical engineering ledger, not the default working backlog.

## Safety rules that matter

- No worker-created subtasks or recursive agent delegation.
- Exactly one coding worker at a time.
- Token-exhaustion failover is explicit and recorded; normal errors fail closed.
- Provider permission and final acceptance are separate approvals.
- Writable workers stay inside a leased task worktree.
- GitHub changes begin as immutable dry-run plans and never auto-merge.
- Secrets are not accepted through the settings screen or written into evidence.

## Repository map

```text
src/agent_factory/       application, runtime, policies, CLI, and web UI
examples/backlog.json    small active example a person can actually read
docs/roadmap.md          current short roadmap and deliberate non-goals
docs/README.md           map of operator, developer, and reference docs
tests/                   executable contracts and regression coverage
infra/temporal/          local durable-workflow development stack
```

Start with the [documentation map](docs/README.md), then use the [getting-started guide](docs/getting-started.md) or the [Ukrainian operator guide](docs/user-guide-uk.md). Provider setup lives in [providers.md](docs/providers.md); the current direction lives in [roadmap.md](docs/roadmap.md).

## Development

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe -m build
```

The deterministic provider is the default test double. Tests do not sign in to Codex, Gemini, Claude, GitHub, or any hosted service.

Apache-2.0 licensed. See [LICENSE](LICENSE).
