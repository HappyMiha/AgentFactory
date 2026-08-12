# Factory Blueprints

AF-013 makes the operating design a mandatory immutable Control Plane artifact. A Blueprint can be created only from an AF-009 intake whose latest verdict is `READY_FOR_BLUEPRINT` and a ready AF-012 composition bound to `intake:<intake-id>`.

Every version contains non-empty `modules`, `workforce`, `tools`, `context`, `verification`, `budgets`, `policies`, and `recovery` sections. The workforce section receives its exact composition ID and SHA-256 digest from the Control Plane rather than caller input.

## Decision trace

Each decision names one required section, supplies a rationale, and cites known mission sources. Collectively the decisions must cover all eight sections, every active authoritative source, every mission risk, every declared assumption, and every rejected alternative. Unknown references, missing coverage, empty required sections, a non-ready intake, or a blocked/foreign workforce fail before a Blueprint record exists. Canonically ordered trace content gives the version a stable SHA-256 digest.

## Approval and execution

Creating a Blueprint does not authorize execution. The signer must exactly match the intake's named human mission owner, use `mission_owner` authority, and sign the exact latest version and digest with a review note. Rejected, missing, stale-version, or digest-mismatched decisions cannot create an execution authorization. Successful authorization is immutable and idempotent.

## Amendments

Only the human mission owner can amend the latest version. An amendment must identify exactly every changed section and describe execution effect, migration plan, and risk changes. It creates a new immutable version with a parent link and new digest; all prior approvals and execution history remain unchanged. The new version is independently blocked until the owner signs its exact digest, and the superseded version cannot authorize new execution.
