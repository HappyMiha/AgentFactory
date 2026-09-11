<a id="пропозиція-беклогу-самовдосконалення-самого-lokvetia-core"></a>
# Backlog proposal: self-improvement of Lokvetia Core itself


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [backlog.md](backlog.md). Source SHA-256 (UTF-8/LF): `50e2d1f8ec59afbe9c2629042cc88c4a73630ccdc2601a3e8a59faf88cac7654`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](backlog.md).

Revision date: 10 September 2026. Q05 refines existing cards; IDs and dependencies are preserved. These are design requirements for the future `docs/evolution/backlog.json`, not an active runtime queue. All `AF-RSI-*` have **proposed** status; this document does not authorize code execution, expenditure, or release acceptance. Under the user's clarification, the three-computer claim workflow is not a prerequisite for this work.

**Lokvetia Core** owns every reusable capability below. Lokiravia consumes accepted contracts and adds its own product evaluation and game rules. Core RSI must operate and demonstrate benefit without a game, Cloud account, or Lokiravia runtime. Existing AF, AF-AMM, AF-GC, and AF-CLD IDs/gates are preserved. `AF-GC-043` already exists and is not reassigned.

`Dependencies` below are internal AF-RSI design/delivery prerequisites. `Reuse` provides traceability to existing capabilities; an ID's presence does not imply acceptance of the corresponding runtime integration. Before implementation, record the accepted upstream commit and measured readiness of the profile used. Any external alias is a reference, not a foreign dependency in an old schema-v2 manifest.

Work phases: **C0** contracts; **C1** externally verifiable experiments; **C2** Core's own harness and source; **C3** governed acceptance of generations; **C4** evaluator/optimizer evolution; **C5** research selection and product direction; **C6** demonstrated recursion. C0–C6 are Core work phases; the shared E0–E5 in the vision are evidence levels. C0–C3 prepare E1, and C4–C6 prepare E2/E5; no phase changes GC/CLD M0–M6. P0/P1 priority is read within a phase; it does not require all P0 work to run simultaneously.

**Traceability:** the “Rationale” field identifies a requirement's source or our own decision, not evidence of completed work. Legend: [source-guide.en.md](source-guide.en.md). Text cards are the content source; every dependency and rationale is synchronized with JSON.

<a id="c0--визначити-що-означає-core-поліпшився"></a>
## C0 — define what “Core improved” means

<a id="af-rsi-001--розділити-повноваження-оптимізатора-оцінювача-та-чинного-core"></a>
<a id="af-rsi-001"></a>
### AF-RSI-001 — Separate the authority of the optimizer, evaluator, and current Core

- **Dependencies:** none. **Reuse:** AF-004 policy, AF-013 Blueprint, AF-018 tools, AF-022 ADR; `policy.py`, `blueprint.py`, `tools.py`, `adr.py`.
- **Outcome:** ADR and authority matrix for change proposer, experiment runner, evidence issuer, evaluator, promotion authority, and active control plane.
- **Acceptance:** permitted records are defined for code, harness, evaluator, and product-goal changes; the optimizer does not change current objectives, evidence, budget, or authorization through its own candidate; every new authority is a separately versioned decision. Scope classifies the actual effect surface: a change called cosmetic/informational gains no hidden right to alter behavior, capabilities, or control. An uncertain experiment has an explicitly permitted scope of unknown outcomes.
- **Negative checks:** substituting policy through prompt/skill/retrieval; a candidate declares itself accepted; service identity impersonates the owner. Every scenario leaves the current control plane unchanged. Attempting to bypass appropriate review by renaming a behavior mutation as formatting.
- **Artifact:** decision table, state transitions, attack/denial fixtures. **Phase/priority:** C0/P0.
- **Rationale:** RSI-SURVEY:R04, RSI-SURVEY:R06, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:experience-improvement

<a id="af-rsi-002--описати-незмінний-субєкт-і-покоління-еволюції"></a>
<a id="af-rsi-002"></a>
### AF-RSI-002 — Describe the immutable subject and generation of evolution

- **Dependencies:** 001. **Reuse:** AF-001 identities, AF-016 skills, AF-024 packs, AF-048 worktrees, AF-055 context.
- **Outcome:** `EvolutionSubject` and `GenerationManifest`: kind, parent generation, Core commit, harness/role/tool/skill/config digests, runtime/profile, dependencies, mutation scope, and rollback target.
- **Acceptance:** one generation digest unambiguously identifies the executable composition; an old manifest is reproducible after a registry update; source/harness/model-weight changes are distinguished. Model weights are a separate research profile, not a promise of available training. ActivationBinding contains target, monotonic activation_seq, manifest digest, authority epoch, writer fence, and exact state binding; immutable GenerationManifest does not reference its own future ActivationReceipt. Canonical entity, incarnation, mutable representation, and execution generation have distinct roles; lineage is not new authority. Output schema, decoder/projection, and label semantics are fixed for comparison; common-meaning mapping between versions is verified or the result is not-comparable.
- **Negative checks:** floating latest, a changed pack under the same version, substituted parent, unknown component, reusing a digest for different bytes. ABA A@41→B@42→A@43 does not permit an old grant for A@41; replaying a promotion ID does not increment the sequence. The same name substitutes another entity; a new decoder re-scores immutable raw receipts as gain without a shared outcome meaning.
- **Artifact:** versioned schema, three non-game examples, compatibility matrix. **Phase/priority:** C0/P0.
- **Rationale:** RSI-SURVEY:R02, RSI-SURVEY:R03, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery, CONTRACT:identity-continuity

<a id="af-rsi-003--зафіксувати-протокол-порівняння-до-запуску-кандидатів"></a>
<a id="af-rsi-003"></a>
### AF-RSI-003 — Freeze the comparison protocol before running candidates

- **Dependencies:** 001, 002. **Reuse:** AF-020 evaluation, AF-032 qualification, AF-027 telemetry.
- **Outcome:** `ExperimentProtocol`: hypothesis, baseline, controlled change surface, datasets, primary outcome, non-regression floors, budget, seeds/repetitions, comparison rule, stopping rule.
- **Acceptance:** protocol digest is fixed before challenger output; changing a metric/threshold creates a new experiment; documented failed/inconclusive results are valid completions. Statistical confidence and minimum useful-effect rules are selected for the particular task before measurement. The protocol explicitly classifies replay/action intervention/input sensitivity/planner comparison/evaluator comparison; pair identity fixes initial observable inputs, goal, rules, exogenous/coupling plan, and horizon. Non-game comparison predefines root/family/slice, R0/Rn reference roles, finite candidate/search/final-gate caps, and cluster-aware analysis. Permitted memory treatment shares an eligible experience pool, not necessarily the same representation. Fault schedule is bound to a semantic boundary: legitimately avoiding an effect neither forces the arm to perform it nor removes the root; task outcome and fault applicability are separate.
- **Negative checks:** raising a cap only for the challenger, selecting a metric after results, discarding failed seeds, retroactively lowering a non-regression floor. After intervention, downstream NPC choices are not copied from the baseline; different tasks do not become paired through the same name. Creating a new final set or criterion epoch to reset cumulative failed-selection history. Artificially forcing a candidate into an unnecessary operation for convenient fault injection.
- **Artifact:** protocol template and acceptance-decision examples. **Phase/priority:** C0/P0.
- **Rationale:** RSI-SURVEY:R04, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:counterfactual-evaluation, CONTRACT:non-game-evaluation

<a id="af-rsi-004--звязати-покоління-спроби-докази-та-рішення"></a>
<a id="af-rsi-004"></a>
### AF-RSI-004 — Link generations, attempts, evidence, and decisions

- **Dependencies:** 002, 003. **Reuse:** AF-003 evidence, AF-002 events, AF-051 candidates; current SQLite evidence ledger.
- **Outcome:** append-only lineage `hypothesis → protocol → baseline/challenger run → receipts → comparison → decision → generation`, including rejected and inconclusive branches.
- **Acceptance:** restart does not create a second promotion; a query explains the current version's provenance and shows every attempt; neither the experiment runner nor review text changes acceptance history. EvidenceSeal fixes the complete admitted-attempt set and explicit missing/invalid dispositions; a late receipt creates an amendment/challenge rather than modifying the seal. A hash does not replace issuer verification. Adoption of a recovered Git commit rebinds actual tree/diff bytes to the validated snapshot; accepted result/gate/linkage have a replayable transition identity and reconciliation without a second gate.
- **Negative checks:** duplicate receipt, another tenant, wrong generation, command repetition after a crash, attempts to erase a negative result. A late conflicting receipt does not rewrite an accepted comparison or permit new promotion before the challenge is resolved.
- **Artifact:** data/API contract, state diagram, replay fixtures. **Phase/priority:** C0/P0.
- **Rationale:** RSI-SURVEY:R03, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery

<a id="c1--отримати-зовнішній-сигнал-який-не-можна-вигадати-рефлексією"></a>
## C1 — obtain external signals that reflection cannot invent

<a id="af-rsi-005--розділити-навчальні-приклади-validation-і-прихований-holdout"></a>
<a id="af-rsi-005"></a>
### AF-RSI-005 — Separate learning examples, validation, and hidden holdout

- **Dependencies:** 003, 004. **Reuse:** AF-015 context, AF-016 memory, AF-021 injection defense, AF-029 storage.
- **Outcome:** dataset/benchmark registry with provenance, rights, task family, split, version, access scope, contamination tracking, and retired-case policy.
- **Acceptance:** the optimizer sees permitted training diagnostics; final holdout operates in a separate evaluator scope; a memorized case does not count as new; any split change changes the protocol. Published paper Q06-C01–C10 have development/design status; a fresh holdout needs independent provenance and a contamination audit, not merely new names or seeds. TaskCase/TaskSetManifest fixes root/source/generator/solution ancestry and a freshness vector; splitting follows dependent roots before outcomes. D development, S adaptive selection, and F final confirmation have different permitted diagnostics and claims. Task-agent access to F input is permitted only within the declared evaluation scope; transitive optimizer/log/skill/retrieval exposure is recorded. Unknown pretraining access is not described as clean. Aggregate feedback, retired sets, and past failed final gates retain lineage.
- **Negative checks:** leakage through logs/memory/error output, renaming a training case as holdout, synthetic holdout copy, retrieval by its private ID. A public expected trace or synthetic retelling is not called hidden external grounding. S with hidden labels is called independent F after selection queries. Sibling schedules, an independent author of the same solution, or a new date are declared fresh roots without an ancestry audit.
- **Artifact:** benchmark-registry contract, access rules, provenance/contamination receipts. **Phase/priority:** C1/P0.
- **Rationale:** RSI-SURVEY:R06, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:counterfactual-evaluation, CONTRACT:non-game-evaluation

<a id="af-rsi-006--узагальнити-evidence-first-evaluator-поза-codex-diff"></a>
<a id="af-rsi-006"></a>
### AF-RSI-006 — Generalize the evidence-first evaluator beyond a Codex diff

- **Dependencies:** 002, 004. **Reuse:** AF-020 `evaluation.py`, AF-052 `validators.py`, AF-GC-006/041 effective identity, AF-GC-043 admission.
- **Outcome:** evaluation-subject adapter for harness/config/skill/workflow/Core release, using the existing evidence ledger and reviewer independence.
- **Acceptance:** a software candidate still requires its five validators; other subjects have an explicitly versioned set of required receipts; acceptance never relies solely on `accepted_evidence=True` or a model-provided URL list.
- **Negative checks:** producer/reviewer aliases of the same model, callback before deterministic failure, forged receipt, replayed proof from another subject version.
- **Artifact:** compatible evaluator contract, adapter conformance, and old-path regression evidence. **Phase/priority:** C1/P0.
- **Rationale:** RSI-SURVEY:R04, REPO-AUDIT, DESIGN:core-architecture

<a id="af-rsi-007--порівнювати-реальну-користь-з-урахуванням-витрат-і-шуму"></a>
<a id="af-rsi-007"></a>
### AF-RSI-007 — Compare actual benefit while accounting for cost and noise

- **Dependencies:** 003, 005, 006. **Reuse:** AF-027 telemetry/cost ledger, AF-032 qualification.
- **Outcome:** comparator for paired baseline/challenger outcome, dispersion, confidence, cost/latency, sample size, aborts, and non-regression floors.
- **Acceptance:** `better`, `worse`, `equivalent`, and `inconclusive` decisions are reproducible from receipts; failed runs and every candidate's costs are preserved; sequential selection/multiple comparisons are handled under the declared protocol. Greater novelty, profitability, or lower cost does not compensate for a violated hard invariant; changing a criterion after results creates a new protocol. Separately evaluate achievement of the original goal, correct handling of refusal/uncertainty, causal contribution, integrity, and full cost. Evaluator comparison uses one frozen corpus with external labels and blind order. Declared consumer slices show benefit and full known cost for different roles, including exit/restore; missing cost is not zero. If a conclusion rests only on those who stayed, its scope is explicitly limited. Independent n is defined by task/source clusters, not seeds, assertions, or reviewer votes. Rn is the incremental-adoption comparator; R0 supports a cumulative claim under a compatible current protocol. Each family named in advance has its own outcome/floor and uncertainty; infrastructure-invalid measurement is distinguished from an unsuccessful valid outcome. Equivalent requires a separate predetermined criterion. Task/nomination/oracle preparation and every search/retest attempt enter campaign cost; zero accepted improvements does not make costs zero.
- **Negative checks:** more tokens disguised as intelligence gain, one lucky seed, overoptimizing the mean with critical tail regression, unlimited holdout peeking. An uncompleted reading does not become completed through a good explanation of refusal; more cascades do not compensate for violated consent or increased costs. Average gain hides costs shifted to another role or violation of that role's fixed hard floor. Candidate better only than the founding version, worse than the current generation. One repository task with six checks presented as cross-family transfer; unproven gain declared equivalence.
- **Artifact:** decision report with adoption/no-go examples. **Phase/priority:** C1/P0.
- **Rationale:** RSI-SURVEY:R04, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:counterfactual-evaluation, CONTRACT:experience-improvement, CONTRACT:non-game-evaluation

<a id="af-rsi-008--резервувати-bounded-бюджет-повного-експерименту"></a>
<a id="af-rsi-008"></a>
### AF-RSI-008 — Reserve a bounded budget for the complete experiment

- **Dependencies:** 003, 004. **Reuse:** AF-008 loop, AF-027/056 budgets, AF-AMM recovery; existing authorization/reservation services.
- **Outcome:** one experiment budget covers the baseline, every challenger, reviewers, retries, tooling, and rejected branches.
- **Acceptance:** preflight blocks new work outside the reservation; Pause/Stop also applies to optimizer/reviewer; restart preserves consumed resources and permits only the same remaining limits; hard expansion requires new authority. Reservation exists before dispatch; an unknown effect/charge after timeout has a bounded-exposure disposition rather than automatic budget release.
- **Negative checks:** splitting one expensive mutation into unlimited child runs; retry resets the counter; increasing budget through artifact text; missing usage is not counted as zero. A cancellation request or lease expiry does not reset an already possible charge; without a required cost upper bound, the next dispatch is blocked.
- **Artifact:** budget-accounting contract and cancel/restart traces. **Phase/priority:** C1/P0.
- **Rationale:** RSI-SURVEY:R08, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery

<a id="af-rsi-009--кваліфікувати-ізольовану-арену-для-змін-core"></a>
<a id="af-rsi-009"></a>
### AF-RSI-009 — Qualify an isolated arena for Core changes

- **Dependencies:** 001, 002, 008. **Reuse:** AF-017 sandbox, AF-044 runtime, AF-048 worktrees, AF-055 context, AF-GC-043 admission.
- **Outcome:** isolated experiment profile with a separate Core instance/database, worktree, temporary resources, fixed tools, and evidence export.
- **Acceptance:** the candidate cannot write to running Core, evaluator datasets, credentials, or accepted artifacts; teardown preserves evidence; supported OS/backend are named precisely. An unverified general Windows sandbox remains unsupported.
- **Negative checks:** path escape, symlink/junction, inherited secret, background process after cancel, network access outside the approved profile, termination during export.
- **Artifact:** arena qualification report and confinement receipts. **Phase/priority:** C1/P0.
- **Rationale:** RSI-SURVEY:R03, RSI-SURVEY:R06, REPO-AUDIT, DESIGN:core-architecture

<a id="af-rsi-010--перетворити-ідею-поліпшення-на-точний-candidate-plan"></a>
<a id="af-rsi-010"></a>
### AF-RSI-010 — Turn an improvement idea into an exact candidate plan

- **Dependencies:** 002, 003, 009. **Reuse:** AF-013 Blueprint, AF-022 ADR, AF-051 candidates, AF-008 repair.
- **Outcome:** mutation proposal with rationale, affected surfaces, diff/patch, dependencies, expected effect, risk, required checks, and rollback class.
- **Acceptance:** a proposal does not execute before protocol/authority match; mechanical rephrasing without behavioral change is not called improvement; the selected patch is explained through specific prior failures or a hypothesis.
- **Negative checks:** hidden evaluator change, unchecked configuration widening, source modification outside the manifest, incompatible dependency disguised as a prompt edit.
- **Artifact:** reviewable mutation manifest and affected-surface diff. **Phase/priority:** C1/P0.
- **Rationale:** RSI-SURVEY:R02, REPO-AUDIT, DESIGN:core-architecture

<a id="af-rsi-011--виконати-baseline-і-challenger-за-одним-протоколом"></a>
<a id="af-rsi-011"></a>
### AF-RSI-011 — Run baseline and challenger under one protocol

- **Dependencies:** 005, 006, 008, 009, 010. **Reuse:** AF-006 workflows, AF-044 runtime, AF-AMM checkpoints/epochs, AF-052 validators.
- **Outcome:** an experiment runner that invokes the existing execution boundary and returns primary receipts, rather than implementing its own queue/workers.
- **Acceptance:** known seeds, model/runtime versions, hardware profile, and budgets are preserved; replay uses accepted inputs; variation in model calls is honestly distinguished from deterministic replay of accepted actions. AttemptIntent is persisted before dispatch; the receiver capability profile determines permitted lookup/dedup/retry. An unknown non-repeatable effect is not retried without reconciliation, under RC01–04 of the recovery contract. The same seed is not a sufficient guarantee of pairing: stream roles/event mapping, unmatched-draw policy, and recomputation of distributions after an action changes are recorded. Planner outputs may differ; replay makes a different claim.
- **Negative checks:** baseline accidentally runs on the new harness; a shared mutable cache contaminates the other group; a failed run is dropped; a partial result after restart is declared complete. A provider without outcome lookup is not described as exactly-once; a cancel acknowledgment does not replace an observed stopped/no-effect receipt. An extra model utterance must not silently shift external weather in the pair; different causal conditions are not forced to produce the same random outcome.
- **Artifact:** baseline/challenger execution bundle and comparison-ready index. **Phase/priority:** C1/P0.
- **Rationale:** RSI-SURVEY:R05, RSI-SURVEY:R08, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery, CONTRACT:counterfactual-evaluation

<a id="c2--навчитися-змінювати-власний-harness-і-власний-source"></a>
## C2 — learn to change its own harness and source

<a id="af-rsi-012--накопичувати-перевірений-досвід-як-граф-існуючих-доказів"></a>
<a id="af-rsi-012"></a>
### AF-RSI-012 — Accumulate verified experience as a graph of existing evidence

- **Dependencies:** 004, 005, 006, 011. **Reuse:** AF-015 context, AF-016 typed memory, AF-021 quarantine.
- **Outcome:** an experience graph links hypotheses, results, skills, consumers, and contradictions through existing immutable IDs.
- **Acceptance:** failed/inconclusive outcomes influence subsequent hypothesis selection; revoked/stale memory stops entering new context packages, while historical consumers remain accessible; tenant/purpose isolation is preserved.
- **Negative checks:** reflection without evidence is promoted to fact; circular citation increases confidence; an invalidated skill continues to propagate; private task data becomes global memory.
- **Artifact:** graph schema/projections and contamination/revocation trace. **Phase/priority:** C2/P0.
- **Rationale:** RSI-SURVEY:R03, RSI-SURVEY:R06, REPO-AUDIT, DESIGN:core-architecture

<a id="af-rsi-013--еволюціонувати-harness-routing-і-skills-через-existing-registries"></a>
<a id="af-rsi-013"></a>
### AF-RSI-013 — Evolve harness, routing, and skills through existing registries

- **Dependencies:** 007, 010, 011, 012. **Reuse:** AF-010 roles, AF-011 routing, AF-012 composition, AF-016 skills, AF-024 packs.
- **Outcome:** one bounded mutation profile for prompts/context policy/tool choice/role topology/skills, with versioned manifests.
- **Acceptance:** the changed harness provides verified benefit on an external task set; route fallback preserves producer/reviewer independence; skill transitions occur in the existing registry with primary evaluation receipts. Reuse of a skill/memory in a new runtime, tenant, or purpose passes separate scope/authority/applicability checks; hash and lineage do not confer rights. An alias/model name does not prove reviewer independence under the declared decision policy.
- **Negative checks:** a producer acquires reviewer duty; routing hides expensive fallback calls; a tool is auto-installed without capability approval; a skill is evaluated only on its own examples. A new agent ID hides producer lineage or conflicting duties; copied memory scope silently expands; a latest-role lookup substitutes for a qualified version.
- **Artifact:** accepted or rejected harness generation, with an ablation removing each key change. **Phase/priority:** C2/P0.
- **Rationale:** RSI-SURVEY:R02, RSI-SURVEY:R03, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:identity-continuity

<a id="af-rsi-014--готувати-зміни-власного-коду-core-як-звичайні-immutable-candidates"></a>
<a id="af-rsi-014"></a>
### AF-RSI-014 — Prepare changes to Core's own code as ordinary immutable candidates

- **Dependencies:** 009, 010, 011. **Reuse:** AF-049/050 workers, AF-051 candidates, AF-052 validators, AF-053 delivery, AF-054 software roles.
- **Outcome:** Core can select its own repository as a target and create a scoped candidate source change through the existing coding pipeline.
- **Acceptance:** the candidate solves a reproduced platform task and has an exact base/head/diff, independent review, and release plan; the active Core is not replaced during its own experiment. The affected surface includes dependent capability changes, required components, and maintenance cost. For a supported schema migration, semantic permission/role/purpose contracts and outcome projections are checked, beyond data readability alone; failure/partial state is defined before activation.
- **Negative checks:** a patch changes tests to conceal failure; unauthorized push/merge/install; worker authority changes; a developer database enters candidate artifacts. Component A is improved through an unapproved change to B; an old permission label gains a broader meaning; a preview or temporary experiment activates the permanent Core on its own.
- **Artifact:** Core-on-Core candidate branch/patch and complete delivery receipt. **Phase/priority:** C2/P0.
- **Rationale:** RSI-SURVEY:R02, RSI-SURVEY:R03, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:identity-continuity

<a id="af-rsi-015--побудувати-незалежний-benchmark-продукту-core"></a>
<a id="af-rsi-015"></a>
### AF-RSI-015 — Build an independent benchmark of the Core product

- **Dependencies:** 003, 005, 007, 011. **Reuse:** AF-025 reference pack, AF-032 qualification, AF-034 acceptance mission, AF-GC-001 checks.
- **Outcome:** a fixed benchmark of real non-game tasks: a bug/feature in an external fixture repo, planning with ambiguous requirements, failure/restart handling, and readability of the operator result.
- **Acceptance:** success is determined by external tests and human evaluation where needed; tool use, time/cost, manual corrections, and failed attempts are counted; the benchmark does not consist solely of Core's own unit tests. The initial NG-F1 bounded external-fixture maintenance and NG-F2 requirements-to-decision packet have different work products and non-overlapping source/root tasks. Context/tool/repair/recovery/evidence are cross-cutting slices, not additional independent families. Existing Core fixtures and NG-O01–06 are public development recipes. Qualification includes source/rights, solvability, a qualified verifier/document adapter, known-good/bad controls, and a human product signal where the claim requires it. Real roots, sample/repeats, and budget are accepted separately before execution.
- **Negative checks:** task identity leakage; hardcoded answer; textual “done” without an artifact; a non-game task requires Godot or Cloud. The same patch is first evaluated as a plan and then as code, and described as two independent families. An F2 schema pass is presented as a complete usability check, while all supported tasks are rejected to achieve a flawless handling score.
- **Artifact:** versioned benchmark suite and baseline report. **Phase/priority:** C2/P0.
- **Rationale:** RSI-SURVEY:R08, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:non-game-evaluation

<a id="af-rsi-016--перевіряти-сумісність-стану-api-і-міграцій-між-поколіннями"></a>
<a id="af-rsi-016"></a>
### AF-RSI-016 — Check state, API, and migration compatibility between generations

- **Dependencies:** 002, 014, 015. **Reuse:** AF-001 migrations, AF-026 API, AF-028/057 recovery, AF-AMM-046 compatibility.
- **Outcome:** a generation compatibility contract for active missions, paused runs, pending gates, evidence, configured integrations, and local user data.
- **Acceptance:** an upgrade preserves IDs/authority; old consumer contracts work within the declared compatibility envelope; rollback or forward repair has a verified state plan; an incompatible version is blocked before the switch.
- **Negative checks:** schema downgrade loses data; an approved old gate launches newly broadened tools; a digest changes after migration; an interrupted upgrade leaves a mixed runtime.
- **Artifact:** upgrade/restore drill with old/new snapshots and an exact compatibility verdict. **Phase/priority:** C2/P0.
- **Rationale:** RSI-SURVEY:R03, REPO-AUDIT, DESIGN:core-architecture

<a id="c3--приймати-покоління-без-втрати-працюючого-продукту"></a>
## C3 — accept generations without losing the working product

<a id="af-rsi-017--просувати-й-відкочувати-generation-через-shadowcanary-stages"></a>
<a id="af-rsi-017"></a>
### AF-RSI-017 — Promote and roll back a generation through shadow/canary stages

- **Dependencies:** 004, 007, 008, 016. **Reuse:** AF-024 pack lifecycle, AF-031 deployment profiles, AF-057 recovery; existing immutable release images/autodeploy plans.
- **Outcome:** a release lifecycle `candidate → qualified → shadow → canary → promoted → superseded | revoked` with a protected ActivationBinding. The profile defines mandatory shadow/canary stages; rejection remains a comparison outcome, and rollback is a new authorized activation, not a state for erasing old history.
- **Acceptance:** shadow does not duplicate external effects; the canary audience/profile has explicit scope; a failure before commit leaves the binding unchanged, while a failure after commit triggers scoped recovery under ActivationReceipt; an incompatible/revoked fallback leads to paused/degraded mode; canary data is not silently lost during restore. Grant/revocation and activation are serialized within one qualified authority boundary; final commit checks the exact ActivationBinding and immutable state readiness. A root supervisor upgrade has independent authority, quiesced control state, and a fenced handoff. Supported identity/role/schema transitions have a ContinuityPlan with an inventory of classes, a defined qualified profile/authority, per-record rights/obligations/resources/privacy dispositions, and unknown/unmapped outcomes. A generation change does not reset unresolved effects, budget lineage, current revocations, or accountability; a one-time approval does not expand the successor's scope.
- **Negative checks:** two concurrent promotions; crash after pointer switch; a rejected generation returns as latest; old approval transfers to new bytes; a canary exceeds its audience. RC06–11/14/16: grant revoke race, ABA, concurrent candidates, lost ack, unreadied successor, revoked fallback; no candidate completes self-approval. A candidate excludes an inconvenient record from the migration inventory; split/merge copies grants or private memory without authority; rollback restores old rights over a current revocation.
- **Artifact:** promotion receipt, rollback drill, and proof of previous-generation availability. **Phase/priority:** C3/P0.
- **Rationale:** RSI-SURVEY:R03, RSI-SURVEY:R06, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery, CONTRACT:identity-continuity

<a id="af-rsi-018--показати-людині-стан-і-причину-самовдосконалення"></a>
<a id="af-rsi-018"></a>
### AF-RSI-018 — Show the human the state and reason for self-improvement

- **Dependencies:** 004, 007, 008, 017. **Reuse:** AF-036 application services, AF-038/043 operator UI, AF-056 telemetry.
- **Outcome:** an operator view of “what Core is trying to improve, why, how much has been spent, what is proven, and what will be applied,” with generation comparison and Pause/Stop.
- **Acceptance:** evaluation, proposal, accepted candidate, and active release have distinct, understandable states; a failed experiment is visible; the primary next action does not require JSON; the current good generation and rollback are accessible. Under the current consumer policy, a real Stop/opt-out before the effect invalidates incompatible queued behavior; the current policy/version check at the final authoritative show/dispatch boundary is serialized with acceptance of the opt-out; stale output is denied/re-rendered, while output already delivered is not declared canceled. State/effect receipts and the cost and state of exit/return are required, beyond a visible button alone.
- **Negative checks:** missing receipts display green success; refresh erases an unsaved owner decision; stale UI permits a different promotion; a paused workflow spends budget in child runs. An old scheduled response bypasses a new restriction; a style change hides the necessary reason for refusal or the path to recovery.
- **Artifact:** UI/API acceptance scenarios, accessibility and interruption walkthrough. **Phase/priority:** C3/P1.
- **Rationale:** RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:experience-improvement

<a id="af-rsi-019--прийняти-перший-core-on-core-цикл-без-заяви-про-повний-rsi"></a>
<a id="af-rsi-019"></a>
### AF-RSI-019 — Accept the first Core-on-Core cycle without claiming full RSI

- **Dependencies:** 013, 014, 015, 016, 017, 018. **Reuse:** AF-034 acceptance mission, AF-020 independent review.
- **Outcome:** end-to-end proof for at least one harness change and one source change to Core itself.
- **Acceptance:** baseline→proposal→execution→comparison→decision→retained generation runs with real providers/tools; one deliberately unsuccessful candidate and recovery are included. Positive improvement requires measured gain; if there is none, the result is no-go/iteration, not a forced pass.
- **Negative checks:** narrative-only change; missing holdout; a local unit-test pass is presented as product gain; only winners are retained.
- **Artifact:** independently reviewed Core-on-Core report, active scope, and remaining limits. **Phase/priority:** C3/P0.
- **Rationale:** RSI-SURVEY:R04, RSI-SURVEY:R08, REPO-AUDIT, DESIGN:core-architecture

<a id="c4--вдосконалювати-optimizer-та-метод-оцінки-не-замикати-самопідтвердження"></a>
## C4 — improve the optimizer and evaluation method without closing a loop of self-confirmation

<a id="af-rsi-020--подавати-новий-evaluator-як-окремий-candidate-subject"></a>
<a id="af-rsi-020"></a>
### AF-RSI-020 — Submit a new evaluator as a separate candidate subject

- **Dependencies:** 001, 002, 005, 006, 019. **Reuse:** AF-020 evaluation, AF-022 ADR, AF-024 evaluation packs.
- **Outcome:** an evaluator manifest with rubric, tools, dataset construction, judgment method, cost, and known failure envelope.
- **Acceptance:** the current frozen protocol and independent holdout authority check the challenger evaluator; the evaluator neither accepts its own replacement nor changes historical verdicts; CriterionManifest records not only the judge but also generation/sampling/replay/scoring dependencies, outcome meaning, prior-access snapshot, policy for subsequent access, and qualification envelope; the profile defines a complete inventory, and unknown dependencies remain unresolved; a new epoch activates with a consistent criterion/selection snapshot under Q05; the source of the primary fact, telemetry producer, and decoder are qualified separately from the judge.
- **Negative checks:** evaluator/optimizer simultaneously weaken the metric; the champion is rewritten during comparison; the new evaluator or its diagnostician receives sealed labels; the same checker erroneously conceals a changed task sampler; a crash switches the evaluator without its selection view.
- **Artifact:** evaluator candidate, CriterionManifest, and comparison/transition report against independent anchors. **Phase/priority:** C4/P0.
- **Rationale:** RSI-SURVEY:R04, RSI-SURVEY:R06, RSI-RQGM:RQGM-01, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:evaluator-succession

<a id="af-rsi-021--кваліфікувати-калібрування-й-систематичні-помилки-evaluator"></a>
<a id="af-rsi-021"></a>
### AF-RSI-021 — Qualify evaluator calibration and systematic errors

- **Dependencies:** 007, 020. **Reuse:** AF-020 criterion evidence, AF-021 hostile cases, AF-023 independent coordination.
- **Outcome:** an eval-of-eval suite with externally verifiable outcomes, blinded human labels for qualitative cases, calibration, and false-accept/false-reject analysis.
- **Acceptance:** bias favoring the author, long answers, a prestigious model, and an optimistic proposal is measured; abstain/inconclusive are permitted; reviewer disagreement is preserved; the frozen qualitative corpus includes distinctions between the author's intent, the recipient's experience, paraphrased repetition, and incomplete answers; external adjudication checks uncertainty and the claim's scope; the anchor exposure audit covers diagnosticians, feedback, aggregate scores, and memory, while final confirmation is separated from adaptive selection; panel acceptance and external factual correctness have different labels and permitted claims; blind quality slices check good/bad work from different authors, parity rates do not equal fairness, several reviews of one artifact count as a cluster, and partial/strict outcomes are retained separately.
- **Negative checks:** an attractive but incorrect research plan; a short correct answer; self-referential confidence claims; opposite labels after model names are swapped; positive responses only from those who stayed substitute for quality for everyone; the solver does not see tests, but a test-aware diagnostic transfers them into a skill, after which the corpus is called an untouched holdout; judge agreement is called ground truth; a missing telemetry marker is called absence of a violation, a valid compatible format is unjustifiably rejected, or a high-quality artifact is rejected for the sake of parity.
- **Artifact:** calibration report and permitted evaluation envelope; thresholds fixed before run. **Phase/priority:** C4/P0.
- **Rationale:** RSI-SURVEY:R04, RSI-SURVEY:R06, RSI-DGM:DGM-03, RSI-RQGM:RQGM-02, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:experience-improvement, CONTRACT:evaluator-succession

<a id="af-rsi-022--розділити-agent-gain-та-evaluator-drift-при-коеволюції"></a>
<a id="af-rsi-022"></a>
### AF-RSI-022 — Separate agent gain from evaluator drift during coevolution

- **Dependencies:** 019, 020, 021. **Reuse:** AF-027 comparison telemetry, AF-022 methodology versioning.
- **Outcome:** 2×2 cross-evaluation: old agent/new agent × old evaluator/new evaluator, plus an external sentinel suite.
- **Acceptance:** it is clear whether the task result improved or only the evaluation method changed; prior released generations retain their original protocols/verdicts; a methodology upgrade has a separate decision; stale fitness/posteriors/ranks and dependent distilled conclusions are excluded from the new selection view under the criterion dependency inventory, while raw receipts are not erased; new evaluations have new records, and the old corpus is not called fresh generation; late results remain historical until an applicability decision and do not reset costs; independent adjudication can establish an error in the incumbent evaluator.
- **Negative checks:** gain disappears under the old evaluator and the challenger is declared a failure without external adjudication; a new evaluator accepts poisoned candidates; drift is masked by an aggregate score or selective omission of cross-evaluation cells; a criterion switch leaves a stale champion; rescoring old outputs is presented as new generator behavior.
- **Artifact:** cross-evaluation matrix, criterion dependency inventory, rebuilt selection view, dissent, and methodology adoption/rejection receipt. **Phase/priority:** C4/P0.
- **Rationale:** RSI-SURVEY:R04, RSI-SURVEY:R06, RSI-RQGM:RQGM-01, RSI-RQGM:RQGM-03, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:evaluator-succession

<a id="af-rsi-023--порівнювати-покоління-самого-optimizer"></a>
<a id="af-rsi-023"></a>
### AF-RSI-023 — Compare generations of the optimizer itself

- **Dependencies:** 007, 010, 012, 019. **Reuse:** AF-011 routing, AF-023 tournament/coordination, AF-008 bounded loop.
- **Outcome:** the optimizer subject has a versioned proposal policy, search strategy, mutation operators, memory retrieval, and experiment selection.
- **Acceptance:** optimizers N and N+1 start with the same permitted knowledge/budget on held-out tasks; independent accepted improvements per total cost and time-to-useful-change are measured, including unsuccessful searches; the unit of useful improvement, resource caps, cost, and adaptive-selection policy are fixed before the experiment; accounting includes creation/qualification, expansions, judges, archive re-evaluation, anchors, and confirmation; conditional reuse efficiency is labeled separately; an archived stepping stone does not obtain release eligibility from search score alone; independent search runs are distinguished from repeated evaluations of one agent, and the starting archive/diagnosis/selection are controlled or openly included in the treatment bundle.
- **Negative checks:** the challenger receives training traces from the test period; additional parallel compute goes uncounted; scoring by number of proposals/commits or splitting one change into several accepted artifacts; copying a ready-made challenger solution; equal evaluation calls hide a more expensive model, additional checks, or creation cost; a revoked predecessor returns through a new rank.
- **Artifact:** optimizer-generation benchmark and counterfactual ablation. **Phase/priority:** C4/P0.
- **Rationale:** RSI-SURVEY:R08, RSI-DGM:DGM-01, RSI-DGM:DGM-02, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:evaluator-succession

<a id="af-rsi-024--замкнути-перший-bounded-рекурсивний-цикл"></a>
<a id="af-rsi-024"></a>
### AF-RSI-024 — Complete the first bounded recursive cycle

- **Dependencies:** 017, 019, 022, 023. **Reuse:** AF-AMM epochs/checkpoints, AF-008 loop, AF-053 delivery.
- **Outcome:** Core runs optimizer N; it proposes N+1; an external procedure accepts/rejects N+1; accepted N+1 participates in creating the next Core/harness generation.
- **Acceptance:** typed lineage O0→O1→O2 shows that accepted optimizer O1 proposed a change to the optimizer/method itself, O2; product artifacts are evaluated separately on fresh tasks; O2's benefit is compared with its immediate accepted predecessor O1 under a shared protocol/knowledge/resource envelope and an ablation without the new method; stopping/depth/cost bounds are fixed and the external anchor is independent; qualification/supervisor is not changed by its own candidate during that candidate's evaluation, and a change to the control process itself has a separate handoff under Q05; without measured benefit, O2 is retained as a rejected/inconclusive change, and O1's local success and recursive participation are not converted into positive next-step gain; the role map and execution receipt confirm actual use of the changed operator, beyond the mere presence of its file.
- **Negative checks:** N+1 appoints itself champion; an incomplete epoch is declared a successor; a new mission ID bypasses a depth/cost limit; the cycle continues after Stop; O2 is better only than O0 but worse than O1; a benchmark or panel curve is called proof of autonomous evolution of the entire control loop or of a correct product goal.
- **Artifact:** recursive lineage bundle with a reproducible rejection/recovery path. **Phase/priority:** C4/P0.
- **Rationale:** RSI-SURVEY:R08, RSI-SURVEY:R12, RSI-DGM:DGM-02, RSI-RQGM:RQGM-03, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:evaluator-succession

<a id="c5--поліпшувати-вибір-задач-і-напрям-розвитку-самого-продукту"></a>
## C5 — improve task selection and the product's own development direction

<a id="af-rsi-025--виводити-можливості-поліпшення-з-реальних-failures-і-friction"></a>
<a id="af-rsi-025"></a>
### AF-RSI-025 — Derive improvement opportunities from real failures and friction

- **Dependencies:** 012, 015, 018. **Reuse:** AF-027 telemetry, AF-009 intake, AF-AMM backlog analyzer/revisions.
- **Outcome:** opportunity records contain observed failure/friction, affected users/tasks, source evidence, frequency/impact uncertainty, and a candidate hypothesis.
- **Acceptance:** the system distinguishes a bug, usability gap, unsupported scope, evaluator problem, and research unknown; it consolidates duplicates by cause/evidence while preserving the original reports; it does not invent user desires from telemetry. A creator signal is bound to the exact product/profile, brief/scope, actual stage, and available source/build/session identities. A hypothesized cause is distinguished from a verified defect. An unconnected Play does not count as an unsuccessful played session; an authored paper fixture does not become an observed user report. The projection checks reviewed human requirements alongside the original source, beyond preservation of the original alone.
- **Negative checks:** one noisy incident becomes a roadmap mandate; private content leaks into a shared hypothesis; an already fixed issue reopens without new evidence. The source checksum matches, but human edits/agreed scope are lost from the execution context. A Cloud UI or world-only candidate gains a claim that the unchanged Core improved.
- **Artifact:** ranked opportunity register with provenance and uncertainty. **Phase/priority:** C5/P1.
- **Rationale:** RSI-SURVEY:R07, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:creator-evolution

<a id="af-rsi-026--ввести-незалежний-продуктовий-сигнал-від-користувачів-core"></a>
<a id="af-rsi-026"></a>
### AF-RSI-026 — Introduce an independent product signal from Core users

- **Dependencies:** 003, 015, 018, 025. **Reuse:** AF-009 intent, AF-015 provenance, AF-016 preferences, AF-029 scoped storage.
- **Outcome:** a consent-scoped feedback/user-study protocol for task completion, clarity, number of manual corrections, trust in the explanation, and controllability.
- **Acceptance:** qualitative evidence is linked to the exact product/version/scenario; simulation and synthetic users are not presented as human studies; temporal/geographic/sample limitations are visible. Within the permitted scope, denominators are shown for starts, completions, stops, and submitted feedback. Withdrawn/missing responses are not filled with invented ratings; declining to answer does not reduce access. Without permission to count it, the denominator is marked unknown. Planning and end-to-end studies have separate prerequisites/outcomes. For a creator case, stage completion does not substitute for a finished game. Planned fidelity to reviewed scope is distinguished from realized fidelity of the exact build's behavior, each applied at its own study level. Fidelity commitments and scope decisions, actual played/source/target versions, independent/assisted outcome, active/wall/wait time, and a usable restore receipt are defined before comparison. Lower effort achieved through unapproved simplification does not pass the floor. An unavailable runtime is not evaluated as time-to-Play; a change in task meaning creates a new versioned hypothesis.
- **Negative checks:** the optimizer fabricates the user's voice; vanity engagement substitutes for task success; dissatisfied sessions are excluded; private texts automatically enter training. A reason for leaving is attributed without evidence; consent withdrawal is ignored for the sake of a complete log; nonresponse is equated with satisfaction. Facilitator assistance is hidden; a history view is presented as a playable restore; V1 feedback is silently attached to latest V2. Several analytical roles of one receipt are counted as independent observations.
- **Artifact:** product feedback evidence contract and blinded comparison template. **Phase/priority:** C5/P1.
- **Rationale:** RSI-SURVEY:R07, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:experience-improvement, CONTRACT:creator-evolution

<a id="af-rsi-027--пропонувати-research-portfolio-та-перегляд-product-goal"></a>
<a id="af-rsi-027"></a>
### AF-RSI-027 — Propose a research portfolio and revision of the product goal

- **Dependencies:** 003, 007, 025, 026. **Reuse:** AF-009 intake, AF-013 Blueprint, AF-022 ADR, AF-AMM backlog revisions.
- **Outcome:** alternative product/research directions with value-of-information, cost, uncertainty, a decisive experiment, opportunity cost, and a stop/abandon criterion.
- **Acceptance:** the agent can demonstrate that the current direction is unsupported; a scope/objective/value-function change is submitted to the owner as a versioned proposal; prior criteria are not rewritten to “successfully” complete the old goal. A separate counterexample has rising local task-success without sufficient progress toward the owner's need; the permitted conclusion is an abandon/change proposal with transition cost and a decisive experiment.
- **Negative checks:** the system's own benchmark weakness becomes a reason to remove a user need; adoption grows by hiding costs; goal drift without a decision; endless research without a decisive experiment. Successful execution of many small tasks is declared proof of the right product direction without checking the need.
- **Artifact:** portfolio decision memo, comparison of alternatives, and owner-decision boundary. **Phase/priority:** C5/P0.
- **Rationale:** RSI-SURVEY:R07, RSI-SURVEY:R10, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:experience-improvement

<a id="af-rsi-028--перевіряти-нові-інструменти-й-топології-як-пояснювані-експерименти"></a>
<a id="af-rsi-028"></a>
### AF-RSI-028 — Test new tools and topologies as explainable experiments

- **Dependencies:** 013, 020, 023, 027. **Reuse:** AF-010 roles, AF-012 workforce, AF-018 tool gateway, AF-023 coordination, AF-024 packs.
- **Outcome:** a research profile for synthesized tools, new skill libraries, agent-role topology, and context/retrieval strategy, with one variable per minimal comparison or an explicit factorial design.
- **Acceptance:** the result is checked on new task families; tool permissions/register/lifecycle remain in force; ablation separates the tool's gain from additional agents/tokens.
- **Negative checks:** a generated tool has a hidden network/write effect; debate creates correlated reviewers; search-space expansion bypasses the cap; a change to many factors lacks attribution.
- **Artifact:** experiment portfolio and qualified reusable capability candidate. **Phase/priority:** C5/P1.
- **Rationale:** RSI-SURVEY:R02, RSI-SURVEY:R08, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture

<a id="c6--довести-тривале-накопичення-користі-й-зупинити-деградацію"></a>
## C6 — demonstrate sustained accumulation of benefit and stop degradation

<a id="af-rsi-029--випробувати-довгу-еволюцію-на-poisoning-drift-і-відновлення"></a>
<a id="af-rsi-029"></a>
### AF-RSI-029 — Test long-term evolution for poisoning, drift, and recovery

- **Dependencies:** 012, 016, 017, 022, 024. **Reuse:** AF-021 security, AF-028 chaos/recovery, AF-033 soak.
- **Outcome:** a versioned long-run schedule with a staged bad skill, evaluator bias, stale memory, corrupted candidate, interrupted migration, provider outage, and exhausted budget.
- **Acceptance:** under the preregistered run length and workload profile, an unaccepted change does not propagate; revoked evidence/skills are traced to consumers; compatible state and a permitted previous accepted generation are restored, while if no suitable fallback exists, history and recovery disposition are preserved in paused/degraded mode; resource growth is not hidden. The future implementation passes RC01–14/16 from recovery-contract.en.md that apply to the accepted Core profiles, using neutral fixtures, including final-commit races, bounded unknown effects, and supervisor handoff. Domain-specific RC15 is checked only in a separate C7 qualification; not-applicable/unsupported does not count as pass and does not create a world prerequisite for standalone Core.
- **Negative checks:** an error survives rollback in a shared cache; several weak accepted changes cause cumulative degradation; an orphan optimizer continues spending resources; evaluator drift disables a sentinel. A written RC table does not count as an executed chaos report; a stale fence does not authorize a remote effect that does not support fencing.
- **Artifact:** soak/chaos report with all interventions and failure lineage. **Phase/priority:** C6/P0.
- **Rationale:** RSI-SURVEY:R03, RSI-SURVEY:R06, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery

<a id="af-rsi-030--прийняти-самовдосконалення-lokvetia-core-як-окремий-продукт"></a>
<a id="af-rsi-030"></a>
### AF-RSI-030 — Accept Lokvetia Core self-improvement as a separate product

- **Dependencies:** 019, 024, 026, 027, 028, 029. **Reuse:** AF-034 acceptance mission, AF-032 qualification, AF-035 GA handover evidence.
- **Outcome:** a separate Core RSI acceptance dossier; no dependency on playable Lokiravia or acceptance of the game world.
- **Acceptance:** under a fixed protocol, several successive generations cover Core's own source/harness and optimizer; benefit is demonstrated on at least two independent non-game task families, with product-signal evidence, a failed candidate, an evaluator challenge, and rollback. The actual number of generations/sample/thresholds are fixed before the run. If the data does not support a gain, the gate is not passed. The two qualifying non-game families and analysis rules are named before outcomes, and their independence is justified through work-product/source/root lineage. Benefit is demonstrated in both under their respective predetermined axes/floors; a pooled mean does not hide a family regression. Candidate selection, final exposure, and cumulative failed gates are visible in the release dossier. Product-signal evidence is not replaced by the structural correctness of a plan.
- **Negative checks:** success only on cached training tasks; no optimizer change; a changed evaluator is the sole source of gain; Core does not operate without Cloud/game pack; support is claimed beyond the qualified OS/model envelope. Two successful slices are selected after the score, or a new F resets unsuccessful searches. Sixty rows of repeats of one fixture are called sixty independent tasks.
- **Artifact:** independent release review, supported scope, measured limits, source/export/restore bundle, and a list of the next open research questions. **Phase/priority:** C6/P0.
- **Rationale:** RSI-SURVEY:R08, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:non-game-evaluation

<a id="чому-це-не-дублює-існуючий-беклог"></a>
## Why this does not duplicate the existing backlog

The new tasks do not rewrite the sandbox, typed memory, role routing, worktrees, coding delivery, or pack lifecycle. They add the missing **generation subjects, protocols/holdout, comparison, promotion lineage, evaluator/optimizer experiments, and Core-specific acceptance** on top of existing services. `AF-RSI-009`, `013`, `014`, `016`, `018`, and `029` specifically integrate/qualify existing capabilities for the new recursion scope, rather than claiming a second implementation of the same modules.

Core-on-Core does not depend on the commercial non-game offering `AF-CLD-066`: Core must already be a domain-neutral standalone product. Likewise, the new Core RSI gate does not permit skipping game Play/rights/age/commercial gates in Lokiravia. Shared evidence infrastructure has one implementation authority; product benefit and world quality are evaluated by each product under its own accepted protocol.

The first reviewable slice is 001–004 and a concrete protocol for 015. In parallel, isolation/evaluator adapters 006/009 and product-signal research 026 can be refined at the design level. Real execution waits for its technical prerequisites; documentary research for later phases need not wait for future implementations.

<a id="c7--спільні-контракти-для-domain-packs-окремо-від-standalone-core-gate"></a>
## C7 — shared contracts for domain packs, separate from the standalone Core gate

031–034 make the previously described gameplay follow-ups concrete. This is an optional consumer track: none of 001–030 depends on it. World rules remain in the game pack, while Core provides neutral validation/runtime/evidence adapters.

<a id="af-rsi-031--типізувати-дозволену-дію-агента-у-зовнішньому-домені"></a>
<a id="af-rsi-031"></a>
### AF-RSI-031 — Type the permitted action of an agent in an external domain

- **Dependencies:** 001, 002, 004, 006. **Reuse:** AF-018 tool gateway, AF-021 injection defense, AF-GC-043 admission; domain-action follow-up from the existing Unreal plan.
- **Outcome:** an optional domain-action adapter: actor/world/session/revision/request identity, expiry, typed arguments, domain validation hook, allowed scope, and receipts.
- **Acceptance:** the adapter has no knowledge of the plot or economy; the domain validator has the final say on the state delta; duplicate/stale/unauthorized proposals produce no effect; provider text cannot create a new action type.
- **Negative checks:** an old save epoch; a destroyed actor; forged authority; a repeated request; a different tenant/world identity; an unknown action type.
- **Artifact:** versioned action contract, compatibility adapter plan, and conformance fixtures. **Phase/priority:** C7/P0.
- **Rationale:** RSI-SURVEY:R03, RSI-SURVEY:R04, REPO-AUDIT, DESIGN:core-architecture

<a id="af-rsi-032--задати-нейтральний-контракт-replay-та-доменного-checkpoint"></a>
<a id="af-rsi-032"></a>
### AF-RSI-032 — Define a neutral replay and domain-checkpoint contract

- **Dependencies:** 004, 031. **Reuse:** AF-002 events, AF-003 evidence, AF-016 memory, AF-028 recovery; game-specific application remains in the pack.
- **Outcome:** the adapter links the accepted event, causation, revision, rule digest, random draws, checkpoint, and replay receipt; the engine/pack owns canonical state.
- **Acceptance:** replay uses recorded inputs, not new LLM generation; an atomic checkpoint preserves the active rule epoch and last accepted revision; causal queries distinguish fact, belief, and an unknown link. The checkpoint has a committed revision/watermark, stable accepted jobs, and rule/schema digest; migration from a stale revision is rejected. Load issues a new session epoch; final state commit rechecks epoch/fence and atomically records delta/event/resource/job completion/dedup.
- **Negative checks:** a missing/duplicate event; a checkpoint before an incomplete transaction; a false claim of global determinism; unbounded offscreen catch-up. RC12/13/15: a lost accepted event between copy and switch; a partial checkpoint; a precheck reply before load with apply after load; a resource issued without a job receipt.
- **Artifact:** replay/checkpoint contract, injected-gap fixtures, and declared determinism envelope. **Phase/priority:** C7/P0.
- **Rationale:** RSI-SURVEY:R03, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery

<a id="af-rsi-033--кваліфікувати-повільні-agent-decisions-поза-ігровим-tick"></a>
<a id="af-rsi-033"></a>
### AF-RSI-033 — Qualify slow agent decisions outside the game tick

- **Dependencies:** 008, 009, 031. **Reuse:** AF-011 routing, AF-027 budgets, AF-044 runtime, AF-GC-041 effective provider evidence.
- **Outcome:** a bounded asynchronous inference profile with cancellation, per-session costs, request expiry, and a domain fallback signal.
- **Acceptance:** the deterministic engine does not wait for an LLM within a frame; stale/canceled replies are discarded; budget accounting includes retries and provider fallback; the qualified envelope includes latency/frame impact, source/target versions, and outage behavior. A late reply after cancel/load is also checked at the authoritative apply boundary; absence of a provider stop observer leaves effect reconciliation, rather than proof of a stopped process.
- **Negative checks:** a five-minute timeout; a missing usage receipt; callback after load; a master key in the player package; a retry storm. A successful precheck does not permit apply after the epoch changes; an unknown provider charge does not disappear from the budget ledger.
- **Artifact:** runtime-profile contract, failure walkthrough, and measurement protocol. **Phase/priority:** C7/P0.
- **Rationale:** RSI-SURVEY:R08, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery

<a id="af-rsi-034--оцінювати-domain-rule-candidates-без-присвоєння-художньої-влади"></a>
<a id="af-rsi-034"></a>
### AF-RSI-034 — Evaluate domain-rule candidates without assuming artistic authority

- **Dependencies:** 007, 016, 017, 031, 032. **Reuse:** AF-020 evaluation, AF-024 packs, AF-051 candidates; the product author defines the domain suite and human playtest.
- **Outcome:** the `world_rules` subject supports old/new rule digest, compatibility/migration, deterministic receipts, and separate human-quality evidence.
- **Acceptance:** a schema/test pass is not considered evidence of humor; Core comparison does not rewrite world state or publish the pack; the comparison decision and scoped promotion authorization are separate; the old accepted consumer pin remains functional. Rule migration switches a coherent rule/schema/checkpoint/revision/writer binding; comparison, scoped grant, and ActivationReceipt are separate. Qualification of a stale snapshot does not transfer to new live writes without checking. The domain scenario bundle distinguishes authored expected outcomes, executed state receipts, and human evidence. A consumer planner claim does not replace the independent non-game Core gate or O0→O1→O2 method proof.
- **Negative checks:** a new evaluator approves its own rule without external anchors; a rule update changes past events; rollback destroys legitimate later actions; a stale canary grant is applied to different bytes. RC07/09/12–16: revoke/ABA, migration of r10 after live r11, half checkpoint, mixed rule/state, a rewound save repeats an external grant. A completed paper story or new world-state trace is presented as Core having already improved; a new evaluator creates an easier corpus for its own evaluation.
- **Artifact:** domain-evolution integration receipt and versioned migration/recovery specification. **Phase/priority:** C7/P1.
- **Rationale:** RSI-SURVEY:R03, RSI-SURVEY:R04, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery, CONTRACT:counterfactual-evaluation

<a id="c8--довгий-дослідницький-горизонт"></a>
## C8 — long-term research horizon

<a id="af-rsi-035--перевірити-доцільність-training-time-self-iteration"></a>
<a id="af-rsi-035"></a>
### AF-RSI-035 — Assess the feasibility of training-time self-iteration

- **Dependencies:** 005, 007, 021, 027, 029. **Reuse:** AF-024 packs, AF-027 cost accounting, AF-032 qualification; RSI-SURVEY §4 and RSI-AEVOLVE.
- **Outcome:** a separate feasibility/experiment design tests whether permitted adapter/model training gives a specific Core workflow additional benefit over a frozen-weight harness-only alternative.
- **Acceptance:** the design separates feasibility, scoped pilot admission, and post-run adoption/reject/inconclusive; measured gain is not required before the first pilot; access to weights/data rights/license, resource profile, and protocol adequacy are justified before admission, and adding the design itself does not authorize training; research/controller model+harness, target/base/tokenizer, trainer/data/recipe, job, and produced checkpoint have separate exact identities, and the future output hash is recorded after creation; a standing recipe does not substitute for the reference, and hidden inheritance of checkpoint/optimizer state is excluded; checkpoint-selection/repeats/noise, actual data manifests, dev/adaptive feedback/final confirmation, and contamination/collapse controls are defined; the internal selection strategy can be a treatment under a shared external criterion, while changing authoritative acceptance requires a separate protocol, and retrospective threshold rescue is prohibited; the receiver profile defines submit/cancel/result reconciliation, exact resume is distinguished from a new warm-start plan/input/admission, and job/campaign caps and unresolved costs are preserved; the full cost ledger includes synthesis, failures/retries, evaluation, I/O/storage/export, reference preparation, and serving, and a policy change does not increase authority; future adoption requires incremental product/regression/cost evidence against a harness-only control and qualification of the exact model+adapter/base+tokenizer+harness serving bundle, while no-go/inconclusive remain fully valid outcomes.
- **Negative checks:** private player traces without consent; synthetic labels presented as external grounding; repeated leaderboard queries hidden from final-set exposure; a reference/alias silently becomes the winning checkpoint; training loss or an external target model is called an improvement to the researcher or Core without integration evidence; a post-hoc threshold accepts its own winner; duplicate submit, partial checkpoint, or weights-only warm start is called a successful resume; a new mission ID/Stop request resets charges; a cheaper harness baseline is missing; 30B/120B/550B or illustrative ratios from the paper become Core's minimum configuration/cost estimate.
- **Artifact:** feasibility memo, scoped admission specification, TrainingPlan/Run/ModelCandidate identity contracts, budgeted comparison/recovery/serving protocol, and Q04-T01–08; the decision on real training is separate. **Phase/priority:** C8/P2.
- **Rationale:** RSI-SURVEY:R09, RSI-SURVEY:R10, RSI-AEVOLVE:AE-01, RSI-AEVOLVE:AE-02, RSI-AEVOLVE:AE-03, RSI-AEVOLVE:AE-04, RSI-AEVOLVE:AE-05, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:training-research

C7 is a parallel consumer track for shared E3/E4 evidence. C8 is an optional E5 research horizon. These additions do not expand the scope of standalone Core acceptance AF-RSI-030.
