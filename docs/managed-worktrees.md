# Managed Git worktrees

`AF-048` makes AgentFactory the sole authority that creates and removes task worktrees. AF-AMM-019 extends that same `WorktreeManager` authority to Autonomous Mission epoch worktrees. A scheduler assignment plus its live fencing token is the task-attempt authority; an immutable execution epoch plus its exact approved/checkpoint base is the epoch authority. Workers and managed Hermes sessions receive resulting paths and never run `git worktree add` themselves.

## Provisioning

Provisioning accepts a repository Git toplevel inside the selected workspace and a full approved commit SHA. The deterministic branch is `agent-factory/task-<task-id>/lease-<fencing-token>` and the deterministic path is `.agent-factory/worktrees/task-<task-id>-lease-<fencing-token>` unless the reviewed policy selects another contained root.

The Control Plane persists immutable `provisioning` metadata before invoking Git: repository, approved base SHA, branch, path, task, assignment, optional attempt, lease, fencing token, and owner. It then executes fixed `git` argument vectors with `shell=False`, verifies the resulting HEAD and branch, and advances the record to `ready`. Replay returns the same record. A restart can reconcile a pre-mutation `provisioning` record to `missing` and safely resume the same branch/path without duplication.

One non-cleaned worktree may belong to an assignment, paths are globally unique, and repository/branch pairs are unique. `assert_owned` revalidates the live lease, durable ownership, directory, and current Git branch before returning a writable path.

## Reconciliation

Startup reconciliation compares durable records, `git worktree list --porcelain`, filesystem directories below the managed root, current branch/HEAD, and porcelain status. It reports and audits:

- clean ready worktrees;
- dirty worktrees, including untracked files;
- missing durable worktrees;
- retained worktrees;
- registered or on-disk paths below the managed root that have no durable record;
- base or branch authority conflicts.

Reconciliation is non-destructive. It never adopts, removes, or rewrites an orphan automatically.

The `autonomous/` subdirectory is a separate managed namespace and is therefore not reported as a standard task orphan. Epoch reconciliation verifies the deterministic branch, registered path, current ref/HEAD, filtered worktree content, and base-or-checkpoint lineage against an append-only authority ledger. See [Mission epoch branches and worktrees](development/mission-epoch-worktrees.md) for the branch policy, statuses, recovery rules, and real-Git fault matrix.

## Retention and cleanup

The default policy retains terminal worktrees for 86,400 seconds. Retention can start only after the assignment is `succeeded`, `failed`, or `cancelled`; cleanup additionally requires the persisted deadline to have elapsed. Cleanup removes the worktree and prunes Git's worktree registry but preserves the deterministic branch and commit history. Candidate evidence must already have crossed the sandbox/evidence boundary before terminal cleanup.
