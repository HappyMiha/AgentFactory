# Deterministic validator runner

AF-052 executes project validation from reviewed packs rather than accepting a shell command from a worker. Every pack must declare exactly five fixed argument vectors: `test`, `lint`, `type_check`, `build`, and `security_scan`. Shell strings, missing categories, empty arguments, and NUL-containing values are rejected before execution.

The runner verifies the live fenced assignment, logical attempt, and AF-048 worktree, then executes each allowlisted vector through the AF-017 sandbox with `shell=False`, denied network, bounded time, and combined output limits. The working directory is always the candidate worktree; the main checkout is never a validator target.

Each immutable result binds the task, attempt, worktree, candidate and pack digests, category, canonical command and command digest, exit state, bounded stdout/stderr, non-secret environment metadata, evidence directory, and one or more exact work-item acceptance criteria. A suite passes only when every category succeeds.

Validators are evidence producers, not implementation workers. If a command leaves any candidate file changed, its effective validation status is failed even when the process exits zero.

AF-020 consumes the exact immutable validator set before invoking an independent reviewer. Every required acceptance criterion must be covered by at least one mapped primary result; a green but unmapped criterion blocks review and acceptance.

The packaged `python-unittest` pack is a reviewed default and can be replaced by a project-owned JSON pack with the same typed contract. Pack presence declares available commands; execution still requires a live fenced candidate and a qualified sandbox backend.
