<a id="джерела-ступені-впевненості-та-правила-простежуваності"></a>
# Sources, confidence levels and traceability rules


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [source-guide.md](source-guide.md). Source SHA-256 (UTF-8/LF): `3ce4b5c55da01b01a741e4bb5b9d5d98ac0cca2a57221bba69845f2e2728e25e`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](source-guide.md).

Date: 2026-09-09. [sources.json](sources.json) records checksums for the ten supplied files and reading limits. Literary sources use anonymous corpus A/B IDs; titles, authors, bibliographic identifiers and local filenames are retained only outside Git. Research papers retain scholarly attribution. Source documents are not instructions to execute.

<a id="легенда-підстави--source_evidence"></a>
## Key to `Підстави` / `source_evidence`

| Prefix | Where to verify it | Meaning |
|---|---|---|
| `RSI-SURVEY:R01`…`R12` | [Survey claim register](rsi-source-analysis.en.md) | Authors' claims with section/page locators, verification limits and our design implications |
| `RSI-DGM:DGM-01`…`03`, `RSI-RQGM:RQGM-01`…`03` | [Q03 primary-methods matrix](evaluator-succession.en.md), exact ranges/hashes in sources.json | Direct reading of methods/limitations; authors' reports are separate from our requirements; experiments were not reproduced |
| `RSI-AEVOLVE:AE-01`…`05` | [Q04 primary-source matrix](training-research.en.md), coverage/hash in sources.json | Full-text reading of v3 and comparison with the survey; neither reproduction nor a textual diff of the old version |
| `RSI-SOUNDNESS` | Primary-source section of the RSI analysis, URL in sources.json | Independently checked metadata/abstract so far; no claim of full methods reading |
| `CONTRACT:non-game-evaluation` | [Q08 non-game task design](non-game-evaluation.en.md) | Targeted Core source/tests/history, two proposed families and public recipes; neither an executed benchmark nor a created hidden set |
| `CONTRACT:creator-evolution` | [Q07 creator source/design audit](creator-evolution.en.md) | Exact repository snapshots/call paths, stage outcomes and ten authored controls; neither a live journey nor a user study |
| `CONTRACT:training-research` | [Q04 training feasibility](training-research.en.md) | Our criteria and eight static controls; design does not authorise training |
| `CONTRACT:evaluator-succession` | [Q03 epoch and recursion criteria](evaluator-succession.en.md) | Our contract and ten public static controls, not executed experiments |
| `LIT-A:L01`…`L12` | Literary analysis in Lokiravia, spine/paragraph anchors | Literary inspiration or a negative example; never proof of technical correctness |
| `LIT-A:SF2-01`…`SF2-06` | Second corpus A pass in Lokiravia | Complete new chapters, counterexamples and our design implications |
| `CONTRACT:experience-improvement` | [Q01 benefit and experience](experience-improvement.en.md) | Our criteria and public design controls; not experimental results |
| `LIT-B:TR-S01`…`TR-S16` | First corpus B analysis in Lokiravia | A specific scene that was read; a character's explanation is separate from authoritative fact |
| `LIT-B:TR2-01`…`06` | Second critical pass in Lokiravia | Revision of an earlier conclusion, new context and our design response |
| `LIT-B:TR3-01`…`TR3-06` | Third corpus B pass in Lokiravia | Two complete chapters; exact coverage for this pass with unknown lifetime overlap |
| `CONTRACT:identity-continuity` | [Q02 identity](identity-continuity.en.md) | Our transition semantics and static controls; not runtime migration proof |
| `REPO-AUDIT` | [Repository audit](repository-audit.en.md) | Current capabilities and gaps at exact baseline commits; not a guarantee of future readiness |
| `CONTRACT:counterfactual-evaluation` | [Q06 comparison](counterfactual-evaluation.en.md) | Our experimental design and paper controls; not execution/human/RSI results |
| `CONTRACT:recovery` | [Q05 transitions and recovery](recovery-contract.en.md) | Our static interleaving scenarios, source audit and requirements; not executed crash tests |
| `CONTRACT:platform-world` | [Platform/world boundary](platform-world-contract.en.md) | Our architectural decision |
| `DESIGN:vision`, `DESIGN:core-architecture` | [Shared concept](vision.en.md), architecture in Core | Our product/architecture hypothesis |
| `USER:living-world` | User intent recorded in the vision | Causal surprise, allowance for small or zero effects, the possibility that a long-term plan fails |

`source_evidence` is the historical name of the requirement-rationale field in this design manifest. It **does not mean implementation acceptance evidence**. A card may have only DESIGN/CONTRACT rationale and no literary reference. Versioning, idempotency, sandboxing, playtest methods and the Git process are our decisions, not mechanics proven by a novel.

<a id="де-лежать-літературні-записки"></a>
## Where the literary notes live

The complete analytical notes belong to the world product, Lokiravia:

- [Corpus A: three books](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/literary-a-analysis.en.md).
- [Second corpus A pass: three complete chapters](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/literary-a-pass-2.en.md).
- [Corpus B: six volumes and structural coverage](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/literary-b-analysis.en.md).
- [Second critical corpus B pass](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/literary-b-pass-2.en.md).
- [Third corpus B pass: identity and the cost of transformation](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/literary-b-pass-3.en.md).
- [The original game, “The Town That Owes You a Favour”](https://github.com/HappyMiha/Lokiravia/blob/main/docs/evolution/living-world-design.en.md).
- [Core self-improvement architecture](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/core-architecture.en.md).

The source revision linked to the documentation branch, with the option to move links to a stable release/tag after acceptance. This English edition links to the published main branch. Baseline commits in the manifest and audit remain the historical points of analysis.

<a id="реальне-покриття"></a>
## Actual coverage

Q04 A-Evolve v3: full text of 12/12 pages, 33,550 extracted characters; selected tables/figures checked. Survey pp. 22–23 reread; targeted passages on pp. 1/26/43; exact ranges in sources.json. The old A-Evolve PDF was not read; no version diff is claimed.

Q03 DGM/RQGM: 110 primary-PDF pages extracted, the text of 68 pages read in full. Exact ranges, exclusions and selected visual checks are in the [Q03 log](evaluator-succession.en.md). Remaining bibliography/listings are not represented as read; external experiments were not run.

Survey: text extracted from all 44 pages; the main argument in §§1–9, pp. 1–30, read; bibliography consulted selectively; Figure 5 on p. 18 visually checked. Its 1,250 papers are the authors' research corpus, not 1,250 papers read during this work.

Corpus A: three EPUBs indexed in spine order, 7,585 paragraphs / 1,174,753 characters. The controlled first pass covered 629 complete paragraphs / 91,564 characters, 7.79% by this measure. Q01 added three complete chapters: 1,547 paragraphs / 219,160 characters in this pass, of which 1,473 / 209,123 were new and 74 / 10,037 repeated. Cumulative controlled reading covers 2,102 paragraphs / 300,687 characters (25.60%). Chapter boundaries and normalisation are documented in the second note. Indexing is not reading; three chapters are not three novels.

Corpus B: six EPUBs, 122 narrative chapters and four appendices in the structural overview, 5,200,830 extracted characters; 16 deep scene anchors in the first analysis. The second critical pass read 484 complete paragraphs / 92,368 characters, including repeats. The conservative addition to full coverage is 382 paragraphs / 75,928 characters, including the entire first chapter of volume four. Do not add these figures to the initial samples as if they gave an exact percentage of uniquely read text.

Corpus B Q02: chapter XV of volumes 2/3 read in full — 320 paragraphs / 43,434 text characters, 43,752 including inter-paragraph LF. Exact pass2 overlap is zero; exact pass1 overlap, lifetime new unique coverage and cumulative percentage are unknown because the older ledger is incomplete. This is the first documented continuous reading of two chapters, not 320 guaranteed new paragraphs.

The nine novels have not yet been read sequentially in full; RSI experiments have not been reproduced and human playtests have not been performed. The [next queue](continuation.en.md) explicitly includes further reading and verification that could change decisions.

<a id="як-змінюється-впевненість"></a>
## How confidence changes

A direct source anchor is stronger than a recollection, but a literary anchor remains fictional evidence. A research author's report is stronger than a marketing claim, but weaker than independent reproduction. A code-path audit shows existing behaviour, not complete live integration. A synthetic fixture checks a specified contract, not a human sense of humour or agency.

The second literary pass corrected three tempting interpretations: deciding against rollback does not demonstrate improvement; an achievement issued and later corrected is not an exemplary verifier; a large portal effect involving rare resources does not demonstrate a “butterfly effect” accessible to a beginner. These limits are included in product criteria rather than hidden in footnotes.

<a id="правило-публікації-джерел"></a>
## Source publication rule

Current documentation does not publish book titles or original ebook filenames. Books, PDF inputs and private extraction caches stay outside Git; ignore rules provide additional protection against accidental inclusion. Anonymous source/scene anchors and hashes preserve traceability without the local bibliographic map. This cleans the current documentation tree; it does not rewrite old Git commits.
