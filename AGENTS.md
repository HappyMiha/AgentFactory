# Three-computer development rules

Read [docs/team-workflow.md](docs/team-workflow.md) before changing files. These rules apply to Core and Cloud coordination work as well as product code.

- Worker IDs are `HappyDucky02`, `HappySnowman` (Ubuntu), and `HappyHahahaker` (Windows 11). Read `git config --local --get team.worker` to identify this clone. Do not infer the worker from a copied conversation or this shared file.
- Inspect `python scripts/team.py status` and `ready`. Claim a dependency-ready task through `start` before implementation. The shared authority is Core's `team-state` branch, not a stale local backlog or chat message.
- Work only on your registered task branch. Registry version 1 creates `team/<worker>/...`; after coordinated version 2 activation, new claims use `agent/<worker>/<TASK-ID>-<8hex>`. Preserve existing branches and tokens. Read `docs/team-migration.md` before cutover. Never push directly to `main`, another worker's branch, tags, or a deletion. Never force-push or bypass hooks.
- Core `team-state` is the only claim authority. AgentFactoryBus is message/status transport, not a second queue of independently claimable tasks. A heartbeat alone never starts AI execution or transfers ownership.
- Declare every changed path and relevant shared resource. Respect existing claims. Do not take a differently named task to duplicate a claimed capability in the other repository.
- A paused computer does not lose ownership automatically. Block or release through the tool when stopping; inspect preserved branches before any explicit reassignment.
- Before each push, fetch and incorporate current `main`, inspect the diff, and run `python scripts/team_checks.py`. The pre-push hook requires checks for the exact commit. Report the actual test scope and failures.
- Keep one focused PR per task. Record it through `review`. Merge prerequisite PRs first, check current CI and ownership, then use `complete` after the recorded PR merges. Pushing is not completion or product acceptance.
- HappyDucky02 coordinates merges initially. The other computers can develop independent tasks and review. Do not merge an unrelated worker's PR without the agreed integration decision.
- The public task register contains only coordination metadata. Keep secrets, private briefs, machine paths, and detailed private evidence out of it.
- Keep generic engine/agent capabilities in Core and product integration in Cloud. Preserve stable backlog IDs and product acceptance gates.

The initial coordination installation uses the two explicit `TEAM-SETUP` maintenance claims. It introduces tooling and rules only; it does not implement a game or Cloud product task.
