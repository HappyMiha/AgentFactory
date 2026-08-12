# ADR governance and impact propagation

AF-022 makes architecture change a durable, approval-gated transaction rather than a document-only convention.

## Decision and approval

Every ADR version records context, at least two alternatives with tradeoffs, the selected decision, consequences, affected workflow-contract keys, evidence, material domains, the architecture owner, and an explicit proposed/approved/rejected/applied state. Core content and decision digests are immutable.

Before approval, an impact analysis must explicitly list affected tasks, context packages, policies, evaluations, artifacts, deployment assumptions, and changed Blueprint sections. Empty categories remain visible as empty arrays. The named reviewer with the exact `human_architecture_owner` role is the only actor allowed to approve or reject, and the approval binds both the ADR digest and impact digest.

## Atomic application

Applying an approved ADR reuses the AF-013 mission-owner amendment checks. One SQLite transaction creates the next immutable Blueprint version, one new immutable version for every affected workflow contract, target-by-target propagation records, the application envelope, ADR state transition, audit event, and outbox event.

If contract serialization, validation, persistence, or any later propagation step fails, the transaction rolls back the new Blueprint and all related records. The prior Blueprint, its approval, and its existing execution authorization remain unchanged and active.
