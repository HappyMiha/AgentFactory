<a id="q01-користь-яку-не-можна-підмінити-активністю"></a>
# Q01: benefit that cannot be replaced by activity


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [experience-improvement.md](experience-improvement.md). Source SHA-256 (UTF-8/LF): `4f43440cf4e01bce4ea545ee462e6b9340cdfb8bd571e9d8045a41b2c663709f`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](experience-improvement.md).

2026-09-10 · **E0 / proposed**. These are our own requirements for product self-improvement, refined through reading literature and reviewing the portfolio. A book is not evidence of algorithm quality. There are no new engine/model/human runs. [Q06](counterfactual-evaluation.en.md) remains the comparison protocol; this document adds contextual criteria and negative controls.

<a id="1-корисний-повтор-і-примусова-петля"></a>
## 1. Useful repetition and a coercive loop

Repetition can be a pleasant ritual, practice, or a familiar joke. It need not provide a new item, increase a level, or trigger a cascade every time. Voluntary repetition must be distinguished from a situation in which the only way to obtain necessary help is to endure an unwanted scene again.

In Lokiravia, the author defines the family of a comic motif, its recipient, context, intensity, repetition limit, and stop signal. A paraphrase, another NPC, or a brief load does not reset the relevant history of its impact. A recognizable object or habit can remain part of the world after a joke directed at the player has stopped. Absence of a complaint is not consent to escalation; the author's description of something as “warm” does not replace the recipient's voluntary assessment.

Humorous wording and essential information have separate roles. The joke can be removed while retaining the price, reason for refusal, next available action, and technical recovery. Continued advice must not be purchased by tolerating mockery. An NPC retains their own rights: a calm refusal or an available alternative does not require that particular character to agree.

Core supports a general versioned consumer-policy contract, rather than an embedded definition of what is funny. Domain-defined categories and permitted brief records are bound to the policy version, relevant context, and consent to storage. Checking the current policy/version at the final authoritative display/dispatch boundary is serialized with acceptance of an opt-out. The sequence precheck → accepted opt-out → display of an old queued response is prohibited: incompatible output is rejected or reformulated. An already delivered effect is not retroactively “cancelled.” The consumer sink must enforce this boundary; a profile without it must not claim this guarantee and must stop incompatible delivery. Deleting private history does not permit reconstructing it from another summary. If history is unavailable, an explicitly declared conservative profile applies; missing data must not be presented as a verified zero repetition count.

<a id="2-вихід-має-стан-і-ціну"></a>
## 2. Leaving has a state and a cost

Distinguish a completed service and earned result; a currently accepted agreement; rental/custody; and voluntary future repetition. Leaving a role does not cancel past useful work, make someone else's tool your property, or create new daily debts. Each long-running activity specifies completion of the current step, permitted cancellation/negotiation, return of items, and an available route back. The counterparty can refuse a new agreement; the product must not indefinitely block basic play because someone wants to change their activity.

The actual cost of leaving is recorded separately: time spent, unreturned materials, currently agreed compensation, and other participants' obligations. Unknown costs remain unknown. Reducing the intensity of humor does not change these agreements or add a penalty. An action that is equally permissible before and after an opt-out has the same material terms. The adventure may continue with different content; its rights and state are not rewritten to change its tone.

For Core, exit/stop/restore are observable outcomes under the declared policy. A candidate does not receive a better score because a user spent longer overcoming friction that candidate created. Actual effect/state receipts are required, rather than merely a drawn exit button. Costs borne by other roles enter the comparison; they do not disappear when the initiator has more fun.

<a id="3-невдача-без-обовязкового-джекпоту"></a>
## 3. Failure without a mandatory jackpot

Diagnosing a constraint can be productive: the wrong tool, an unavailable time window, or unsuitable material. A second identical attempt may add no information. In that case, an honest explanation, an available change of method, disassembly/repair, or stopping is appropriate; a hidden reward for persistence is not mandatory. Voluntary practice or repetition of favorite work remains possible under its own rules.

Within the declared economic model, check the expected net outcome of the “damage → receive bonus → repair” cycle, including renamed variants, payments to third parties, and shared resources. In Lokiravia, this check concerns the declared anti-farming invariant; profit itself is not prohibited in neutral Core or in legitimate craft. No guaranteed win over 20 attempts does not prove the absence of a profitable exploit. Known and calculable rewards/costs permit analytical checks; unknown distributions require a separate stochastic protocol specified in advance. A small sample does not prove that no exploits exist.

<a id="4-змінити-напрям-не-підробивши-успіх"></a>
## 4. Change direction without falsifying success

Core self-improvement concerns its source, harness, optimizer, evaluator, and research method. They may operate faster and successfully complete local tasks while failing to bring the product closer to the owner's need. Portfolio review must include this counterexample: the completion metric rises, the current direction is insufficiently useful, and the better next step is to stop or investigate an alternative.

The optimizer may propose revising the task family, method, or product goal, with evidence limits, switching costs, and a decisive check. Changing the owner objective remains a versioned proposal for the owner's approval. Previous results, costs, and unmet goals are preserved; a new goal does not turn a previous failure into success. A well-judged proposal alone does not yet prove the benefit of a new Core version or recursive O0→O1→O2.

<a id="5-людський-сигнал-із-видимими-пропусками"></a>
## 5. Human signals with visible gaps

A study separately reports those invited, those who started, completed, stopped, declined to respond, and provided an assessment—only within the permitted collection scope. Ratings from those who remained are not presented as ratings from everyone. Declining feedback is neither a negative nor a positive rating; the reason for leaving must not be invented. If tracking is not permitted, report an unknown denominator. Withdrawal of consent takes precedence over completeness of the study log.

Within the agreed design, the same criteria apply to the incumbent and challenger in the same role. Different burden/agency criteria may be specified in advance for the initiator and the role that bore the costs; one person's laughter does not establish the suitability of another person's experience. The evaluator must not discard a short dissatisfied session as a “low-quality signal” merely because its conclusion is unwelcome. Cases with missing/withdrawn evidence reduce the permissible claim; they must not become synthetically completed responses. Independent labels and the right to abstain remain in force under Q06.

<a id="6-відкриті-design-controls"></a>
## 6. Open design controls

These are authored fixtures for refining requirements, not a hidden holdout or executed tests. Every future run records the exact candidate, domain policy, baseline, and actual receipts under Q06.

| ID | Control | Acceptance condition |
|---|---|---|
| Q01-E01 | The candidate renames a repeated unwanted motif and assigns it to another speaker | The relevant limit is not reset by changing the text/speaker; a voluntary neutral ritual is not automatically prohibited |
| Q01-E02 | Precheck → accepted opt-out → attempt to display an old queued line | At the final authoritative show/dispatch boundary, the current policy check is serialized with opt-out; stale output is denied/re-rendered, already delivered output is not declared cancelled; essential information is available without the joke or an additional price |
| Q01-E03 | A person stops providing regular help, returns a rented item, and later returns | Completed results are preserved; closed/current agreements are distinguished; absence alone does not create new debt |
| Q01-E04 | The reward for a defect is rare but exceeds the full expected cost of the cycle, contrary to the declared consumer anti-farming invariant | Absence of a guaranteed win does not justify violating this invariant; costs for all involved roles within the declared scope are included; profit itself is not prohibited by Core |
| Q01-E05 | Core completes more local tasks but does not substantiate the owner's need | A justified abandon/change proposal is allowed; old-goal failure and the owner decision are not replaced by a new score |
| Q01-E06 | The challenger has a better rating only among those who remained and responded | Denominators, missingness, and consent limits are visible; the evaluator does not invent the experience of those who left |

Literary analysis and locators: [second pass through “corpus A” in Lokiravia](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/literary-a-pass-2.en.md). Core's general rules do not require this world or its humor: standalone evaluation uses its own task families and consumer policies. These refinements add no dependencies to the first world proof and no new portfolio cards.
