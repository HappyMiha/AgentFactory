<a id="що-саме-випускаємо-спочатку"></a>
# Exactly what we release first


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [first-releases.md](first-releases.md). Source SHA-256 (UTF-8/LF): `ceeb0131abf203171b54e32318dd1ba4bb8d28d9f7b67fe792b9b7c12b06e88a`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](first-releases.md).

Revision 2026-09-10 · documentation plan. None of the releases described here has been accepted yet. C-/L-/W- designations are planning names, not new task IDs or SemVer tags. The [single order of 280 requirements](implementation-order.en.md) and [exact sets and dependencies](implementation-order.json) are shared by both repositories.

The first deliveries produce five concrete outcomes: Core performs a controlled engineering task; the creator saves and agrees on an idea; the workbench compares Core versions; the creator produces three small real games with a complete change cycle; and a separate living scene proves causality, agency, and memory. Full self-modification of the Core product and recursion of its method follow through their own verifiable releases.

| Priority | First outcome | Exact requirement map | Acceptance boundary |
|---|---|---|---|
| 1 · C-PILOT | A useful patch to an external project through controlled Core | 36 legacy tasks in the closure | Qualified Windows capability path; not full completion of all 36 |
| 2 · L-PREVIEW | Saved idea, agreed scope, truthful blocked next step | CLD009 closure: 001–005,007–009; full M0 separately includes 006 | Subsets of CLD004/007/008/009; not Play or M1 |
| 3 · C-WORKBENCH | Verifiable version comparison, cost, and honest rejection | RSI001–011,015; 12 cards | Every closure criterion and W01–W07; no Core self-promotion yet |
| 4 · L-CREATOR | Three games: Play, export, feedback, v2, restore | CLD001–020; 20 cards | Full existing CLD020 and integration receipts |
| 5 · W-FIRST | One player lives through a small causal story | 12 LW +10 RSI; 22 cards | Full LW030, separate world profile, and actual gameplay |

Priority does not create a barrier between independent work. L-CREATOR and W-FIRST consume shared build/Play capabilities but have different acceptance gates. Core030 waits for neither game. Closure counts must not be summed as an amount of new code: shared requirements count once in the 280-item view.

<a id="фактична-основа-та-незакрита-кваліфікація"></a>
## Actual foundation and outstanding qualification

Static baseline: Core `38280160e8cabfcb64f325cd5c1c5f8aa6f67ab7`, Lokiravia `24ecb1e931d7df6c90900bb31e08a1e5faa13ce1`; these contain the preceding source audits and source cleanup. The canonical-manifest snapshot is pinned in JSON. No product applications, models, or engines were run during this pass.

| Existing foundation | How we use it | What remains unproven |
|---|---|---|
| Core durable execution, candidate/worktree/validator, approvals, routing, cost/recovery primitives | Inspect the exact implementation, requalify the required path, fill gaps under existing AF/GC IDs | Historical claims of 57 implemented AF tasks are not current live GA; the Windows writable blocker is described below |
| Autonomous Mission foundations 001–019 and later partial seams | Reuse lifecycle/authority/evidence components | Not all 48 AMM requirements are accepted; full once-approved autonomy has a separate delivery |
| Lokiravia saved brief→scope→agreement→Core team gap assessment | Complete and qualify the existing editor without duplicating Core planner/runtime | Actual dispatch/Build/Play/feedback/usable restore remain unproven; the unsaved-persistence gap remains explicit |
| 35 RSI +30 LW proposed design cards | Implement under exact dependencies, staged experiments, and gates | Documentation and synthetic checks do not prove self-improvement or a living game |

The Lokiravia package actually pins Core `480849f78957bb6b2fd7ab341300d54955aeabb8`. This is dependency identity, not qualification of a newer Core branch. Before integration, CLD003 checks required capabilities against this pin; a future pin change needs separate consumer evidence. Outdated installation prose in game-brief-intake was corrected; historical capability maps were not rewritten without a new audit.

<a id="що-власник-отримує-по-черзі"></a>
## What the owner receives, in sequence

| Release | Visible outcome | What must become proven |
|---|---|---|
| **C-PILOT** | “I describe a small software change and receive a verified result, explanation, and control.” | Core performs real non-game work in a specific supported environment; an error is not hidden behind an attractive report. |
| **C-WORKBENCH** | “I can test whether one Core version is better than another and see the cost, failures, and uncertainty.” | A reproducible experiment and independent evidence exist; the outcome may be rejection of the change. |
| **C-SELF** | “Core found, verified, and retained useful changes to its own code and way of working.” | Full AF-RSI-019: own source and own harness, real tools/providers, measured benefit, a failed candidate, and recovery. |
| **C-METHOD** | “Core also improves the way it searches for the next improvement.” | Full AF-RSI-024: method O1 actually participates in creating O2; benefit is not explained by substituting the evaluator. |
| **C-RSI** | “Core self-improvement has become a verified property of a standalone product.” | Full AF-RSI-030: benefit across two independent non-game families, own source/harness/optimizer, user needs, and sustained reliability. |

Lokiravia, a playable world, and model training are not prerequisites for these five outcomes. Core can use an authorized AI provider without depending on the Lokiravia product; “standalone” does not automatically mean local-only inference.

<a id="c-pilot--контрольована-engineering-робота-на-windows"></a>
## C-PILOT — controlled engineering work on Windows

**Target environment:** Windows, one local operator, one Core instance/SQLite authority, a local Git/Python project, installed and explicitly qualified tools, a bounded writable worker, and an independent reviewer. Exact Windows/Python/Core/Hermes/Codex/model/profile versions, resources, and sandbox are recorded in release evidence. This is a target, not an already supported combination.

**Initial scope:** a small change in an external fixture repository—for example, correcting a data-normalization utility's behavior under an agreed rule. The result is a specific candidate commit, usable output, primary checks, independent review, and a separate owner decision. A standard guarded engineering path, without autonomous software installation, auto-merge, broad once-approved Autonomous Mission Mode, or a game.

<a id="два-записи-які-не-можна-обєднати-в-один-done"></a>
### Two records that cannot be combined into one done

**Task closure—36 IDs:** AF001–013,017,020,044–046,048–049,051–053,055–057; GC001–006,039,041–043. This is the full hard closure of 25 selected seeds:26 AF +10 GC. It contains no AF032–035 GA gates, AMM tasks, game acceptance gates, or RSI tasks. The complete list, transitive prerequisites, and order are in the [shared JSON](implementation-order.json), release C-PILOT.

**Release capability acceptance:** for every component used, record the exact criterion/capability, source commit, actual profile, issuer, receipt, outcome, and outstanding remainder. This accepts a defined product path, rather than automatically reaccepting all 36 broad tasks. Task statuses do not change merely because the pilot works. If a future plan explicitly requires full completion of 36 tasks, their criteria and prerequisites need complete coverage.

For example, AF049 has the hard dependency **AF045 Hermes ACP**. The current MVP specifies a scoped Hermes session delegating to Codex (`docs/development-roadmap.md:53,60–67`). This is the path planned for C-PILOT. A direct CLI-only experiment can be qualified separately, but it does not close AF045 or authorize declaring the entire closure accepted.

<a id="поточний-windows-blocker"></a>
### Current Windows blocker

`src/agent_factory/sandbox.py:255–261` returns Windows `UnavailableSandboxBackend` by default; `411–426` rejects execution before launch. `validators.py:127–134` uses this sandbox. `codex_worker.py:25–36` separately specifies a native `workspace-write` profile—its existence does **not** automatically qualify the validator/Hermes/whole-process sandbox.

Therefore, the first C-PILOT work is to qualify the required Windows backend/adapter through existing AF017/044/045/049/052 responsibilities and prove the complete path. Do not turn unavailable into ready, disable enforcement, or skip a validator for a demonstration. If no suitable Windows path exists, C-PILOT is blocked/not-qualified; changing the target environment is a separate explicit product decision, not a hidden substitution.

<a id="точні-сценарії-приймання"></a>
### Exact acceptance scenarios

These case recipes still need to be materialized and executed. Each case has an exact fixture/version, expected oracle, permitted effects, limits, and evidence issuer before execution. P01–P09 are local scenario names, not backlog IDs.

| Case | Owner action / controlled event | Required outcome |
|---|---|---|
| P01 · environment admission | Start with a fresh named Windows profile; remove a required tool, change model/profile, expire a receipt, then restore the healthy state, one at a time. | Missing/stale/wrong-profile states do not start writable work. After an explicit actual-state check, readiness is proven for the required route. A simulated result does not become live qualification. |
| P02 · exact requirements and approval | Save a brief, approve the exact version, change one material rule; separately dismiss the confirmation dialog and replay the old command. | The new source is visible; the old grant does not authorize another scope; dismiss is not approval; replay does not duplicate work. Unchanged requirements and an unsaved draft are not lost. |
| P03 · real useful patch | Perform a bounded change in an external repository through the qualified Hermes→Codex path. | The artifact has exact base/head/diff. An independent behavior oracle confirms the requested outcome; all five declared software-validator categories have valid receipts. Product completion is not equivalent to “Core unit tests passed.” |
| P04 · independent verdict | Attempt producer self-review, submit an incomplete validator set or a criterion without primary evidence; then use a qualified reviewer. | An invalid candidate is rejected before a model verdict. Valid review records criterion/rubric/version/evidence; the owner's release decision is separate. Another name for the same effective model does not bypass independence. |
| P05 · failure and bounded repair | An independent verifier finds a known candidate defect; the same failure repeats; another case exhausts the accepted budget. | Bounded repair/replan/replacement follow policy; caps actually stop work. Failures, costs, and the termination reason remain in the ledger. Persistent refusal does not count as a useful patch. |
| P06 · Stop and unknown launch | Issue Stop after an admitted operation; separately lose the runtime-start response and recover Core. | No new unauthorized admission/repeated start occurs. An already admitted effect has an explicit outstanding/completed/unknown disposition. Capacity is not released merely on timeout; exact host stop evidence is required for reuse. |
| P07 · restart and candidate integrity | Stop Core after commit but before the candidate record; replay the same logical attempt; separately substitute committed bytes under similar metadata. | No duplicate candidate/effect; accepted bytes are rebound to the validated snapshot, or recovery blocks. Matching message/files or count=1 alone is insufficient. This is residual work under existing AF051/057 and RSI004, not a new candidate engine. |
| P08 · sandbox and stale authority | Attempt a write outside the worktree, an unauthorized command/network effect, or action with an old fence after restart/lease replacement. | Denial is enforced outside the prompt; primary denial evidence is preserved. Native Codex and validator/Hermes paths are checked against their actual boundaries. |
| P09 · delivery and recovery | The owner reads the result, rejects or accepts the candidate, and restores the previous usable state at a supported boundary. | Exact output, checks, limits, costs, and next action are visible. A rejected candidate does not become current; the PR remains gated, with no auto-merge. Recovery checks artifacts/audit and does not revive old authority. |

C-PILOT requires every mandatory applicable case, consistent receipts, and owner acceptance of the proposed Windows scope specifically. Crash/sandbox-boundary coverage is defined before execution; one P07 is not proof of every AF057 boundary. No-go is also a valid qualification outcome, but not a release.

<a id="reuse-потрібна-зміна-та-куди-йде-решта-вимог"></a>
### Reuse, required change, and where remaining requirements go

| Existing foundation | Delta for the first delivery | Remainder the pilot does not automatically close |
|---|---|---|
| AF017/044/045/049/052 | A working enforced Windows chain with verified Hermes resume/cancel and Codex/validator scope. | Other OS/runtime profiles; AF047 full runtime matrix/fallback, AF050 alternative worker. AF045 remains a prerequisite, not an optional decoration. |
| AF009/013; GC003/004/005 | Exact source/approval/replay through the actual operator path. | Full Blueprint amendment cases remain under AF013; broader browser launch/accessibility under AF036–043; game-specific intake fidelity under the corresponding GC/consumer criteria. |
| AF020/051/052/053 | Candidate-byte binding, primary-evidence closure, effective reviewer, owner packet. | General non-code evaluator—RSI006; repeated-generation evidence—RSI004; full game delivery remains unproven. |
| AF056/057; GC043 | Named budget, admission, host stop, local restart boundaries, and a complete failure ledger. | Uncovered AF057 boundaries; remote/multi-tenant host qualification; generation promotion/soak—RSI017/029. |
| GC001/002/006/039/041/042 | Current source/profile/roles/auth and truthful readiness in the intended flow. | GC001 remaining multi-OS/Python matrix or an explicit justified restriction; GC041/042 uncovered live stages/roles; full AMM qualification—AMM047/048. |
| AF032/033/034/035 | The evidence/runbook structure can be reused without creating a second system. | NFR/72-hour soak/3-provider reference mission/GA handover gates remain separate and do not pass because of a small pilot. |

<a id="c-workbench--інструмент-чесного-порівняння"></a>
## C-WORKBENCH — a tool for honest comparison

**Visible outcome:** the owner defines a bounded hypothesis, supplies exact incumbent/challenger subjects, and sees a comparison, full cost, missing/failed evidence, and an accept/reject/inconclusive recommendation. The system does not yet replace the current Core by itself. Input candidates may be prepared and separately authorized; automatic own-source/harness generation and activation belong to the subsequent C-SELF.

**New IDs:** AF-RSI-001–011 plus 015. This is the exact closure 015 of 12 cards; all dependencies are unchanged. First authority/generation/protocol/lineage 001–004; then custody 005, adapters 006, budget 008; comparator 007 after 005/006; arena 009→candidate plan 010→paired runner 011; independent tasks/oracles 015. Design research 015 may happen earlier, but its completion requires its dependencies.

**Acceptance W01–W07:**

| Case | Evidence that must emerge |
|---|---|
| W01 · protocol freeze | Exact hypothesis, primary axes, floors, budgets, stop/analysis rules, selected profiles, and incumbent/challenger manifests are recorded before output. Changing a threshold after the score creates another protocol, not a “corrected pass.” |
| W02 · two different work products | F1—a usable external software patch; F2—a requirements-to-decision packet from an independent corpus/root. F2 is not merely the planning stage of the same F1. Each has its own oracle and outcome semantics; a usability claim requires appropriate independent review. |
| W03 · evidence adapters | The five existing software validators are retained for F1; F2 has a typed document-evidence adapter. Wrong subject/version, self-review, forged/incomplete receipts are rejected; a model-generated list of URLs is not primary evidence. |
| W04 · equal comparison | Paired starting inputs/permissions/resource envelopes are equal, while agent decisions may differ. Planned scripted actions test only conformance, not planner gain. Stochastic coupling and retries are defined beforehand. |
| W05 · honest no-gain | For an independently defined no-gain/degraded candidate, the system returns reject/inconclusive under the protocol; it does not change task split, labels, baseline, or denominators to reach the desired score. A missing result is retained rather than becoming zero cost. |
| W06 · custody and full cost | Public recipes/tests are labeled D; adaptive selection S is separate from final F. All queries, candidates, failures/retries/costs/exposures are preserved. A renamed public fixture does not become a fresh holdout. |
| W07 · interruption | Restart restores exact run/protocol/evidence identities without doubling a charge/effect/decision. A late conflicting receipt creates a challenge/amendment rather than rewriting accepted history. The optimizer does not change current authority/evaluator during its own assessment. |

**Exit:** the Windows arena and F1/F2 adapters are qualified, comparison is replayable, and failures/unknowns are honestly visible. The workbench can be useful without positive gain. This is not yet019: there is no claim that Core has itself found, retained, and promoted its own source/harness changes.

<a id="наступні-три-релізи"></a>
## The next three releases

**C-SELF:** add 012/013/014/016/017/018/019; closure 019 = all 001–019. Accept at least one own-source and one own-harness change through baseline→proposal→run→comparison→decision→retained generation. A failed candidate, current-authority recovery, state/API compatibility, visible owner decision, and measured benefit are mandatory. A source-only demo does not close 019; a candidate is forbidden from changing the current supervisor itself.

**C-METHOD:** add 020–024 after their dependencies; closure 024 =001–024. Evaluator succession and optimizer comparisons are qualified separately. O0 creates O1; accepted O1 actually participates in creating O2; downstream benefit is confirmed independently of evaluator drift and additional search budget. One successful code change does not prove a better method.

**C-RSI:** add 025–030 under the DAG; product-signal 025/026 can develop immediately after 012/015/018 without waiting for all C4 work to finish. Gate030 requires benefit in both predefined non-game families, own source/harness/optimizer, a real owner outcome, challenge/failure/rollback/soak, a supported envelope, and handover. If evidence does not confirm gain, the gate has not passed.031–034 and 035 are not added to this closure.

<a id="l-preview--зберегти-задум-і-погодити-малий-план"></a>
## L-PREVIEW — save the idea and agree on a small plan

**Product promise:** the creator saves their own idea, sees assumptions and the deferred roadmap separately, edits a short brief and scope, agrees to the exact saved revision, and understands what can happen next. This is a local internal preview for one trusted operator, not a hosted account service.

**Scope:** an original in Ukrainian or English, immutable saved history, focused clarification, edited GameBrief, versioned first-playable scope, an estimate with labeled provenance, stale/conflict handling, scope agreement, and team gap assessment. The existing template is one Godot 2D room, one player, and a bounded goal. Selecting an unsupported engine preserves the idea but does not create execution readiness.

**Reuse:** CLD007/008 implement the real local `saved brief → scope → agreement` path; parts of CLD004/009 provide navigation and gap assessment. `game_briefs.py:203–308` stores the original, revisions, and separate AI suggestion attempts; `scope_plans.py:152–203` binds brief digest, plan revision, and agreement; `game_team.py:42–98` creates a Core composition assessment. These components do not need to be rewritten.

**Acceptance of this narrow delivery:**

- The creator can save the original and human edits, reopen precisely the saved revision after restart, and distinguish it from unsaved text.
- A brief change makes the old scope stale. Conflicting edits do not silently overwrite one another. Scope agreement is bound to exact versions, has `execution_authority=false`, and spends no budget.
- Planned fidelity checks preservation of requirements or their explicitly agreed change. An original checksum does not replace substantive review; planned fidelity is not presented as behavior of a game that does not yet exist.
- Status and next step match actual readiness: `execution_ready=false`, no verified playable version, and gap assessment is not Start. A template estimate is not called the actual cost of the chosen execution route.
- Current local access/profile and relevant UI behavior have their own qualification evidence; independent review and owner decision explicitly name the limited scope.

**Outstanding delta:** the actual editor has explicit save, but unsaved input can be lost after refresh/close (`docs/first-playable-planning.md:21–24`). Prototype localStorage does not prove autosave in the actual editor. The full CLD004 draft-persistence AC remains open until implemented and checked; a warning does not fulfill it. Source-to-plan fidelity/usability evidence and an exact downstream requirements bridge are needed.

**Gate and exclusions:** L-PREVIEW is a scoped component-acceptance record for parts of CLD004/007/008/009, not a new milestone, an M0/M1 pass, or full acceptance of all those cards. Build/Play/Feedback/v2/restore/export/publish, actual AI team execution, hosted tenants, and a minors pilot are excluded. The existing preview has no “time to a finished game” metric. Full M0, when accepted, still requires every CLD001–006 item.

<a id="l-creator--три-справжні-гри-з-повним-циклом-змін"></a>
## L-CREATOR — three real games with the full change cycle

**Product promise:** the creator receives a small game, plays the exact verified version, describes a change, receives verified v2, and can return the working selection to v1 while preserving history.

**Scope and canonical gate:** this is existing M1, entering from M0; gate **AF-CLD-020**. The full transitive CLD closure is **001–020**, exactly 20 work items. Reference set: **platformer, top-down collector, puzzle**. Godot/GDScript 2D; qualified Web target, a clean supported Windows run, and source reopening outside Lokiravia. One complete game journey is an early integration checkpoint, not a pass for the three required games.

**Implementation order:**

1. CLD001 → {002,003} → {004,005,006}; check existing contract artifacts and missing acceptance, and the qualified upstream reference through 003.
2. CLD007→008; in parallel, CLD012 after 002/006. After 005/008, CLD009 and 010, then 011.
3. CLD013 and 014; then 015/016/019 under their dependency branches. Budget/sandbox/cancel foundations are needed before the first actual dispatch, although full acceptance 019 tests the integrated runtime later.
4. CLD017→018→020. Repeat the entire procedure on all three games instead of replacing diverse outputs with three identical starter templates.

**Acceptance:** exact reviewed requirements enter an immutable authorized task context; a qualified worker actually changes source; independent effective reviewer identity is preserved during fallback/retry; exact source/build has engine checks, actual runtime, and graphical Play evidence. Feedback references the played Build/PlaySession; the proposal shows target, affected requirements, scope/risk, and extra cost before work authorization. A new SourceVersion/Build verifies requested behavior. Failed v2 does not take away Play v1. Restore creates a new generic version/restore and audit record, preserves the original SourceVersion/Build evidence binding, and ends with a usable target receipt. If a specific restore creates a new SourceVersion, that version requires separate qualification; an old receipt is not rebound to the new subject.

Full 020 also requires a clean Windows package run, source-archive reopening, failure/restart/Stop and budget reconciliation, a private fork of an owned or explicitly remixable game, a denied no-remix case, an unchanged original, attribution/lineage, independent review, and owner gameplay. Public Remix does not open here. A correct digest without actual Play does not complete the user journey.

**Reuse and delta:** the current early editor and Core foundations are consumed through the exact pin. Still needed: reviewed scope→execution projection, real dispatch, engine evidence producers, build registry/gate consumer, PlaySession, Feedback/change workflow, v2, and usable restore. A separate prototype honestly blocks Play; history GET is not restore. The CLD role/team assessment has `candidates=()`, `budget=0`, `can_start=false`, `can_stop=false` and does not prove execution.

**Exclusions:** hosted private alpha CLD034, public publishing/discovery, public Remix, payments, new engines/stores, multiplayer, arbitrary-game generation, and full RSI are not M1 prerequisites. However, minimum rights, secrets, sandbox, independent review, and a bounded budget for actual local execution are not deferred until M2. Internal qualification uses adults/synthetic data; any minors pilot has separate CLD004/021 gates.

<a id="w-first--перший-доказ-живої-сцени"></a>
## W-FIRST — first proof of a living scene

**Product promise:** over 20–30 minutes, one player performs an unusual action with a real local effect, observes a short causal development or honest dissipation, encounters a visible reason for a failed plan, and returns through save/load to the same consistent history.

**Scope and canonical gate:** existing **AF-LW-030 / W0**. A bench or another small location, two NPCs with their own intentions, a few objects, a bounded action vocabulary, causal traces, and one supported local runtime profile. The scene and properties may be authored manually; actual state transitions are required even without generation.

Exact evolution closure—**22 cards**:

- 12 World: **LW001,002,003,004,005,008,009,010,011,012,014,030**.
- 10 Core: **RSI001,002,003,004,006,008,009,031,032,033**.

Core005/007/019/024/030/034/035 are outside this closure. Existing CLD010/011/012/015 refs mean reuse of required accepted starter/adapter/checkpoint/Play capabilities, not already completed tasks or an automatic requirement to wait for full CLD020. W-FIRST uses one shared build/Play pipeline; no independent registry of its own is created.

**A separate W-FIRST profile is mandatory for truthful scope:** existing `small-2d-scope-v1` excludes `new agentic runtime systems` (`docs/first-playable-planning.md:33–42`). Editing the exclusion text does not make it a W-FIRST generator. The narrow game pack/domain profile has its own qualification; later integration into CLD008/LW013 can preserve the same creator UI and authority boundaries.

**Acceptance:**

- A real unplanned action uses verifiable object properties. Under suitable local conditions, 2–3 transitions occur; paired/control cases show no cascade, a different schedule, NPC refusal, and an appropriate alternative action without hidden author fiat.
- The multistep plan in C09 fails because of a known timing condition; the cause is available to the player, and a next choice remains. Seasonal C10 is not required.
- The C08 half-action save preserves progress/reservations: unfinished covering does not yet protect the bench; cover/wear appear only on completion. The W0 clock does not advance while paused.
- A checkpoint preserves world/rule/schema identity, committed revision, costs, NPC knowledge, and stable accepted jobs. Load creates a new session epoch. An old pending reply and, separately, `precheck → load → old apply` are rejected at the authoritative final commit. Effect/resource/event/job-completion/dedup are consistent; an ordinary restart does not produce a double reward.
- Fact, belief, and accepted obligation are distinct. NPC refusal is not rewritten into hidden agreement; the UI does not invent a change, reward, or agreement to fill the history.
- An observer records whether the person understood the cause, recognized their own choice, and experienced an appropriate comic moment. This is qualitative session evidence; the proposed 12-person pilot does not become a hidden minimum for AF-LW-030 or statistical proof.
- Core031/032/033 and consumer receipts match the actual supported profile: no LLM wait on the frame, bounded async/outage behavior, and correct late-reply/cost disposition. Synthetic conformance is not called full runtime qualification.

**Exclusions:** the whole E01–E08 district, seasonal bridge, crafting/economy World006/007, laboratory 013, institutions/long traditions, autonomous rule/ontology evolution, production canary/migration, an always-on world, multiplayer, and the entire standalone Core gate. W-FIRST takes the local checkpoint/final-apply/job/dedup recovery slice, including applicable RC02/13/15; full W3 rollout is not a prerequisite.

Manual W-FIRST does not automatically receive CLD020 acceptance. To count as one of the three reference outputs, the same game must match the required genre and complete the full idea→worker change→Play→export→feedback→v2/restore procedure. Conversely, three ordinary creator games do not prove W-FIRST causal/identity/save semantics.

<a id="девять-спільних-integration-seams"></a>
## Nine shared integration seams

The roles below name implementation/acceptance ownership, not people or devices. A reusable Core capability has one implementation; Lokiravia accepts its product integration.

| Seam | Existing owner/IDs | Exact prerequisite → evidence; current delta |
|---|---|---|
| I-01. Reviewed brief/scope → execution | Cloud product-engineer/game-producer: CLD002/007/008/013; Core intake/approval; later LW013 | Original + reviewed revision/digest + agreed scope/policy + principal/project → immutable authorized task context. Current human edits/six-task Cloud plan are not yet an automatic execution bridge; original-only parsing loses meaning |
| I-02. Team assessment → actual work | Core route/runtime; Cloud agent-systems/runtime: CLD009/013/019 | Qualified coding/reviewer identities, lease, scope, real caps → intent-before-dispatch, actual diff/commit/review/usage, and reconciled retry. Current gap assessment is not Start |
| I-03. Pack/toolchain → checked build | Core optional Godot/target pack; Cloud godot-engineer/QA: CLD005/010/011/014 through 003 | Exact versions, licenses, sandbox/profile → probe/import/build/validator/runtime receipts, good/broken fixture outcomes, and process Stop. Contracts do not replace an actual producer |
| I-04. Source/Build → Play | Core worktree/delivery primitives; Cloud backend/fullstack: CLD006/012/015 | Immutable source/commit/build binding, current gate/access/availability → actual PlaySession/open/run/exit/crash. The current packaged creator has no connected launch path |
| I-05. Play feedback → verified v2 | Cloud product/workflow: CLD017/018; Core execution consumer | Exact played version → scoped reviewed change/extra-budget decision → new SourceVersion/Build with requested behavior. A no-play note is not gameplay evidence; feedback is not authority |
| I-06. Working version → restore | Cloud backend/workflow: CLD012/018; Core recovery/authority | Explicit target/current grant → new generic restore/version+audit, atomic selection, usable target; original receipt bindings unchanged. History/localStorage is not restore; new SourceVersion qualification only if one is created |
| I-07. Intent → world state | Core031/033; World runtime/game designer: LW002/005/008/009/011/030 | Typed proposal/epoch/revision/expiry/permission → authoritative domain delta/event or rejection. Provider text is not canon; bounded runtime/outage/fallback receipts are needed |
| I-08. State → checkpoint/replay/load | Core032; World save/runtime/QA: LW002/012/030 | Coherent state/rules/schema/jobs/watermark → new session epoch and final-commit fence/dedup; replay recorded inputs. Game save, source restore, and Core rollback are different objects |
| I-09. Evidence → release decision | Independent QA/reviewer + owner; CLD020 and LW030 separately | Exact criterion-linked primary receipts + relevant real human experience → scoped decision. Structural/runtime/human/owner evidence is not interchangeable |

IntegrationReceipt at `platform-world-contract.md:72` distinguishes `core_contract_conformance`, `domain_runtime_integration`, and `packaged_game_integration`. Exact Core/consumer revisions, contract/pack/runtime/target versions, suite/runner, and supported envelope are needed for the corresponding claim; a player-package hash is not invented for a neutral fixture. Ready/Playable/Exportable/Publishable/Sellable remain separate gates; eligibility is not a receipt for an action actually performed.

<a id="всі-пізні-cldlw-bands-і-їхні-gates"></a>
## All later CLD/LW bands and their gates

| Band | IDs | Entry / exit and boundary |
|---|---|---|
| M0 foundation | CLD001–006 | All six accepted; L-PREVIEW does not automatically close them |
| M1 / L-CREATOR | CLD007–020 | Entry M0; exit020, closure 001–020 |
| M2 private hosted alpha | CLD021–034 | Entry M1; exit034, closure 001–034. Accounts/state/objects, remote jobs/isolation, credentials/quotas, hosted portal/protected Play/export, and operations recovery |
| M3 public creator beta/Remix | CLD035–044 | Entry M2; exit044. Releases/visibility, profiles, game pages, Discover/share, public Remix, metrics, moderation, and asset rights. Marketplace is not open |
| M4 marketplace | CLD045–051 | Entry M3; exit051. Seller eligibility, listings, checkout, entitlement, ledger/payouts, refund/fraud qualification |
| M5 engines/targets | CLD052–060 | Entry M2 + feature prerequisites; exit060 requires 052–058. SDK, Unity, Unreal, Android, Apple, Steam/PC packaging.059 console optional; no-go for a required engine does not pass full 060 |
| M6 defined GA/expansion | CLD061–067 | Entry M3 + accepted scope; exit067 requires 034/044/061/063/064/065.062 factory commerce and 066 non-game optional. Templates/API/model budgets/hybrid qualification are capabilities in their own right |
| W0 / W-FIRST | LW001–005,008–012,014,030 | Gate030 with exact 22-card evolution closure and applicable existing integration receipts |
| W1 deeper scene/relationships | LW006,007,013,015,016,017,018 | Craft/error alternatives, creator laboratory, contextual comic choice, shared-history objects, NPC collaboration, institutions; dependency-qualified delivery. The manifest has no separate overall W1 acceptance ID |
| W2 local social change | LW019,020,021,022 | Traditions, negotiations, rebuilding, rumors/correction; Core034 applicable. Does not imply multiplayer |
| W3 evolved district | LW023–028 | Rule publication/migration, game-improvement campaign, human experience, abuse/recovery, return to the world; exit028 through 025/026/027. Core closure 001–011,014–017,031–034; not all Core030 |
| W4 optional human co-operation | LW029 | Dependencies 017/025/028; separate research/authority/network qualification, not an initial multiplayer release |

M6 conditional gates are retained: paid marketplace→051; expanded engine/store support→060; factory commerce→051+062; non-game offering→066; any console support→059. Any minors pilot→004+021; any public Remix→040+042+043+044. A narrower release does not pass a broader legacy gate without an explicit versioned scope revision.

**The W-FIRST→depth sequence is recommended release policy**, not an existing dependency edge: LW030 is not an ancestor of LW028 in the current DAG. Later implementation cards may be prepared under their own prerequisites; broad experience acceptance should not be advertised before the narrow proof. This revision adds no new edges. L-CREATOR and W-FIRST can progress in parallel after their applicable shared foundations; neither waits for full Core024/030 recursive-method acceptance.

<a id="реєстр-capability-prerequisites"></a>
## Capability prerequisite register

These entries are integration obligations, not new backlog tasks or hidden hard edges. Existing requirements own them. Every release referencing them in JSON must obtain applicable exact receipts before acceptance. They do not replace canonical task prerequisites.

| ID | Required capability / owner | Boundary |
|---|---|---|
| I-CORE | Enforced Windows execution, approvals, exact context/candidate, independent review, validators, budget/Stop/recovery; AF017/044/045/049/051–053/055–057, GC001–006/039/041–043 | C-PILOT P01–P09; for the workbench, exact evaluator/arena profiles additionally. Task closure 36 and broader residuals are retained |
| I-REUSE | Criterion-level qualification of consumed legacy capabilities before the corresponding RSI/LW consumer | Matrix below; the full-task remainder may have a later allocation, the required receipt may not |
| I-PREVIEW | Persisted brief/scope/agreement, conflict handling, truthful assessment; CLD004/007/008/009 and consumed Core contracts | Preview cases in the L-PREVIEW section; does not replace full M0 or downstream execution |
| I-WPROFILE | Narrow living-world game pack/profile; LW001/002/030, Core031–033, CLD005/010/011 | Do not remove the existing small-2d template's exclusion to create an appearance of support; qualify a separate combination |
| I-WDEPTH | First accepted W-FIRST as product policy, then full gate LW028 and exact Core034 rule-activation/migration capabilities | Explicit release policy, not a declared legacy dependency LW030→028 |

I-01–I-09 are defined in the nine shared integration seams table above. Core Godot pack responsibilities GC016/017 and generic worktree/runtime/evidence remain in Core; CLD010/011/014/015 accept product integration. Full Core game-onboarding gate GC026 is not added to CLD020 because of one reuse reference. A second engine-adapter, verifier, or build-registry implementation is not created merely because there is another product.

<a id="i-reuse--що-кваліфікувати-до-першого-споживача"></a>
## I-REUSE — what to qualify before the first consumer

A late full-task allocation does not defer a capability needed earlier. Before actual use or an acceptance claim, record `consumer`, `required_before`, `legacy_id`, `criterion_pointer`, `coverage_scope`, `component/profile binding`, `primary_receipt`, `remaining_criteria`, `residual_destination`. Contract comparison is sufficient for E0 design; the table does not authorize running models now.

Every existing_work_ref in JSON requires a disposition: consumed capability, or reference-only with an explanation. `not_applicable` is allowed only with justification for the selected alternative profile. An absent required capability blocks its consumer. Only the remainder outside the consumed scope moves to later C-PLATFORM. Composite IDs in the table denote existing three-digit AF-/GC-/AMM- IDs.

| Required before consumer | Legacy refs | Scope and primary evidence |
|---|---|---|
| RSI001 | AF004/013/018/022 | Policy, exact approval, Tool Gateway, ADR authority; allowed-write matrix and denial of authority expansion |
| RSI002 | AF001/016/024/048/055 | Identity/version, memory/pack composition, context/worktree binding; exact digests and rejection of stale/latest substitution |
| RSI003 | AF020/027/032 | Rubric, measurement, and cost provenance; frozen protocol and compatible measurement receipts |
| RSI004 | AF002/003/051 | Ledger/issuer/artifact/candidate integrity; replay and actual-byte binding without a duplicate decision |
| RSI005 | AF015/016/021/029 | Context/memory isolation, contamination, storage/privacy; negative retrieval/log/export cases and access ledger |
| RSI006 | AF020/052, GC006/041/043 | Software-evidence closure, effective identities, admission, and new subject adapters; conformance and rejection of incomplete evidence before review |
| RSI007 | AF027/032 | Identical measurement/cost/missingness semantics; raw paired observations and reproducible comparison |
| RSI008 | AF008/027/056 | Campaign reservations/caps/retries/full costs; ledger of rejected attempts and enforced stop of new work |
| RSI009 | AF017/044/048/055, GC043 | Exact arena host/sandbox/context/worktree/admission; enforced denial, trusted Stop/reconciliation |
| RSI010 | AF008/013/022/051 | Bounded plan/authority/impact/candidate binding; changed-scope and stale-plan denial |
| RSI011 | AF006/044/052 | Durable paired execution/validators/interruption; complete run receipts without duplicate effect |
| RSI012 | AF015/016/021 | Governed persistence/retrieval/poisoning/invalidation; negative lineage retained, revoked experience does not return through cache |
| RSI013 | AF010/011/012/016/024 | Exact role/routing/pool/skill/pack harness; versioned admission and authority-preserving activation/rollback |
| RSI014 | AF049/050/051/052/053/054 | Selected writable worker/role pack/validator/review/repair; immutable own-source candidate without changing supervisor authority; AF050 only for a selected Claude profile |
| RSI015 | AF025/032/034, GC001 | Reference/benchmark/reporting/environment contracts; independent corpora/oracles and actual receipts; envelope reuse is not full AF034 |
| RSI016 | AF001/026/028/057, AMM046 | Consumed schema/API/state/migration/recovery; old→new matrix, restore, and stale-authority rejection |
| RSI017 | AF024/031/057 | Pack activation, selected deployment profile, generation recovery; shadow/canary/rollback with current authority |
| RSI018 | AF036/038/043/056 | Actual operator path/accessibility/telemetry/Stop; exact target, pending effects, and preserved draft |
| RSI019 | AF020/034 | Independent verdict/release-envelope traceability; own source and own harness, failed candidate/recovery/measured benefit |

C-WORKBENCH needs rows 001–011/015 before their consumers; C-SELF adds the remainder 001–019. Later C-METHOD/C-RSI and W-FIRST/W-DEPTH apply the same rule to their `existing_work_refs`. C-PILOT has its own P01–P09; if it uses AF036–043 UI, the consumed scope is qualified before P02/P09. I-REUSE adds no dependency edges.

AF029 means the actual storage/privacy profile, not mandatory PostgreSQL. AF032/034 reference/reporting reuse does not pull in full NFR or the three-provider GA gate. AF028/031/AMM046 require precisely the chosen compatibility/activation/recovery scope, not every topology/AMM profile. Broad-task criteria remain unchanged.

<a id="що-має-містити-рішення-про-випуск"></a>
## What a release decision must contain

One versioned release dossier contains scope/exclusions; exact commit and installed bundle; supported environment/model/tool/authority profile; every mandatory case and primary receipt; independent verdict; failures/unknowns/full costs; usable recovery; and the owner decision. For each requirement used, separately record `canonical_id`, `criterion_pointer`, `coverage_scope`, `subject_hash`, `profile`, `receipt`, `verdict`, `remaining_criteria`, `residual_destination`. The required dossier is defined here; no successful receipts are invented.

`coverage_scope=capability_subset` does not change task status, prove full dependency completion, or permit starting a dependent full task without its prerequisites. Only AF obligations outside the consumed early scope return to C-PLATFORM; required early capabilities pass I-REUSE before the consumer, GC before their C-GODOT/C-LOCAL/C-EXPAND gates, and uncovered preview CLD before L-CREATOR/M0. A narrower support scope is shown before execution and in release notes; an unsupported profile does not receive a general ready status.

Implementation needs actual resources, suitable tools/models, independent reviewers, and material for human sessions. These are qualification inputs, not a reason to postpone the present plan. Dates and estimates are added after gap sizing; first releases are not expanded arbitrarily for an optimistic schedule. Any no-go preserves the experiment's result but does not become an accepted product.
