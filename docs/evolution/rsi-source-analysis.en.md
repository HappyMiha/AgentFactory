<a id="rsi-від-перевіреного-джерела-до-вимог-продукту"></a>
# RSI: from verified sources to product requirements


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [rsi-source-analysis.md](rsi-source-analysis.md). Source SHA-256 (UTF-8/LF): `b6f62af896a1417e5b3ecad2c9496367e83f16315f90f9ab5fea54924a33b62e`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](rsi-source-analysis.md).

Initial analysis: 2026-09-09; primary-methods passes Q03/Q04: 2026-09-10. Status: a research basis for design, not evidence of product readiness.

<a id="джерело-та-межі-перевірки"></a>
## Source and verification limits

**RSI-SURVEY** — Mingguang Chen, Licheng Wang, Bo Qu, *Recursive Self-Improvement in AI: From Bounded Self-Refinement to Autonomous Research Loops*, [arXiv:2607.07663v2](https://arxiv.org/abs/2607.07663v2), 6 September 2026, 44 pages. The supplied PDF identifies v2 in `/arXivID`; SHA-256: `a7622a4816c873ea45d511de909b5cbbf5c8f366a4515ea31e00ef2362e2a3f7`. The title page says July 2026; this does not conflict with the v2 revision date.

Text was extracted locally from all 44 pages. The main argument, §§1–9, pages 1–30, was read; the bibliography on pages 30–44 was consulted selectively for key references, not treated as 196 separately read papers. Figure 5 on page 18 was visually checked. Survey metadata and abstracts of four key primary sources were checked against arXiv on 2026-09-09. Experiments were not reproduced. Web verification through Firecrawl could not proceed because credits were unavailable; arXiv was accessed through the available web tool. The books and local PDF were not uploaded anywhere.

Critical limits of the survey itself: the 1,250 arXiv publications are a sample, not a census of science; 871 initial + 379 additional papers; one classification annotator; roughly 54 of the 379 additional papers are peripheral but retained in aggregate counts; a strong bias towards 2026; and many internal industry results are inaccessible (§2.3, pp. 5–6). Percentages describe this corpus, not the entire field.

<a id="реєстр-тверджень"></a>
## Claim register

| ID | Verified claim and locator | Strength and limitation | Consequence for Lokvetia / Lokiravia |
| --- | --- | --- | --- |
| R01 | Four improvement targets: deployment, training, evaluator, research; a separate axis for loop closure (§2.2, pp. 4–5) | The authors' taxonomy; categories are not successive maturity levels | Each experiment records its target, persistence mechanism, autonomy and external grounding |
| R02 | The harness includes prompts, tools, memory, skills, retrieval, orchestration and stopping rules (§2.1, p. 3) | A definition; changing the harness is not equivalent to changing weights | Core can improve its own components while the base model remains unchanged |
| R03 | Scaffolding and skill changes accumulate across episodes (§3.5–3.6, pp. 11–13) | Persistence increases both benefit and the reach of regressions | Versions, provenance, dependent consumers, revocation and migration verification are part of every change |
| R04 | Formal verifier → execution feedback → learned judge → intrinsic signal (§5.2, pp. 17–18, Figure 5) | The authors explicitly describe the relationship with improvement strength as a qualitative pattern, not a measured law | Use the strongest available signal for each claim; tests do not prove complete correctness |
| R05 | Mirror Loop: 10 rounds, three providers, four task families; a 55% fall in informational change and an effect from external verification are reported (§5.2, p. 18, ref. 140) | A result reported in the survey; the individual study and metric were not reproduced | Compare reflection with resampling and equal-budget controls; do not sell round count as progress |
| R06 | Self-confirmation, model collapse, diversity collapse, frame lock-in (§5.3, pp. 18–19) | Different mechanisms; collapse is possible even with verifiable rewards | Use different detectors; null results and candidate rejection are valid outcomes |
| R07 | Selecting the space of questions precedes evaluating answers (§5.4, p. 20) | A good evaluator does not prove that an objective is relevant | Core should investigate its own product objective and propose changes through a separate decision |
| R08 | Result-level and process-level improvement differ in cost and transferability (§5.5, pp. 20–21) | A conceptual synthesis | Measure whether the next generation conducts the next cycle better/at lower cost on new tasks |
| R09 | A-Evolve-Training: 30B, four rounds, 0.86 vs 0.87, a human-defined objective (§6.2, pp. 22–23, ref. 180) | The experiment authors' report, not general superiority over researchers | The training loop is a separate later direction; starting with the harness does not require training a large model |
| R10 | A high development score diverged from the external result; the search policy was revised (same passage) | Local proxy correction, not proof of autonomous selection of any socially valuable objective | An external-outcome canary, an archive of disagreements, alternative objectives and a limit on cycles without improvement |
| R11 | Scientific reports can appear convincing without corresponding artifact quality (§6.3, pp. 23–24) | Reading the report cannot substitute for artifact review | An evidence manifest binds every claim to a run and failed outcomes |
| R12 | Six open problems: grounding, non-verifiable quality, stability, accumulation, measurement, frame revision (§8, pp. 28–29) | Research questions, not ready-made APIs or solved problems | Separate the delivery backlog from the research portfolio and define criteria for terminating hypotheses |

<a id="адресна-перевірка-першоджерел"></a>
## Targeted primary-source verification

**RSI-DGM / RSI-RQGM.** Q03 replaced the earlier metadata/abstract-only basis with direct reading of versioned PDFs. The [DGM-01–03 / RQGM-01–03 matrix](evaluator-succession.en.md) records verified methods, budget/theoretical limitations, locators and separate project criteria for AF-RSI020–024. The text of 34 pages of each paper was read in full; exact ranges and hashes are in sources.json. We do not claim to have read every listing/reference or reproduced the results.

**RSI-AEVOLVE.** Q04 read the full 12-page text of [v3, dated 08.09.2026](https://arxiv.org/pdf/2606.20657v3) and compared it with the supplied survey v2 dated 06.09. The [AE-01–05 matrix](training-research.en.md) clarifies autonomy, policy-only promotion, the role of external feedback, scale and the unknown budget. R09/R10 agree with the primary text within those limits. This is not a textual diff of the earlier A-Evolve v2→v3; no such diff was performed. Exact coverage/hash and survey rereading are recorded in sources.json; results were not reproduced.

**RSI-SOUNDNESS** — [SoundnessBench, arXiv:2605.30329v1](https://arxiv.org/abs/2605.30329v1), metadata/abstract verified. 1,099 reconstructed proposals, 12 models, optimism bias. It measures recoverable soundness at the proposal stage, not precise prediction of the final peer review outcome. Consequence: the proposer and judge must not decide alone where to spend the entire research budget.

Gödel Agent, Escher-Loop, Experience Graph, SkillsBench and other papers from §§3–6 are used here **through the survey**, without claiming each was independently read. Their names are not grounds for adopting a component or API in the product.

<a id="архітектурний-висновок-обєктом-є-сам-core"></a>
## Architectural conclusion: Core itself is the target

Our working formula is `Hypothesis → Candidate → Isolated execution → Evidence → Independent comparison → Accept / Reject / Inconclusive → Versioned persistence → Next-generation experiment`. This is our architectural synthesis, not a verbatim diagram from the paper.

Core's first evolution targets are routing policy, context assembly, verified skills, tool contracts, retry/stop policy, memory retrieval and decomposition. Later targets include its developer tools, runtime/architecture candidates, experimental methodology, search scheduler and evaluator candidates. Weight training and production-runtime self-modification are separate levels requiring new evidence.

Actual recursion must be evaluated separately: generation G1 must not merely perform a task better; it must also conduct the next cycle on a new task distribution better than G0 under an equal budget. This requires at least a baseline without evolution, a control with additional attempts but no persistence, and an ablation without the new method. More compute, a newer model, an accumulated test hint or a more accommodating judge does not by itself demonstrate a recursive effect.

In Lokiravia, software verification can establish causal integrity, resource balance, absence of duplicate rewards and save compatibility. It cannot prove humour, a sense of life or the value of surprise. Those qualities require blinded comparisons of human experience, representative playtests, negative feedback and room for people to dislike the result. Time spent in the game is not a sufficient objective on its own.

<a id="дослідницькі-тести-які-можуть-спростувати-наш-задум"></a>
## Research tests that could falsify the concept

1. **Grounding budget.** Under equal compute, vary the proportion of external checks; compare held-out quality, regressions and cost per accepted improvement. There is no basis for promising a universal minimum percentage in advance.
2. **Method transfer.** G1 selects/conducts new experiments; G0 and G1 have equal resources and holdouts unavailable in advance. If only a familiar benchmark improves, reject the process-improvement claim.
3. **Proxy reversal.** Development scores rise while real success declines. Test detection, stopping, proposing an alternative hypothesis and preserving unfavourable evidence.
4. **Evaluator succession.** The incumbent evaluator, external anchors and withheld adversarial cases assess a new evaluator; changes occur between epochs. Test cases where the old evaluator is itself wrong: disagreements need independent resolution, not a permanent veto by the old system.
5. **Durable memory.** Revoke a corrupt skill and find its derivatives; demonstrate that subsequent calls do not use the revoked version. Retain redacted forensic provenance without restoring deleted personal data.
6. **World novelty.** Compare causally connected surprise with a random plot twist and a static authored baseline. Do not conceal some participants' lower ratings behind an average score.
7. **Frame revision.** Provide a task with an obsolete objective but a rising local metric; assess correct termination, preserved invariants, a new objective and response latency. This is our experimental design, not an already validated benchmark.

All tests are requirements for future verification. This analysis did not run self-modification, model training or player experiments.
