# Local recovery and orphan reconciliation

`LocalRecoveryService` implements the read-only AF-057 recovery boundary for the single-node coding loop.

For a durable run, a recovery snapshot restores every stage checkpoint plus the latest lease/assignment, Hermes ACP session reference, execution-context package and digest, managed worktree, and pending stage, Founder, or GitHub approval. Reopening SQLite produces the same authoritative identities rather than reconstructing them from a transcript.

Orphan inspection reports provider attempt PIDs, Hermes ACP sessions, and unowned worktree paths as three independent collections. Worktree reconciliation may refresh managed status but never adopts, deletes, kills, or cleans an orphan; destructive action still requires separate human Control Plane authority.

Restore verification runs SQLite integrity and foreign-key checks, recomputes every stored artifact digest, and verifies the complete chained audit log. Recovery inspections are content-digested and immutable. Existing fenced mutation tests prove an older worker cannot commit after lease replacement, while AF-053 checkpoint replay proves process termination/retry does not duplicate a candidate commit or GitHub operation.

AF-AMM-018 extends this boundary to Autonomous Mission Mode. Every command, installation, service/model action, Git/worktree operation, checkpoint, and revision/epoch transition uses a typed append-only operation journal. `LocalRecoveryService.reconstruct_mission()` verifies the active mission scope, checkpoint, Git authority, inference lease, services, journal, artifacts, and audit before persisting `RESUME_SAFE` or a fail-closed disposition. An unknown completion is observed against actual state before any retry. The protocol, fault matrix, and operator procedure are documented in [Autonomous Mission operation journal and recovery](development/autonomous-mission-recovery.md).
