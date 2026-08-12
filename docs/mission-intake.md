# Mission intake and readiness

AF-009 is the fail-closed boundary between a free-form mission and Factory Blueprint generation. `MissionIntakeService` stores a normalized, content-addressed intake and emits one of four allowed verdicts:

- `READY_FOR_BLUEPRINT`
- `NEEDS_CLARIFICATION`
- `NEEDS_HUMAN_REVIEW`
- `INFEASIBLE`

Every assessment contains a versioned machine-readable rationale, ordered blocking gaps, and a `can_proceed` flag. Identical assessments replay the existing immutable record rather than creating duplicate review work.

## Source authority

Every source requires a stable key, subject, authority (`authoritative`, `advisory`, or `reference`), version, provenance, and content. The database retains its SHA-256 content digest and classifies the source as `clear`, `conflicted`, or `superseded`. Two active authoritative sources on the same subject with different content are both conflicted and produce a clarification gap.

## Blocking behavior

Ambiguities and authoritative-source conflicts create clarification requests. High-risk findings create risk-review requests. Infeasible constraints and proposed materially reduced scope create scope-review requests. No such assessment can report `READY_FOR_BLUEPRINT`.

Resolutions are immutable and must target a current blocking gap. The actor must exactly match the intake's named human mission owner and use the `mission_owner` authority. A reduced-scope proposal additionally requires explicit acceptance; a failed or unauthorized resolution attempt does not mutate readiness state. Reassessment retains the complete sequence of decisions and review requests in the audit event stream.
