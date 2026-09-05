# Human Control Plane

AF-030 adds `HumanControlPlaneService` for authenticated, tenant-scoped human actions. Mission owners, operations owners, and security reviewers have explicit action allowlists; workers and agents cannot approve, release, or impersonate a human. Approve/reject, pause/resume/cancel, recompose, release, emergency-stop, enable/drain/quarantine/replace, and irreversible retire actions are persisted as immutable audit records. Retirement requires an explicit irreversible confirmation payload.

The existing dashboard remains the presentation layer over shared application services. Evidence, provenance, dissent, cost, policy, leases, incidents, and action history are read from the same durable state and never require direct database access. Accessibility remains governed by the existing keyboard/screen-reader checklist and end-to-end tests.

The production HTTP surface is `/api/control/actions`. The shared [local API access policy](local-api-access.md) protects all API reads and mutations with the configured bearer credential or short-lived browser session. The server binds actor, role and tenant scope; command JSON must match them. Mutations require explicit confirmation and use the same service and audit path as non-HTTP callers. Reads require an explicit authorized `tenant_id` scope.
