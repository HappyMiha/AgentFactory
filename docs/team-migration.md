# Three-PC coordination migration

Maintenance tasks: `core:AF-TEAM-001` and `cloud:AF-TEAM-001`.
Decision: Core's Git `team-state` branch remains the only claim authority for
both repositories. AgentFactoryBus carries messages, status and review evidence.
Source stays in local clones. There is no independently claimable bus task queue.

## Rollout order

1. Keep new automatic tasks paused. Finish or preserve each current task branch,
   PR and claim token. Do not rename active `team/...` branches.
2. Review and merge Core's migration PR, then complete its owning maintenance
   claim. It installs readers that accept registry versions 1 and 2. The live
   registry stays at version 1, so new claims still use `team/...` during rollout.
3. Claim, review, merge and complete Cloud's dependent migration task. Copy the
   reviewed neutral coordination tooling and tests; update Cloud's CI branch
   parser and instructions. Both repositories must be deployed before cutover.
4. Every worker updates both local owning clones from `main`, including any
   retained working branch. Use normal merges and rerun checks after changes.
   Confirm the correct local `team.worker` and existing hooks. Do not copy claim
   tokens between clones or replace files by hand to imitate an update.
5. In one clean updated repository, run the command below with the local path
   to the other clean updated repository. Repeat on each of the three PCs.
6. HappyDucky02 activates version 2 only after all three acknowledgements match
   the reviewed Core and Cloud migration commits. Then verify `status` and `ready`
   from both repositories on every PC before starting the first parallel batch.

```sh
python scripts/team.py migration-ack --peer-repo /path/to/other/repository
```

On Ubuntu use `python3`. The command reads this clone's worker identity; both
clones must have the same worker. It verifies clean worktrees, ancestry of the
merged migration commit in both local HEAD and current remote main, and exact
reviewed Git blobs for `scripts/team.py` and `.github/workflows/team-policy.yml`.
It records only the worker, public commit/blob IDs and time, never machine paths.
Run it from the clones you will actually use; update any additional retained
clone before reusing it. The tool cannot inventory disconnected personal clones.

The coordinator then runs:

```sh
python scripts/team.py migration-activate
python scripts/team.py status
python scripts/team.py ready
```

Activation is a normal atomic registry transaction. It requires both maintenance
tasks to be completed and matching current proofs from HappyDucky02, HappySnowman
and HappyHahahaker. No branch, task owner, claim token or prior event is rewritten.
Version 2 makes old readers fail closed at their next registry fetch, even before
the first new branch exists. A stale writer losing a push race must reload the
new version and cannot treat its rejected claim as ownership.

## Branches and failure recovery

New branches use `agent/<worker>/<TASK-ID>-<8hex>`. For example,
`agent/HappySnowman/AF-GC-005-12ab34cd`. The stable task ID is unchanged; the suffix
distinguishes attempts. Do not reuse a released branch. Existing `team/...`
branches remain valid only when they have their exact active registry claim.
New version 2 claims cannot request a legacy branch. Both local hooks and CI
still check owner, dependencies, scopes, fresh main and the exact checked commit.

If a reader is outdated or an acknowledgement fails, update the affected clone
and verify again. If a node becomes unreachable, pause new work; do not downgrade
the registry or transfer its tasks automatically. Preserve its branch and inspect
the claim before any explicit reassignment. A failed branch-creation step follows
the existing token-fenced release path; an uncertain registry update must be
inspected before retrying. No force push, lock deletion or hook bypass is needed.

## Verification limits

Tests use real local Git remotes for concurrent claim collisions, old/new branch
rules, preserved legacy claims, stale tokens, exact reader blobs and rejected
incomplete cutover. A worker acknowledgement is cooperative evidence under the
shared GitHub account, not cryptographic proof of a distinct human identity.
Cutover enables compatible task coordination; it does not start a background AI
executor, prove a game works, or bypass product acceptance gates.
