# Execution telemetry and budgets

`ExecutionTelemetryService` implements AF-056 locally; `ObservabilityService` adds the AF-027 OpenTelemetry-compatible export, operational metrics, and cost ledger.

Each workflow has at most one immutable correlation root and budget scope. The root links task and workflow identities and can hydrate the AF-053 delivery lineage: Codex worker process, managed worktree, every validator result, candidate, independent evaluation, stage approval, Founder approval, GitHub approval, and any Hermes ACP session attached to the same run.

Immutable idempotent usage samples retain stage, duration, tokens, estimated cost, tool calls, terminal reason, and bounded metadata. Retry decisions and stage reservations are separate immutable records. Trace totals survive restart and terminal traces cannot be rewritten.

Before a stage starts, the service checks its estimated token, cost, and tool usage plus the maximum stage count; retry requests check their own cap. A denied reservation is recorded, pauses the trace, and raises `BudgetExceeded`. Actual usage that crosses a cap also pauses the trace. The dashboard operational block reports active sessions, queued tasks, active leases and worktrees, failure count, and recent trace budget states.

AF-027 exports the existing `correlation_root` unchanged, with usage samples as spans, linked runtime entities, and derived queue depth, wait time, run duration, failure rate, iteration count, and orphaned-resource metrics. Export and cost records are idempotent and immutable. The cost ledger distinguishes provider-reported from estimated USD usage. Threshold policies deterministically record notify, reroute, pause, or require-approval actions; a hard cost-cap increase creates an immutable authorization for the exact `human_budget_authority` role before updating the trace budget.

## Outstanding stage reservations

Schema 77 extends the existing `execution_stage_reservations` authority with
immutable `execution_reservation_closures`; it does not introduce a separate
budget ledger. Migration preserves every old reservation and usage sample. Old
unclosed reservations remain held, including ones whose result is unknown.

`reserve_stage` serializes the read/check/write with SQLite `BEGIN IMMEDIATE`.
For tokens, USD and tool calls, committed usage is recorded trace usage plus
`max(estimate - recorded usage for that stage, 0)` for each allowed, unclosed
reservation. Usage for another stage never reduces its hold. Thus two requests
for 75 tokens cannot both reserve a 100-token trace, even on separate SQLite
connections. USD comparisons use decimal arithmetic over the stored numeric
values; this does not establish provider pricing or make estimates actual bills.
New usage that raises actual usage plus remaining commitments above a cap pauses
the trace. A closure never automatically resumes a paused trace.

A stage key identifies one attempt. The first successful reservation returns
`True`; an exact replay returns `False`, which grants no additional execution.
Changing its estimates is rejected. Blocked decisions remain blocked; use a new
attempt key only under an active trace and its remaining caps. A stage with
already recorded usage cannot acquire a new reservation retroactively. Maximum
stage and retry counts are never refunded by closure.

The trusted host must ingest all final usage before calling
`settle_stage(trace_id, stage_key, reason=...)`. Settlement requires at least one
usage sample, including an explicit zero sample for known zero usage. It releases
only the unused estimate; the usage already charged stays charged. Partial usage
alone does not mean execution finished. For an attempt proven not to have executed,
`release_stage(..., confirmed_no_effect=True, reason=...)` requires no usage samples.
A timeout, disconnected worker, missing receipt or unknown result is insufficient
for that assertion: leave its reservation outstanding until reconciled.

Exact closure replays return `False`; changed reasons or closure kinds are
rejected. Neither API can close a missing or blocked reservation or a terminal
trace. Late new usage after closure is rejected in both service and SQLite; only
settle once final usage is known. The legacy ingestion contract still retains the
first sample for an idempotency key even if a replay changes its payload. Replays
never add usage. Legacy unreserved samples remain supported as telemetry, without
granting permission to execute.

Finishing a trace does not release unresolved holds or permit late execution.
Terminal history remains immutable. Transactional methods preserve an enclosing
caller transaction through a savepoint; the host must commit the successful
reservation before dispatching an external effect. Lock or stale-snapshot errors
are failures to authorize, not permission to proceed.

These APIs are local budget accounting primitives. They do not bind a provider
call to account policy, pricing, mission authorization, a live worker lease or
provider credentials. AF-GC-009 still requires that integration and qualification;
this change performs no live calls or spending.
