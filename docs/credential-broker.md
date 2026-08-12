# Scoped credential broker

AF-019 issues short-lived credential leases bound to exactly one tenant, mission, AF-018 tool, sorted operation set, sensitive environment key, and expiration time. A requested operation outside the mission's pre-approved set requires attributable human system-owner approval.

Credential values exist only in the broker's process-memory vault. SQLite stores an opaque random handle and non-secret scope, never the value or a value-derived hash. The handle and value are forbidden in prompts and tool arguments. At exact-scope use, the executor receives one temporary environment mapping; recursive sanitization replaces value or handle echoes in strings, nested output, and exceptions before immutable evidence or audit records are written.

Expiration changes lifecycle state, removes the in-memory value, and blocks use. Explicit revocation is idempotent, removes the value immediately, records actor/reason and exact non-secret scope, and causes every later attempt to be denied and audited. Scope mismatch never calls the executor.
