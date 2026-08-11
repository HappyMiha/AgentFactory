# Local writable-worker sandbox

`AF-017` introduces a fail-closed Control Plane boundary for future writable worker runtimes. It does not make the existing read-only provider adapters writable.

## Policy boundary

A `SandboxPolicy` names one task worktree, zero or more per-execution paths below `.agent-factory/sandbox-temp`, a hard timeout, a combined stdout/stderr limit, and the fixed `deny` network policy. The policy rejects the workspace root, Control Plane state, broad temp roots, paths outside the workspace temp namespace, and network-enabled execution.

Every launch requires a live AF-007 assignment and fencing token. The worker receives a scrubbed environment and a fixed argument vector with `shell=False`. A path-mediated write is resolved before use; an out-of-scope target is denied and recorded as `sandbox.write.blocked` without placing the sensitive path in the audit payload.

## OS enforcement

- Linux uses Bubblewrap with a read-only host root, separate process/network namespaces, parent-death tree cleanup, and writable binds only for the worktree and declared temp paths.
- macOS uses `sandbox-exec` with default deny, read-only host access, denied network operations, and explicit writable subpaths.
- Hosts without a qualified backend fail before process creation and emit `sandbox.execution.blocked`. The current Windows build therefore keeps writable execution disabled until a separately qualified Windows backend is configured; process groups alone are not treated as a filesystem or network sandbox.

Proxy environment variables point at a closed loopback port as defense in depth. They are not the network boundary; the qualified OS backend is authoritative.

## Limits and teardown evidence

The existing process supervisor creates a contained process group and terminates its complete tree on timeout or combined-output overflow. Teardown snapshots the worktree without `.git` internals, records added/modified/deleted files and SHA-256 metadata, copies changed file content, and preserves bounded stdout, stderr, `candidate.json`, and `evidence.json` below `.agent-factory/sandbox-evidence/<execution-id>`. Declared per-execution temp paths created by the manager are removed only after evidence capture.

The sandbox does not create a worktree, launch Hermes, select a worker, validate a project, or accept a candidate. Those authorities remain with AF-048, AF-045/AF-049, AF-052, and the later review/founder flow.
