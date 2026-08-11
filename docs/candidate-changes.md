# Candidate changes and PR plans

AF-051 turns a successful writable-worker result into an immutable, validated Git candidate. Creation requires all five AF-052 categories to have succeeded for the exact worker diff digest and logical attempt. Missing, failed, or candidate-mutating validation fails before commit or PR-ready state.

The Control Plane stages only the changed files declared by the AF-049 result and commits them on the deterministic AF-048 task branch. The message must start with a stable `AF-NNN` task ID. Before and after the commit, the repository's checked-out base branch and SHA are compared; the base ref must not move.

The artifact records base/head SHA, branch, worktree identity, diff digest, changed files, commit message, worker result, and a digest of validator evidence. A pull request remains a dry-run immutable GitHub operation with its own pending one-use gate. No push or PR creation occurs while the gate is pending.
