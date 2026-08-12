# Chaos recovery and verified restore

AF-028 records deterministic fault-boundary evidence for clustered operation: mutation boundaries, host/service termination, network partition, queue restart, and storage restart. A run passes only when stage, lease, runtime-session, context, worktree, budget, approval, and external-operation identities are all retained and `LocalRecoveryService` verifies database integrity, accepted artifacts, foreign keys, and audit continuity.

`restore_exercise()` performs an online backup into a fresh database and runs the same verification against the restored authority. Evidence is immutable; destructive reconciliation or rollback remains a human-authorized operation.
