# Audited coordination patterns

AF-023 turns multi-agent coordination into bounded workflow state. Agents do not exchange authoritative free-form messages: every contribution enters an immutable typed ledger before arbitration can use it.

## Pattern contract

Each versioned manifest fixes:

- participants, roles, and model identities;
- a reviewer pool using least-used rotation that excludes both producer agent and producer model;
- explicit independence constraints;
- maximum turns, tokens, and cost;
- one deterministic arbitration strategy and terminal rule;
- evidence keys required on every contribution.

The supported mappings are parallel/ranked choice, generator-critic/critic acceptance, quorum/majority, debate/independent judge, tournament/deterministic bracket, and red-blue/blue resolution.

## Execution and evidence

Proposals, critiques, votes, arguments, verdicts, attacks, defenses, and scores are JSON-typed, content-addressed records with participant/model/role, usage, required evidence, and dissent. Critiques and verdicts require the exact persisted model-aware reviewer selection. Missing evidence or a reviewer collision fails closed.

Arbitration stores the ordered contribution identities, outcome, strategy, and every non-empty dissent statement. Replaying a completed run returns the same immutable arbitration. Turn, token, or cost overflow terminates the run before the excess contribution can enter the ledger.
