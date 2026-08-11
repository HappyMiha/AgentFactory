# Coding delivery loop

`CodingDeliveryService` implements the AF-053 single-node vertical slice over the existing guarded components.

A logical delivery starts from an immutable AF-049 result whose assignment and AF-048 worktree prove the ready-task claim and implementation lineage. The service requires the exact AF-052 result set, creates the idempotent AF-051 candidate commit, runs AF-020 independent review, and records the outcome in the AF-008 bounded engineering loop. Validation or review failure selects the same worker by default or a policy-provided compatible replacement; the configured repair cap deterministically terminates exhausted work.

Accepted reviewer evidence creates a separate Founder approval gate. Only an explicit Founder approval produces a PR-ready AF-051 plan, and that plan still has its own pending GitHub mutation gate. The delivery service never calls GitHub apply and never creates a merge operation.

Delivery and iteration records are durable and immutable at supported checkpoints. Replaying the same logical attempt returns stored worker, worktree, candidate, evaluation, Founder, and PR-plan identities without another provider/model invocation or commit.
