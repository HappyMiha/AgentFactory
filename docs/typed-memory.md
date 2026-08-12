# Typed memory and governed skills

AF-016 stores durable memory as immutable typed records. Every write declares store and memory type, tenant/mission/task scope, purpose, authority, source and digest, confidence, validity interval, invalidation conditions, content, and content digest.

The eight stores remain separately queryable and enforce distinct write types: working (`decision`, `context`), semantic (`fact`, `decision`), episodic (`outcome`), procedural (`procedure`), entity (`entity`), contextual (`context`), preference (`preference`), and raw history (`raw_event`). Working memory requires task scope; raw history retains raw authority.

Retrieval requires an exact tenant, mission, purpose, allowed store set, minimum authority, current validity time, and a maximum of 1–50 results. Optional task scope cannot expose another task's scoped memory. Each returned record can append an immutable consumer link to the Blueprint, context package, task, or other caller.

Invalidation must match a condition declared at write time and records reason, actor, and optional replacement. The original entry, source provenance, digest, and every historical consumer remain intact; only future retrieval excludes it.

Generated reusable skills start as immutable semantic versions in `draft`. Approval requires a curator or human review with a versioned passing test suite, passed security review, positive representative case count, and evaluation score meeting its declared threshold. Lifecycle transitions are audited and bounded to draft → approved → deprecated → revoked, with direct revocation also supported.
