# Mission epoch branches and worktrees

`WorktreeManager` is the single AgentFactory authority for standard task worktrees
and Autonomous Mission epoch worktrees. Epoch provisioning is additive: the
standard `agent-factory/task-<task>/lease-<token>` contract and its retention flow
are unchanged.

## Deterministic identity

An epoch branch is:

```text
autonomous/<normalized-mission-key>/epoch-<number>
```

Safe existing mission keys remain readable, for example
`autonomous/AFM-PAYMENTS/epoch-2`. A key that contains separators, Unicode that
requires transliteration, a reserved Git suffix, or more than 64 characters is
converted to an ASCII component with a 12-character SHA-256 suffix. The suffix
prevents two distinct unsafe keys from collapsing onto the same branch or path.

The worktree is rooted below the configured managed-worktree root:

```text
.agent-factory/worktrees/autonomous/<normalized-mission-key>/epoch-<number>
```

Repository, branch, and path comparison keys are persisted with unique
constraints. The resolved repository and worktree must stay inside the configured
workspace, and the repository must equal the path bound to the mission.

## Durable authority before mutation

`reserve_epoch()` validates the immutable epoch, exact base commit, deterministic
branch, repository, and (for epoch 2+) the content-addressed base checkpoint. It
then commits one immutable `autonomous_epoch_worktrees` row and the first
`RESERVED` event. Only after that transaction commits may `provision_epoch()` run
`git worktree add`.

Every observation is append-only in `autonomous_epoch_worktree_events`:

- `RESERVED`: identity and pre-mutation Git state were persisted;
- `PROVISIONING`: the exact `git worktree add` intent may execute;
- `READY`: path, branch, HEAD, registration, cleanliness, and lineage agree;
- `DIRTY`: the authoritative worktree has uncommitted content;
- `MISSING`: neither the path nor a conflicting worktree registration exists;
- `CONFLICT`: a branch, ref, path, registration, or evidence check differs.

The authority, reservation, and observation documents are canonical JSON with
SHA-256 digests. Authority rows and events cannot be updated or deleted.

## Base and lineage rules

Epoch 1 is created at the exact approved repository base SHA. A later epoch is
created at the exact commit from its verified base checkpoint. A managed epoch
branch may subsequently point at its base or at a clean descendant recorded as an
immutable checkpoint for that same epoch. An uncheckpointed or unrelated head is
reported as `CONFLICT`.

Prior epoch branches and worktrees are preserved. Provisioning never invokes
`reset`, deletes a branch, removes an existing worktree, prunes Git metadata, or
checks out the repository's main worktree. Publishing and protected-branch
mutation remain outside this API.

## Recovery and operator response

`reconcile_epoch()` and `reconcile_epochs()` only inspect Git and append evidence;
they do not repair Git state. A missing clean worktree can be reprovisioned against
its preserved branch. Dirty, divergent, multiply registered, path-occupied, or
indeterminate state fails closed and must be reviewed before another provision
attempt.

Useful checks are:

```powershell
git -C <repository> worktree list --porcelain
git -C <repository> show-ref --verify refs/heads/autonomous/<mission>/epoch-<n>
git -C <epoch-worktree> status --porcelain=v1 --untracked-files=all
```

The real-Git regression matrix is in `tests/test_mission_epoch_worktrees.py`.
It covers two coexisting epochs, a different checkpoint base, mutation kill-point
evidence, divergent refs, dirty and missing paths, recovery, collision-resistant
normalization, and workspace containment. `tests/test_worktrees.py` remains the
compatibility suite for standard task worktrees.
