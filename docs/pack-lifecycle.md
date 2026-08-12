# Signed pack SDK and lifecycle

AF-024 provides data-driven extension contracts for domain, capability, connector, policy, evaluation, and UI packs without editing Agent Factory core.

Every manifest declares identity, semantic version, core compatibility interval, permissions, dependencies, migrations, evaluation tests, and HMAC-SHA-256 signature metadata. The signature covers canonical manifest and payload content. Signing material stays in process memory; SQLite retains only the fingerprint and approval of a named human administrator.

Install and upgrade fail before activation when the signature or trust root is invalid, the core version is outside the declared interval, payload permissions exceed the manifest, dependencies are missing/inactive, or qualification results are incomplete or failing. Mutation, network, or credential permissions additionally require the lifecycle actor to hold the `human_administrator` role.

Pack versions, qualifications, and lifecycle events are immutable. The installation row is only a versioned active pointer and enabled/disabled state. Upgrade links to the previous working version; rollback restores that pointer and records the transition without deleting either version, changing source files, or discarding mission history.
