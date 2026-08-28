# AgentFactory Temporal development stack

This directory runs a loopback-only, PostgreSQL-backed Temporal development environment. It follows the current official `temporalio/samples-server` PostgreSQL compose shape, with a named database volume added so normal stops and container recreation preserve workflow history.

Pinned versions:

- Temporal Server and Admin Tools: `1.31.2`
- Temporal UI: `2.53.0`
- PostgreSQL: `16.14-alpine3.24`
- AgentFactory Python SDK: `temporalio==1.31.0` (declared in `pyproject.toml`)

The Compose topology is based on Temporal's current [official samples-server repository](https://github.com/temporalio/samples-server). Version pins correspond to the [Temporal Server 1.31.2 release](https://github.com/temporalio/temporal/releases/tag/v1.31.2), [Temporal UI 2.53.0 release](https://github.com/temporalio/ui/releases/tag/v2.53.0), and [Temporal Python SDK 1.31.0 package](https://pypi.org/project/temporalio/1.31.0/).

Start from the repository root:

```powershell
.\infra\temporal\start.ps1
```

The gRPC endpoint is `localhost:7233`, the UI is `http://localhost:8080`, and the idempotently-created namespace is `agentfactory`. Its default Workflow retention is seven days and can be changed with `TEMPORAL_NAMESPACE_RETENTION` before first creation. Ports bind to `127.0.0.1`; PostgreSQL is not published to the host.

`stop.ps1` preserves `agentfactory-temporal-postgresql-data`. `reset.ps1` is the only routine that removes it and therefore requires confirmation or `-Force`.

The schema and namespace init containers are expected to exit successfully after their one-time work. `temporal`, `postgresql`, `temporal-admin-tools`, and `temporal-ui` remain running.

Additional commands:

```powershell
.\infra\temporal\status.ps1
.\infra\temporal\health.ps1
.\infra\temporal\stop.ps1
.\infra\temporal\reset.ps1
```

`health.ps1` returns exit code `0` only when PostgreSQL, Temporal gRPC, the configured namespace, and the UI respond. The full Windows developer and troubleshooting guide is in `docs/development/temporal.md`.
