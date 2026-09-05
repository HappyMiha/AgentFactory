# Working from three computers

The team uses the same two repositories and one shared task register.

| Worker ID | Computer | Starting responsibility |
| --- | --- | --- |
| `HappyDucky02` | This workstation | Coordination and integration; then a ready Core or Cloud task |
| `HappySnowman` | Ubuntu PC | Linux and cross-platform checks are a good first area |
| `HappyHahahaker` | Windows 11 PC | Windows and interface checks are a good first area |

These are worker names, not separate GitHub identities. All three may use the same GitHub account. Configure the correct worker name on each clone. Never share provider keys, GitHub tokens, or local authentication folders through Git.

## One place to see current work

The live register is [`team-state.json` on Core's `team-state` branch](https://github.com/HappyMiha/AgentFactory/blob/team-state/team-state.json). It covers both Core and Cloud. Keep this branch separate from application `main`; never merge its contents into application branches.

The register records task ID, dependencies, worker, branch, declared paths, shared resources, state, PR, and an event history. It contains coordination metadata only. Do not put private source, product briefs, personal data, server addresses, credentials, or detailed incident reports in the public register. Put detailed evidence in the relevant repository's PR.

The catalogue starts with 42 `core:AF-GC-*` tasks and 67 `cloud:AF-CLD-*` tasks. Two `TEAM-SETUP` maintenance records track this coordination setup. Historical AF and AF-AMM requirements remain references; do not invent a claim under another ID to bypass the active catalogue.

Use the tool instead of editing the register by hand. A claim is a small commit pushed normally to `team-state`. If two computers race, only one update can fast-forward. The loser reloads the winning state and checks the rules again. A failed or uncertain claim is not permission to start work.

## Set up each clone once

Install Git, Python 3.11 or newer, and GitHub CLI, then sign in with `gh auth login`. Use your own supported authentication flow; never paste credentials into task notes.

On Ubuntu, use `python3` below. On Windows, use `python` with the chosen Python environment.

```bash
git clone https://github.com/HappyMiha/AgentFactory.git
cd AgentFactory
python scripts/team.py configure --worker HappySnowman
python scripts/team.py status
python scripts/team.py ready
```

Use `HappyHahahaker` on the other Windows PC and `HappyDucky02` on this workstation. Repeat configuration in the Cloud clone:

```bash
git clone https://github.com/HappyMiha/AgentFactory-Cloud.git
cd AgentFactory-Cloud
python scripts/team.py configure --worker HappySnowman
```

Configuration is local to the clone. It installs the repository's pre-push hook through `core.hooksPath`; Git does not activate hooks just because a repository was cloned. An existing custom hook configuration must be reviewed instead of silently overwritten. Run `git config --local --get team.worker` and `git config --local --get core.hooksPath` to inspect it.

The tooling needs GitHub access on every PC. This setup does not remotely install anything or log in on the other two computers.

## Choose and claim a task

Always read `AGENTS.md`, run `ready`, and inspect `status` before starting. `ready` considers dependencies and current claims. Also inspect nearby work and shared contracts; a task can be technically ready but still need an interface discussion.

```bash
python scripts/team.py ready
python scripts/team.py status
python scripts/team.py start core:AF-GC-003 --worker HappyHahahaker --scope core:src/agent_factory/static/app.js --scope core:tests/test_monitor_web.py
```

Use the actual paths needed by the task. The example is a command shape, not a reservation. The tool combines declared paths with required catalogue scopes and shared-resource locks. If those overlap active work, it rejects the claim. Do not choose false or narrower scopes just to get past a conflict: preflight also checks the changed files.

Registry version 1 uses `team/<worker>/<repo>-<task-id>-<unique-suffix>`. After the [coordinated migration](team-migration.md), version 2 uses `agent/<worker>/<TASK-ID>-<8hex>`, for example `agent/HappyHahahaker/AF-GC-003-12ab34cd`. The suffix identifies a claim attempt; the stable backlog ID stays unchanged. A new claim gets a new identity and branch; released branch names are not reused. Existing `team/...` claims keep their branches and tokens. Start from the latest fetched `main` in a clean clone. `start` selects the format from the live registry, claims the task and creates its branch. If a local branch step fails, inspect the register and resolve the claim before trying again.

One task has one owner and one branch. Keep branches focused. Do not commit to another worker's branch or use a task's branch for unrelated work. Multiple independent tasks can run at once when they have different scopes and no unmet dependency.

Before another task needs a new shared contract, merge a small contract change first. Downstream work can then use the accepted interface while the larger feature continues in a separate task. Do not weaken dependencies just to start earlier.

If the task needs another file, use `rescope` with the full intended scope before editing it. The tool checks the new paths against other active claims atomically and keeps the current branch. Do not silently expand into another worker's files.

```bash
python scripts/team.py rescope core:AF-GC-003 --worker HappyHahahaker --scope core:src/agent_factory/static/app.js --scope core:tests/test_dialog_confirmation.py
```

The tool stores the claim token in local Git configuration. Lifecycle changes must match the current token; an old process cannot release or complete a newer claim merely by using the same worker name. Keep a task in its owning clone and do not copy local claim tokens between unrelated tasks.

## Check before every push

Commit the focused change, fetch the current target, and merge the new `main` into your own branch when needed. Do not rebase a published shared branch or force-push.

```bash
git fetch origin main
git merge origin/main
python scripts/team_checks.py
git push -u origin HEAD
```

The check command records results for the exact commit, tree, base, and changed paths inside the local Git directory. It does not commit machine-specific evidence. A new commit, dirty file, or changed base invalidates the record. Run checks again after updating the branch.

For a focused Core change, `team_checks.py --test <test_module>` can run relevant tests instead of the full suite. Repeat `--test` for more modules. Select tests that actually exercise the changed behavior and state the scope in the PR. The record distinguishes selected tests from the full suite. Existing CI still runs its own broader checks; a known baseline failure is not evidence that a new regression is acceptable.

The pre-push hook checks task ownership, dependencies, declared paths, branch identity, current `main`, and the exact checked commit. It rejects deletion, tags, multiple refs, non-fast-forward updates, direct `main` pushes, and another worker's branch. It then verifies the local check record.

Never use `--force`, `--force-with-lease`, `--no-verify`, or a changed hooks path to get around these checks. Fetch and resolve the reason instead. A protected push is a final check, not a substitute for reading the diff.

## Review, merge, and release ownership

Open a pull request to `main` in the repository that owns the change. Include the qualified task ID, worker, scopes, dependencies, what changed, tests, known failures, and any downstream impact. PR creation is separate from authorizing contact through email or chat.

```bash
python scripts/team.py review core:AF-GC-003 --worker HappyHahahaker --pr https://github.com/HappyMiha/AgentFactory/pull/NUMBER
```

Review keeps the task and scopes reserved. A pushed branch is not a completed dependency. If the PR changes, rerun checks and update the review record for the new head commit.

HappyDucky02 coordinates merges initially. Another worker reviews the diff and relevant evidence. Worker names do not create separate GitHub review identities, so a same-account team must record who reviewed in the PR instead of pretending GitHub supplied an independent account approval.

Before merging, fetch the latest `main`, update and retest the branch when needed, check live task ownership and prerequisite completion, and inspect CI for the exact head. Merge prerequisite PRs first. For changes in both repositories, merge and record the upstream Core result, then update and test the Cloud consumer against that commit. Do not mark both tasks done merely because one PR merged.

```bash
python scripts/team.py complete core:AF-GC-003 --worker HappyHahahaker --pr https://github.com/HappyMiha/AgentFactory/pull/NUMBER
```

Completion requires the recorded PR to be merged into the right `main` with the expected branch and reviewed head. It releases the claim. The task register tracks merged engineering work; product acceptance still needs the evidence and owner decision required by the original backlog. A merged planning document does not certify a game, deployment, or release gate.

## When work stops or conflicts

Use `heartbeat` to record continuing work. There is no automatic expiry or takeover: a quiet computer may still have valid work that another computer must not overwrite.

```bash
python scripts/team.py heartbeat core:AF-GC-003 --worker HappyHahahaker
python scripts/team.py block core:AF-GC-003 --worker HappyHahahaker --note "Waiting for a reviewed interface; details are in the PR."
python scripts/team.py release core:AF-GC-003 --worker HappyHahahaker --note "Stopped before implementation; branch preserved."
```

Blocking or releasing keeps history and frees active scopes according to the state rules. The old worker must stop editing and pushing that task. Release never deletes a branch or someone else's files. Reclaim only after rereading the latest state; preserve the earlier branch and coordinate any useful unmerged changes.

A broken or unreachable computer needs an explicit reassignment decision after its branch and PR are inspected. Do not invent a heartbeat, impersonate the old worker, or treat elapsed time as consent. Pick another ready task while ownership is unresolved.

If another task is blocking yours, record the exact dependency and expected interface. Avoid reserving broad directories for weeks. Split the smallest shared prerequisite, finish it first, and then take the independent work.

## First parallel batch

These are suggestions, not preclaimed work:

| Worker | Suggested first task | Reason |
| --- | --- | --- |
| HappySnowman | `core:AF-GC-001` | Reproduce and repair cross-platform CI checks on Ubuntu |
| HappyHahahaker | `core:AF-GC-003` | Verify and fix the Windows/browser confirmation flow |
| HappyDucky02 | `core:AF-GC-006` | Verify that selected and effective models match |

Check the live register before following this table. CI/test scopes can overlap even when source files differ. Do not work on `003` and `004` together if both change `app.js`; do not combine separate claims that edit the same provider defaults or web route. Resolve overlap by scope, a small prerequisite, or a different ready task.

The original backlog order and IDs remain intact. The shared catalogue adds cross-repository prerequisites and resource conflicts; `ready` provides a practical work queue. These coordination constraints can be refined with review as implementation reveals exact paths. They do not silently rewrite product acceptance criteria.

## AgentFactoryBus and continued work

Core `team-state` remains the sole atomic claim authority for both repositories.
The bus carries immutable messages, review requests, results and availability.
It never grants a second task claim, bypasses Git checks, or executes message text.
Do not mirror a claimed Git task into a separately claimable bus queue.

Use `ready` to prioritize prerequisite-complete tasks, then inspect actual scope
conflicts with `status` and `start`. The queue sorts earlier milestones and
priorities first, then tasks that unlock more direct dependants. Scope hints are
planning aids, not reservations: declare the actual paths before work. If an
upstream contract is still missing, choose independent work instead of weakening
dependencies or occupying a broad directory. Record a newly discovered shared
prerequisite through reviewed catalogue maintenance with stable task IDs.

An active coding session can continue the claim, implement, test, push and review
cycle within the owner's authorization. An idle heartbeat watcher only reports
availability and receives messages. Automatic model execution requires a separate
verified local runner with bounded scope and stop/recovery behavior; this migration
does not launch one. Never enable arbitrary shell execution from bus messages.

## Enforcement and limits

Core can use server-side branch protection: PRs into `main`, current required coordination checks, and no force pushes or deletion. `team-state` accepts normal fast-forward tool updates and rejects destructive changes.

The owner has made Cloud public, allowing the same server-side protection there. Both repositories remain separate; making Cloud public does not choose a new software license or make every future commercial component open source. The shared register, required checks, and integration-owner rule apply to both.

Do not claim the scripts provide an adversarial security boundary between people using one GitHub account. They prevent accidental collisions when the agreed workflow is followed, and make ownership and changes visible.
