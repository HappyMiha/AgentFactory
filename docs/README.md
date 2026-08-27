# N0DRA documentation

This directory contains two different things: guides people use while operating N0DRA, and detailed engineering records kept so old decisions remain verifiable. They should not be read in the same way.

## Start here

- [Getting started](getting-started.md) — install, run the offline demo, import a backlog, and approve a result.
- [Ukrainian operator guide](user-guide-uk.md) — the full local workflow in Ukrainian.
- [Local control room](local-control-center.md) — what the browser interface can change and what it cannot.
- [Current roadmap](roadmap.md) — the next useful outcomes, written as a short working plan.

## Run the system

- [Providers](providers.md) — authentication, model pins, and the Gemini → Claude → Codex coding line.
- [Workflows](workflows.md) — stages, evidence, reviews, budgets, and failure behavior.
- [GitHub integration](github-integration.md) — read access, dry-run planning, and guarded apply.
- [Operations](operations.md) — state, backups, recovery, and day-two checks.
- [Temporal development](development/temporal.md) — durable local execution and restart testing.
- [Troubleshooting](troubleshooting.md) and [CI troubleshooting](ci-troubleshooting.md).

## Change the system

- [Architecture](architecture.md) — the shortest useful map of the codebase.
- [Role contracts](role-contracts.md), [workflow contracts](workflow-contracts.md), and [provider contract](provider-contract.md).
- [Configuration](configuration.md), [schema](schema.md), and [testing strategy](testing-strategy.md).
- [Security policy](security-policy.md), [threat model](threat-model.md), and [accessibility checklist](accessibility-checklist.md).

## Historical engineering record

The dated audits, release notes, handover bundles, and the [57-task development ledger](development-roadmap.md) describe how the current foundation was assembled. They are retained as evidence, not presented as the active backlog. The corresponding importable manifest is [`examples/development-backlog.json`](../examples/development-backlog.json).

If you only need to use N0DRA, you can ignore the historical layer.
