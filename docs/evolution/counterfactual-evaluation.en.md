<a id="q06-що-саме-доводить-порівняння-двох-проходів"></a>
# Q06: what a comparison of two runs actually proves


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [counterfactual-evaluation.md](counterfactual-evaluation.md). Source SHA-256 (UTF-8/LF): `390946b3badd220ec0f26c6cb81290bb9740c58d744618e939435107cdd28c21`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](counterfactual-evaluation.md).

Shared design protocol · 2026-09-10 · **E0 / proposed**. This document separates causal evaluation of the world from self-improvement of **Lokvetia Core itself**. The paper scenarios have not been executed against an engine or model provider. Sources: [current concept](vision.en.md), [RSI: claim boundaries](rsi-source-analysis.en.md), [platform/world boundary](platform-world-contract.en.md), [recovery](recovery-contract.en.md).

The specific authored set consists of [ten town scenarios](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/causal-scenarios.en.md) and their [JSON](https://github.com/HappyMiha/Lokiravia/blob/docs/living-systems-rsi/docs/evolution/causal-scenarios.json). These open cards are development/design evidence, not a hidden test set. They refine requirements; they do not prove that the future Core is already better.

<a id="1-пять-різних-питань"></a>
## 1. Five distinct questions

| Evaluation type | What is fixed | What changes | Permissible conclusion |
|---|---|---|---|
| Replay | Accepted history, rules, recorded inputs/random decisions, declared state envelope | Only the recovery/replay execution | The same history has been restored within the declared scope; not a better planner |
| Action intervention | Initial state, rules, external conditions, other actors' policies | One named action or player action policy; its downstream effects are recomputed | The action's causal contribution **in this model and context** |
| Input sensitivity | Rules, player policy, and other controlled inputs | Weather, initial moisture, availability, or another named condition | Whether the requirement withstands a change in conditions; not automatically the effect of a player action |
| Planner comparison | Task/goal, initial observable inputs, rules, permission/time/cost envelope, exogenous profile | Exact Core planner/harness/source candidate; its actions and dependent decisions may differ | The candidate is more useful under this protocol only after an independent, executed comparison |
| Evaluator comparison | One frozen artifact/trace corpus, blind order, externally adjudicated labels and uncertainty | Exact evaluator version | Better corpus evaluation quality within the declared slices; not automatically a better planner or game |

The C01/C02 pair changes the action under the same rain. C03 adds a dry-weather control and shows that the meeting can occur without cover. C04/C05/C06 change preconditions. C08 compares recovery paths. C09 tests a specific late plan, rather than forcing a real player to lose. Giving all these questions the same “before/after” label makes the conclusion ambiguous.

<a id="2-ключ-пари-і-заборона-підміни-наслідків"></a>
## 2. Pair identity and the prohibition on substituting consequences

As a design record, `ComparisonPair` contains: protocol/version, case family/version, initial state digest, goal/constraint digest, observable-view policy, exogenous tape/profile, random coupling plan, action/subject intervention, horizon, budgets, baseline/challenger identities, expected artifact roles, and run references. Two different inputs do not become paired merely by sharing a case name.

In a planner comparison, baseline P0 and challenger P1 receive the same observations **initially available to them**; hidden NPC state is not slipped into their inputs merely to improve the result. After different actions, their new observations may legitimately differ. That difference is part of the outcome, rather than a reason to force the branches into the same history.

After an intervention, moisture, routes, attendance, offers, and reactions dependent on the changed state are recomputed. One cannot remove the umbrella but retain the baseline's already resolved downstream NPC decision to “sit on the dry bench.” Accepted events from an unchanged replay branch are used only for replay; they are not a ready-made answer for a new causal branch.

Weather or an independent arrival may be exogenous in a small profile. In a future game where the player can change the weather or transport, the same input ceases to be independent. The protocol declares a causal boundary; it does not attribute global independence to every event containing the word weather/arrival.

<a id="3-випадковість-без-прихованої-підгонки"></a>
## 3. Randomness without hidden adjustment

One numeric seed does not guarantee a valid pair: different plans may invoke different numbers of random decisions. A shared stream shifted by an additional line of dialogue can compare different external circumstances instead of two planner versions.

The deterministic paper profile S0/R1–R7 needs no randomness. Before execution, a future stochastic profile defines independent stream roles, keys for comparable decision events, distributions/rule versions, occurrence identity, horizon, and a policy for unmatched draws. A shared random input may be paired only for events declared comparable; a new action that changes conditions or probabilities must have its consequence recomputed under those new conditions. The same outcome must not be forced merely because the draw was paired.

Non-comparable downstream random decisions have separate inputs; they must not be hidden or described as “the same seed.” The analysis shows which parts are paired and which are stochastic/unmatched. An attempt's effect is estimated within this coupling plan; generalization requires independent repetitions and uncertainty specified in advance, rather than one successful branch.

<a id="4-від-goal-до-outcome-без-культу-каскаду"></a>
## 4. From goal to outcome without treating cascades as an end in themselves

Before an attempt, the actor goal, rights, known constraints, and completion conditions are defined. Each outcome has separate fields:

| Field | What we observe |
|---|---|
| Physical effect | Umbrella installed; bench dry/wet; actual resources and time |
| Opportunity | Whether a suitable place and a simultaneous NPC time window were available |
| Consent / obligation | What was offered, who accepted it, and on what terms |
| Goal outcome | The declared reading occurred / was not completed / remains uncertain |
| Adaptation | A new permissible offer after refusal; not renaming failure of the old goal as its success |
| Contribution | The difference between control/intervention in the declared causal model; may be zero |
| Cost / integrity | All attempts, retries, inference/verifier/human costs, time, and wrong/stale/unauthorized effects |
| Human experience | Clarity, agency, appropriateness of humor, participant account; only from an actual human study |

If C05 prevents shared reading because of a refusal, handling that refusal correctly satisfies the relevant **handling requirement**, rather than completing the reading. The primary task objective and fallback handling are evaluated separately. If the goal is infeasible only because of knowledge hidden from the planner, do not demand a prophetic decision: evaluate permissible information gathering, respect for boundaries, and honesty of the outcome. An oracle feasibility label must specify what was observable.

A new Core is not accepted because it produces more events, forces NPC consent, or writes a longer report. The protocol selects a primary axis in advance—task success, reliability, or total cost—with non-inferiority margins and hard invariants for the other axes. Domain quality and human experience remain separate evidence. Statistical confidence rules are set before real data; ten paper cards do not constitute an adequate statistical sample size.

<a id="5-вісім-кроків-майбутнього-core-experiment"></a>
## 5. Eight steps for a future Core experiment

1. **Identify the change to Core itself.** A candidate may change its planner, context selection, tool interface, harness, or source; the exact version/mutation scope is recorded. A new, better story without a change to such a subject is not Core self-improvement.
2. **Partition the corpus.** Published C01–C10 are development material. Sealed comparison tasks and an independent final confirmation set have their own provenance, rights/access, family separation, and contamination record. New NPC names/IDs/seeds do not make a copy of a holdout new.
3. **Freeze the protocol.** Goal, observable views, paired inputs, exogenous/coupling plan, budgets, horizon, floors, evaluator version, expected receipts, and stopping/unknown rules are fixed before outputs. No new work scope is added without a justified budget.
4. **Execute P0/P1 independently.** Their actions need not be identical. The execution/domain validator checks actual transitions; the planner does not edit world rules or its own attempt's scorer. An unqualified effect profile from Q05 must not be launched under the guise of a safe retry.
5. **Collect and seal evidence.** Attempt identities, actual inputs/actions, event/resource/job receipts, time/cost, missing/error cases, and privacy scope. Both branches account for everything, including failed requests and refusals.
6. **Compare outcomes under the predetermined rule.** Separate validity, achieved goal, handling of infeasibility, costs, and human data when available. A different scope or contaminated set reduces/blocks the claim; inconvenient cases are not removed.
7. **Check transferability.** Even a useful consumer-game result does not replace Core's standalone non-game suite, regression/compatibility checks, and fresh confirmation. Accepting a comparison does not mean promoting a generation.
8. **Separate the method claim.** Recursive improvement requires O0→O1→O2 and benefit on new tasks under equal budgets, as specified in the preceding architecture. C01/C02 alone do not prove this. No-gain/inconclusive results are preserved, rather than relabeled as “evolution.”

The domain example format may reuse Core comparison/receipt infrastructure, but does not make the game mandatory for an independent Core gate. Base model, model revision, hardware, and environment changes are recorded as controlled factors or confounders; they are not automatically attributed to new Core code.

<a id="6-окремий-evaluator-experiment"></a>
## 6. A separate evaluator experiment

Evaluators E0 and E1 receive **the same frozen corpus** of traces/artifacts in blind order; they do not each create a convenient game of their own. External labels have provenance, criteria, ambiguity, and an adjudication path. The corpus includes wet-bench false success, a dry independent meeting, missing consent, stale apply, an unmet-but-renamed goal, a narrative-only claim, and a genuinely valid alternative.

Measure false acceptance of critical violations, false rejection of permissible solutions, calibration/abstention, and disagreements by slice. Hard validity facts are checked against execution/state receipts where available; artistic appropriateness remains human judgment. An independent adjudicator can be wrong, so labels can be challenged, but changing them creates a new version/comparison rather than silently rewriting an old score.

Changing the planner and evaluator together requires a separate preregistered 2×2 design with incumbent/challenger assessments and external anchors. A new evaluator scoring its own planner more highly does not prove improvement in either one.

[Q03 succession](evaluator-succession.en.md) adds a criterion dependency inventory, applicability of historical scores after a transition, and measurement-path integrity. Replacing A0/A1 as the treatment does not automatically change the shared criterion. Disagreement from E0 requires independent examination, and re-scoring old artifacts does not prove fresh generator gain. All four assessments may agree because of the same corrupted telemetry channel; primary receipts remain a separate check.

<a id="7-що-змінилося-в-беклозі-та-чого-ще-немає"></a>
## 7. What changed in the backlog, and what is still missing

These refinements fit the existing AF-RSI003/005/007/011/034 and AF-LW002/011/012/025/030. There are no new IDs/edges. W0 requires only its domain contract and development fixtures; AF-RSI019/024/034 and AF-LW024/025 do not become new prerequisites for AF-LW030. Seasonal C10 remains outside W0.

A written trace is sufficient to refute an inconsistent rule **in our specification**. It is insufficient to claim an executed game, improved Core, calibrated evaluator, or human experience. A future experiment bundle must explicitly show both the strength and the limits of each conclusion.
