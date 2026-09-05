# Shared team task register

This branch coordinates HappyDucky02, HappySnowman, and HappyHahahaker across AgentFactory Core and Cloud.

Read [the workflow](https://github.com/HappyMiha/AgentFactory/blob/main/docs/team-workflow.md), then use `python scripts/team.py status`, `ready`, and `start` from an application clone. Do not merge this branch into application main.

The register contains 109 product task IDs and two setup records. Claims use normal fast-forward Git pushes with revalidation after conflicts. Do not force-push, delete this branch, copy secrets into it, or assume a quiet worker lost its claim.

Task ownership and status are in [team-state.json](team-state.json). Git history and the events array retain changes. The initial suggestions are not reservations; check the live register before starting. Product gate acceptance remains separate from a merged engineering task.
