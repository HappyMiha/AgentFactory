<a id="q07-від-задуму-автора-до-перевірного-поліпшення-core"></a>
# Q07: from the creator's idea to verifiable Core improvement


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [creator-evolution.md](creator-evolution.md). Source SHA-256 (UTF-8/LF): `50b411eb1d175a8846314a35502c638cb2e356449282c92a27ef6291e0877738`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](creator-evolution.md).

Date: 2026-09-10. Status: E0 / static source audit + proposed contract. This refines the existing portfolio without a new creator pipeline, backlog IDs, or execution authority. Q07 did not run the application, a model, an engine, or a human study. Reading test assertions does not constitute a new test pass. Literary and PDF coverage are unchanged in this pass.

<a id="1-рішення-та-межа-наявного-продукту"></a>
## 1. Decision and the existing product boundary

Lokiravia connects the local path **saved brief → versioned scope → agreement → Core team gap assessment**. These are actual records and Core calls. An assessment with an empty executor pool and zero budget does not perform development. This entry point has no connected game build → PlaySession → feedback → verified V2 → restore path. A separate creator/operator prototype honestly displays Play unavailable; its localStorage recovery is not game recovery.

This yields two product decisions. First, we can study whether people understand preservation of their idea, scope tradeoffs, and why the next step is unavailable. Evidence that “the creator independently obtained the intended game” requires a separately qualified Play/change/restore path. For Core, the specific improvement subject is how its own source/harness carries **agreed requirements and their versions** into the next plan, check, and explanation. Successfully editing the Cloud UI or one scene does not itself establish Core self-improvement.

Saved original text is provenance evidence. Planned fidelity checks whether the reviewed scope preserves the idea's commitments or changes them through explicit agreement; it does not establish implementation. Realized fidelity checks the behavior of an exact completed version. A planning study uses only planned fidelity; an end-to-end claim requires realized behavior evidence. A preserved original replaces neither check. Scope may legitimately change at the creator's decision; this creates a new task version rather than retroactively correcting failure of the previous one.

<a id="2-джерельна-матриця-поточного-шляху"></a>
## 2. Source matrix for the current path

Verified snapshots: Lokiravia `c3093b2edb9ccfafaaa0b68fa3681aec87832122`, Core `472b2a45bf0473b7d66a9067ed58ca5967da385c`. Their upstream main revisions at the time of this pass were `3d42cf9606d1100ebe0887306300b5fa4aaaea5e` and `c22954f144702fdf7a3da16cf58176baa345f7c4`, respectively. Links below are immutable; hashes of the source files used and the audit boundary are recorded in `sources.json`.

| Anchor | What was checked in source | What does not follow |
|---|---|---|
| CP-01 · [entry point](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/brief_web.py#L84) | `create_app` creates BriefStore/ScopePlans and connects team and guidance routes; the API returns `build_enabled=False`, `publish_enabled=False` | Hosted tenant isolation or a completed game build |
| CP-02 · [create/edit](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/game_briefs.py#L203) | Create passes the original to Core DRAFT intake; edit retains a Cloud revision, checksum, command/revision guards, and human clarifications | A subsequent parse of only the original already accounts for every edit; create/edit authorize execution |
| CP-03 · [scope](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/scope_plans.py#L62) | Bounded Godot template, six leaf tasks, synthetic usage estimate; `write` binds an exact brief/scope revision; `execution_ready=False`, agreement without execution authority | The template generally understands any idea; the CHF0 local API assumption is the full price; a list of checks constitutes receipts |
| CP-04 · [navigation](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/static/scope.js#L31), [assessment](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/game_team.py#L78) | Scope → game-team is already connected; the snapshot is checked, and `WorkforceComposer.compose` is called with `candidates=()` and `budget=0`; the view does not permit Start/Stop | An operating AI team or admission of an actual run |
| CP-05 · [prototype](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/prototypes/creator-operator/app.js#L8) | `restore()` reads a localStorage draft; `play()` displays missing proof; fetch loads synthetic scenarios | An actual gate service, Feedback record, or SourceVersion/Build/checkpoint recovery |
| CP-06 · [brief UI](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/static/brief.js#L52), [scope UI](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/static/scope.js#L36) | The actual editor has explicit saving and historical revision viewing. Unsaved input may be lost after browser refresh/close | Prototype autosave applies to the actual editor; opening history already moves the current pointer |
| CP-07 · [domain model](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/docs/domain-model.md#L35), [evidence gates](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/docs/evidence-gates.md#L79) | Run, SourceVersion, Build, PlaySession, Feedback, and exact binding already have a shared contract model; reference policy requires separate gate evidence | Schema/fixtures alone provide trusted receipt production, a qualified engine, or an executed action |

Core has a separate local creator facade and general delivery/recovery services. They must not be confused with automatically connected Cloud routes:

| Anchor | Implemented primitive | Integration boundary |
|---|---|---|
| CP-08 · [local intake / projection](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/local_games.py#L166), [HTTP caller](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/web.py#L544) | Frozen creation input, stable command, DRAFT mission; detail/project return `latest_working=None` and a reason for missing playability | This is not a started workflow; the local API does not provide a completed game |
| CP-09 · [planning](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/game_planning.py#L143), [approval](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/autonomous_backlog_approval.py#L314) | Manual immutable HUMAN revision, source/revision guards; approval is a separate exact version/digest/owner boundary, `APPROVED_NOT_DISPATCHED` | Core's five template tasks are not Cloud's six scope tasks and are not automatically combined; a saved draft does not pass approval or dispatch |
| CP-10 · [child delivery](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/coding_delivery.py#L1099), [Temporal caller](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/orchestration/temporal/activities.py#L1332) | Current scope/fence, terminal provider stages, artifact/commit completion; integration evidence retains the simulation flag | A generic accepted commit is not an engine build/runtime/playtest. The autonomous child uses bounded authority without a per-item Founder gate; standard coding review has a different Founder path—this is not Play promotion |
| CP-11 · [checkpoint](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/mission_checkpoints.py#L203), [recovery](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/local_recovery.py#L573) | Mission/revision/Git identity, control evidence, disposition, and separate epoch/owner/fence guards | Mission recovery does not prove a usable old game build or player-state restore; the inspected local creator routes have no such restore caller |

For CP08–11, the source audit compared ten `src/agent_factory` files with the actual consumer pin: `local_games`, `game_planning`, `game_planning_web`, `mission_intake`, `coding_delivery`, `local_recovery`, `mission_checkpoints`, `autonomous_backlog_approval`, `web`, `workforce` (all `.py`). The Git diff for these files is empty. The Temporal caller is not included in this ten-file claim. Existing owners are Core AF-GC007/008/019/020/022/023, AF-AMM intake/approval/recovery, and AF048–053; duplicates under RSI names are unnecessary.

In the actual dependency, [pyproject.toml:11](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/pyproject.toml#L11), the Core pin is `480849f78957bb6b2fd7ab341300d54955aeabb8`. The [intake guide:29](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/docs/game-brief-intake.md#L29) retains a different pin, `7ec9ff33f1c4e7f2980e4b121d05f3c366acedd1`. This is source/documentation drift; qualification uses the actual pin. Q07 changes neither the dependency nor the old intake guide. Equality of selected Core files between the pin and HEAD does not prove their integration into the Cloud app.

The statically read [brief tests](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/tests/test_game_briefs.py#L44), [scope tests](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/tests/test_scope_plans.py#L90), and [team tests](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/tests/test_game_team.py#L36) describe persistence, stale guards, idempotent agreement, and assessment without assignments/leases/attempts. [Prototype tests](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/tests/test_creator_flows.py#L122) expect Play to be unavailable. These assertions help define boundaries; Q07 did not execute them or treat them as live game acceptance.

<a id="3-тертя--чинний-власник--reusable-core-capability--приймання"></a>
## 3. Friction → existing owner → reusable Core capability → acceptance

These are acceptance deltas to existing work, not new tasks or dependencies. Core owns general execution/evidence/experiment mechanisms; Lokiravia owns creator outcomes and its UI; the pack owns the world's causal and artistic properties.

| Problem or uncertainty | Existing owner | What must be reused / checked |
|---|---|---|
| The original says one thing, the reviewed brief/scope includes clarifications, but execution reads only the original | AF-CLD-002/007/008/013; Core AF-009/013, RSI025 | Projection uses original digest **and** exact reviewed brief revision/content digest **and** agreed scope revision/policy/commitments. Tenant/Project/SourceVersion mapping is explicit. A stale or conflicting snapshot stops handoff; human choices do not disappear on reparsing |
| The creator does not understand what was saved or what the small scope excluded | AF-CLD-004/007/008; RSI018/026 | Saved/unsaved/history are distinct states; assumptions/exclusions are visible. Rejecting both scope alternatives preserves the original idea. Fidelity is checked against agreed commitments, not merely the original checksum |
| Agreement and Prepare are interpreted as Start or a paid reservation | AF-CLD-009/013/019; Core routing/workforce/budgets, RSI008/018 | Actual dispatch requires an actual qualified route/profile, exact scope, current execution/funding authority, and cost envelope. Planned token shares are not reservations. UI shows missing prerequisites, refusal, and absence of execution |
| “Ready,” task completion, or an attractive image stands in for a played version | AF-CLD-006/010/011/014/015; Core evidence/coding delivery | Authenticated producers → exact SourceVersion/Build/profile receipts → gate decision → actual open/exit receipt. Eligibility is separate from execution and current availability/access. Private Play does not wait for Publishable/Sellable |
| Feedback about V1 is silently applied to V2/latest | AF-CLD-017/018; Core versioned context/intake, RSI025/026 | Feedback is bound to the actual PlaySession/Build and scope; a change proposal has an explicit target source/version and conflict disposition. A note without play is valid creator input, but not playtest evidence. Feedback does not authorize a new build |
| Restore displays “successful,” but the required artifact is unavailable | AF-CLD-012/018; Core recovery/checkpoints, RSI029 | Explicit target and operation type; completion follows a verified usable-target receipt. Unknown/failed does not become success. CLD012 requires a new restore/version and audit records with explicit target SourceVersion/Build, lineage, and activation result; a simple pointer rewind is insufficient. History, costs, and current authority are preserved; refreshing history is not artifact restore |
| An improved score hides loss of NPC freedom, quiet play, or the creator's intent | AF-LW-001/013/024/025; RSI007/026/027 | Fidelity/consent/recovery floors alongside task outcome. A higher goal score obtained by coercing NPCs is rejected. Creator, player, and Core outcomes have separate claim scopes |
| Leaf tasks finish faster, but the creator does not obtain the needed result | RSI025/026/027, AF-CLD-020 | Opportunity classifies the cause: UI/version binding, Core context, unsupported scope, evaluator, or unknown. Compare the exact candidate subject; a direction may be rejected without rewriting the old criterion |

The actual source/build lifecycle belongs to CLD012/018. Hosted identity/serving additionally depends on CLD021/030/031. W0 may use a manually defined Godot scene through a qualified Play/checkpoint adapter: universal autonomous generation, World023 rollout, and World027 offline season do not become its prerequisites.

<a id="4-projection-і-чотири-різні-відновлення"></a>
## 4. Projection and four distinct forms of recovery

A build/change plan requires a versioned input envelope with tenant/project, original source, reviewed brief, agreed scope, requirements/commitments, exact source target, and evidence profile. Its authority comes from the current service context; the envelope itself creates no grant. The downstream receipt references this envelope and the artifact actually executed. A new revision does not redefine previous receipts. Restore under CLD012 creates a new version record and audit record referencing the selected historical SourceVersion/Build. The old Build and its evidence remain bound to the original SourceVersion. If restore creates a new SourceVersion, its Build/Playable qualification is recorded separately under the current exact-binding contract; identical bytes do not permit rewriting old receipts onto a new ID. Feedback on V1 may be useful for V2, but transfers through an explicit versioned decision with a currency check; “always latest” is not a universal fix.

| Action | What it restores | Required future evidence and boundary |
|---|---|---|
| Draft resume / history view | Saved brief/scope or viewing an old record | Visible revision and saved status; unsaved input is not promised to survive without a mechanism. A view does not change the working artifact |
| Creator version restore | Working SourceVersion/Build selection | New version/audit record with exact target SourceVersion/Build, current permission, compatible usable artifact/profile, completed restore receipt, and opening check. Old artifact receipts retain their original source identity. Previous failed V2 and its costs remain in history. A missing target needs an explicit recovery disposition, not a fictional pass |
| World save/load | Domain checkpoint/state/rules/jobs/session | Qualified adapter under [Q05](recovery-contract.en.md) and [Q02](identity-continuity.en.md); a late response from an old session is rejected at final apply; accepted effects are not duplicated. Source restore alone does not promise compatible save migration |
| Core generation rollback | Platform's active source/harness/optimizer binding | Separate scope grant, coherent activation, and recovery receipts. Does not erase costs, revocations, or historical world events; World/Cloud restore has no implicit authority to replace Core |

The new version/audit-record requirement comes from [current AF-CLD-012](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/docs/backlog.md#L401). The card does not specifically require a new SourceVersion for every restore; the particular version contract decides this while preserving exact source/build identity and active work.

An old verified game may remain available while a new one is being built. If the old target is now unavailable or incompatible, the system honestly displays that limitation and permitted recovery options. “One action” is assessed through a completed result and the need for manual repair, rather than the number of buttons drawn.

<a id="5-один-наскрізний-паперовий-прохід"></a>
## 5. One end-to-end paper walkthrough

This document's original fixture: a creator wants a peaceful 2D scene near a bench with two NPCs, an unusual everyday use of an object, NPCs' right to refuse, and the ability to save the game. This is neither a participant's brief nor a book quotation. Agreed paper-case commitments: a peaceful path; a real change in available state; refusal without coercion. NPC logic may be authored manually; the fixture does not claim a new agentic runtime is available in the current scope template.

1. **Brief.** Save the idea, explicitly change one field, and check the revision and original provenance. Distinguish saved from unsaved. This is a future verification scenario for the actual component, not a Q07 report of running it.
2. **Scope.** The challenger design offers two small ways to test the idea: bench/cover or workshop/object. Both explain commitments, exclusions, and unsupported capabilities. Two alternatives are an experimental proposal, not an existing feature. Markers instead of an unusual use are not declared equivalent without the creator's decision.
3. **Agreement / handoff.** Agree to the exact saved scope revision. Negative branch: brief changed in another tab → stale agreement rejected without losing unsaved input. In the current profile, the result is an agreed plan with missing execution readiness. **This is the boundary before future qualified build/Play.**
4. **V1 / Play.** In the future, open exact verified V1 with controls/Exit and a session receipt. In the paper/prototype version, V1 is only hypothetical and Play evidence is absent. Physical state, consent, explanation, and goal outcome are assessed separately under Q06.
5. **Feedback / V2 proposal.** Authored feedback fixture: “I want the reason for refusal to be clearer.” Bind it to V1; show target source, affected commitments, scope/risk, and a new estimate. The proposal improves explanation and the next available choice. A variant in which the NPC always agrees violates the fidelity floor.
6. **Failed V2 / restore.** If V2 fails a behavior check or the creator rejects it, create a new restore/version and audit record to return the working selection to explicit V1 under current authority while retaining the original SourceVersion/Build evidence binding. Actual target/restore/open receipts are required; V2, feedback, and costs remain in history. A separate W0 save/load with a pending reply checks Q05; source-version restore does not substitute for it.

This is an open authored walkthrough. It is not a hidden benchmark, actual user feedback, an executed game, or evidence of market demand.

<a id="6-як-вимірювати-поліпшення-без-підміни-задачі"></a>
## 6. Measuring improvement without substituting the task

The first study has two levels. A **planning study** is possible after qualification of the current local profile: original/edited brief, saved status, scope tradeoffs, agreement, and understanding a blocked next step. There is no “time to completed game” metric for an unavailable path. An **end-to-end creator study** is admitted after actual qualified build/Play/feedback/restore on exact baseline/challenger bundles. The pilot's 8–12 creators in the [delivery plan](delivery-plan.en.md) are a plan for qualitative problem discovery with people, not a power calculation or completed experiment.

Before starting, select one primary axis: independent completion or reduced effort at non-inferior fidelity for the relevant level. For planning, this is review of planned commitments; for end-to-end, realized behavior of the exact build. A planning-only pass neither requires a game that has not been created nor receives a claim about its fidelity. Creator changes to scope remain separate decisions. Floors and incomplete/inconclusive rules are fixed before comparison; greater speed through unapproved simplification is rejected.

| Axis | Operational definition |
|---|---|
| Task / version | Initial intent, agreed commitments, brief/scope revision, baseline/challenger subject, and qualified profile. Different people's own briefs are not called identical tasks merely because of length |
| Completion | Separately: brief saved, scope agreed, build admitted, checked build opened, requested behavior accepted, change/restore completed. N/A, blocked, abandoned, failed, unknown, and completed are not merged; scope agreement is not a played game |
| Fidelity | For each commitment: preserved / changed by the creator / violated / unknown, with version-bound evidence and an explicit planned/realized level. Truthful preservation of the original does not establish realization of its content |
| Assistance and time | Independent versus assisted outcome; what the facilitator did. Active creator effort, wall time, queue/build/model waiting, and interruption are separate; failed and incomplete attempts are not excluded to improve the average |
| Recovery | Exact requested target, actual disposition/receipt, time to usable state, manual repair, preservation of required records. Green UI without target proof is unknown, not success |
| Cost / missingness | Complete permitted cost including failed attempts/retries/retrieval/review and unresolved usage. Consent-scoped start/finish/stop/feedback denominators; missing/withdrawn values are not filled with ratings, and refusal does not reduce access |

Baseline and challenger receive comparable starting states/rights/budget. A qualitative within-person study controls order and learning; the same brief after showing the first result already has carryover. An unavailable path does not become independent completion through facilitator assistance. A statistical claim requires a separate sampling plan and fresh confirmation; this open fixture is excluded from holdout.

<a id="7-конкретна-гіпотеза-самовдосконалення-lokvetia-core"></a>
## 7. A specific Lokvetia Core self-improvement hypothesis

**Hypothesis, not yet tested:** a new generation of Core's own context-selection source/harness uses stale requirements less often in a change plan, preserves agreed commitments, and does not exceed accepted cost/latency/regression floors.

Chain: permitted creator report → RSI025 opportunity with cause checking → exact Core candidate → RSI003/007 protocol → baseline/challenger execution → external version/behavior evidence and RSI026 product signal → accept/reject/inconclusive → separate promotion. If the cause is Cloud rendering, the candidate belongs to Cloud; if it is a new world rule, it belongs to the pack. Their gain cannot be attributed to unchanged Core.

Baseline and candidate see the same available original/reviewed/scope/version context. Comparison includes stale/conflicting feedback, an unavailable target, an agreed scope change, and a simple manual/reference path. Additional retrieval, model/environment changes, and review time count as costs or confounders. Automatic selection of latest and unlimited context are not accepted in advance as the correct strategy. The new method may not help: RSI027 then proposes better version explanations or abandoning the hypothesis while preserving the initial verdict.

This creator case provides candidate motivation and consumer evidence. Standalone Core030 still requires independent non-game families; recursion O0→O1→O2 requires a separate method proof under [Q03](evaluator-succession.en.md). Q08 must define fresh non-game task families, not rename this scene. The same receipt may have several explicitly stated analytical roles, but is not counted as several independent observations.

<a id="8-відкриті-статичні-controls"></a>
## 8. Open static controls

The expectations below are written, not executed. P09 refers to the already defined W0/Q05 check and creates no new runtime mechanism.

| ID | Counterexample | Expected decision |
|---|---|---|
| Q07-P01 | Scope is faster through hidden removal of the peaceful unusual solution | Fidelity floor violated; an explicit new task does not rescue the old task's result |
| Q07-P02 | Facilitator fixes the plan themselves, but outcome is marked independent | Assisted outcome retained separately; time and assistance visible |
| Q07-P03 | Original preserved, but human edits/agreed scope absent from execution projection | Handoff not accepted without exact reviewed-requirement binding; original checksum insufficient |
| Q07-P04 | Scope agreement or gap assessment launches a paid build | Reject dispatch without separate current execution/funding authority and qualification |
| Q07-P05 | Play opens V1, feedback is assigned to V2, planner edits latest | Preserve played/feedback/target identities; explicit conflict/transfer decision, not silent transfer |
| Q07-P06 | V2 achieves the goal better because the NPC cannot refuse | Commitment/consent floor violated; score does not justify acceptance |
| Q07-P07 | Restore shows success, but exact V1 is unavailable | Unknown/failed until usable-target proof; show a permitted recovery disposition |
| Q07-P08 | Restore only moves a pointer without a new version/audit record, erases V2 costs/feedback, or implicitly rolls back world save/Core | New restore/version and audit records reference the exact target; old receipts are not rebound. Subject/scope explicit, history/costs/current authority preserved; other restore operations remain separate |
| Q07-P09 | Old model reply passes precheck, then applies a duplicate effect after load | Current Q05 final-apply fence and coherent state/event/job/dedup reject stale apply |
| Q07-P10 | Incomplete sessions removed, missing feedback becomes positive, leaf completion is called a game | Denominators/uncertainty and stage outcome preserved; product gain not demonstrated |

Q07 refines Core025/026, World013/025, and the World030 evidence boundary in existing cards. IDs, dependencies, W0, and standalone scope are preserved. CLD007/008/015/017/018/020 remain the owners of creator delivery; this contract does not move them to done.
