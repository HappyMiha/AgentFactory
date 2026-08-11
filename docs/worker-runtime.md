# Worker Runtime contract

`AF-044` separates lifecycle-aware worker execution from the earlier AF-005 `health/execute` provider adapter. The Control Plane owns the durable session and exposes one shared operation set: `start`, `resume`, `heartbeat`, `cancel`, `collect_events`, and `finalize`.

## Durable lifecycle

`start` validates the AF-007 assignment and fencing token before persisting a `starting` worker session. The runtime driver then binds one immutable external session identity and advances the session to `running`. Request persistence contains task, worker, permission, mutability, permission-bridge, and context-digest scope; raw context is not copied into session state.

Heartbeats, suspension/resume, cancellation, and terminal finalization use the existing versioned worker-session state machine. Runtime events are immutable and strictly sequenced per session. The normalized event kinds are status, message, tool call, artifact, heartbeat, and error. `finalize` returns those events plus typed tool-call, artifact, and message collections; runtime success does not accept the work item.

## Direct CLI and Hermes

`DirectCLIProviderDriver` adapts an existing synchronous provider to the lifecycle. Because a writable direct CLI can mutate before `start` returns, a mutable direct launch crosses the durable fallback boundary immediately.

`HermesACPWorkerRuntime` uses the same Control Plane contract over an injected ACP driver. Mutable ACP launches require a permission-bridge identity, and the fallback boundary is crossed when a mutable structured event is collected. The concrete [AF-045 Hermes ACP process driver](hermes-acp-runtime.md) now supplies protocol mapping, worktree/context binding, executable qualification, stable identity, restart reattachment, and process-tree cancellation.

Hermes one-shot transport is accepted only for qualification or read-only launches. A mutable one-shot request is rejected before a session is created because one-shot mode bypasses interactive approval handling.

## Fallback rule

Every mutable runtime event increments the durable `mutable_action_count`. `assert_fallback_allowed` reads that authoritative count and rejects fallback after it becomes non-zero. A transcript, in-memory driver state, or provider error cannot reset the boundary.
