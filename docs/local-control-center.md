# N0DRA local control room

The browser UI is a single-operator window into the same application service used by the `agent-factory` CLI. It listens only on loopback, reads the same SQLite state, and uses the same guarded commands. There is no hidden second orchestration path in the browser.

## Start it

Install the optional web dependencies and run the foreground server:

```powershell
python -m pip install -e ".[web]"
agent-factory --workspace . web
```

On Windows, this one-liner installs the web extra, starts N0DRA, and opens the default browser:

```powershell
python -m pip install -e ".[web]"; if ($LASTEXITCODE -eq 0) { python -m agent_factory --workspace . web --open }
```

The default address is `http://127.0.0.1:8765/`. Press `Ctrl+C` in the terminal to stop the service cleanly. The command does not require or change `Set-ExecutionPolicy`.

Use `--port 8877` if the default port is busy. N0DRA accepts `127.0.0.1`, `localhost`, or `::1` and rejects non-loopback bind addresses.

## What is on the screen

- **Home** shows the local work pulse and the coding line: Gemini 3.1 Pro, then Claude Sonnet 5, then Codex.
- **Health** checks database integrity, migrations, providers, agents, runtime readiness, and emergency-stop state.
- **Backlog** imports a reviewed JSON manifest, filters work, and opens each item’s criteria and evidence.
- **Runs** opens the ordered workflow artifacts and exact stop reason.
- **Kill switch** exposes active runs, sessions, and leases with guarded pause, resume, cancel, stop, and release actions where supported.
- **Crew** shows provider health, agent assignments, and independent-review routing.
- **Reviews** contains the decisions that still require a person.
- **Logs** searches correlated audit evidence, changes two allowlisted numeric settings, and builds GitHub dry-run plans.

The page refreshes every five seconds. If a refresh fails, the last successful snapshot stays visible and is marked stale.

## Coding line

Codex owns orchestration and workers cannot create or delegate extra tasks. The default implementation route is:

```text
Gemini 3.1 Pro -> Claude Sonnet 5 -> Codex
```

The route advances only after an explicit token or account-quota exhaustion signal. Authentication failures, timeouts, missing executables, policy blocks, ordinary coding errors, and a bare transient HTTP 429 stop the run instead of spending the next provider’s quota.

## Backlog and specification intake

The default readable manifest is [`examples/backlog.json`](../examples/backlog.json). Validate it before import. Stable IDs make repeated imports safe: items already present are skipped.

Specification upload is a proposal step. N0DRA accepts a supported local document, asks the suitable planning role to extract a draft hierarchy, and shows the result for review. Uploading a document does not import tasks or start coding.

Archiving is guarded. Active runs, leases, or dependent items can block the action; audit history is retained.

## Confirmations and authority

Every browser mutation shows its target and impact before execution. The request must contain both:

```text
confirmed: true
X-Agent-Factory-Confirm: true
```

Omitting either signal changes nothing. Provider permission is also separate from final acceptance.

The Founder decision packet keeps the work-item criteria, mapped evidence, implementation and validation artifacts, reviewer identities, verdicts, and unresolved findings visible. Approving it changes only the local workflow decision. It does not merge, close, release, push, or apply a GitHub plan.

Repeating the same Founder decision is idempotent. A conflicting replay is rejected and the first attributed decision remains in the audit trail.

## Providers and reviews

Provider cards report ready, unhealthy, unavailable, or disabled state, plus sanitized executable and version evidence. Changing an agent’s provider affects future assignments only; previous artifact attribution is immutable.

Independent reviews exclude every model that produced the artifact being judged. The UI displays the selected reviewer, producer models, rotation strategy, verdict, and candidate exclusions so a routing mistake is inspectable.

## Settings and GitHub preview

The web UI accepts only `dashboard_refresh_seconds` from 2 to 60 and `audit_page_size` from 10 to 200. Each change creates a versioned audit record. Secrets, environment values, executable paths, and unrestricted command arguments are not accepted here.

GitHub preview takes an `OWNER/REPOSITORY`, a workspace-relative backlog path, and an existing issue snapshot. It performs no network read and executes no mutation. A non-empty preview stores an immutable SHA-256 plan and a separate pending gate; applying that exact plan remains a distinct CLI flow.

## API

Interactive documentation is available at `http://127.0.0.1:8765/api/docs`. Resources live under `/api`; list responses are bounded:

```json
{
  "items": [],
  "offset": 0,
  "limit": 50,
  "total": 0
}
```

`limit` must be between 1 and 200. Missing resources return `404`, malformed inputs return `422`, and storage failures return `503` with a structured error body.
