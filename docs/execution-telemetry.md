# Execution telemetry and budgets

`ExecutionTelemetryService` implements AF-056 locally before the later AF-027 OpenTelemetry export.

Each workflow has at most one immutable correlation root and budget scope. The root links task and workflow identities and can hydrate the AF-053 delivery lineage: Codex worker process, managed worktree, every validator result, candidate, independent evaluation, stage approval, Founder approval, GitHub approval, and any Hermes ACP session attached to the same run.

Immutable idempotent usage samples retain stage, duration, tokens, estimated cost, tool calls, terminal reason, and bounded metadata. Retry decisions and stage reservations are separate immutable records. Trace totals survive restart and terminal traces cannot be rewritten.

Before a stage starts, the service checks its estimated token, cost, and tool usage plus the maximum stage count; retry requests check their own cap. A denied reservation is recorded, pauses the trace, and raises `BudgetExceeded`. Actual usage that crosses a cap also pauses the trace. The dashboard operational block reports active sessions, queued tasks, active leases and worktrees, failure count, and recent trace budget states.
