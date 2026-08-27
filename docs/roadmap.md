# N0DRA roadmap

This is the working roadmap. It stays intentionally small: finish one useful operator loop, prove it on a real repository, then decide what deserves to exist next.

The importable version is [`examples/backlog.json`](../examples/backlog.json). The older AF-001–AF-057 manifest remains a historical implementation ledger.

## Now — make the handoff obvious

- Show `Gemini 3.1 Pro → Claude Sonnet 5 → Codex` wherever an operator chooses or inspects a coding worker.
- Distinguish quota exhaustion from ordinary provider failure. Only the first condition advances the coding line.
- Keep the chosen provider, reason, and budget visible in the run evidence.
- Finish the compact retro control room without hiding dangerous actions behind style.

Done means a new operator can explain who is coding, why that model was selected, and what will happen if its quota ends.

## Next — prove the relay

- Add deterministic tests for each handoff and for the “do not fail over” paths.
- Exercise pause, restart, and recovery while a coding attempt is in progress.
- Produce one readable run report containing the task, route, diff, checks, reviews, budget, and final human decision.

Done means every branch of the relay can be reproduced without spending real tokens.

## Then — run one real repository

- Choose a small repository and a task with unambiguous acceptance criteria.
- Let Gemini implement it inside a leased worktree.
- Review the diff, validations, independent verdicts, and token accounting.
- Record rough edges in the operator guide before adding new machinery.

Done means a person can complete the mission from a clean checkout using only documented steps.

## Deliberate non-goals

- AI workers creating more AI workers or slicing off unapproved tasks.
- Parallel coding models competing on the same task by default.
- Silent fallback after ordinary errors.
- Automatic merge, release, or GitHub mutation.
- A hosted multi-tenant platform before the local tool is pleasant and dependable.

If a proposed feature does not make the local run clearer, safer, or easier to recover, it waits.
