# Local Control Center

The Local Control Center is a loopback-only, single-operator interface over the same application services used by the Agent Factory CLI. It combines the read API, live dashboard, backlog inspection, and guarded workflow controls without creating a second orchestration path.

## Start the local API

Install the optional web dependencies and start the server:

```powershell
python -m pip install -e ".[web]"
agent-factory --workspace . web
```

On Windows, this single PowerShell line installs the optional dependencies, starts the foreground loopback service, and opens the default browser after startup:

```powershell
python -m pip install -e ".[web]"; if ($LASTEXITCODE -eq 0) { python -m agent_factory --workspace . web --open }
```

Press `Ctrl+C` in that PowerShell window to stop Uvicorn cleanly. The command does not run a script file and does not require or change `Set-ExecutionPolicy`. `--open` only schedules the loopback URL in the default browser; the server remains attached to the terminal and still rejects non-loopback hosts.

The default address is `http://127.0.0.1:8765`. Interactive API documentation is available at `http://127.0.0.1:8765/api/docs`. The CLI rejects non-loopback bind addresses; `127.0.0.1`, `localhost`, and `::1` are accepted.

The dashboard refreshes its local snapshot every five seconds without reloading the page. It summarizes ready, active, blocked, failed, awaiting-review, and awaiting-approval work; recent workflow runs; provider health; pending decisions; and recent failures. A failed refresh retains the last successful snapshot and marks it stale. Initial connection failures, empty state, and loading state remain visually distinct.

Use a different local port when needed:

```powershell
agent-factory --workspace . web --port 8877
```

## Read API

The API exposes health, projects, work items, workflow runs, artifacts, agents, providers, reviewer assignments, approvals, audit events, settings, and integration status under `/api`. List responses use this bounded envelope:

```json
{
  "items": [],
  "offset": 0,
  "limit": 50,
  "total": 0
}
```

`limit` must be between 1 and 200. Missing resources return a structured `404`, malformed parameters return a structured `422`, and storage failures return `503`. Provider and GitHub integration states are explicit; missing or unhealthy integrations are not reported as successful execution.

## Work-item and workflow controls

The Work items workspace can import a validated workspace-relative backlog into a named local project, then filters current work by project, type, status, priority, dependency, and assignee. Stable IDs make repeated imports safe: existing items are skipped. Selecting an item shows its description, acceptance criteria, expected outputs, dependencies, linked artifacts, and previous workflow runs.

The following mutations are intentionally narrow:

- claim a work item for an enabled agent;
- start the reviewed `delivery` workflow in simulation mode;
- approve or reject an artifact through the existing review command.

Every mutation displays a summary before execution and requires both `confirmed: true` in the JSON body and `X-Agent-Factory-Confirm: true` in the request header. Requests that omit either signal fail without changing state. The API delegates to `AgentFactoryService`, so agent eligibility, workflow gates, review ownership, and audit events remain identical to the CLI path.

Run detail preserves stage order and displays the producing agent/provider, verdict, evidence, errors, artifact status, and exact stop reason. Cancellation and resume are shown as unavailable because the MVP has no reviewed service command for either operation. Real provider execution is not exposed by the web control; the run action is simulation-only.

## Agent, provider, and reviewer controls

The runtime workspace lists every agent's role, enabled state, provider/model identity, permissions, latest claimed work, and reviewer usage. Enable, disable, and compatible-provider replacement commands show their future-assignment impact before the same two-part confirmation used by work-item controls. Changes are persisted as a workspace-local agent override under `.agent-factory/config` and audited; packaged defaults and existing artifact attribution are never rewritten.

Provider cards distinguish ready, unhealthy, unavailable, and disabled states. They include the reviewed executable path, version or sanitized error, execution capability, allowed roles, and redacted health detail. Provider replacement fails when the provider is unknown, disabled, or does not allow the agent's role. Selecting the deterministic provider remains available as a local simulation-safe assignment.

The independent reviewer view displays each durable routing decision, selected reviewer/provider/model, producer models, verdict, rotation strategy, and the reason every rejected candidate was excluded. The UI independently marks a routing conflict if a recorded reviewer model matches any producer model; the workflow router itself continues to fail closed before recording such an assignment.

## Audit explorer and runtime settings

The audit explorer correlates stored events with project, work item, workflow run, producing/reviewing agent, provider, outcome, and related artifacts. Filters cover time range, every correlated entity, action text, and normalized `success`, `failure`, `pending`, or `info` outcomes. Event payloads remain available in expandable detail while linked run and artifact evidence stays one action away.

The web UI accepts only `dashboard_refresh_seconds` (2–60) and `audit_page_size` (10–200). Both are integers with explicit bounds. Each successful update creates an immutable row in `runtime_setting_versions`, advances the current version, and records `settings.updated` with the previous and resulting value. Unknown names—including anything that resembles a token or secret—fail validation. The endpoint has no field for environment values, secrets, executable paths, or command arguments.

## GitHub dry-run preview

GitHub preview accepts an `OWNER/REPOSITORY`, a workspace-relative backlog path, and a JSON array containing a previously obtained issue snapshot. It does not read the network. Paths outside the selected workspace are rejected. The existing backlog diff and GitHub allowlist generate only reviewed create/update operations.

After explicit confirmation, a non-empty preview stores the existing immutable mutation plan, its SHA-256 digest, and a separate pending GitHub gate. `GitHubClient` remains in dry-run mode, so every result reports `executed: false`. The Local Control Center deliberately exposes no apply endpoint: an operator must separately inspect and approve the exact plan through the existing GitHub approval flow before the CLI can apply it. An empty diff receives a deterministic digest but no unnecessary gate.

## Founder review inbox

Each pending workflow approval opens as one decision packet containing the work-item contract, acceptance criteria and mapped evidence, ordered implementation/validation/policy artifacts, producing agents and providers, independent reviewer identities/models/verdicts, and derived unresolved findings. A missing direct mapping from a work-item criterion to recorded stage evidence is shown as an unresolved finding rather than silently treated as satisfied.

Approve and reject are separate Founder-only commands. The dialog keeps the evidence visible, accepts an optional rationale, summarizes the exact target and unresolved-finding count, and then requires the standard body/header confirmation pair. Automated reviewer and artifact-review endpoints cannot call this command, and the API actor schema accepts only `Founder`. A decision changes only the workflow approval/run state; it does not merge, close, release, or run a GitHub operation.

Repeating the same decision is idempotent and returns the original immutable result without rewriting its note or adding another decision event. A conflicting decision is rejected. The audit record and response include the actor, database timestamp, workflow-run target, previous state, resulting state, and note.
