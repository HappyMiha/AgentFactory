# GitHub integration

Agent Factory uses GitHub Issues for work items and GitHub Projects for prioritization fields. Repository content remains the source of truth for code and reviewed documentation.

The integration is deliberately plan-first and dry-run by default.

## Prerequisites

Install [GitHub CLI](https://cli.github.com/), then authenticate:

```bash
gh auth login
gh auth status
```

Verify the intended target and your permission:

```bash
gh repo view OWNER/REPOSITORY --json nameWithOwner,viewerPermission,defaultBranchRef
```

Do not paste authentication output containing token details into an Issue, artifact, or support report.

## Supported operations

The mutation allowlist contains only:

- create an Issue;
- update an Issue title, body, or add labels;
- add an Issue comment;
- set one GitHub Project single-select field.

Automatic merge, close, delete, label removal, and arbitrary Issue state changes are not supported.

## Validate and import locally

```bash
agent-factory backlog validate --path examples/backlog.json
agent-factory backlog import --path examples/backlog.json --project-id 1
```

Validation performs no network I/O. Import writes only to the local orchestration database.

## Create a dry-run plan

```bash
agent-factory backlog sync --path examples/backlog.json --repo OWNER/REPOSITORY
```

This command:

1. normalizes and validates all proposed operations;
2. rejects unsupported actions before any mutation;
3. stores an immutable plan and SHA-256 digest;
4. creates a pending approval gate;
5. prints the exact dry-run commands without executing them.

Record the displayed plan ID, gate ID, repository, and digest. Review the entire operation set rather than only its summary.

## Apply an approved plan

Inspect and decide the exact plan gate:

```bash
agent-factory backlog gates
agent-factory backlog approve 1 --note "Reviewed repository, operations, and SHA-256 digest"
```

Use `backlog reject` when the target, scope, or operation set is wrong. After approval, apply explicitly:

```bash
agent-factory backlog sync --apply --plan-id 1 --gate-id 1
```

The apply path verifies that:

- the gate is approved and unused;
- plan ID, repository, and SHA-256 digest match;
- the authenticated GitHub identity can write to the exact target repository;
- every operation is still in the allowlist.

The gate is consumed by that apply attempt. A partial or failed apply needs a newly reviewed plan and gate for retry.

## Idempotency

Every operation carries a stable idempotency key. Successful keys are persisted for the repository. If a later approved plan contains a completed key, Agent Factory skips it rather than creating a duplicate.

An apply report records each result and an overall status:

- `succeeded`: every outstanding operation succeeded;
- `partial`: at least one operation succeeded and at least one failed;
- `failed`: no requested mutation succeeded.

Idempotency does not make an operation reversible. Review the plan before approval.

## Backlog format

The example file contains a project-neutral hierarchy with stable IDs, dependencies, and acceptance criteria. Stable IDs should remain unchanged even if titles evolve.

Guidelines:

- use globally unique, readable stable IDs within the repository;
- keep parent relationships separate from execution dependencies;
- ensure every dependency names another item in the same import or an explicitly documented external item;
- include at least one measurable acceptance criterion per executable item;
- keep descriptions free of credentials and private personal information;
- use source references only for repository paths or public specifications the reviewer can access.

## GitHub Projects

Project field updates require the node IDs for:

- the project;
- the project item;
- the field;
- the selected option.

These values belong in a reviewed mutation plan, not in runtime-generated provider arguments. Read access is available through GitHub CLI, while updates remain approval-gated.

## Operational recommendations

- Run dry-run sync in CI, but never approve or apply from an untrusted pull request.
- Protect the default branch independently in repository settings.
- Require human review for pull requests produced from Agent Factory artifacts.
- Keep GitHub CLI authentication outside provider prompts.
- Use a least-privilege account or token appropriate to the target repository.
- Back up the local state database before a large apply.
- Preserve partial-failure reports for audit and retry planning.

## Troubleshooting

### `gh` is missing

Install GitHub CLI and open a new terminal so `PATH` is refreshed. `agent-factory env check` should then report it.

### Authentication verification fails

Run `gh auth status`, then `gh repo view OWNER/REPOSITORY`. Confirm the active account has `WRITE`, `MAINTAIN`, or `ADMIN` permission.

### Plan digest mismatch

Do not bypass the check. Generate a new plan from the current backlog, review it, and create a new approval.

### Partial apply

Keep the report. Correct the failing cause, regenerate the plan, confirm completed idempotency keys will be skipped, and approve the new digest.
