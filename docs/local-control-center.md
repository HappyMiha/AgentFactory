# Local Control Center

The Local Control Center is a loopback-only, single-operator interface over the same application services used by the Agent Factory CLI. It combines the read API, live dashboard, backlog inspection, and guarded workflow controls without creating a second orchestration path.

## Start the local API

Install the optional web dependencies and start the server:

```powershell
python -m pip install -e ".[web]"
agent-factory --workspace . web
```

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

The Work items workspace filters the current backlog by project, type, status, priority, dependency, and assignee. Selecting an item shows its description, acceptance criteria, expected outputs, dependencies, linked artifacts, and previous workflow runs.

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
