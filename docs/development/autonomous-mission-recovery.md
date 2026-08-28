# Autonomous Mission operation journal and recovery

AF-AMM-018 makes a restart a persisted authority decision, not an instruction to rerun the last Activity. SQLite migration 70 adds a typed mission operation journal, immutable lifecycle events, authoritative recovery snapshots, and append-only recovery decisions. Temporal history remains orchestration evidence; SQLite, Git, checkpoints, leases, and observed host state determine whether execution may resume.

## Mutation protocol

Every external effect must reserve one stable operation key before execution. The reservation binds the mission version, active backlog revision, execution epoch, checkpoint, optional child/stable item, control fencing token, typed operation class, canonical request digest, and reconciliation policy. Supported classes are provider call, command, installation, service, model lifecycle, worktree, Git integration, GitHub, checkpoint, revision transition, and epoch transition. Arbitrary operation strings are rejected.

The caller must append `running` before invoking the external effect. A known result appends `completed` or `failed` with canonical result and evidence digests. A process loss after `running` becomes `unknown`; it can never be retried merely because Temporal or the caller did not receive a result. Lifecycle events are append-only, sequence-checked, idempotency-keyed, and audit-correlated to the mission.

`unknown` is resolved only by a typed read-only observer:

- `present` adopts actual state as `reconciled` and forbids another execution;
- `absent` becomes `retry_ready` only for `verify_then_retry` or `idempotent_replay` policy;
- `conflict` or `indeterminate` becomes `needs_attention`;
- a missing observer fails closed as `indeterminate`.

Environment observers compare bounded command, installation, service, and model state and redact credential-like fields. Git observers read worktree HEAD/branch state or prove that the requested commit is reachable from the authoritative local branch. Remote GitHub mutations require their own connector observer and fail closed when it is absent; local Git ancestry is never treated as proof of remote state. Checkpoint, revision, and epoch observers compare immutable SQLite records and active mission pointers.

## Recovery reconstruction

`LocalRecoveryService.reconstruct_mission()` requires a stable recovery key and actor. It reconstructs and digest-binds:

- mission phase/disposition/version and the control fence;
- active backlog revision, execution epoch, running child task, and latest Temporal run;
- the current verified checkpoint and its Git commit/branch/worktree authority;
- the active or releasing inference lease;
- the checkpoint service manifest and journaled service requirements;
- every operation's latest lifecycle, request/result/evidence digests, and replay disposition;
- SQLite, foreign-key, artifact, audit, checkpoint, Git, fence, and journal integrity.

Running reservations are marked unknown before observation. Reservations that never entered `running` are safe to make `retry_ready` because the protocol forbids starting their effect. The service persists one immutable recovery record plus every state, operation, integrity, and resume decision. Replaying the same recovery key returns that exact record without appending events or repeating observations.

`RESUME_SAFE` is emitted only for a running mission whose complete authority and operation set verify. `PAUSED`, `STOPPED`, and `COMPLETED` remain non-resumable dispositions. Any corrupt evidence, Git conflict, unknown result without a conclusive observer, stale execution authority, or `needs_attention` operation emits `NEEDS_ATTENTION` and `replay_safe=false`.

## Fault matrix

| Kill point | Durable lifecycle on restart | Required check | Authoritative result |
|---|---|---|---|
| Before external invocation | `reserved` | No observer; the effect was prohibited from starting | `retry_ready` |
| During invocation, effect absent | `running -> unknown` | Typed actual-state observer returns `absent` | `retry_ready` only when policy permits |
| During invocation, effect present | `running -> unknown` | Observer returns `present` with evidence | `reconciled`; never invoke again |
| After effect, before result persisted | `running -> unknown` | Observer proves installed/service/Git/other accepted state | `reconciled`; adopt actual result |
| Actual state conflicts | `unknown` | Observer returns `conflict` | `needs_attention` |
| Probe unavailable or evidence corrupt | `unknown` or any nonterminal state | Observer/integrity check is indeterminate or fails | `needs_attention` |

The automated matrix applies all three normal kill boundaries to every typed mutation class. Dedicated tests reopen SQLite, reconcile an actual fast-forward Git integration without another commit, detect unmerged Git authority, detect artifact/audit corruption, and reconstruct revision, epoch, child task, checkpoint, model lease, and services.

## Restart procedure

1. Reopen the existing SQLite database; do not create a replacement mission or operation key.
2. Configure only read-only reconciliation probes for the operation classes present in the journal.
3. Call `reconstruct_mission()` once with a new stable recovery key for this restart attempt.
4. Resume scheduling only when the persisted record is `RESUME_SAFE` and `replay_safe=true`.
5. For `NEEDS_ATTENTION`, inspect its decision records and actual state. Never manually rewrite the journal, checkpoint, audit, or Git ref to force a retry.
6. After a human-authorized repair, use a new recovery key so the new authority decision remains distinct from the original evidence.

Targeted validation:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_autonomous_mission_recovery tests.test_storage_migrations
```
