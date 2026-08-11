# Provider-neutral role definitions

AF-010 stores each role as an immutable semantic version independent of every agent and provider configuration. A role contract includes purpose, responsibilities, typed required or optional inputs, outputs and evidence fields, a sorted tool and permission surface, positive numeric limits, and incompatible duty IDs.

`RoleRegistry` validates object shape and primitive field types at each input, output, and evidence boundary. Re-registering the same version is idempotent only when the SHA-256 contract digest is unchanged; altered content requires a new version.

Workflow requirements bind `workflow_id`, workflow version, stage key, role ID, and role version without naming an agent. Agent selection remains a later routing concern. Per-decision duty assignments are immutable and symmetric: if either role declares the other incompatible, the same agent cannot hold both for that decision. This prevents an implementer from becoming its own final reviewer even if its provider or model changes.
