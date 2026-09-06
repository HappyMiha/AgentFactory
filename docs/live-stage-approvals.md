# Live stage execution approvals

AF-046 connects durable workflow waiting states to the Worker Runtime boundary. A mutable stage starts in `running`, requests an exact Control Plane gate, and moves to `waiting_approval` without changing the workflow run to a failure state.

The approval scope includes project, task, run, stage, worker, runtime, worktree, permissions, and a canonical SHA-256 request digest. Runtime launch reconstructs that scope independently from its fenced assignment and immutable binding. Any mismatched envelope, rejected decision, expired decision, emergency stop, inactive attempt, or foreign worktree fails before a worker session or provider process is created.

Approval consumption is durable and one-use at two levels:

- `scoped_execution_approvals` records the exact request and decision lifecycle;
- `stage_approval_consumptions` immutably binds the consumed gate to one assignment and one logical attempt.

After successful consumption, the exact stage returns from `waiting_approval` to `running`. Completing it records a succeeded checkpoint and deterministically starts the first dependency-ready pending stage. Runtime success still does not grant final acceptance, merge, push, or external mutation authority.

Tests in `tests/test_live_stages.py` cover durable waiting, exact-stage enforcement, one-attempt consumption, rejected and expired gates, pre-process failure, and automatic dependency-ready continuation. The shared Direct CLI and Hermes ACP contract tests also run mutable launches through this boundary.

## Exact effects and transaction composition

`PolicyRequest` accepts an optional `effect_digest`, a lowercase SHA-256 digest
of a trusted host's immutable effect descriptor. The host must compute it from
all effect-specific inputs and limits, then reconstruct the same descriptor at
the execution boundary. A digest supplied by untrusted request data is not
itself authority. The field augments the scope; `stage_id` and `run_id` retain
their real workflow identities. Assignment-bound consumption still verifies the
live task, worker, runtime, attempt, waiting stage and worktree.

When `effect_digest` is `None`, `PolicyRequest.canonical()` omits it entirely:
legacy canonical JSON, request hashes and previously issued approvals stay
unchanged. A raw request dictionary may omit the field or provide a valid digest;
explicit null, malformed digests, missing required fields and unknown fields
are rejected. Adding, removing or changing the digest requires a different exact
approval. No schema migration or rewrite of historical approval records occurs:
the existing request digest binds the effect and existing audit records retain
the full canonical request. An effect digest does not silently add new runtime
support: consumers that reconstruct a legacy scope reject effect-bound approvals
until their host composition explicitly supports that exact effect.

Policy evaluation, approval request/decision and consumption now acquire SQLite
writer exclusion before reading mutable authority. Each unit owns a transaction
when called alone, or a savepoint when a caller already has a transaction.
`ControlPlanePolicy.authorize` composes its policy decisions and consumption as
one unit; a later audit failure rolls that unit back without committing or
rolling back the caller's earlier work. Standalone expiry still records the
expired approval and raises `PermissionError`. Inside a caller transaction,
expiry remains subject to the caller's final commit or rollback.

A trusted host can begin a writer transaction before combining the existing
telemetry reservation with exact policy consumption. Both remain uncommitted
until the host commits; an outer rollback restores both. A returned `ALLOW`
inside that transaction is provisional. No external effect may start before
successful commit. Concurrent consumers cannot use an approval twice, and an
obsolete WAL snapshot must fail rather than authorize stale policy state.

This prerequisite supplies neither provider account/pricing authority nor a
complete installer/canary dispatcher. Current credentials, worker lease, account
permissions, pricing limits and complete usage evidence still need their own
reviewed host integration. Unknown provider outcomes retain budget holds; no
live call or spend is enabled by adding an effect digest.
