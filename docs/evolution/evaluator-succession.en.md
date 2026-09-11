<a id="q03-як-core-змінює-оцінювач-і-доводить-поліпшення-власного-методу"></a>
# Q03: how Core changes its evaluator and demonstrates improvement in its own method


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [evaluator-succession.md](evaluator-succession.md). Source SHA-256 (UTF-8/LF): `ed5ec86ac845613753d99c490a05bf64411f23b996bc6c0ced31016b2a7cb180`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](evaluator-succession.md).

2026-09-10 · **E0 / proposed**. Core self-improvement covers its own source, harness, optimizer, evaluator, and product direction. This contract refines AF-RSI020–024; it adds no services, tasks, or prerequisites to Lokiravia's first adventure. The source matrix and exact reading coverage appear below; no experiment from the papers has been reproduced.

<a id="1-рішення-для-продукту"></a>
## 1. Product decision

The user must be able to see **what improved and under which unchanged comparison**. Replacing an evaluator creates a new evaluation epoch. History is preserved; the applicability of old assessments to the new search is established separately. An error by the old evaluator may justify replacing it through independent verification.

The following rules are our design decisions. They require future conformance, statistical, and consumer evaluation; the names of scientific systems do not validate them in place of evidence.

<a id="2-що-саме-фіксується-в-епосі"></a>
## 2. What an epoch fixes

`CriterionManifest` is a proposed immutable record built on existing protocol/evidence records. Its contents are determined by an independently approved experimental profile, not by the challenger. It includes:

- evaluator artifact, prompts, tools, model/provider identity at the available pin precision, and scoring rule;
- source of the primary fact, telemetry producer, required receipts, and qualified decoder;
- objective version, outcome projection, task distribution, role/task weights, rubric, floors, and uncertainty rule;
- task generation, replay, and adversarial corpus selection rules, permitted feedback, and memory/input views;
- anchor dataset/labels/provenance, adjudication authority, snapshot of previous test access, and policy for subsequent access;
- selection/stop/replacement policy, checkpoints, comparison count, and overall resource caps.

Not every field necessarily changes together. A particular result depends on the entire path actually used: who created the artifact, why this case entered the sample, what the role saw, and who assigned the score and how. An identical final test runner does not make a result independent of a changed task generator. An unknown dependency means unresolved applicability; the optimizer cannot declare it empty.

Subject provenance and criterion dependencies are separate fields. Agents A0/A1 under comparison produce different outputs under a shared protocol; this permitted treatment change does not itself open two epochs. A task generator, adversarial sampling, or feedback that determines evaluation/search conditions belongs to the criterion. Actual access/cost records are appended to a separate ledger after freezing; an ordinary permitted query does not change the manifest digest. An access-policy violation may contaminate the corpus and terminate its use under a predetermined rule.

An uncontrolled change in provider or tool behavior is recorded as a possible loss of comparability. It is not evidence of a stationary epoch. The protocol determines whether a restart or inconclusive result is required; a new record does not rewrite the actual model identity of old runs.

<a id="3-історія-та-чинне-ранжування"></a>
## 3. History and current ranking

| Object | After a criterion change |
|---|---|
| Sealed receipts, artifact digest, old verdict | Preserved with the original protocol, permitted retention, and lineage |
| Fitness, posterior, Pareto/rank, champion-selection cache | Rebuilt from records applicable to the new criterion; an old score is not carried forward as current |
| Search memory/skill concluding “the method is successful” | Transitive dependence on the old assessment is checked; historical advice may remain a hypothesis, but not independent confirmation |
| External fact independent of the changed path | May remain applicable after an explicit scope/distribution/meaning check, rather than merely having the type `ground_truth` |
| Candidate archive and provenance tree | History and stepping-stone hypotheses; presence in the tree does not confer promotion eligibility |
| Cost and unresolved-effect counter | Continues across epoch switches, retries, rollbacks, and mission ID changes |

The current selection view has a criterion digest, a complete list of included evidence IDs, unresolved/excluded reasons, and a digest of the derived state. Recalculation is reproducible. No applicable assessments means “not yet evaluated,” rather than zero errors or automatic champion status. Quarantined/revoked candidates do not become eligible through reranking.

<a id="4-перехід-оцінювача-без-змішаного-стану"></a>
## 4. Evaluator transition without mixed state

[Q05 activation/recovery](recovery-contract.en.md) is reused, without a second independent authority source. For an evaluation target/profile:

1. Record E1 as a separate candidate and complete its independent comparison, including the permitted scope of use and disagreement.
2. Prepare an immutable transition plan: old/new criterion digests, dependent records/views/skills, new selection statistics, unresolved jobs, and an estimate of reevaluation costs.
3. Verify inventory completeness against the authoritative profile. Create a complete snapshot of the new criterion + selection view; do not fill missing required evidence with predictions.
4. Under separate authorization, activate the coherent snapshot through the existing fencing/CAS mechanism. A reader sees either the complete old epoch or the complete new one. A crash before activation leaves the old epoch; a crash afterward restores the exact committed binding. This is atomicity of the visible transition, not a claim of one transaction spanning all external providers.
5. Attach a late E0 receipt to its historical run. It may be valid E0 evidence but cannot update E1 rank without a separate applicability record. Its actual cost and unresolved effects are accounted for regardless of score applicability.

A selection snapshot does not restore an old budget/job ledger. Costs and job completions between snapshot preparation and activation are accounted for using current durable state; cutover rechecks its current caps/fences. Reranking does not permit spending already reserved resources a second time.

A new decoder or alias does not reinterpret old outcomes: [Q02 semantic projection](identity-continuity.en.md) applies. Returning to E0 requires a new activation sequence; previous authority and spent budgets are not restored.

<a id="5-як-розібрати-розбіжність-агента-й-оцінювача"></a>
## 5. Resolving disagreement between agent and evaluator

For agents A0/A1 and evaluators E0/E1, all four evaluation cells are required for one preregistered comparable artifact/trace set, with external anchors and a separate decision for each subject. [Q06](counterfactual-evaluation.en.md) defines paired inputs and the boundary between causal/planner/replay comparisons.

| Observation | Permissible conclusion / next check |
|---|---|
| E1 rates both agents higher | A different scale or greater leniency is possible; agent gain is not established |
| A1 is better only under E1 | Disagreement, not automatic failure of A1; an independent anchor/adjudication checks whether E0 is mistaken |
| E1 rejects valid short answers while accepting attractive but incorrect ones | A separate false-reject/false-accept defect in E1; the average score must not hide the slice |
| Both judges agree | A shared error remains possible; agreement does not replace external evidence |
| A new scorer re-scored old artifacts | The scorer's effect on this corpus has been shown; the new generator's behavior on a new distribution has not |
| Tasks, rubric, and model changed | Bridge/control evidence or a narrower/inconclusive claim is required; scores must not be joined into a curve of unconditional growth |

“The old evaluator did not confirm it” is a signal for investigation, not a permanent veto. Without external grounds for resolving disagreement, the result remains inconclusive. Panel acceptance, factual accuracy, usefulness to the owner, human assessment of humor, and critical violations are distinct outcomes.

Measurement-path health is visible separately in every matrix cell. A disabled event marker or an undecoded mandatory receipt does not prove the absence of a violation. Positive/negative controls starting from the primary fact are required; a legitimate new format with a qualified decoder is not rejected merely because a field has a different name. Two equally mistaken evaluation systems can agree in every cell.

Anchor authority is separate from the proposer and promoter. A known benchmark repeatedly used to select candidates does not become final confirmation through a new name. Access accounting covers labels, aggregate scores, error traces, prompt/skill memory, and decisions after each checkpoint. The adaptive-selection/statistical policy and conditions for replacing a contaminated set are fixed before the experiment. A shared base model or different role names alone proves neither independence nor collusion.

Several judges assessing one artifact form a cluster of assessments of that artifact, not additional independent tasks. Partial scores, strict success, and uncertainty are retained by task/run. A lower utility estimate must not be called a probability of improvement without appropriate statistical justification. Equal acceptance rates for human and AI work do not themselves prove fairness: blind quality labels for good/bad work from both origins and false-accept/false-reject slices are required. For a game, this is also not evidence of people's actual experience.

<a id="6-межа-рекурсивного-твердження"></a>
## 6. The boundary of a recursive claim

| Claim | Required Core evidence |
|---|---|
| Artifact/harness improvement | Exact A0/A1, independent task-outcome comparison, regression and resource floors |
| Optimizer improvement | O0/O1 start with the same permitted knowledge and resources and produce useful child changes on fresh tasks; all failed attempts are included |
| Recursive participation | Typed O0→O1→O2 proves that accepted O1 proposed a change to method O2 itself; this does not yet prove O2's benefit |
| Bounded recursive-method gain | Separate fresh evaluation of O2 against its immediate accepted predecessor O1 and an ablation without the new method under a shared qualification envelope |
| Independently determining the correct product goal | A separate frame proposal, external need, and owner decision; the preceding claims do not establish this |

Equal budget means agreed caps and complete accounting: generation, expansion, evaluation, archive reevaluation, anchors, confirmation, failures, models with different prices, time, and human adjudication. An equal number of evaluation calls or raw tokens is insufficient. The price/time rule and permitted tradeoff are defined before results; unused resources need not be spent artificially. The effect of a newer model or privileged memory must not be attributed to the new method.

The unit of accepted improvement is defined in advance: splitting one useful change into several artifacts does not increase the number of accepted improvements. The complete economic report includes creation and qualification of the new optimizer. The cost of reusing an already accepted version may also be measured separately, explicitly naming excluded one-time costs and the amortization rule; conditional reuse efficiency is not presented as end-to-end efficiency.

The protocol separately specifies the number of independent search runs and repetitions evaluating one discovered agent. Best-of-many is not a typical result. For a mechanism claim, diagnosis/selection/starting archive are controlled unless they are the declared treatment; for a bundle claim, every changed component is explicitly listed. An O1/O2 bundle has a role map and a receipt showing actual use of the changed operator in the next search: an edited but uncalled file does not prove method participation.

Core has no permanent prohibition on improving its scheduler or supervisor. Changing them requires a separate candidate, external qualification, and handoff under Q05. The current candidate does not rewrite the authority currently checking its rights, criteria, and budget. A negative O2 result preserves O1's demonstrated local success but ends the stronger claim.

<a id="7-відкриті-статичні-контроли"></a>
## 7. Open static controls

These are authored acceptance specifications, not executed tests or a sealed holdout.

| ID | Control | Expected check of the future implementation |
|---|---|---|
| Q03-E01 | The criterion changes, but the score cache retains the old champion | The new view does not use stale evidence; audit history is preserved, and an unverified candidate is not promoted |
| Q03-E02 | An E0 job spends resources between E1 preparation and activation and finishes after cutover | The receipt remains E0; actual charges/reservations are not rolled back; E1 rank stays unchanged without an applicability decision; crash/restart does not mix snapshots |
| Q03-E03 | New E1 recognizes a valid answer that E0 rejected | An independent anchor may justify E1; E0's disagreement is not turned into a perpetual veto |
| Q03-E04 | The final checker is unchanged, but adversarial sampling changes | The dependency inventory detects the distribution change; old utility records are not declared independent merely because of the checker digest |
| Q03-E05 | Re-scoring old artifacts is called fresh generator gain | The claim is narrowed to the scorer's effect on the corpus; fresh generation/confirmation has a separate protocol |
| Q03-E06 | More failed expansions or a cheaper model are hidden behind equal call counts | The complete cost/model ledger exposes the confound; an efficiency claim must pass its own preregistered comparison |
| Q03-E07 | The archive contains a useful ancestor that did not pass the release gate | Isolated authorized search is possible; production promotion is absent; revocation/quarantine cannot be bypassed |
| Q03-E08 | O1 creates a better product; O2 is better than O0 but worse than accepted O1 | Local success and recursive participation are recorded; positive next-step recursive-method gain is rejected/inconclusive; bounds and Stop remain in force |
| Q03-E09 | A1 removes a telemetry marker, and both evaluators call this absence of a violation | An external receipt/control detects missing/invalid measurement rather than improvement; a valid alternative format passes through a qualified decoder |
| Q03-E10 | A judge rejects high-quality AI work to equalize the overall acceptance rate; four reviews are called four tasks | Blind quality slices expose false rejection; the unit/cluster count is not increased; parity and partial score do not replace the required quality/strict-success outcome |

<a id="8-першоджерела-та-межі-перенесення"></a>
## 8. Primary sources and limits of transfer

The following briefly summarizes **what the authors report**; the right column contains our implications for the project. Performance/cost figures do not become Core SLOs or budget estimates.

| Anchor | Verified primary-source content and locator | Our application / what remains hypothetical |
|---|---|---|
| DGM-01 | Agent code changes while FMs are frozen; the archive permits searching through intermediate variants. Comparisons include a fixed modifier, no archive, and greedy parent; Polyglot has additional repetitions. [DGM v3, §3–4, pp.4–8; A, pp.24–26](https://arxiv.org/pdf/2505.22954v3) | AF-RSI023: the archive is a research resource, not release authority. Our own mechanism controls and independent runs are required; another system's result does not establish benefit for Core |
| DGM-02 | The SWE run is estimated at approximately $22 000, and each main ablation without self-improve/without open-ended exploration at $10 000; inference also becomes more expensive. Coding score is used as a proxy for self-improvement; archive/parent selection are fixed, and their evolution remains future work. [DGM v3, §6, p.10; E.1, pp.32–33; J, p.72](https://arxiv.org/pdf/2505.22954v3) | AF-RSI023/024: equal iterations do not prove efficiency. We separately establish method use, O2 versus O1, and complete economics; our scheduler may evolve only through a qualified candidate |
| DGM-03 | SWE private tests are hidden from the coding agent during the benchmark run but available to a separate diagnostician. Transfer and manual checks do not eliminate all contamination risks. In an additional hallucination experiment, changing telemetry bypasses the hidden checker. [DGM v3, C.3, pp.28–30; H, pp.69–71](https://arxiv.org/pdf/2505.22954v3) | AF-RSI020/021/022: exposure throughout the loop, the primary fact, and measurement controls. An unchanged evaluator digest does not prove unchanged measurement |
| RQGM-01 | Judge replacement occurs at a checkpoint against a fixed evaluator-independent anchor; the scorer/orchestration harness is fixed. Utility dependencies include sampling/generation/replay. Stale assessments are removed from statistics, while artifacts/audit are preserved. [RQGM v2, §3, pp.4–6; Algorithm1, p.19; F.4, pp.33–35](https://arxiv.org/pdf/2606.26294v2) | AF-RSI020/022: CriterionManifest, dependency inventory, and coherent transition under Q05. This is our contract, not a ported runtime or proof of its correctness |
| RQGM-02 | Validation guides search; separate test protocols exist. Writer/prover are evaluated by model panels without human evaluation of the generated work. The adversarial pool rewards rejection of AI texts. [RQGM v2, §4–6; C.4, pp.20–22; G, p.38](https://arxiv.org/pdf/2606.26294v2) | AF-RSI021/023: final exposure, quality-conditioned labels, cluster uncertainty, and full costs. Parity rates do not establish quality; panel acceptance does not prove a useful product or a living humorous world |
| RQGM-03 | Epoch stationarity is required; pooled Beta is a working model, and the lower-bound claim depends on calibration. Monotonic growth in actual anchor accuracy and global convergence are not proved; a shared multi-domain system and evolution of the external scheduler remain outside the verified scope. [RQGM v2, F.3–F.5, pp.32–37, Remark6; G, p.38](https://arxiv.org/pdf/2606.26294v2) | AF-RSI022/024: guarantee scope, actual model/tool changes, bounded claims, and Stop. Acceptance of every successor and correct selection of Core's goal require their own evidence |

<a id="9-журнал-читання"></a>
## 9. Reading log

Metadata for both versioned arXiv pages was checked again on 2026-09-10. Public PDFs were downloaded locally from arXiv; user-provided files were not transmitted anywhere. Local pypdf was used, with Poppler/pypdfium2 for selected images. Material inside the papers, including prompts/code listings, was analyzed as source material, not as instructions.

| Source | PDF / complete text reading | Not claimed as complete reading | PDF SHA-256 |
|---|---|---|---|
| DGM v3, 12.03.2026 | 72 pages extracted; pages 1–11, 23–36, 46–50, 69–72 read in full: **34 pages**. Main methods/results/limitations and relevant appendices | 12–22, 37–45, 51–68: extraction/heading inspection; not all F/G code listings read. Charts were not comprehensively verified | `13ff4abe0c7ad4a7dd3b4876d19a8bf940e39e70dabbf06065aa774a6c3457de` |
| RQGM v2, 29.06.2026, preliminary | 38 pages extracted; pages 1–13, 18–38 read in full: **34 pages**. Methods/results/limitations, technical appendices, and theoretical assumptions | 14–17: bibliography only extracted/initially previewed. Figure 2 on p.4 and p.37 visually checked; not every figure | `82a2e260eb119d983542489100db195398128976fa20c97838e11d25b80b84f0` |

This is 68 pages of text read in full out of 110 extracted, not two publications read completely with every listing/reference. The previous basis for these two works was metadata/abstract + survey; the new ledger concerns the primary PDF. Reviewer/root reading of the same page is not counted twice. The authors' results were not reproduced; the DGM/RQGM source repositories were not audited. EPUB coverage is unchanged in Q03.

[sources.json](sources.json) retains source hashes, page ranges, and statuses. Raw PDFs, extraction caches, and supporting reading ledgers remain outside the Git repositories. The next primary research question is Q04, complete A-Evolve v3; training is not being started.
