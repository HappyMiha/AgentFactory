# Execution Context Packages

AF-055 gives every Worker Runtime dispatch a content-addressed context snapshot. AF-015 adds the full role/purpose broker, provenance and freshness enforcement, and governed semantic compaction. The Control Plane builds the package before launch and binds it to the task, durable workflow run, live assignment, and fencing token. A runtime refuses content whose canonical SHA-256 does not match the stored package digest.

The versioned package contains the task description and inputs, acceptance criteria, expected outputs, dependency snapshots, approved base SHA, effective policies, permissions, budgets, relevant requirements, and previous decisions. Optional material is represented as a `ContextSource` with a stable source ID, kind, authority, priority, content digest, and optional supersession links.

The source manifest always distinguishes:

- `included`: source IDs whose content is present;
- `excluded`: source IDs and digests omitted by the bounded compactor;
- `superseded`: obsolete source IDs and the source that replaced each one.

Compaction is deterministic. Active sources are considered by descending priority and then source ID. A source is included only if the canonical package remains within both configured UTF-8 byte and deterministic token-estimate limits. Mandatory task, dependency, base, policy, scope, and manifest content is never silently truncated; package construction fails closed if that core cannot fit.

Broker sources additionally retain provenance, observation time, and an optional maximum age. Stale optional sources are explicitly excluded with reason `stale`; stale mandatory sources fail closed. Active authoritative requirements and safety constraints are always required, regardless of priority, and package creation fails if they cannot fit the configured byte/token ceiling.

Raw transcript compaction is a separate immutable operation. The transcript content is removed and represented only by a SHA-256 digest and removed byte count. The compacted source must retain non-empty decisions, unresolved risks, evidence references, and next-step state. Each broker dispatch binds the resulting package digest to an exact task, run, assignment, role, and purpose while preserving included, excluded, and superseded source outcomes.

The canonical JSON, digest, scope, byte/token counts, and compaction result are immutable in SQLite. Runtime session rows retain the exact package ID and digest, while their request envelope contains only the digest rather than duplicating package content.
