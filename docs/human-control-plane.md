# Human Control Plane

AF-030 adds `HumanControlPlaneService` for authenticated, tenant-scoped human actions. Mission owners, operations owners, and security reviewers have explicit action allowlists; workers and agents cannot approve, release, or impersonate a human. Approve/reject, pause/resume/cancel, recompose, release, emergency-stop, enable/drain/quarantine/replace, and irreversible retire actions are persisted as immutable audit records. Retirement requires an explicit irreversible confirmation payload.

The existing dashboard remains the presentation layer over shared application services. Evidence, provenance, dissent, cost, policy, leases, incidents, and action history are read from the same durable state and never require direct database access. Accessibility remains governed by the existing keyboard/screen-reader checklist and end-to-end tests.

The production HTTP surface is `/api/control/actions`. When `AGENT_FACTORY_API_TOKEN` is configured, reads and mutations require `Authorization: Bearer <token>`; mutations use the same service and audit path as non-HTTP callers, and reads require an explicit `tenant_id` scope.
