# Hermes ACP runtime

AF-045 implements the concrete process driver below the shared AF-044 Worker Runtime. The Control Plane launches the fixed `hermes-acp` executable with `shell=False`, speaks newline-delimited ACP JSON-RPC over stdio, normalizes streamed messages/tool calls/diffs, answers permission requests through an injected Control Plane decision function, and terminates the complete process tree on cancel or finalization.

## Qualification boundary

The driver fails before session creation unless all evidence passes:

- an explicitly configured executable candidate resolves to a file;
- `hermes-acp --version` is exactly within the qualified `>=0.20.0,<0.20.1` range;
- `hermes-acp --check` exits successfully with its expected confirmation;
- the selected workspace and AF-048 worktree are readable and writable;
- the ACP initialize response negotiates protocol version 1.

This narrow version constraint binds the known upstream `hermes-acp` toolset and wire behavior to the qualification evidence. The driver sends `mcpServers: []`, accepts only the exact reviewed tool allowlist, and advertises no client-side filesystem or terminal capabilities. Version drift requires a reviewed qualification update rather than silently widening the tool surface. See the upstream [Hermes ACP internals](https://hermes-agent.nousresearch.com/docs/developer-guide/acp-internals).

## Durable identity and scope

Every session row binds the AF-044 worker session to task, durable run, active stage, logical attempt, assignment/fencing token, agent role, AF-048 worktree, AF-055 context package, exact tool list, executable/version/protocol evidence, and stable Hermes session ID. Scope columns and external identity are immutable.

`session/new` receives the already-created worktree as its absolute `cwd`; AgentFactory never passes a Hermes worktree-creation option. The only prompt content is the canonical AF-055 package whose digest was verified before launch.

On Control Plane restart, a new driver reads the durable binding, requalifies the executable and worktree, performs ACP initialize, and calls `session/load` with the same external session ID and worktree. AF-057 remains responsible for deciding whether interrupted mutable work may be replayed; AF-045 restores identity and protocol attachment without inventing a new session.

## Event and cancellation behavior

ACP `session/update` notifications become immutable runtime messages, tool calls, status records, and candidate-diff artifacts. An allowed permission response is a mutable event and therefore closes the AF-044 fallback boundary. Unknown permission outcomes deny by default.

Heartbeat uses the ACP session-list request rather than treating process existence alone as protocol health. Cancel sends the ACP cancellation notification and then uses the existing process supervisor to terminate and reap the entire child tree. Raw stderr is drained but not persisted into audit scope.
