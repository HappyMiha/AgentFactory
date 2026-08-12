# Deployment profiles

AF-031 defines four versioned profiles through `DeploymentService`: single-node, clustered, hybrid, and air-gapped. Each profile declares replicas, required services, model path, connector path, update channel, artifact-transfer path, and egress policy. The smoke contract validates every profile and makes air-gapped mode deny all network egress, use local models, disable connectors, and require signed offline bundles plus human-approved media.

Deploy, upgrade, and rollback operations persist immutable continuity evidence. An upgrade or rollback is accepted only when active mission authority, pending approvals, accepted artifacts, and the audit-chain identity are all carried forward. Incomplete evidence is persisted as a blocked attempt and cannot mutate runtime authority. A human operator remains responsible for production deployment, version change, rollback, and air-gap transfer approval.
