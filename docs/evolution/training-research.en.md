<a id="q04-коли-навчання-моделі-справді-поліпшує-lokvetia-core"></a>
# Q04: when model training actually improves Lokvetia Core


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [training-research.md](training-research.md). Source SHA-256 (UTF-8/LF): `901976703d5f12df04b5951d8bc3c9cd881988f0e0b0a028e1aabbf450800bef`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](training-research.md).

2026-09-10 · **E0 / proposed**. AF-RSI035 is an optional research direction. The current delivery defines a protocol; it does not authorize training, expenditure, or deployment. Standalone Core030 and Lokiravia's first adventure do not depend on training 035.

Core must improve its own source, harness, tools, optimizer, evaluator, and product decisions. Weight training is another possible tool. Its suitability is established by the additional benefit for a specific Core task and its full cost. A large model, a completed GPU job, or lower training loss does not establish that benefit on its own.

<a id="1-три-різні-рішення"></a>
## 1. Three distinct decisions

| Decision | What is required | What it permits |
|---|---|---|
| Feasibility / accept research design | An observable Core problem, an available model/data profile, a cheaper alternative, and a protocol capable of distinguishing the outcome | Prepare a pilot proposal that can be assessed; gain has not yet been measured |
| Admit bounded pilot | Explicit authorization for specific resources, current rights, exact inputs/limits, external verification, recovery, and stop policy | One specified experiment within the authorized scope; not adoption |
| Adopt / reject / inconclusive | Actual sealed receipts, comparison against the baseline, product/regression/cost outcomes, and qualification | Accept a bounded claim; rollout requires a separate promotion decision |

Requiring an already measured training gain before the first pilot would be circular. Before execution, assess feasibility and the protocol's ability to answer the question; afterward, assess the result. Missing rights/resources produce `not_admitted`, insufficient evidence produces `inconclusive`, and a demonstrated unfavorable result produces `no-go`. These reasons are not conflated with a technical run failure.

<a id="2-початкова-продуктова-гіпотеза"></a>
## 2. Initial product hypothesis

Each proposal identifies the Core user, observed failure, task family, and primary outcome: for example, correct execution of a tool contract or fewer failed code-repair attempts. It explains why training might solve the problem and tests a frozen-weight harness-only alternative. Benchmark growth or verbosity alone is not an independent benefit.

The model/adapter, training method, and scale are selected after checking signal availability and sufficiency. The paper's 30B/120B/550B figures do not set a minimum size for Core. A small pilot also does not prove transferability to larger models or other task families. If the budget is insufficient for comparable measurements, narrow the claim or do not run the experiment.

<a id="3-що-є-кандидатом"></a>
## 3. What constitutes a candidate

The proposed records build on existing Candidate/Experiment/Evidence contracts, rather than introducing a new runtime API or service:

Research-agent models/harnesses, the model being trained, and the Core component that will consume the result have separate identities. An improved external trained artifact does not prove a change in the researcher's weights or benefit to Core itself. Such a claim requires an explicit integration/serving subject and a verified Core workflow.

| Record | Immutable contents and boundary |
|---|---|
| Reference substrate | Base model/checkpoint, tokenizer/config, reference recipe, data pipeline, trainer/evaluation environment, and permitted mutations. This is an exact reference, not mutable `latest` |
| TrainingPlanManifest | Reference digest, research/controller model+harness identities, trainer version, policy/standing recipe, candidate delta, data manifests, generation/filter/dedup/split rules, seeds, caps, checkpoint-selection and evaluation protocols |
| TrainingRunReceipt | Exact plan, job/attempt identity, effective hardware/runtime, data actually consumed, reservations/charges, recovery lineage, failures, and output availability |
| ModelCandidateManifest | The created immutable output: checkpoint shards or adapter + exact base, tokenizer/config, recipe/data/run provenance, format, and compatibility. The digest is fixed after the artifact is complete |
| Comparison / adoption record | Exact model+harness subject, sealed evidence, independent verdict, permitted scope; deployment authority is separate |

A future output hash is not written into the input manifest before it exists. A mutable checkpoint alias is not a comparison identity. If the data pipeline generates or filters data during a run, the input specifies the permitted procedure and sources, while the output data manifest attests to the actual records/order/versions. An unknown actual training corpus does not become a valid claim through a dataset name.

An adaptive curriculum or schedule may be part of a program described in advance. An arbitrary recipe change made by a worker outside that program receives a new plan/attempt; it does not edit an already hashed input or remain a hidden continuation of the old experiment.

Reference, standing recipe, and mutation are separate objects. Re-forking from a shared foundation may apply a versioned standing recipe and permitted memory view; it is not necessarily a repetition of the clean baseline. Carrying forward a previous trained checkpoint as a warm start is a different declared input/treatment. A result transferred into search policy does not automatically become the next run's base checkpoint or Core's active model.

Homogeneous or specialized workers, the number of parallel branches, and shared memory are hypotheses of our profile. One scientific configuration does not establish a universally optimal agent organization. Each candidate receives a defined input/memory view; lessons may persist in a versioned policy/experience graph without hidden inheritance of a checkpoint or test answers.

<a id="4-дані-критерії-та-policy-revision"></a>
## 4. Data, criteria, and policy revision

Data manifests include provenance, permitted purpose, usage rights, derived records, dedup/split rules, and known exposure. Train, visible dev, adaptive selection feedback, and final confirmation have different roles. A public leaderboard may provide external feedback, but repeated use of its scores for search is not untouched final confirmation.

The access ledger covers data builders, diagnostic agents, summaries, optimizer memory, and checkpoint selection. Synthetic data may help training, but its own labels are not independent evidence of generalization. Unknown pretraining overlap remains unknown. Private player traces do not enter the experiment merely because they exist in Core's memory. The consequences of expiry/revocation for already derived artifacts are specified before admission; deleting a source record does not prove unlearning from completed weights.

Under [Q03](evaluator-succession.en.md), search proposal policy may change within the declared treatment scope. Internal checkpoint-selection/early-stop strategy may be part of an optimizer candidate under the same external qualification criterion; the changed plan/subject has an exact version. Changes to authoritative scoring, inclusion/task distribution, acceptance, or measurement meaning require criterion revision and an applicability check. A candidate does not lower its own acceptance threshold after seeing the result. An updated noise threshold for qualification is a separate methodological proposal for the next frozen protocol.

A drop in dev performance alongside an increase in the external outcome may be a useful signal about the proxy. It is not permission to silently change the product goal. Core's own goal, budget/rights, and promotion authority remain separate decisions; [frame revision](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/core-architecture.en.md) in Core has an external need and an identified decision-maker.

<a id="5-порівняння-та-ціна-відповіді"></a>
## 5. Comparison and the cost of obtaining an answer

The minimum design distinguishes a reference model+harness, a frozen-weight harness challenger, and a training challenger. Inputs, task family, effective serving config, feedback, quality floors, and resource accounting are specified in advance. For a claim about weights, the harness is controlled; if both change, the result is called bundle gain and requires appropriate ablations for stronger attribution.

The comparison includes dev and external outcomes, critical regressions, forgetfulness/collapse controls, latency, inference cost, and operator experience within the declared scope. The number of independent training/search runs is separate from repeated evaluations of one checkpoint; checkpoint fishing and best-of-many enter the selection/statistical policy. No seed count or gain threshold is universally sufficient: precision/variance review and budget must determine them before execution.

The resource envelope specifies GPU type/count, concurrency, wall-clock timeout, storage/egress limits, data synthesis, agent/verification calls, and a dated pricing rule. The full ledger includes failed jobs, retries, checkpoints, selection, confirmation, and human review when needed. Planned upper bound, actual expenditure, and unresolved obligation are separate fields. Time-to-first-useful-candidate does not hide the rest of the campaign's costs.

Caps apply to both the job and the entire campaign. The resource profile justifies memory/storage/throughput assumptions and their uncertainty; unknown quantities are not zero. The ledger includes billed queue/idle allocation, checkpoint I/O/export, and preparation of the reference substrate. A rolling-policy change may reallocate an authorized budget, but cannot increase the cap or authority. Without a sufficient bound on resource commitments, the pilot is not admitted or its scope is narrowed.

Serving the discovered model is assessed separately. Training may be economically justified through reuse, but break-even and amortization require explicit assumptions. More parameters, a reference to H200, or an illustrative ratio from a paper does not replace an actual resource profile and Core measurements.

<a id="6-довгий-job-відновлення-та-rollout"></a>
## 6. Long-running jobs, recovery, and rollout

[Q05 recovery](recovery-contract.en.md) applies. Remote training requires a qualified receiver profile: stable job/attempt key, available status/result/cancel receipt, and verified retry semantics. Losing a response after submission does not mean the job does not exist. Without lookup/idempotency guarantees, a repeat submission is not launched autonomously; timeout does not release spent or unresolved budget.

Resuming training state differs from a warm start using weights. The protocol specifies required checkpoint shards, optimizer/scheduler, RNG, data cursor/order, trainer/runtime/config, and permitted nondeterminism. Missing state must not be called exact resume. A weights-only warm start receives a new exact input/plan, intent, and admission within the current campaign budget; a new attempt ID under the old plan is insufficient. It cannot bypass a cap or pretend to continue the control trajectory. Even complete state does not promise bitwise identity on different hardware without separate verification.

A partial checkpoint or cancellation request is not a completed result/cancel receipt. Abort/Stop halts new work within its authority, but the actual state of already running jobs is reconciled. A new campaign ID does not reset obligations. Storage/download permissions do not automatically extend to serving.

Before rollout, qualify the exact combination of model/base+adapter, tokenizer, context/input format, quantization, inference runtime, tool-output contract, and Core harness. A research score from a different serving configuration does not accept the production bundle. Rollback returns a compatible model+harness manifest through a new activation binding; it does not restore old rights or erase costs. Q02 semantic identity and consumer constraints remain in force.

<a id="7-відкриті-статичні-контроли"></a>
## 7. Open static controls

These are authoring specifications for future verification, not executed training tests or a hidden benchmark.

| ID | Control | Expected decision |
|---|---|---|
| Q04-T01 | A pilot plan is rejected because measured gain does not yet exist before execution | Feasibility/admission assess their own prerequisites; adoption waits for actual evidence |
| Q04-T02 | After a successful recipe policy update, `default` or a model alias silently becomes the winner checkpoint | Exact reference/standing recipe/output identities reveal the input change; the comparison is not described as an unchanged baseline |
| Q04-T03 | An adapter with a different base/tokenizer or a partial shard pack achieves good dev performance | Model candidate/serving qualification does not accept an incomplete or incompatible bundle |
| Q04-T04 | A public leaderboard or diagnostic feedback repeatedly guides selection but is called an untouched final set | Exposure is preserved and the claim limited; final confirmation has an independent protocol |
| Q04-T05 | After seeing results, the meta-agent lowers the threshold for this same candidate | The current verdict remains governed by the frozen protocol; the new methodology is evaluated separately |
| Q04-T06 | A submit timeout causes a duplicate job; a Stop request resets the charge | Lookup/reconciliation and caps prevent unaccounted work; actual costs/unknown effects are preserved |
| Q04-T07 | Resume loses optimizer/data state; a new ID hides costs | Warm start has a new exact plan/input and admission under the current cap, or the run is aborted/inconclusive; exact resume and budget reset are not claimed |
| Q04-T08 | A large external model has better loss but is not used in the declared Core workflow | Model/harness/integration and product/regression outcomes are separately checked against a cheaper control; infrastructure/target-model evidence does not prove improvement in the researcher or Core |

<a id="8-першоджерело-та-зіставлення-із-survey"></a>
## 8. Primary source and comparison with the survey

The left column summarizes the authors' claims in [A-Evolve-Training v3](https://arxiv.org/pdf/2606.20657v3), by Zhan Shi and colleagues. The right column contains our conclusions. The paper does not confirm Core's implementation.

| Anchor | Source claim and locator | Implication for our decision |
|---|---|---|
| AE-01 | 30B Nemotron, four rounds, eight workers/round; challenge leaderboard 0.86 versus 0.87, standing as of 01.06.2026. Autonomy is claimed between human preparation and submission. P.1, §4 p.8, Appendix A p.12 | Survey R09 is confirmed within this scope. This is not a current ranking, statistical parity, or matched-budget superiority over researchers |
| AE-02 | The immutable default contains a base checkpoint and pipeline/training/eval code; workers re-fork, and rolling policy carries the standing recipe/axes. The constitution is immutable; promotion is policy-only. §3 pp.5–7 | We distinguish reference, policy, trained artifact, and serving adoption. Worker organization is a testable hypothesis, not a universal Core requirement |
| AE-03 | The collector obtains the leaderboard each round; the constitution already designates it authoritative. Proxy reversal changes search policy; empirical thresholds are revisable. No complete numeric acceptance algorithm/candidate ledger is provided. §3 p.7; §5 pp.8–9 | Survey R10 is consistent with policy adaptation under a specified goal. Core's independent final confirmation and thresholds require their own protocol |
| AE-04 | Table 1 ratios are illustrative, not measurements; a complete GPU-hours/cost ledger is not provided. 120B/550B appear only in the abstract: an infrastructure claim without a human baseline or separate run details. Pp.1–2, checked against the remainder of pp.3–12 | Scale feasibility does not prove quality or economics. External figures do not qualify our resource envelope |
| AE-05 | One unreplicated campaign, one task family/leaderboard; full code/substrate/checkpoint release is not yet specified. §6.1–7 pp.9–10 | Our own product evaluation, noise/selection controls, and reproduction evidence remain necessary; success is not guaranteed |

<a id="9-версії-та-точне-покриття"></a>
## 9. Versions and exact coverage

[A-Evolve history](https://arxiv.org/abs/2606.20657) lists v1 on 09.06, v2 on 25.06, and v3 on **08.09.2026**. The [supplied survey v2](https://arxiv.org/abs/2607.07663v2) was published on **06.09.2026**. Its ref180 has an unversioned URL. Here, the survey's content is compared with complete v3; the older A-Evolve PDF was not read, and no textual v2→v3 diff was performed. A detail absent from the survey is not called new in v3; which previous version the survey authors used is unknown.

The official primary PDF was downloaded locally, without sending user-provided files to a third-party service. SHA-256: `6914910acf4267f2d8280eb0371a73b438408b71b44e08ea6b12a16ec3704db7`. Text from all **12/12 pages**, including references and Appendix A, was extracted and read in full: **33 550 characters** in the pypdf extraction. This is the first documented complete text reading of this primary PDF; rereading by different reviewers does not multiply coverage. Table 1 p.2, Figure 2 p.6, Figure 3 p.8, and Table 2 p.12 were visually checked; not every detail of every illustration was verified.

Survey pp.22–23 were reread in full; pp.1/26/43 only in the exact fragments recorded in [sources.json](sources.json). This is rereading of previously examined main text and targeted bibliographic verification, not additional pages read in full. The exact lifetime overlap of earlier bibliographic fragments is not reconstructed by guessing. EPUB coverage is unchanged in Q04.

Neither the authors' campaign nor Core training was run; upstream code and checkpoints were not audited. Source instructions were analyzed as data. Raw PDFs/extracts/private ledgers remain outside Git. Q04 concludes with this research design; the next question, Q07, returns to the existing creator path brief→scope→Play→feedback→restore.
