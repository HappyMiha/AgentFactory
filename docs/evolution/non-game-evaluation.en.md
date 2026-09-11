<a id="q08-на-яких-задачах-core-має-довести-власне-поліпшення"></a>
# Q08: the tasks on which Core must demonstrate its own improvement


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [non-game-evaluation.md](non-game-evaluation.md). Source SHA-256 (UTF-8/LF): `258133d9eaecb9da19917f085549f620db5fa14ac69a64536ac7ee2438051bc1`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](non-game-evaluation.md).

Date: 2026-09-10. Status: E0 / source-informed evaluation design. This specifies a future set, not a finished benchmark or an executed experiment. There are no new test programs, fixture repositories, models, or runs. Every example in this document is open and suitable only as development/design material. Hidden tasks, answers, and private reports are not added to Git.

<a id="1-рішення-дві-сімї-результатів-окремі-перевірки-надійності"></a>
## 1. Decision: two outcome families, separate reliability checks

Core must demonstrate benefit on tasks that require neither Lokiravia, Godot, nor a game pack. The initial “context, tool use, code repair, recovery, planning, user-facing evidence” were six different evaluation dimensions; one task can cover all of them. Q08 does not count them as six independent families.

| Family | User work and result | What is checked externally | What does not constitute completion |
|---|---|---|---|
| NG-F1 · bounded software maintenance | Modify a small external fixture repository under an exact brief: correct behavior or add a bounded feature while preserving compatibility. Result: exact patch/commit, executable artifact, and an honest report | An isolated verifier runs independently prepared behavior/regression checks on the actual output; checks permitted diff, provenance, and delivery status | Only tests or the report changed; Core's own unit suite passes; a correct commit for another task; “done” without an artifact |
| NG-F2 · requirements-to-decision planning | From versioned non-game requirements, clarifications, and constraints, prepare a plan suitable for a decision: what to do, what is unknown, dependencies, criteria, and questions. Result: a reviewable requirements/plan packet, not an implemented product | Deterministic checks compare sources/revisions, requirements and contradictions, references, DAG, scope, and authority. Independent review assesses substantive adequacy and clarity; multiple valid plans are allowed | Valid JSON that loses the need; invented owner approval; a long plan without decisive questions; planned fidelity presented as an implemented feature |

The families have different input corpora, work products, and outcome rubrics. F2 is not the same F1 task evaluated before coding: for a two-family claim, their root tasks and source materials do not overlap. This is operational independence, not an assumption that all observations are statistically independent. Shared fixture, solution-strategy, or source ancestry remains a dependency/cluster in the analysis plan.

Each family includes **cross-cutting slices**: currency of requirements/context; tool/permission boundaries; retry/recovery; artifact/evidence provenance; failure/unknown handling; and operator usability. No slice alone adds a family or independent task. Both families contain ordinary feasible tasks, intentionally blocked cases, and ambiguous cases. An “always refuse” strategy does not pass the outcome floor on feasible tasks.

Current Core bugs/fixtures help select slices but do not establish representative coverage of user needs. NG-F1/F2 are initial hypotheses for RSI015/030 requiring qualification and RSI026 product-signal evidence.

<a id="2-підстави-з-поточного-core"></a>
## 2. Evidence from current Core

Snapshot: Core `1147d72195d390ac16e15e466ca5f8313d055b8b`; Lokiravia for shared-portfolio boundaries: `23704f316948a50aba724ede5d461ecbd8cdaaea`. Upstream main checked again: Core `c22954f144702fdf7a3da16cf58176baa345f7c4`, Lokiravia `3d42cf9606d1100ebe0887306300b5fa4aaaea5e`. Below are specific code paths, assertions, and one historical commit that were read. Tests were not run; a regression's name does not prove an actual user incident.

| Anchor / class | Evidence read and its status | Implication for new task design |
|---|---|---|
| NG-D01 · stale requirements | The [intake test](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_autonomous_mission_intake.py#L267) expects invalidation of an old proposal after its source changes; the [intake source](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/mission_intake.py#L1311) implements supersession/invalidation. Synthetic fixture + current guard, not an established live incident | Denial of the old version is a floor. A useful new work product also updates dependent requirements correctly and preserves current commitments; a checksum does not prove understanding |
| NG-D02 · mandatory context / dispatch | [Context fixtures](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_context_packages.py#L147) and [source](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/context_packages.py#L414) check mandatory budget, stale required content, and a different dispatch; [runtime binding](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/worker_runtime.py#L373). Synthetic cases + explicit current checks | Retaining content marked required does not mean correctly identifying all important conditions. Check content sufficiency, permitted additional reading, and the actual final result |
| NG-D03 · wrong-plan / stale / simulated readiness | [Readiness source](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/environment_readiness.py#L239), [caller](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/coding_delivery.py#L481), [fixtures](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_environment_readiness.py#L40). [Historical commit cf7896b](https://github.com/HappyMiha/Lokvetia-Core/commit/cf7896b66f202ba537e62b6a15f7ee3f7bc614a0) added the current route gate before development | A historical gate correction and synthetic negative cases do not imply a new breakage. F2 needs only its own capability profile, not automatically a coding/GPU route. Readiness does not replace the outcome |
| NG-D04 · persuasive review without primary evidence | The [evaluator](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/evaluation.py#L100) requires validators/digest/criterion evidence and rejects same-model review; [worker fixtures](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_codex_worker.py#L389) include an artificially positive reviewer | This is a concrete software-candidate gate, not a universal document evaluator. RSI006 must qualify a document adapter; a different model name does not guarantee independence, and primary references do not prove correct oracle mapping |
| NG-D05 · interrupted commit / artifact adoption | The [local-Git fixture](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_codex_worker.py#L289) expects adoption of one HEAD after commit but before candidate-artifact recording; the [adoption branch](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/candidate_changes.py#L105) checks parent/message/file set | This narrow inspected branch does not rehash actual committed bytes against the validated snapshot; this does not prove an available exploit and is already covered by RSI004. The new task checks exact output bytes/receipt, not merely one commit or a filename |
| NG-D06 · Pause / unknown effect | The [control fixture](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_autonomous_mission_control.py#L373) uses a simulation child and synthetic provider; [runtime operation gate](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/worker_runtime.py#L324); [recovery fixtures](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_autonomous_mission_recovery.py#L60) have a test observer | An already accepted effect and a new dispatch differ. A mission-bound gate does not prove remote fencing of every sink. A qualified receiver profile must honestly distinguish completed/absent/unknown and the effect of Pause |

Also read: [proposal-verifier assertions](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_autonomous_proposal_verifier.py#L208), with golden document fixtures and specific findings; the [stale-source case](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_autonomous_proposal_verifier.py#L492), which preserves an immutable report. This supports NG-F2 structural/revision slices, not a claim about human planning quality. Existing AF055, AF020/051/052/057, and AF-AMM intake/approval/recovery services are reused; a new implementation under another name is unnecessary.

<a id="3-taskcase-що-має-бути-визначено-до-запуску"></a>
## 3. TaskCase: what must be defined before execution

These are logical fields for existing RSI003/004/005/015 dataset/protocol/evidence services, not a new store or runtime schema import.

| Group | Required information |
|---|---|
| Identity / lineage | Case ID/version/digest, family, root-task ID, parent/source/generator/solution ancestry, mechanism and challenge slices, rights/provenance. Any relationship to a known defect seed is explicit |
| Initial state | Exact non-game repository/document bundle, source/requirement revisions, objective, accepted constraints, permitted tools/actions, granted scope, and qualified environment. The same name or random seed does not make inputs identical |
| Task feasibility | Supported and feasible / intentionally blocked / ambiguous under known facts; permitted result type. An oracle cannot require a fact unavailable through permitted inputs or capabilities |
| Outcome / verifier | Objective acceptance facts, valid alternatives and hard floors, qualified verifier/decoder version, checker fixtures, and external review rubric. Human usefulness/clarity is not replaced by a schema check |
| Exposure | Split, permitted readers/diagnostics, prior-access snapshot, subsequent access ledger, inherited memory/skill/retrieval/optimizer lineage, contamination status, and confidence limits |
| Execution / analysis | Baseline/challenger bundles, pair/attempt/repetition IDs, workload/environment/fault schedule, caps, missing/outage/retry policy, unit of analysis, decision/stopping rule, and known limitations |

Task roots are grouped before splitting, not after results. Neighboring seeds, renamed documents, different schedules for the same fault, model repetitions, and votes from several reviewers do not become independent roots. If a relationship is discovered later, applicability/analysis is reviewed through an explicit amended protocol; an old verdict is not silently rewritten.

The public oracle specification describes permissible solutions rather than hardcoding one answer. For F1, hidden checks assess behavior under a controlled runner and cannot be changed by the candidate. For F2, a missing required dependency or unaccounted version may have an externally verifiable verdict; a plan's rhetorical persuasiveness or benefit to the owner requires separate review. `READY_FOR_REVIEW`, `APPROVED`, `DISPATCHED`, and actually completed work remain different states.

<a id="4-як-створювати-нові-задачі-й-не-називати-копію-прихованим-тестом"></a>
## 4. Creating new tasks without calling a copy a hidden test

1. **Register the open seed.** Existing tests, bug reports, this document, and Q05–Q07 scenarios are exposed development material. They support debugging, mechanism analysis, and regression, but not evidence of an unfamiliar task.
2. **Choose the declared transfer claim.** A new instance of a known mechanism, new source/solution lineage, new mechanism, or new family are different levels. `freshness` is this vector plus exposure status, not a boolean. An independent author or new date alone does not make a task new.
3. **Prepare task roots separately from candidate search.** Use a different fixture repository/document corpus, structurally different interactions and constraints, and explicit ancestry. Do not copy a Core test body with changed names. Answer secrecy does not replace new task provenance.
4. **Verify solvability and the oracle.** The custodian/independent reviewer checks that a valid solution exists within the qualified scope and that contradictory/blocked cases are assessed honestly. Known-good and known-bad controls qualify the measurement path. The visible candidate does not create its own final labels or acceptance criterion.
5. **Split by roots, check similarity and prior access.** Compare sources, graph/constraint structure, expected solutions, tasks/answers in logs, artifacts, skills, distilled summaries, retrieval, and previous judge diagnostics. Similarity is a signal for investigation, not an automatic guarantee of cleanliness. Unknown pretraining exposure is recorded as unknown.
6. **Seal before selection and track subsequent access.** The immutable TaskSetManifest/digest and exposure snapshot belong to the qualified evaluator scope. The actual task agent receives its permitted task input during the final run; the optimizer and future generations do not gain unrestricted replay of that input, answers, or diagnostics through shared memory. Task-agent access is a permitted part of evaluation, not proof that the case remains unknown forever.
7. **Retire/reclassify after use.** An aggregate score is also information. Anything that guides subsequent search becomes adaptive/development evidence for the relevant lineage. Final tasks do not become fresh again through Pause, rollback, a new candidate ID, or a deleted log.

This pass has not created a final set or verified the privacy of such an environment. New source families are not declared an external user population without research establishing their correspondence to real work.

<a id="5-три-набори-і-три-різні-reference-ролі"></a>
## 5. Three sets and three distinct reference roles

| Set | Access and purpose | Claim boundary |
|---|---|---|
| D · development / calibration | Open recipes, known regressions, debugging, baseline noise/runner checks. Repeated diagnostics permitted within resource limits | Explains the mechanism and performance on known cases; not fresh transfer |
| S · adaptive selection | Separate roots, bounded queries, declared feedback detail, complete access ledger. Candidate search may use results | Sealed custody does not make an adaptive selection score independent final confirmation |
| F · final confirmation | Roots independent of D/S within the declared transfer scope; labels held by the custodian; protocol and selected candidate frozen before results are revealed | One predetermined confirmation procedure for the selected candidate. Subsequent changes to the candidate/threshold after F require a new procedure and a new suitable F |

A final procedure may include several preregistered arms/looks under an appropriate correction/stopping policy. This does not permit unlimited selection of the “best” candidate by final score. Even acceptance-only or aggregate feedback enters the exposure ledger. All exploratory candidates, failed checks, and costs are preserved; the winner does not masquerade as the only attempt. A finite final-gate/retest allowance is set before the campaign; a new F, mission, candidate, or criterion epoch does not reset cumulative selection/comparison history. Exhausting it means stop/inconclusive or a separately authorized new experiment with preserved history, not automatic searching for a lucky final set.

| Reference role | Question answered |
|---|---|
| Frozen founding reference R0 | Is there cumulative benefit over the specified starting version? Exact source/harness/model/tool/memory/profile are fixed; an old historical score is not compared directly with a new task/criterion epoch |
| Immediate accepted predecessor Rn | Is candidate Rn+1 better than the version it intends to replace? Required comparator for incremental adoption; better than R0 but worse than Rn does not pass as improvement |
| Bounded no-evolution / compute / ablation control | Can gain be explained by extra compute, resampling, accumulated access to experience, or a different model? Ablation checks the claimed mechanism; it does not replace the final product outcome |

Rn and the candidate execute comparable root tasks under the current shared CriterionManifest, resource/authority envelope, and starting state. For a cumulative claim, R0 runs under a compatible current protocol; re-scoring historical outputs does not replace fresh execution of the new workload. If R0 cannot operate within the profile, that is a separate compatibility limit; its old score is not arbitrarily rescaled.

When memory/context strategy is the treatment, the **permitted experience pool and budget** are identical, rather than necessarily the generated memory representations. The difference must be declared; future/final data is added to neither arm. A changed model, runtime, scheduler, or dependency/toolchain is a controlled factor or confounder. Installing a better model at the same time does not justify attributing the result to Core's own source.

For O0→O1→O2, compare more than finished patches: actual participation by O1 in creating O2, multiple independent search runs under the declared plan, downstream product outputs, and O2 benefit over immediate O1 with complete search accounting are required. One successful patch is not evidence of a better optimizer. Changing the evaluator/criterion requires a separate Q03 protocol; a candidate does not weaken its own current acceptance.

<a id="6-вибірка-outcomes-шум-і-вартість"></a>
## 6. Sample, outcomes, noise, and cost

The previously proposed **60 paired tasks** remain a planning hypothesis: for one future confirmation block, 60 root-task pairs, initially 30 NG-F1 and 30 NG-F2. D/S preparation and search runs are separate work with their full costs; they are not silently included in the denominator of these 60. This is not a prepared task inventory, power calculation, or compute authorization. Before admission, precision/noise review on D determines suitable root counts, repetitions, margins, and caps in a specific protocol. Changes before execution are allowed as versioned design; after outcomes, cases cannot be purchased until a desired pass appears.

Three repetitions of a stochastic case are an initial hypothesis for variance estimation, not three independent tasks. With 60 roots, two arms, and three repetitions, this means 360 executions before retries, development, selection, review, or a third reference arm. Deterministic cases do not need repetitions merely to increase a counter. The actual repetition plan is accepted before execution; these figures do not promise sufficient precision.

Select one primary axis per family: accepted outcome under cost/latency floors, or total cost at non-inferior quality. Core030 requires benefit in **both families named in advance**, rather than post hoc selection of the two best slices. Effect, dispersion/interval, non-inferiority margins, family/multiple-candidate comparisons, and sequential looks have a method fixed before evidence. A wide interval or insufficient sample produces `inconclusive`; this is the honest outcome of a bounded pilot.

Separate outcome fields: artifact/plan validity; achieved user goal; correct handling of unknown/blocked scope; fidelity; operator clarity/assistance; latency; total cost; permissions/integrity/recovery. Correct abstention in a blocked case is not presented as an implemented feature. A hard-invariant violation blocks acceptance even if average utility rises. For F2, deterministic correctness does not establish independent human usability without people.

Pair identity retains starting inputs and the exogenous/fault schedule. Candidate actions may differ from the predecessor's. A crash “after an accepted external effect, before the local receipt” must be bound to each arm's semantic boundary if that is the declared slice; impossible pairing is not hidden behind the same seed. If an arm legitimately achieves the user goal without that action, it is not forced to produce the effect and the root is not removed: retain the task outcome and assess fault exposure/applicability separately. If the original task requires the effect, its absence is assessed as failure to achieve the goal, not convenient N/A. The same task root remains a cluster across repetitions/sibling variants/reviewer votes.

Timeout, cancelled, failed, unsupported, environment-invalid, and missing evidence have separate dispositions. Eligibility, retry caps, and handling of infrastructure faults are defined before execution. Distinguish a planned stochastic repetition, an independently established invalid measurement, and a valid final result without positive gain; the third is not repaired by repeating until a pass. There is no ad hoc removal of baseline failures or difficult candidate cases. Environment-invalid remains in flow counts and the cost ledger; paired missingness limits inference. No demonstrated gain does not imply practical equivalence: `equivalent` requires its own predetermined criterion. A missing charge is not counted as zero, and zero accepted improvements does not make campaign cost zero.

Budget covers task/oracle preparation, qualification, all candidate search runs, failures/retries, model/retrieval, verifier/human review, storage/I/O, and serving/measurement. Generation/mission IDs, rollback, or Stop do not reset campaign obligations. Candidate utility and complete campaign efficiency are two separate reports. The resource owner sets actual caps; this design does not derive a budget from another paper's ratios.

<a id="7-відкриті-recipes-та-статичні-controls"></a>
## 7. Open recipes and static controls

The recipes below are new authored textual examples, not created fixture repositories, hidden tasks, or descriptions of actual user incidents. They illustrate how a failure class can be tested in different work products.

| Recipe | Family / slice | Example and expected boundary |
|---|---|---|
| NG-O01 | F1 / scope-version | In a local parser utility, the author clarifies the empty-line rule. The change must consume the exact reviewed requirement, preserve old compatible cases, and deliver a verified patch; the stale brief does not “win” because it is shorter |
| NG-O02 | F1 / artifact provenance | A worker reports success for an export utility, but the receipt belongs to another commit. The external checker does not accept the report without output from the correct source; this is not a requirement to copy a Core test |
| NG-O03 | F1 / interrupted effect | The response is lost after writing a patch artifact. Retry must reconcile accepted output and current rights rather than duplicate a side effect. The receiver profile determines what can be verified and what remains unknown |
| NG-O04 | F2 / ambiguity | A local document-archive plan contains conflicting retention requirements and unapproved export. The result shows the conflict, dependencies, and questions; an invented compromise does not become the owner's decision |
| NG-O05 | F2 / source revision | A reviewed plan relies on an old resource limit; a new source changes the permitted scope. An explicit applicability/review decision is required; the immutable old verdict is not rewritten |
| NG-O06 | F2 / semantic adequacy | The plan is structurally valid but omits the user's path after an operation fails. Independent review distinguishes the substantive gap from a DAG/schema pass; good style does not compensate |

| ID | Counterexample | Expected decision |
|---|---|---|
| Q08-N01 | The same Core unit fixture is renamed and placed in final | It remains an exposed root/lineage; fresh claim rejected |
| Q08-N02 | Six checks of one patch are called six families | One task root with slices; the two-family gate is not passed |
| Q08-N03 | Candidate better than R0, worse than current Rn | No incremental improvement/adoption on this basis |
| Q08-N04 | After dozens of selection queries, an aggregate score is called independent final confirmation | Exposure accounted for; a suitable separate confirmation is required, and search/costs are not hidden |
| Q08-N05 | Task agent sees F input; a summary enters shared optimizer memory | Lineage contaminated for a future fresh claim; reclassification/new set, not a new ID |
| Q08-N06 | Three stochastic retries and five reviewer votes increase n for one root to 15 | Cluster/unit of analysis preserved; uncertainty not artificially narrowed |
| Q08-N07 | Schema-valid F2 packet declared a useful product without human evidence | Structural evidence remains within its scope; usability/product-signal gate remains open |
| Q08-N08 | Everything is rejected “for reliability,” including supported tasks | Handling and achieved goal differ; outcome floor not met |
| Q08-N09 | Challenger changes the final checker or chooses two convenient families after scoring | New criterion/selection experiment, not current Core030 acceptance |
| Q08-N10 | Report removes failures, unknown costs, and early search candidates | Comparison rejected; denominator, lineage, and campaign cost reconstructed from appropriate receipts |

<a id="8-admission-claims-та-наступне-рішення"></a>
## 8. Admission, claims, and the next decision

Before any future execution, the following are required: a qualified local model/tool/runner profile, permitted fixture/data rights, owner budget/caps, independent custodian/reviewer, TaskSetManifest with actually prepared roots, a frozen protocol, and a recovery/stop envelope. Calibration/admission do not require an already measured improvement; **adoption** requires it after execution. Code/test harnesses are implemented only after a separate decision to begin implementation.

A separate local proof of one source **or** harness mutation may be an early technical slice. Full RSI019 acceptance requires at least one harness change **and** one source change, a failed candidate, and recovery. RSI024 is the subsequent recursive-method proof. RSI030 is a standalone product with benefit in two independently constructed non-game families, a human product signal, an evaluator challenge, and rollback. None of these gates receives a pass from this document or the public recipes.

Q08 refines existing RSI003/005/007/015/030 and the evidence plan; IDs and dependencies are preserved. W0 gains no new prerequisites. Q01–Q08 are complete as bounded source/design passes, not as implementation or complete reading of nine novels. The current queue retains Q09 (participants/actual experience) and Q10 (resources/profile/implementation order). Automatic passes pause after this delivery until those conditions change or a new research question arises.
