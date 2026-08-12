# Mission bootstrap

AF-014 instantiates the latest exactly authorized Factory Blueprint into runnable local mission state. The Blueprint ID, version, digest, and AF-013 execution authorization are independently reconstructed before any resource is created.

An exact request creates one project, one root work item, one version-pinned durable workflow run and stage graph, one active queue claim, and exactly seven immutable manifests: agent, role, tool, policy, context, budget, and environment. An initial checkpoint binds all resource IDs, the Blueprint and workflow digests, and every pending stage. Replaying the same Blueprint digest and request returns the existing mission; a different request cannot reuse that digest.

## Rollback and retry

Every attempt first records an immutable resource-count rollback point. Project, task, graph, manifests, mission, and checkpoint are then created in one immediate transaction. Any validation, storage, or injected resource failure rolls the whole unit back. A separate immutable failed outcome lists compensated resource classes, expected and restored states, and a verification flag. Retry receives a fresh rollback point and can succeed without inheriting partial resources from the failed attempt.
