# Persistent engineering loop

`EngineeringLoopService` implements AF-008 as a durable state machine attached one-to-one to an AF-006 workflow run.

Every completed iteration stores the fixed objective, structured plan, content digest of the candidate diff, validator results, critic result, per-iteration and cumulative budget use, failure signature, consecutive-failure count, and selected outcome. Iterations and terminal loop records are immutable and reload unchanged after process restart.

The loop enforces maximum iterations, seconds, tokens, cost, and tool failures. Reaching the iteration cap or exceeding another cap pauses progress. Resumption requires an immutable human approval record and limits that increase at least one cap without reducing another or falling below consumed budget. Two consecutive identical failure snapshots force the configured `replan` or `replace_worker` outcome.

Only three terminal paths exist: an accepting iteration with accepted evidence, an iteration with an explicit failure reason, or a human escalation with actor and reason. SQLite triggers enforce these conditions independently of the service API.
