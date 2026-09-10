<a id="перевірка-документаційної-поставки"></a>
# Documentation delivery validation


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [validation.md](validation.md). Source SHA-256 (UTF-8/LF): `ba6b10d0c3e3811612a678dec4f85aed0c11bbda901726934be7976e4fe8e911`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](validation.md).

Date: 2026-09-09. Scope: E0, consistency of the concept, architecture, and portfolio. There is no new product code; game engines, provider experiments, model training, and rollout were not run.

<a id="структурні-перевірки-нового-портфеля"></a>
## Structural checks of the new portfolio

Both `backlog.md` and `backlog.json` pairs were checked together:

- 65 unique qualified IDs: 35 Core, 30 Lokiravia; all proposed.
- 239 dependency edges; no unknown IDs, duplicate edges, or cycles.
- Outcomes, acceptance, negative scenarios, artifacts, rationale, and exact dependencies in the text cards match the structured JSON.
- Historical reuse IDs exist in current manifests; AF/AF-AMM/AF-GC belong to Core, AF-CLD to Lokiravia.
- Standalone Core030 has exactly 29 Core prerequisites 001–029 and no Cloud/world dependency.
- World030 has 11 world and 10 Core prerequisites; it does not include full-world acceptance, human multiplayer, full Core RSI, or training.
- Source SAFE/TR/RSI IDs exist in the corresponding notes. Their semantic relevance was also reviewed independently; this does not verify the truth of every fictional explanation.
- Relative Markdown links and fenced-block pairing were checked. Ten shared files are byte-identical between the repositories.
- The combined diff from the audit baselines is limited to README and `docs/evolution/`, with only `.md`/`.json` files. Existing runtime manifests, code, and dependency pins are preserved. `git diff --check` passed.

Structure was checked by a local helper script outside the repositories; it was not presented as a new runtime capability. Card texts are the source of content; JSON was synchronized with them. The validation procedure for the next pass is to compare all fields, combine qualified dependencies from the two manifests, check the acyclic graph and stated closures, match reuse against existing manifests and sources against the dictionary, check relative links against files, and check scope through Git.

<a id="чинні-repository-validators"></a>
## Existing repository validators

| Check | Actual result | Boundary |
|---|---|---|
| Core `scripts/validate-game-creator-backlog.py` | Passed: 47 items / 43 executable, schema-v2 round-trip, labels, references, DAG, milestone order, release gates, roadmap agreement | Planning consistency of the old backlog, not task completion |
| Lokiravia `scripts/validate_engine_target_pack.py` | Passed: 18 synthetic operation results | No engine was run; no live target was qualified |
| Lokiravia `scripts/validate_evidence_gates.py` | Passed: 13 synthetic scenarios / 5 separate gates | No real build was accepted |

These checks match the documentation change. A full runtime test suite is unnecessary to conclude that the concept is documented consistently, and was not run merely to suggest broader verification.

## Q05, 2026-09-10

Rechecked Markdown/JSON parity, unchanged 65 IDs/239 edges, DAG/closures, legacy refs, relative links, docs-only scope, and whitespace. The recovery contract is identical in both repositories. Independent source review and interleaving review refined final-commit, external-effect, and control-process handoff semantics. T01–08 and RC01–16 were reviewed as static specifications, not executed against a runtime. Existing validators were repeated for this documentation revision with the same synthetic-evidence boundaries.

## Q06, 2026-09-10

Checked 10 unique paper scenario IDs, Markdown/JSON field parity, the W0/extended boundary, and valid control references. This is schema/authoring consistency, not execution of expected traces. Rechecked backlog parity, 65 IDs/239 edges, DAG/closures, legacy/source refs, links, and docs-only scope. Shared counterfactual-evaluation.md is identical in both repositories. Independent review checked temporal/causal assumptions and permissible Core claims. Existing static/synthetic repository validators were repeated; no engine or model runs took place.

## Q01, 2026-09-10

Source coverage was recalculated from sets of spine/paragraph anchors against the unchanged pass1 ledger; file hashes and the exact boundaries of three chapters were checked. Checked Markdown/JSON parity, 65 IDs/239 edges, DAG/closures, source/legacy refs, links, shared docs, and docs-only scope. Q01-E01–06 are static authoring controls, not played scenes or executed Core experiments. Relevant existing repository validators were repeated within their previous static/synthetic boundaries.

## Q02, 2026-09-10

Two complete chapters were checked against original EPUB XML/NCX and hashes. Paragraph-text/LF counts are separate; unknown pass1 overlap remains unknown, not zero. Checked source-manifest parity, Markdown/JSON, 65 IDs/239 edges, DAG/closures, refs/links, shared docs, and docs-only scope. Q02-I01–08 are authored static controls; the source audit is limited to roles/memory paths, not the complete execution stack. Existing repository validators were repeated within their static/synthetic boundaries; no model/engine/human runs took place.

## Q03, 2026-09-10

PDF hashes, pypdf metadata/version/page counts, and exact reading ranges were checked against private ledgers; extraction is separate from reading. Checked six primary-source anchors, ten unique static controls, source-manifest parity, Markdown/JSON, unchanged 65 IDs/239 edges, DAG/closures, refs/links, 15 identical shared docs, and docs-only scope. Independent reviews checked source boundaries and criterion/treatment/access/activation semantics. Existing repository validators were repeated within their static/synthetic boundaries. Q03-E01–10 were not executed against a runtime; no Core, model, engine, training, or human experiments took place.

## Q04, 2026-09-10

Checked PDF hash/version/page count, 12/12 full-text pages, and 33 550 extraction characters; two reading ledgers were reconciled, and rereading does not multiply coverage. Survey ranges/hash and version chronology were checked; no old A-Evolve textual diff is available. Checked five source anchors, eight static controls, Markdown/JSON parity, 65 IDs/239 edges, DAG/closures, refs/links, 16 identical shared docs, and docs-only scope. Existing validators were repeated within their static/synthetic boundaries. Q04-T01–08 were not executed; training, serving, and human experiments were not run.

## Q07, 2026-09-10

Checked 24 cited source files at exact repository snapshots: commit/blob/content hashes, presence of line anchors, and the actual consumer pin. Ten listed Core source files are identical at the pin and audited HEAD; this does not imply caller qualification or equality of the entire repository. Checked 11 source-matrix anchors, six paper steps, and ten unique authored controls. This is authoring/source consistency, not execution of expected outcomes.

Only Core025/026, World013/025, and the World030 evidence boundary were refined; titles/status/phase/priorities/dependencies were preserved. Markdown/JSON parity, 65 IDs/239 edges, DAG/closures, legacy/source refs, relative links, 17 identical shared docs, whitespace, and docs-only scope passed checks. Independent Core/World/product reviews examined the actual call paths and closed findings on planned/realized fidelity and restore version/audit/evidence identity.

Existing validators were repeated: Core—47 items / 43 executable; World—18 synthetic engine-operation results and 13 synthetic evidence scenarios / 5 gates. Source/browser/runtime tests for this creator path were read only, not run. Q07 performed no app/model/engine/provider/training/user experiments and did not increase literary/PDF coverage.

## Q08, 2026-09-10

Checked 14 cited Core source/test files at an exact snapshot: commit/blob/content hashes and line anchors; separately checked the SHA, date, and subject of the historical readiness commit. Six failure classes are distinguished from live-incident claims. Checked two user-work families, six public development recipes, and ten authored controls; no actual task corpus/final set was created, and their outcomes were not executed.

Five existing Core cards 003/005/007/015/030 were changed; World cards are unchanged. Markdown/JSON parity, 65 IDs/239 edges, DAG/closures, titles/status/phase/priorities/dependencies, refs/links, 18 identical shared docs, docs-only scope, and whitespace passed checks. Independent review closed cumulative final-history, semantic fault applicability, and precision of the interrupted-adoption boundary; clarifying the harness AND source gate 019 does not change dependencies.

Existing validators were repeated: Core47/43, World18 synthetic engine-operation results and 13 synthetic scenarios/5 gates. No app/model/provider/engine/training/user runs or reruns of the source/browser/runtime tests in this audit took place. Literary/PDF coverage is unchanged. The decision to pause automatic passes was recorded after completing the available Q01–Q08 queue; this is not product acceptance.

<a id="незалежне-ревю"></a>
## Independent review

Separate reviews examined architectural authority, lifecycle, and the recursive claim; standalone/MVP dependencies; and the semantic provenance of literary bindings. All concrete findings were addressed in the [correction journal](iteration-review.en.md). A second direct literary pass added counterexamples and changed acceptance criteria.

This delivery does not prove increased Core quality, long-term RSI stability, market demand, or player satisfaction. For those conclusions, the portfolio defines future protocols, external evidence, and no-go criteria.

<a id="d01--анонімізація-поточного-дерева"></a>
## D01 — anonymizing the current tree

Checks: nine source identities without titles/authors/filenames; unchanged SHA-256, bytes, Q01/Q02 coverage; source parity between both repositories; new literary paths and anchors; absence of ebook files; ignore guards with a product-PDF positive control. The strengthened search catches an old corpus name in a private path and a book title in a chapter anchor. The available-history check found no supplied book files, but historical bibliographic mentions remain. The product runtime was not started.

<a id="d02d04--підсумкова-перевірка-узгодженого-плану"></a>
## D02–D04 — final validation of the consolidated plan

- Exact bijection: 280 requirements; 44 containers counted separately; 796 canonical hard edges, with no missing targets/cycles. Titles, kind, parents, raw labels, existing refs, source items, and AC pointers/digests were checked against all six manifests.
- Source SHA-256 and 65 authoring Markdown bindings were checked against Git-blob bytes at the stated commits; the platform checkout comparison explicitly normalizes CRLF to LF. The item digest is normalized as described in JSON.
- All 24 closures/allocations were recalculated; earliest allocation, memberships, deterministic topological order, and depth are consistent. Exact gates: Core030=30; workbench 015=12; CLD020=20; LW030=22; C-PILOT=36 without AF032–035/AMM gates. W-FIRST→W-DEPTH is recorded as release policy, not a legacy dependency.
- Three new shared artifacts are identical between repositories; 21 shared files in total. Markdown/JSON for all 65 RSI/LW cards and 239 new edges remain consistent. Links and diff whitespace were checked; canonical manifests were not changed.
- Existing Core game-creator validator: 47 entries/43 executable, schema round-trip, labels, DAG, milestones, gates, and roadmap agreement passed. Lokiravia validators: 18 synthetic engine/target results and 13 synthetic scenarios/5 gates passed; no engine was run or real build accepted.
- Current-tree privacy and reference ignore guards were rechecked. The independent cleanup scan included every available text type; new public artifacts contain no book titles or private source paths. Git history was not rewritten.
- Independent reviews closed CRLF source binding, the global console gate, and early reuse scope. The I-REUSE matrix was checked against 19 consumers/45 unique legacy refs; required capabilities are not deferred until a broad platform release.

This is evidence of documentation quality and traceability. Unit/conformance fixtures are not live product acceptance. Product code, dependencies, model/engine/training/deployment were neither changed nor run during this cycle.
