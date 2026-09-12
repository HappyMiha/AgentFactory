# What is happening, and what a stop would stop

A progress bar that invents a finishing time is worse than no progress bar. The
person watching a run is trying to answer four questions, and each of them has
an honest answer available — including "we do not know".

1. What is it doing right now?
2. Is it still alive, or has it stopped reporting?
3. What has it cost, and what is still committed?
4. If I stop it, what actually stops?

Requirement trace: `AF-GC-023` (honest work status and a stop that covers
spending) and the progress screen that presents it.

## The rules the module enforces

`agent_factory.work_status` composes facts the caller already has. It starts
nothing, stops nothing and reads no database, so the rules below can be tested
without a run.

- **An estimate needs measurements.** At least three finished, comparable steps
  of this very run, or the estimate is `unknown` and says which of the four
  reasons applies: nothing measured yet, too few measured, the work is not
  reporting, or the work is waiting on a person. A configured expectation is
  never used as a measurement.
- **Silence is a blocker, not a status.** A heartbeat older than
  `STALLED_AFTER_SECONDS` produces a blocker that carries an action, and every
  blocker carries one: something the person can actually do.
- **Silence is only silence when something is supposed to be running.** A run
  parked on a person's decision is `waiting`, not a dead worker — reporting it
  as stalled would send someone chasing a process that was never started.
- **Reserved money is not spent money.** A provider-reported cost is spent and
  cannot be recovered; an estimate is a reservation that a stop releases. The
  cap is exceeded by the sum of the two, so a run is blocked before the money
  is gone rather than after.
- **A stop states its own limits.** `plan_stop` separates what can be cut short
  from what will finish anyway, and when any paid call is already in flight it
  says plainly that its cost stays spent. There is no wording in the module
  that claims a sent call can be recalled.
- **A restart never relaunches.** `reconcile_after_restart` returns accepted
  work as preserved and every orphan as something to check, because an
  unfinished action may have completed after the crash.

## Where the facts come from

`agent_factory.work_status_store.WorkStatusReader` reads rows the controller
already writes:

| Claim on the screen | Row it comes from |
| --- | --- |
| Stage and position | `workflow_stages`, numbered inside the run's own workflow |
| Alive, quiet, stalled | `provider_execution_attempts.heartbeat_at` of an attempt still in flight, else the running stage's `updated_at` |
| Blockers | a stage `waiting_approval` or `failed` |
| Spent / reserved | `cost_ledger_entries`, split by `source` |
| Cap | `execution_traces.max_cost_usd`, or the latest `budget_authorizations` a person signed |
| Estimate | durations of this run's succeeded attempts |
| What a stop covers | attempts in flight, plus queued stages |

A stage is numbered inside the workflow it belongs to ("stage 2 of 3"), not
mapped onto a fixed vocabulary, because a configured workflow is the only thing
that knows how many stages this run has. Its name is shown as configured:
`localisation.verbatim` states that a name from data is the same in every
language rather than inventing a translation for it.

## The screen

`/work` in the Local Control Center, in Ukrainian or English (`?lang=en`).
It shows the stage, liveness and the age of the last sign of life, the blockers
with their actions, the money, the estimate or the reason there is none, and a
stop panel that previews the plan before anything is stopped.

Pausing exists only for runs orchestrated by Temporal. On a run that is not,
the button is disabled and says why, instead of being offered and doing
nothing.

## From the command line

```bash
lokvetia work runs                      # runs that have not finished
lokvetia work status --run 12           # one truthful account; exit 3 if blocked
lokvetia work stop-plan --run 12        # what stopping would stop
lokvetia work after-restart --run 12    # what survived, what needs checking
```

Every command takes `--language uk|en`.

## Read-only by construction

`/api/work/...` exposes `GET` only, and a test asserts it: reading the status
of a run must never be a way to change it. Stopping goes through the existing
guarded `POST /api/executions/runs/{id}/cancel`, which needs an explicit
confirmation header, and the screen refuses to send it until the person has
acknowledged that calls already sent will finish and be paid for.

## What is not claimed

- The reservation released by a stop is the estimated part of the ledger. If a
  provider reports a cost later, it lands in the ledger as spent, and the
  screen will show it then — the number on the screen is what is known now.
- Nothing here detects a worker that is alive but making no progress. A
  heartbeat proves a process exists, not that it is doing anything useful.
