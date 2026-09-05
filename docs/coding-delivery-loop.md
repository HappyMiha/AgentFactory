# Coding delivery loop

`CodingDeliveryService` implements the AF-053 single-node vertical slice over the existing guarded components.

A logical delivery starts from an immutable AF-049 result whose assignment and AF-048 worktree prove the ready-task claim and implementation lineage. The service requires the exact AF-052 result set, creates the idempotent AF-051 candidate commit, runs AF-020 independent review, and records the outcome in the AF-008 bounded engineering loop. Validation or review failure selects the same worker by default or a policy-provided compatible replacement; the configured repair cap deterministically terminates exhausted work.

Accepted reviewer evidence creates a separate Founder approval gate. Only an explicit Founder approval produces a PR-ready AF-051 plan, and that plan still has its own pending GitHub mutation gate. The delivery service never calls GitHub apply and never creates a merge operation.

Delivery and iteration records are durable and immutable at supported checkpoints. Replaying the same logical attempt returns stored worker, worktree, candidate, evaluation, Founder, and PR-plan identities without another provider/model invocation or commit.

## Live autonomous stage identity (AF-GC-041)

A child job's implementation authorization is not reused as the identity of its
validation, proxy review or policy stages. Each live stage now requires its own
enabled configured agent, exact approved provider/role/model and a permission set
within the parent grant. The selected model must have a qualified CLI request
binding. Missing role grants, remote providers outside the local grant, unknown
models and added permissions stop before invocation; no fallback grants access.
Existing missions that approved only `Developer` must explicitly authorize their
other stage roles before live execution. This change does not broaden shipped
provider role allowlists or qualify real model quality (AF-GC-042 remains separate).

Migration 72 adds immutable per-child/per-stage assignments with the original agent
configuration, effective model, authorization decision and binding digest. Replay,
resume and worker replacement reuse the assignment and recheck current parent
authority. They cannot silently change instructions, identity, model or permissions.
A material change requires an explicit new attempt with compatible authority; old
stage evidence stays attached to the old attempt. Simulation remains deterministic
and is not evidence of independent live inference.

Independent reviewer selection uses the effective producer identities recorded on
artifacts. A replay checks the same reviewer against the same source artifacts and
current eligibility instead of rotating and inserting a second assignment. If the
reviewer is unavailable, disabled, the producer model, or no longer matches the
approved assignment, execution stops before provider spawn. The nonretryable child
configuration failure leaves the existing parent workflow in `NEEDS_ATTENTION` for
an operator decision; it does not manufacture a passing verdict or retry paid work.
The operator must reconcile the stopped attempt through the existing mission
control/retry process. This is not an automatic provider replacement mechanism.

`tests/test_autonomous_stage_identity.py` uses four distinct model arguments sent to
real local Python stub processes, checks replay and revocation, and verifies denied
review/model bindings through the actual stage entry point with zero provider
spawns. It does not call paid providers or certify a real autonomous game delivery.
