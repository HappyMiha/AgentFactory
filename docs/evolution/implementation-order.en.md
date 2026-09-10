<a id="один-порядок-реалізації-lokvetia-core-та-lokiravia"></a>
# One implementation order for Lokvetia Core and Lokiravia


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [implementation-order.md](implementation-order.md). Source SHA-256 (UTF-8/LF): `b434e29d0ae2b90e472f7565fe872d5a56228918a2a4a50786ce2ef43d72ba6d`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](implementation-order.md).

Revision 2026-09-10 · proposed implementation plan, not a report of finished products.

Start with qualified local Core and completion of the existing idea editor. Next build the evidence workbench, end-to-end creator path, and first living scene. Core-on-Core and method recursion have their own gates; the game does not block them. [Exact first-release boundaries](first-releases.en.md) define what the user receives and how it is verified.

<a id="як-користуватися-планом"></a>
## How to use the plan

1. Find the earliest available requirement in the table. The number recommends the next work to select; it does not require independent tasks to execute sequentially.
2. Open its canonical manifest through the source pointer in [JSON](implementation-order.json). Inspect existing code/artifacts and exact evidence. Reuse what is suitable; implement only the gaps. First placing a broad legacy task in a later release does not defer qualification of a capability needed by an earlier consumer: I-REUSE in first-releases applies.
3. Check every hard prerequisite before new implementation. Check a capability's exact profile and integration receipts before using it. `existing_work_refs` identifies reuse, not readiness or a new hard edge.
4. Track implementation, criterion coverage, live qualification, and the release decision separately. A capability subset does not complete a broad task. A baseline/checkpoint mismatch requires requalification.
5. Accept a release under its gates, not by the number of closed cards. A negative experiment may complete research work without a shipping claim.

There are 280 requirements: Core 57 AF + 43 GC + 48 AMM + 35 RSI; Lokiravia 67 CLD + 30 LW. Epics/features/stories remain hierarchy containers, not additional executable tasks. Core `examples/backlog.json` is an example and is not duplicated in this plan. The `cloud:` prefix denotes Lokiravia, not mandatory hosted deployment.

<a id="релізи-та-наступні-напрями"></a>
## Releases and subsequent directions

Row order is a product preference when readiness is equal, not a barrier between all directions. L-CREATOR and W-FIRST can advance in parallel; W-FIRST does not wait for full CLD020 or Core030. Choosing W-FIRST before accepting W-DEPTH is an explicit policy of this plan; the current DAG has no such edge. Later optional directions start only when needed and after their gates pass.

`Closure` includes seeds and all declared hard prerequisites, even if some are already implemented. `New` means a requirement's first planned allocation, not an amount of new code. For C-PILOT/L-PREVIEW, closure is the complete obligation map of the source tasks, while release acceptance is limited to the stated capabilities.

| Order | Delivery | Closure | New | Acceptance |
|---|---|---:|---:|---|
| 1 | **C-PILOT** — Core: qualified local engineering pilot | 36 | 36 | Narrow capability path; full tasks separately |
| 2 | **L-PREVIEW** — Lokiravia: saved idea and agreed plan | 8 | 8 | Preview scope; full M0/M1 separately |
| 3 | **C-WORKBENCH** — Core: candidate comparison with evidence | 12 | 12 | Every closure criterion and workbench scenario |
| 4 | **L-CREATOR** — Lokiravia: three real games and a change cycle | 20 | 12 | Existing gate and all its prerequisites |
| 5 | **W-FIRST** — Lokiravia: first living scene | 22 | 15 | Existing gate and all its prerequisites |
| 6 | **C-SELF** — Core improves its own source and harness | 19 | 7 | Existing gate and all its prerequisites |
| 7 | **C-METHOD** — Core improves the next research method | 24 | 5 | Existing gate and all its prerequisites |
| 8 | **C-RSI** — Standalone product with evidence-based RSI | 30 | 6 | Existing gate and all its prerequisites |
| 9 | **W-DEPTH** — Deeper district and verified rule evolution | 47 | 18 | Existing gate and all its prerequisites |
| 10 | **C-PLATFORM** — Full advertised Core platform / legacy GA | 57 | 31 | Full AF034/035 and every criterion of the advertised scope |
| 11 | **C-GODOT** — Full existing Core Godot creator path | 30 | 21 | Full applicable GC milestone gates |
| 12 | **C-AUTONOMY** — Full once-approved autonomous mission | 48 | 48 | Full AMM047/048 and their prerequisites |
| 13 | **L-HOSTED** — Private hosted alpha | 34 | 14 | Existing gate and all its prerequisites |
| 14 | **C-LOCAL** — Qualified local-only / hybrid game path | 36 | 5 | Full applicable GC milestone gates |
| 15 | **L-PUBLIC** — Limited public creator beta | 44 | 10 | Existing gate and all its prerequisites |
| 16 | **L-MARKET** — Marketplace | 51 | 7 | Conditional direction; existing gate and all its prerequisites |
| 17 | **C-EXPAND** — Full advertised Core game-creator scope | 43 | 7 | Full applicable GC milestone gates |
| 18 | **L-ENGINES** — Additional engines and target platforms | 54 | 8 | Conditional direction; existing gate and all its prerequisites |
| 19 | **L-GA** — Defined Lokiravia GA / factory scope | 50 | 5 | Existing GA gate and conditional gates for selected features |
| 20 | **L-CONSOLE** — Conditional console-support feasibility | 36 | 1 | Conditional direction; conditional partner gate; no-go is not a release |
| 21 | **L-FACTORY-MARKET** — Conditional sale of Factory packs | 54 | 1 | Conditional direction; marketplace and rights to Factory packs |
| 22 | **L-NONGAME** — Conditional Lokiravia non-game pack | 38 | 1 | Conditional direction; separate non-game qualification |
| 23 | **W-COOP** — Research into player cooperation | 48 | 1 | Conditional direction; research, with no-go permitted |
| 24 | **C-TRAINING** — Optional training research | 29 | 1 | Conditional direction; experiment admission and adoption/no-go separately |

In JSON, every release contains exact `seed_ids`, `task_closure`, `newly_allocated`, and `capability_prerequisites`. The first five deliveries are detailed in first-releases; later gates inherit full canonical criteria. C-PLATFORM preserves AF034/035 and their broader requirements; C-GODOT/C-LOCAL/C-EXPAND preserve existing GC milestone gates; C-AUTONOMY preserves full AMM047/048. L-GA does not enable sales, consoles, or a new engine without the conditional gates listed in JSON. Optional does not mean an automatic pass following no-go.

<a id="єдина-черга-вимог"></a>
## One requirement queue

Exact dependencies and source locations are in JSON; titles below are translated from the canonical manifest where needed, with existing English titles retained verbatim. `First review` is the first point to check the reusable result or implement the gap. A requirement may participate in multiple releases; membership does not duplicate its implementation.

| No. | ID | First review | Requirement |
|---:|---|---|---|
| 1 | `core:AF-001` | C-PILOT | [Versioned domain model and compatibility migration](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L31) |
| 2 | `core:AF-002` | C-PILOT | [Transactional event outbox and tamper-evident audit chain](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L55) |
| 3 | `core:AF-003` | C-PILOT | [Content-addressed artifact and criterion-evidence ledger](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L79) |
| 4 | `core:AF-004` | C-PILOT | [Deterministic policy plane, autonomy modes, and emergency stop](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L103) |
| 5 | `core:AF-005` | C-PILOT | [Normalized adapter contract, qualification, and agent lifecycle](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L130) |
| 6 | `core:AF-006` | C-PILOT | [Durable workflow execution, checkpoints, and resume](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L154) |
| 7 | `core:AF-007` | C-PILOT | [Dependency scheduler, TTL/fenced leases, and conflict domains](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L182) |
| 8 | `core:AF-008` | C-PILOT | [Persistent Loop Engineering and no-progress control](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L207) |
| 9 | `core:AF-009` | C-PILOT | [Mission intake, source authority, clarifications, and readiness verdict](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L364) |
| 10 | `core:AF-010` | C-PILOT | [Provider-neutral Role Definitions and compatibility contracts](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L390) |
| 11 | `core:AF-011` | C-PILOT | [Evaluation-aware Agent Router, independent reviewer rotation, and qualification history](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L415) |
| 12 | `core:AF-012` | C-PILOT | [Role pools, arbitration strategies, and Workforce Composer](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L440) |
| 13 | `core:AF-013` | C-PILOT | [Factory Blueprint generation, alternatives, approval, and amendments](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L466) |
| 14 | `core:AF-017` | C-PILOT | [Local sandbox subset for writable workers](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L611) |
| 15 | `core:AF-044` | C-PILOT | [Worker Runtime abstraction](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L235) |
| 16 | `core:AF-046` | C-PILOT | [Per-stage live execution approvals](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L272) |
| 17 | `core:AF-048` | C-PILOT | [Worktree manager](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L873) |
| 18 | `core:AF-052` | C-PILOT | [Deterministic validator runner](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L946) |
| 19 | `core:AF-055` | C-PILOT | [Execution Context Package MVP](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L289) |
| 20 | `core:AF-020` | C-PILOT | [Independent evaluation service and criterion verdicts](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L690) |
| 21 | `core:AF-045` | C-PILOT | [Hermes adapter and session lifecycle](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L253) |
| 22 | `core:AF-049` | C-PILOT | [Codex CLI implementation worker](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L892) |
| 23 | `core:AF-051` | C-PILOT | [Candidate change artifact and approval-gated PR plan](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L928) |
| 24 | `core:AF-053` | C-PILOT | [End-to-end coding delivery loop](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L964) |
| 25 | `core:AF-056` | C-PILOT | [Minimal execution telemetry and enforced budgets](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L306) |
| 26 | `core:AF-057` | C-PILOT | [Local recovery and orphan reconciliation](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L323) |
| 27 | `core:AF-GC-001` | C-PILOT | [Restore reproducible CI on three operating systems](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-001) |
| 28 | `core:AF-GC-002` | C-PILOT | [Show readiness only after actual checks](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-002) |
| 29 | `core:AF-GC-003` | C-PILOT | [Closing a dialog never confirms an action](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-003) |
| 30 | `core:AF-GC-004` | C-PILOT | [Preserve drafts and focus during automatic refresh](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-004) |
| 31 | `core:AF-GC-005` | C-PILOT | [Preserve the meaning of an ordinary game description](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-005) |
| 32 | `core:AF-GC-006` | C-PILOT | [Bind the selected model to actual execution](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-006) |
| 33 | `core:AF-GC-039` | C-PILOT | [Align local API authorisation with the promised policy](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-039) |
| 34 | `core:AF-GC-041` | C-PILOT | [Preserve roles and reviewer independence in a live mission](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-041) |
| 35 | `core:AF-GC-042` | C-PILOT | [Qualify planning and bootstrap roles for providers](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-042) |
| 36 | `core:AF-GC-043` | C-PILOT | [Atomically admit qualified workers with scoped attempts and shared capacity](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-043) |
| 37 | `cloud:AF-CLD-001` | L-PREVIEW | [Agree on the Core and Cloud product boundaries](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L292) |
| 38 | `cloud:AF-CLD-002` | L-PREVIEW | [Define the shared data model and API contracts](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L340) |
| 39 | `cloud:AF-CLD-003` | L-PREVIEW | [Map Cloud work to the existing Core backlog](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L390) |
| 40 | `cloud:AF-CLD-004` | L-PREVIEW | [Design separate Creator and Operator views](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L440) |
| 41 | `cloud:AF-CLD-005` | L-PREVIEW | [Define engine, build target, and game pack interfaces](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L492) |
| 42 | `cloud:AF-CLD-007` | L-PREVIEW | [Turn a plain-language idea into a Game Brief](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L592) |
| 43 | `cloud:AF-CLD-008` | L-PREVIEW | [Keep the first playable version small](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L643) |
| 44 | `cloud:AF-CLD-009` | L-PREVIEW | [Assemble a visible AI game team](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L693) |
| 45 | `core:AF-RSI-001` | C-WORKBENCH | [Separate the authority of the optimizer, evaluator, and current Core](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-001) |
| 46 | `core:AF-RSI-002` | C-WORKBENCH | [Describe the immutable subject and generation of evolution](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-002) |
| 47 | `core:AF-RSI-003` | C-WORKBENCH | [Freeze the comparison protocol before running candidates](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-003) |
| 48 | `core:AF-RSI-004` | C-WORKBENCH | [Link generations, attempts, evidence, and decisions](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-004) |
| 49 | `core:AF-RSI-005` | C-WORKBENCH | [Separate learning examples, validation, and hidden holdout](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-005) |
| 50 | `core:AF-RSI-006` | C-WORKBENCH | [Generalize the evidence-first evaluator beyond a Codex diff](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-006) |
| 51 | `core:AF-RSI-007` | C-WORKBENCH | [Compare actual benefit while accounting for cost and noise](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-007) |
| 52 | `core:AF-RSI-008` | C-WORKBENCH | [Reserve a bounded budget for the complete experiment](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-008) |
| 53 | `core:AF-RSI-009` | C-WORKBENCH | [Qualify an isolated arena for Core changes](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-009) |
| 54 | `core:AF-RSI-010` | C-WORKBENCH | [Turn an improvement idea into an exact candidate plan](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-010) |
| 55 | `core:AF-RSI-011` | C-WORKBENCH | [Run baseline and challenger under one protocol](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-011) |
| 56 | `core:AF-RSI-015` | C-WORKBENCH | [Build an independent benchmark of the Core product](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-015) |
| 57 | `cloud:AF-CLD-006` | L-CREATOR | [Define evidence levels and release gates](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L542) |
| 58 | `cloud:AF-CLD-010` | L-CREATOR | [Prepare a small Godot 2D starter pack](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L745) |
| 59 | `cloud:AF-CLD-011` | L-CREATOR | [Connect a real Godot engine adapter](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L797) |
| 60 | `cloud:AF-CLD-012` | L-CREATOR | [Keep source versions and working game checkpoints](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L849) |
| 61 | `cloud:AF-CLD-013` | L-CREATOR | [Connect live coding workers to game tasks](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L900) |
| 62 | `cloud:AF-CLD-014` | L-CREATOR | [Check the rules of the generated game](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L952) |
| 63 | `cloud:AF-CLD-015` | L-CREATOR | [Build a Web version and add Play](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1004) |
| 64 | `cloud:AF-CLD-016` | L-CREATOR | [Export a Windows game and the full source](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1056) |
| 65 | `cloud:AF-CLD-017` | L-CREATOR | [Turn play feedback into a change plan](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1108) |
| 66 | `cloud:AF-CLD-018` | L-CREATOR | [Create version 2, restore version 1, and try a private remix](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1159) |
| 67 | `cloud:AF-CLD-019` | L-CREATOR | [Show progress and enforce budget and stop controls](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1212) |
| 68 | `cloud:AF-CLD-020` | L-CREATOR | [Accept three real reference games](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1263) |
| 69 | `cloud:AF-LW-001` | W-FIRST | [Constitution of the living-world experience](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-001) |
| 70 | `core:AF-RSI-031` | W-FIRST | [Type the permitted action of an agent in an external domain](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-031) |
| 71 | `core:AF-RSI-032` | W-FIRST | [Define a neutral replay and domain-checkpoint contract](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-032) |
| 72 | `cloud:AF-LW-002` | W-FIRST | [Game model of events and consequences](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-002) |
| 73 | `cloud:AF-LW-003` | W-FIRST | [Versioned rulebook and discoverable possibilities](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-003) |
| 74 | `cloud:AF-LW-004` | W-FIRST | [A palette of composable affordances for authors](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-004) |
| 75 | `cloud:AF-LW-005` | W-FIRST | [Adjudicating an unplanned player action](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-005) |
| 76 | `cloud:AF-LW-008` | W-FIRST | [Impact scope and understandable adventure risk](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-008) |
| 77 | `cloud:AF-LW-009` | W-FIRST | [Perspective-specific memory for NPCs and witnesses](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-009) |
| 78 | `cloud:AF-LW-010` | W-FIRST | [Traces from which the player can reconstruct causality](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-010) |
| 79 | `cloud:AF-LW-014` | W-FIRST | [Humor direction as an experience setting](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-014) |
| 80 | `core:AF-RSI-033` | W-FIRST | [Qualify slow agent decisions outside the game tick](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-033) |
| 81 | `cloud:AF-LW-011` | W-FIRST | [Cascades with thresholds, delay, and decay](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-011) |
| 82 | `cloud:AF-LW-012` | W-FIRST | [Counterfactual review of a world scenario](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-012) |
| 83 | `cloud:AF-LW-030` | W-FIRST | [First single-player proof in 30 minutes](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-030) |
| 84 | `core:AF-RSI-012` | C-SELF | [Accumulate verified experience as a graph of existing evidence](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-012) |
| 85 | `core:AF-RSI-013` | C-SELF | [Evolve harness, routing, and skills through existing registries](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-013) |
| 86 | `core:AF-RSI-014` | C-SELF | [Prepare changes to Core's own code as ordinary immutable candidates](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-014) |
| 87 | `core:AF-RSI-016` | C-SELF | [Check state, API, and migration compatibility between generations](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-016) |
| 88 | `core:AF-RSI-017` | C-SELF | [Promote and roll back a generation through shadow/canary stages](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-017) |
| 89 | `core:AF-RSI-018` | C-SELF | [Show the human the state and reason for self-improvement](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-018) |
| 90 | `core:AF-RSI-019` | C-SELF | [Accept the first Core-on-Core cycle without claiming full RSI](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-019) |
| 91 | `core:AF-RSI-020` | C-METHOD | [Submit a new evaluator as a separate candidate subject](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-020) |
| 92 | `core:AF-RSI-021` | C-METHOD | [Qualify evaluator calibration and systematic errors](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-021) |
| 93 | `core:AF-RSI-022` | C-METHOD | [Separate agent gain from evaluator drift during coevolution](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-022) |
| 94 | `core:AF-RSI-023` | C-METHOD | [Compare generations of the optimizer itself](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-023) |
| 95 | `core:AF-RSI-024` | C-METHOD | [Complete the first bounded recursive cycle](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-024) |
| 96 | `core:AF-RSI-025` | C-RSI | [Derive improvement opportunities from real failures and friction](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-025) |
| 97 | `core:AF-RSI-026` | C-RSI | [Introduce an independent product signal from Core users](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-026) |
| 98 | `core:AF-RSI-027` | C-RSI | [Propose a research portfolio and revision of the product goal](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-027) |
| 99 | `core:AF-RSI-028` | C-RSI | [Test new tools and topologies as explainable experiments](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-028) |
| 100 | `core:AF-RSI-029` | C-RSI | [Test long-term evolution for poisoning, drift, and recovery](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-029) |
| 101 | `core:AF-RSI-030` | C-RSI | [Accept Lokvetia Core self-improvement as a separate product](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-030) |
| 102 | `cloud:AF-LW-006` | W-DEPTH | [Craft with material cost and shared contributions](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-006) |
| 103 | `cloud:AF-LW-007` | W-DEPTH | [Productive error and secondary use](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-007) |
| 104 | `cloud:AF-LW-013` | W-DEPTH | [An authoring laboratory for one scene](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-013) |
| 105 | `cloud:AF-LW-015` | W-DEPTH | [A comic consequence with a new choice](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-015) |
| 106 | `cloud:AF-LW-016` | W-DEPTH | [A quiet session and objects with shared history](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-016) |
| 107 | `cloud:AF-LW-017` | W-DEPTH | [Equally meaningful player and NPC contributions to an expedition](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-017) |
| 108 | `cloud:AF-LW-018` | W-DEPTH | [Institutions with needs and duties](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-018) |
| 109 | `core:AF-RSI-034` | W-DEPTH | [Evaluate domain-rule candidates without assuming artistic authority](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-034) |
| 110 | `cloud:AF-LW-019` | W-DEPTH | [The birth and fading of a local tradition](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-019) |
| 111 | `cloud:AF-LW-020` | W-DEPTH | [Negotiating changes to shared space](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-020) |
| 112 | `cloud:AF-LW-021` | W-DEPTH | [Reconstruction with a choice of the place's future](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-021) |
| 113 | `cloud:AF-LW-022` | W-DEPTH | [Rumors, reputation, and the possibility of rebuttal](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-022) |
| 114 | `cloud:AF-LW-023` | W-DEPTH | [Publishing world evolution with version history](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-023) |
| 115 | `cloud:AF-LW-024` | W-DEPTH | [A game campaign for verifiable self-improvement](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-024) |
| 116 | `cloud:AF-LW-025` | W-DEPTH | [Playtesting surprise, fairness, and the desire to stay](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-025) |
| 117 | `cloud:AF-LW-026` | W-DEPTH | [Player and world-author abuse suite](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-026) |
| 118 | `cloud:AF-LW-027` | W-DEPTH | [Returning to a world that lived without the player](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-027) |
| 119 | `cloud:AF-LW-028` | W-DEPTH | [The complete evolving neighborhood: later acceptance](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-028) |
| 120 | `core:AF-014` | C-PLATFORM | [Idempotent mission bootstrap, manifests, and rollback point](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L493) |
| 121 | `core:AF-015` | C-PLATFORM | [Immutable Context Packages, provenance, broker, and compaction](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L518) |
| 122 | `core:AF-016` | C-PLATFORM | [Typed memory, bounded retrieval, invalidation, and governed skills](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L543) |
| 123 | `core:AF-018` | C-PLATFORM | [Tool Registry, Tool Gateway, MCP manager, and connector lifecycle](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L636) |
| 124 | `core:AF-019` | C-PLATFORM | [Short-lived scoped credential broker with zero prompt/log exposure](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L663) |
| 125 | `core:AF-021` | C-PLATFORM | [Prompt-injection red team, tripwires, quarantine, and incidents](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L718) |
| 126 | `core:AF-022` | C-PLATFORM | [ADR governance and transactional Blueprint impact propagation](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L747) |
| 127 | `core:AF-023` | C-PLATFORM | [Audited parallel, generator-critic, quorum, debate, and red/blue patterns](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L774) |
| 128 | `core:AF-024` | C-PLATFORM | [Signed pack SDK and install/upgrade/disable/rollback manager](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L799) |
| 129 | `core:AF-025` | C-PLATFORM | [Software Engineering reference pack and release evidence](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L826) |
| 130 | `core:AF-026` | C-PLATFORM | [REST operations API, idempotency/ETags, webhooks, and SDK contracts](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1005) |
| 131 | `core:AF-027` | C-PLATFORM | [OpenTelemetry and cost ledger](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1030) |
| 132 | `core:AF-029` | C-PLATFORM | [PostgreSQL/object storage migration and end-to-end tenant isolation](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1083) |
| 133 | `core:AF-031` | C-PLATFORM | [Single-node, clustered, hybrid, and air-gapped deployment definitions](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1146) |
| 134 | `core:AF-028` | C-PLATFORM | [Full chaos recovery and verified restore](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1057) |
| 135 | `core:AF-036` | C-PLATFORM | [Shared application-service boundary for CLI and web](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1196) |
| 136 | `core:AF-037` | C-PLATFORM | [Local FastAPI host and read-only operations API](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1217) |
| 137 | `core:AF-038` | C-PLATFORM | [Live development dashboard and navigation shell](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1240) |
| 138 | `core:AF-039` | C-PLATFORM | [Backlog, work-item, and workflow run controls](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1263) |
| 139 | `core:AF-040` | C-PLATFORM | [Agent, provider, and reviewer routing controls](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1288) |
| 140 | `core:AF-041` | C-PLATFORM | [Review inbox and founder approval workspace](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1311) |
| 141 | `core:AF-042` | C-PLATFORM | [Audit explorer, runtime settings, and GitHub sync preview](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1337) |
| 142 | `core:AF-043` | C-PLATFORM | [Windows launch experience, accessibility, and end-to-end qualification](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1360) |
| 143 | `core:AF-030` | C-PLATFORM | [Human Control Plane for evidence, approvals, incidents, cost, and intervention](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1114) |
| 144 | `core:AF-032` | C-PLATFORM | [NFR, performance, accessibility, isolation, and recovery qualification suite](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1412) |
| 145 | `core:AF-033` | C-PLATFORM | [72-hour fault-injection soak with bounded resource growth](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1440) |
| 146 | `core:AF-034` | C-PLATFORM | [Full heterogeneous-agent reference acceptance mission](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1465) |
| 147 | `core:AF-035` | C-PLATFORM | [Runbooks, clean install, restore exercise, GA evidence, and handover](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L1494) |
| 148 | `core:AF-047` | C-PLATFORM | [Hermes qualification and controlled fallback](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L856) |
| 149 | `core:AF-050` | C-PLATFORM | [Claude Code implementation worker](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L910) |
| 150 | `core:AF-054` | C-PLATFORM | [Software engineering role pack](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/development-backlog.json#L570) |
| 151 | `core:AF-GC-007` | C-GODOT | [Add a “My games” home screen and guided start](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-007) |
| 152 | `core:AF-GC-008` | C-GODOT | [Turn an idea into an understandable first-game plan](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-008) |
| 153 | `core:AF-GC-010` | C-GODOT | [Store and revoke AI access without leaking keys](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-010) |
| 154 | `core:AF-GC-011` | C-GODOT | [Check PC capabilities before selecting a model and engine](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-011) |
| 155 | `core:AF-GC-012` | C-GODOT | [Recommend a realistic engine and AI configuration](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-012) |
| 156 | `core:AF-GC-013` | C-GODOT | [Show an exact installation plan from verified sources](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-013) |
| 157 | `core:AF-GC-014` | C-GODOT | [Execute and recover software installations](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-014) |
| 158 | `core:AF-GC-015` | C-GODOT | [Start local infrastructure with one action](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-015) |
| 159 | `core:AF-GC-016` | C-GODOT | [Create a Godot pack for the first 2D game](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-016) |
| 160 | `core:AF-GC-017` | C-GODOT | [Validate a Godot project and produce a real build](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-017) |
| 161 | `core:AF-GC-025` | C-GODOT | [Define an eligible path for ages 12+ and adult participation](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-025) |
| 162 | `core:AF-GC-009` | C-GODOT | [Connect cloud AI through an understandable wizard](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-009) |
| 163 | `core:AF-GC-018` | C-GODOT | [Authorise a bounded cloud session with a transparent budget](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-018) |
| 164 | `core:AF-GC-019` | C-GODOT | [Connect real development to the game plan](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-019) |
| 165 | `core:AF-GC-020` | C-GODOT | [Preserve the latest verified game version](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-020) |
| 166 | `core:AF-GC-021` | C-GODOT | [Launch “Play” for a specific working version](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-021) |
| 167 | `core:AF-GC-022` | C-GODOT | [Turn post-play feedback into the next version](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-022) |
| 168 | `core:AF-GC-023` | C-GODOT | [Explain progress and reliably stop work](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-023) |
| 169 | `core:AF-GC-024` | C-GODOT | [Make the main journey accessible in Ukrainian and English](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-024) |
| 170 | `core:AF-GC-040` | C-GODOT | [Test understandability with users aged 12–15](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-040) |
| 171 | `core:AF-GC-026` | C-GODOT | [Accept the complete Godot journey on a clean PC](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-026) |
| 172 | `core:AF-AMM-001` | C-AUTONOMY | [Autonomous Mission aggregate, configuration, and lifecycle migration](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L516) |
| 173 | `core:AF-AMM-002` | C-AUTONOMY | [Rich backlog schema, immutable revisions, and impact projection](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L534) |
| 174 | `core:AF-AMM-003` | C-AUTONOMY | [Mission Execution Epoch and supersession model](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L552) |
| 175 | `core:AF-AMM-004` | C-AUTONOMY | [Typed mission checkpoint model and integrity contract](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L570) |
| 176 | `core:AF-AMM-005` | C-AUTONOMY | [Autonomous authorization resolver and revocation](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L588) |
| 177 | `core:AF-AMM-006` | C-AUTONOMY | [Provider execution-location and local capability model](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L606) |
| 178 | `core:AF-AMM-007` | C-AUTONOMY | [Autonomous mission specification intake and source artifact](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L624) |
| 179 | `core:AF-AMM-008` | C-AUTONOMY | [Autonomous planning role pack and role-to-model manifest](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L642) |
| 180 | `core:AF-AMM-009` | C-AUTONOMY | [Structured multi-role architecture and backlog generation pipeline](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L660) |
| 181 | `core:AF-AMM-010` | C-AUTONOMY | [Deterministic backlog and architecture proposal verifier](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L678) |
| 182 | `core:AF-AMM-011` | C-AUTONOMY | [Approve Backlog - Start Mission and revision authority service](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L696) |
| 183 | `core:AF-AMM-012` | C-AUTONOMY | [AutonomousMissionWorkflow contracts, queries, client, and Worker registration](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L714) |
| 184 | `core:AF-AMM-013` | C-AUTONOMY | [Pre-approval analysis/generation phases and durable approval wait](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L732) |
| 185 | `core:AF-AMM-014` | C-AUTONOMY | [Post-approval phase and child work-item orchestration](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L750) |
| 186 | `core:AF-AMM-015` | C-AUTONOMY | [Mission-wide pause, resume, stop, and retry control fence](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L768) |
| 187 | `core:AF-AMM-016` | C-AUTONOMY | [Checkpoint restart and backlog-revision Signal contracts](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L786) |
| 188 | `core:AF-AMM-017` | C-AUTONOMY | [Continue-as-new, history thresholds, visibility, and Worker versioning](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L804) |
| 189 | `core:AF-AMM-018` | C-AUTONOMY | [Mission operation journal and authoritative recovery reconstruction](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L822) |
| 190 | `core:AF-AMM-019` | C-AUTONOMY | [Mission epoch branch and worktree manager](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L840) |
| 191 | `core:AF-AMM-020` | C-AUTONOMY | [Per-item worktree and autonomous local integration path](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L858) |
| 192 | `core:AF-AMM-021` | C-AUTONOMY | [Checkpoint materialization, validation, and epoch restart service](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L876) |
| 193 | `core:AF-AMM-022` | C-AUTONOMY | [Apply Backlog Changes - Restart domain service](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L894) |
| 194 | `core:AF-AMM-023` | C-AUTONOMY | [Installed local model inventory and role selection](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L912) |
| 195 | `core:AF-AMM-024` | C-AUTONOMY | [Durable global local-inference scheduler](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L930) |
| 196 | `core:AF-AMM-025` | C-AUTONOMY | [Ollama dynamic model and lifecycle adapter](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L948) |
| 197 | `core:AF-AMM-026` | C-AUTONOMY | [Writable local LLM Worker Runtime through Tool Gateway](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L966) |
| 198 | `core:AF-AMM-027` | C-AUTONOMY | [Fresh isolated role contexts and mission memory integration](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L984) |
| 199 | `core:AF-AMM-028` | C-AUTONOMY | [MODEL_INDEPENDENT and LOGICALLY_INDEPENDENT review routing](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1002) |
| 200 | `core:AF-AMM-029` | C-AUTONOMY | [Autonomous Local telemetry and non-monetary safety policy](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1020) |
| 201 | `core:AF-AMM-030` | C-AUTONOMY | [Required-vs-current environment discovery artifact](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1038) |
| 202 | `core:AF-AMM-031` | C-AUTONOMY | [Versioned environment and service manifests](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1056) |
| 203 | `core:AF-AMM-032` | C-AUTONOMY | [Policy-bound bootstrap planner and idempotent executor](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1074) |
| 204 | `core:AF-AMM-033` | C-AUTONOMY | [Environment health convergence, service recovery, and NEEDS_HUMAN_ACTION](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1092) |
| 205 | `core:AF-AMM-034` | C-AUTONOMY | [Windows local long-run profile and orchestration preflight](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1110) |
| 206 | `core:AF-AMM-035` | C-AUTONOMY | [Active-revision ready selector and technical subtask creation](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1128) |
| 207 | `core:AF-AMM-036` | C-AUTONOMY | [Autonomous work-item coding-delivery integration](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1146) |
| 208 | `core:AF-AMM-037` | C-AUTONOMY | [Bounded autonomous repair and strategy escalation chain](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1164) |
| 209 | `core:AF-AMM-038` | C-AUTONOMY | [Architecture evolution, ADR propagation, and scope guard](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1182) |
| 210 | `core:AF-AMM-039` | C-AUTONOMY | [Accepted-work checkpoint and mission-memory progression](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1200) |
| 211 | `core:AF-AMM-040` | C-AUTONOMY | [Final mission validation and COMPLETED transition](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1218) |
| 212 | `core:AF-AMM-041` | C-AUTONOMY | [Autonomous Mission application service and persisted projections](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1236) |
| 213 | `core:AF-AMM-042` | C-AUTONOMY | [Autonomous Mission REST API](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1254) |
| 214 | `core:AF-AMM-043` | C-AUTONOMY | [Autonomous Mission CLI command group](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1272) |
| 215 | `core:AF-AMM-044` | C-AUTONOMY | [Control Center mission creation, planning, approval, status, and controls](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1290) |
| 216 | `core:AF-AMM-045` | C-AUTONOMY | [Control Center backlog editor, checkpoints, architecture, environment, and activity](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1308) |
| 217 | `core:AF-AMM-046` | C-AUTONOMY | [Domain migration, authorization, compatibility, and security qualification](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1326) |
| 218 | `core:AF-AMM-047` | C-AUTONOMY | [Temporal, local-runtime, environment, and end-to-end mission qualification](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1344) |
| 219 | `core:AF-AMM-048` | C-AUTONOMY | [Fault/reboot soak, resource-growth gate, documentation, and release evidence](https://github.com/HappyMiha/Lokvetia-Core/blob/c35f20cf90b0caf4d9bdd2d1fd25d1557de016ad/examples/autonomous-mission-backlog.json#L1362) |
| 220 | `cloud:AF-CLD-021` | L-HOSTED | [Add account boundaries, roles, and the 12+ access gate](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1317) |
| 221 | `cloud:AF-CLD-022` | L-HOSTED | [Use PostgreSQL for hosted state](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1369) |
| 222 | `cloud:AF-CLD-023` | L-HOSTED | [Store source, builds, and assets as protected objects](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1420) |
| 223 | `cloud:AF-CLD-024` | L-HOSTED | [Qualify server resources and register remote workers](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1471) |
| 224 | `cloud:AF-CLD-025` | L-HOSTED | [Make hosted workflows survive restarts](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1523) |
| 225 | `cloud:AF-CLD-026` | L-HOSTED | [Isolate agent and build jobs](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1574) |
| 226 | `cloud:AF-CLD-027` | L-HOSTED | [Guide creators through AI connections](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1625) |
| 227 | `cloud:AF-CLD-028` | L-HOSTED | [Keep Cloud credentials outside game work](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1677) |
| 228 | `cloud:AF-CLD-029` | L-HOSTED | [Enforce Cloud quotas and track usage](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1728) |
| 229 | `cloud:AF-CLD-030` | L-HOSTED | [Provide the hosted Creator Portal](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1780) |
| 230 | `cloud:AF-CLD-031` | L-HOSTED | [Serve protected playable builds](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1834) |
| 231 | `cloud:AF-CLD-032` | L-HOSTED | [Export a portable ownership package](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1886) |
| 232 | `cloud:AF-CLD-033` | L-HOSTED | [Add operations visibility and recovery drills](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1937) |
| 233 | `cloud:AF-CLD-034` | L-HOSTED | [Accept the private Cloud alpha](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L1990) |
| 234 | `core:AF-GC-027` | C-LOCAL | [Install and verify local models](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-027) |
| 235 | `core:AF-GC-028` | C-LOCAL | [Give local AI a qualified development tool](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-028) |
| 236 | `core:AF-GC-029` | C-LOCAL | [Share PC resources between AI, the engine and the game](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-029) |
| 237 | `core:AF-GC-030` | C-LOCAL | [Route cloud/local work under explicit rules](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-030) |
| 238 | `core:AF-GC-031` | C-LOCAL | [Qualify local-only and hybrid game creation](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-031) |
| 239 | `cloud:AF-CLD-035` | L-PUBLIC | [Add releases and visibility controls](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2054) |
| 240 | `cloud:AF-CLD-036` | L-PUBLIC | [Add creator profiles and libraries](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2107) |
| 241 | `cloud:AF-CLD-037` | L-PUBLIC | [Add game pages with browser Play](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2161) |
| 242 | `cloud:AF-CLD-038` | L-PUBLIC | [Add Discover, search and tags](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2215) |
| 243 | `cloud:AF-CLD-039` | L-PUBLIC | [Add share links and embed controls](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2269) |
| 244 | `cloud:AF-CLD-040` | L-PUBLIC | [Add Remix and Fork with source history](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2323) |
| 245 | `cloud:AF-CLD-041` | L-PUBLIC | [Add likes, bookmarks and basic play statistics](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2378) |
| 246 | `cloud:AF-CLD-042` | L-PUBLIC | [Add age-aware moderation and reporting](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2432) |
| 247 | `cloud:AF-CLD-043` | L-PUBLIC | [Check asset origin and licences before release](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2487) |
| 248 | `cloud:AF-CLD-044` | L-PUBLIC | [Approve a limited public creator beta](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2542) |
| 249 | `cloud:AF-CLD-045` | L-MARKET | [Add seller setup and adult or guardian approval](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2603) |
| 250 | `cloud:AF-CLD-046` | L-MARKET | [Add sale listings, prices and licence choices](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2657) |
| 251 | `cloud:AF-CLD-047` | L-MARKET | [Add checkout through a payment provider](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2712) |
| 252 | `cloud:AF-CLD-048` | L-MARKET | [Add purchase access and the buyer library](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2766) |
| 253 | `cloud:AF-CLD-049` | L-MARKET | [Add the revenue ledger, fees and payouts](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2820) |
| 254 | `cloud:AF-CLD-050` | L-MARKET | [Add refunds, disputes and fraud review](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2875) |
| 255 | `cloud:AF-CLD-051` | L-MARKET | [Approve the marketplace release](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2930) |
| 256 | `core:AF-GC-032` | C-EXPAND | [Set up Unity Hub, Editor and required modules](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-032) |
| 257 | `core:AF-GC-033` | C-EXPAND | [Add a Unity pack, tests and build adapter](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-033) |
| 258 | `core:AF-GC-034` | C-EXPAND | [Accept the complete Unity journey for a beginner](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-034) |
| 259 | `core:AF-GC-035` | C-EXPAND | [Manage game asset provenance and import](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-035) |
| 260 | `core:AF-GC-036` | C-EXPAND | [Expand complexity through measurable reference games](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-036) |
| 261 | `core:AF-GC-037` | C-EXPAND | [Export a game and share it through a separate action](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-037) |
| 262 | `core:AF-GC-038` | C-EXPAND | [Update the application and collect understandable diagnostics](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/game-creator-backlog.en.md#af-gc-038) |
| 263 | `cloud:AF-CLD-052` | L-ENGINES | [Publish an EngineAdapter SDK and compatibility tests](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L2988) |
| 264 | `cloud:AF-CLD-053` | L-ENGINES | [Qualify the Unity adapter](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3043) |
| 265 | `cloud:AF-CLD-054` | L-ENGINES | [Prove Unreal feasibility and qualify its adapter](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3097) |
| 266 | `cloud:AF-CLD-055` | L-ENGINES | [Add Android builds and Google Play preparation](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3156) |
| 267 | `cloud:AF-CLD-056` | L-ENGINES | [Add Apple builds and App Store preparation](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3211) |
| 268 | `cloud:AF-CLD-057` | L-ENGINES | [Add Steam release preparation](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3267) |
| 269 | `cloud:AF-CLD-058` | L-ENGINES | [Add a shared PC store packaging contract](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3322) |
| 270 | `cloud:AF-CLD-060` | L-ENGINES | [Approve the multi-engine and multi-target release](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3432) |
| 271 | `cloud:AF-CLD-061` | L-GA | [Package reusable Agent Teams and Factory templates](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3492) |
| 272 | `cloud:AF-CLD-063` | L-GA | [Let creators choose qualified models and team budgets](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3602) |
| 273 | `cloud:AF-CLD-064` | L-GA | [Publish an API, SDK and signed webhooks](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3656) |
| 274 | `cloud:AF-CLD-065` | L-GA | [Qualify self-hosted and hybrid deployment](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3712) |
| 275 | `cloud:AF-CLD-067` | L-GA | [Approve the defined general-availability scope](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3824) |
| 276 | `cloud:AF-CLD-059` | L-CONSOLE | [Plan optional console support behind partner approval](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3377) |
| 277 | `cloud:AF-CLD-062` | L-FACTORY-MARKET | [Add an optional marketplace for Factories and packs](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3547) |
| 278 | `cloud:AF-CLD-066` | L-NONGAME | [Explore a later non-game executable pack](https://github.com/HappyMiha/Lokiravia/blob/39dd3030acd642dccec30abebdd7ce6caf0a2ec8/examples/agentfactory-cloud-backlog.json#L3768) |
| 279 | `cloud:AF-LW-029` | W-COOP | [Optional research into human cooperation](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/backlog.en.md#af-lw-029) |
| 280 | `core:AF-RSI-035` | C-TRAINING | [Assess the feasibility of training-time self-iteration](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/backlog.en.md#af-rsi-035) |

<a id="джерело-правди-й-оновлення"></a>
## Source of truth and updates

This is a derived design view, not a seventh executable backlog. Six source manifests with exact commit/SHA-256 are listed in JSON. Every requirement has a JSON pointer and a digest of the canonical item; criteria are not rewritten into a shorter version. New RSI/LW cards continue to be synchronized between Markdown and JSON. Legacy IDs, source labels, hierarchy, dependencies, and acceptance criteria are unchanged.

Reproduction algorithm: read source items; preserve hierarchy separately; qualify local IDs; reject duplicate/missing IDs or cycles; compute the closure of each seed set; assign the earliest release membership; among available DAG nodes, select the minimum `(priority_band, id)`. Source SHA-256 is computed from the Git-blob bytes at the stated commit, not a platform-specific checkout; checkout comparison normalizes CRLF to LF. A substantive source-digest change makes the view stale until it is recalculated, checked, and reviewed. Both repositories contain an identical copy of the view.

`declared_status` carries the raw label (or null), while `completion`, `live_qualification`, and `release_acceptance` are deliberately not upgraded. Historical release notes about implementation and a current proposed label may coexist; the reuse matrix in first-releases explains existing slices. Calendar and actual cost estimates are added after gap assessment and environment qualification, without changing first-release promises.
