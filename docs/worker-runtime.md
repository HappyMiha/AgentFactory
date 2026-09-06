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

## Effect-bound admitted starts

`RuntimeLaunch.effect_digest` is optional. When present it must be a lowercase
SHA-256 digest, the launch must be mutable, and a current stored worker admission
must bind the same digest. Unregistered legacy assignments cannot opt into this
path. The host computes the digest of the immutable effect descriptor and passes
it unchanged to `AdmissionRequest`, the real stage's `PolicyRequest` and the
`RuntimeLaunch`. The digest is a scope binding, not an account grant or executable
instruction; the host still has to reconstruct and validate the actual effect.

Runtime validation compares the launch effect with the immutable admission
request, including its saved request hash, before reserving a start. Exact policy
reconstruction includes the effect while retaining the real run, stage, attempt
and worktree. A substituted approval envelope is also rejected before creating a
start reservation. These checks do not consume the approval; existing one-use
consumption and current authority checks still precede the driver.

The existing committed start reservation includes the effect in its durable
scope and `admission_start_digest`. Concurrent or restarted callers with the
identical launch observe the same session without another driver call. Changing
or removing the effect rejects. A driver response lost after dispatch retains
`starting` and occupied capacity; it does not authorize retry. Reservation-write
failure rolls back before approval consumption or driver start. A later failure
after a committed start can remain unresolved under the existing recovery rules.

Without an effect, durable scope JSON and admission/start hashes retain their old
shape: no `effect_digest: null` is added. Existing saved admissions and sessions
remain readable and replayable. The default runtime behavior and legacy immutable
bindings remain unchanged. This interface performs no provider login, live call,
account/pricing authorization or installer launch on its own.
