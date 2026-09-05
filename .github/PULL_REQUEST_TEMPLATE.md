## Outcome

Task: `core:AF-GC-...` or `cloud:AF-CLD-...`

Worker: `HappyDucky02` / `HappySnowman` / `HappyHahahaker`

Claim branch and declared scopes:

Merged prerequisites and upstream commit evidence:

Reviewer worker and downstream impact:

Describe the operator-visible result and why it matters.

## Scope

- Included:
- Explicitly excluded:

## Evidence

- Tests:
- Manual checks:
- Artifacts or screenshots:

## Approval and trust-boundary impact

Explain any change to provider execution, external mutations, credentials, process isolation, approval gates, or audit records. Write `None` when there is no impact.

## Compatibility and migration

Describe configuration, database, CLI, package, or Docker compatibility. Released migrations must never be rewritten.

## Checklist

- [ ] The change is focused and project-neutral.
- [ ] Tests cover success and denial or failure paths.
- [ ] Documentation and examples match the implemented CLI.
- [ ] No credentials, personal data, private content, local absolute paths, or runtime databases are included.
- [ ] Simulation and dry-run remain the default where applicable.
- [ ] Provider execution and final acceptance remain separate decisions.
- [ ] New external mutations are narrowly allowlisted and idempotent.
- [ ] Package and Docker checks pass when relevant.
- [ ] Alpha limitations are documented honestly.
