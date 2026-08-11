# Codex CLI implementation worker

AF-049 adds a qualified `codex exec` runtime for one mutable implementation attempt. The reviewed invocation follows the [official Codex CLI command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli): non-interactive execution, `workspace-write`, newline-delimited JSON events, an ephemeral session, and a working root set to the Control-Plane-owned task worktree.

The fixed profile sets approval handling to `never` because AF-046 has already consumed the exact human gate. It never uses `--dangerously-bypass-approvals-and-sandbox`, `danger-full-access`, or `--add-dir`. User configuration is ignored for the run so it cannot widen the reviewed profile; authentication still uses Codex's own credential store.

Before launch, Agent Factory verifies the Codex version/help surface, implementation role, live fenced assignment, logical attempt, worktree ownership, immutable context package, and consumed stage approval. Mutable command execution remains inside the Codex native `workspace-write` sandbox rooted at the task worktree. Control Plane state and other worktrees are outside that root, while model-generated commands retain the sandbox's default network restrictions.

The driver emits structured Runtime events and stores one immutable `codex_worker_results` record with:

- changed files and a canonical candidate diff digest;
- parsed command executions and exit states from Codex JSONL;
- terminal status, Codex version, and the exact non-secret invocation profile;
- the final worker handoff and content-addressed evidence directory.

Merge, push, issue closure, secret access, and final approval are absent from the permission profile and remain Control Plane authorities. Timeout, output overflow, and operator cancellation target the complete Codex process tree; a retry requires a new logical attempt and AF-046 gate.
