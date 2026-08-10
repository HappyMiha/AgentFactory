# Local Control Center

The Local Control Center is a loopback-only, single-operator interface over the same application services used by the Agent Factory CLI. AF-037 provides the read-only operations API and AF-038 adds the live dashboard and navigation shell; guarded controls follow in later R0.2 tasks.

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

AF-037 deliberately exposes no mutation routes. Future controls must call `AgentFactoryService` guarded commands and preserve the existing approval and audit paths.
