# Live stage execution approvals

AF-046 connects durable workflow waiting states to the Worker Runtime boundary. A mutable stage starts in `running`, requests an exact Control Plane gate, and moves to `waiting_approval` without changing the workflow run to a failure state.

The approval scope includes project, task, run, stage, worker, runtime, worktree, permissions, and a canonical SHA-256 request digest. Runtime launch reconstructs that scope independently from its fenced assignment and immutable binding. Any mismatched envelope, rejected decision, expired decision, emergency stop, inactive attempt, or foreign worktree fails before a worker session or provider process is created.

Approval consumption is durable and one-use at two levels:

- `scoped_execution_approvals` records the exact request and decision lifecycle;
- `stage_approval_consumptions` immutably binds the consumed gate to one assignment and one logical attempt.

After successful consumption, the exact stage returns from `waiting_approval` to `running`. Completing it records a succeeded checkpoint and deterministically starts the first dependency-ready pending stage. Runtime success still does not grant final acceptance, merge, push, or external mutation authority.

Tests in `tests/test_live_stages.py` cover durable waiting, exact-stage enforcement, one-attempt consumption, rejected and expired gates, pre-process failure, and automatic dependency-ready continuation. The shared Direct CLI and Hermes ACP contract tests also run mutable launches through this boundary.
