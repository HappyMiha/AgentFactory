<a id="аудит-lokvetia-core-та-lokiravia-перед-проєктуванням-рекурсивного-самовдосконалення"></a>
# Audit of Lokvetia Core and Lokiravia before designing recursive self-improvement


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [repository-audit.md](repository-audit.md). Source SHA-256 (UTF-8/LF): `e82f74515fa5ca6fec97b52221271d77602885abb54bb1bd453207c8bbbcd7fe`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](repository-audit.md).

Date: September 9, 2026. This is an independent analysis of source code, contracts, and backlogs. The repositories were not changed during this audit; product, provider, engine, server, and CI tests were not rerun. `Core:path:line` references are relative to the Lokvetia-Core root, and `Lokiravia:path:line` references to the Lokiravia root. A line number identifies the checked start of the relevant passage, not an immutable position in future versions. Other research streams analyze the attached books and paper; this document does not attribute unverified conclusions to them.

Q07, 2026-09-10: the [additional creator audit](creator-evolution.en.md) traced actual brief/scope/team callers, Core delivery/recovery primitives, and the boundary before Play/feedback/restore. It is a separate updated source snapshot with exact commits and a pin comparison; the initial audit below retains its date.

Q08, 2026-09-10: the [non-game evaluation design](non-game-evaluation.en.md) uses six concrete Core failure classes from code/tests and a historical readiness gate. Synthetic fixtures, current guards, and narrow static limits are distinguished; no new live defects or executed experiments are claimed.

<a id="1-висновок-для-продуктового-рішення"></a>
## 1. Conclusion for the product decision

The foundation is already substantially more serious than an “agents talking to each other” prototype. Core contains real modules for immutable candidates, deterministic checks, independent evaluation, memory, governed skills, bounded repair, worktrees, policies, sandboxing, qualification, and recovery. These should be extended into verifiable evolution of the **Lokvetia Core product itself**. Creating parallel Evaluator, Skill Registry, scheduler, or evidence-store services in Lokiravia would be an ownership and integration error.

However, module existence does not prove continuous self-improvement of the platform or a living world. The current engineering loop repairs one candidate against an unchanged objective; it does not compare Core generations, maintain a population of harness versions, govern a hidden task set, or measure the ability to improve the improvement process itself. Lokiravia has a functioning local idea/plan editor and several hosted components, but its visible team currently consists deliberately of empty pools and does not start game creation.

A strong new concept must distinguish at least three subjects of change:

1. **The Core product:** its UX, planning, harness, routing, tools/skills, orchestration, runtime, and own code—through verified generations and separate release decisions.
2. **The Lokiravia product:** creation, validation, gameplay, explanation of consequences, version management, and feedback—as a consumer of the same Core mechanisms.
3. **The authored game world:** NPCs, memory, event causality, and permissible rule changes—as domain contracts/game packs; they do not receive authority to change the control plane.

Recursion means a successful change helps produce subsequent successful changes, and this effect is measured. Merely running an agent again or accumulating its reflections does not establish that.

<a id="2-зафіксовані-версії-та-назви"></a>
## 2. Pinned versions and names

| Subject | Checked value | Conclusion |
| --- | --- | --- |
| Core HEAD | `c22954f144702fdf7a3da16cf58176baa345f7c4` | Current source for the audit; latest change concerns immutable deployment image references, PR49 |
| Lokiravia HEAD | `3d42cf9606d1100ebe0887306300b5fa4aaaea5e` | Current source for the audit; PR22 concerns deployment images/archive recovery |
| Lokiravia's Core dependency | `480849f78957bb6b2fd7ab341300d54955aeabb8` | Actual pin at `Lokiravia:pyproject.toml:11`; this is Core PR47, not current HEAD |
| Historical capability map | Core `d097ac0b04445183c647012a0c92a9d6348135b6`, Cloud `720c79b3530cf2dddfd8b0351094a0763f757a63` | `Lokiravia:docs/upstream-capability-map.md:9`; the map's inventory baseline, not the current package dependency |
| Old consumer supplement | Core `7ec9ff33f1c4e7f2980e4b121d05f3c366acedd1` | `Lokiravia:docs/upstream-capability-map.md:226`, `docs/game-teams.md:15`, `docs/game-brief-intake.md:29`; describes a previous pin |

**AgentFactory Core → Lokvetia Core; AgentFactory Cloud → Lokiravia, by Lokvetia.** These are two products, not four. `Core`/`Cloud` remain architectural abbreviations. `agent_factory`, `agentfactory_cloud`, `AGENT_FACTORY_*`, `core:`/`cloud:`, and AF IDs preserve compatibility (`Core:README.md:11`; `Lokiravia:README.md:15`, `:53`, `:82`). AgentFactoryBus is the technical name of the transport mechanism, not an alternative task queue.

The new concept should use the current brands and explain compatibility IDs once. Documentation updates must explicitly distinguish historical sources from the current consumer pin. A historical map cannot be “refreshed” by substituting HEAD and transferring its evidence to an unverified version.

<a id="3-що-реально-є-в-core-та-як-це-використати"></a>
## 3. What actually exists in Core and how to reuse it

| Capability | Source and actual boundary | RSI decision |
| --- | --- | --- |
| Shared application boundary | `src/agent_factory/application.py`; `docs/architecture.md:45` defines `AgentFactoryService` for CLI/UI over current services | Extend the shared API for evolution sessions; do not launch the CLI from a new web handler or copy transitions |
| Candidate validation | `src/agent_factory/validators.py:16` fixes `test`, `lint`, `type_check`, `build`, `security_scan`; `:25` requires all five shell-free vectors | Preserve the software contract; add versioned research protocols, without calling a static test an assessment of usefulness or humor |
| Independent evaluation | `src/agent_factory/evaluation.py:85`: the candidate is bound to `codex_worker_results`; `:111` rejects the producer model; `:115` reconstructs the exact five pieces of evidence; `:148` rejects gaps in criteria evidence | Extend with a compatible evaluation-subject contract: harness/config/skill/workflow/product-release. Do not restrict all RSI to a Codex diff or bypass existing independence |
| Immutable candidate and PR plan | `src/agent_factory/candidate_changes.py:60`, `:157`; `docs/candidate-changes.md` | Use the candidate/separate PR gate for changes to Core's own code; add parent-generation, experiment, and benchmark identity |
| Bounded engineering loop | `src/agent_factory/engineering_loop.py:76`, `:128`, `:185`; one objective, one run, plans/diffs/results history, caps, replan/replace_worker | Reuse as an inner repair loop. Above it, an experimental cycle is needed with baseline/challenger, holdout, cost-quality comparison, and generation promotion |
| Connected coding delivery | `src/agent_factory/coding_delivery.py:1683` creates a candidate and evaluation; `:1700` records an accepted iteration after evaluation and creates a separate Founder gate | Preserve lineage and separation of candidate/release acceptance. Do not treat a successful iteration as automatic Core deployment |
| Typed memory | `src/agent_factory/memory.py:105`, `:148`, `:203`; eight stores, provenance, scope, validity, and invalidation (`docs/typed-memory.md:3`) | Build the experience graph as derived relationships between existing evidence/memory IDs, not a second memory authority |
| Governed skills | `src/agent_factory/memory.py:266` creates an immutable draft; `:299` stores tests/security/evaluation; `:342` manages lifecycle | Bind skill review to authenticated runner receipts and a fixed protocol. Distributing a new skill needs lineage, consumers, quarantine, and rollback |
| Versioned packs | `src/agent_factory/packs.py:177`, `:272`; install/disable/rollback; `docs/architecture.md:201` | Reuse for opt-in evolution capabilities, evaluator packs, and game packs; do not treat a signature as quality evidence |
| Worktrees and the write boundary | `src/agent_factory/worktrees.py`; `docs/architecture.md:205`; `src/agent_factory/sandbox.py:61`, `:255` | Separate experimental Core from the current control process. Proven effects must enter an immutable candidate version |
| Sandbox | `src/agent_factory/sandbox.py:154` Bubblewrap; `:197` macOS; `:255` Windows returns unavailable | Do not claim system-wide Windows isolation based on a process group. Native Codex writable-profile qualification and the general sandbox are different boundaries |
| ADR / frame changes | `src/agent_factory/adr.py:100`, `:190`, `:242`, `:299`; `docs/architecture.md:199` | Reuse impact analysis and versions. An agent may propose changing the objective or evaluation function; this creates a new protocol rather than rewriting result history |
| Telemetry / budgets | `src/agent_factory/execution_telemetry.py`, `observability.py`; `docs/architecture.md:229` | Add cost per independently accepted improvement, failure recovery, user outcome, and baseline comparison; do not optimize the number of changes/commits |
| Durable mission / Temporal | `src/agent_factory/autonomous_mission.py`, `orchestration/temporal/`; `docs/architecture.md:185`, `:205` | Reuse long-running job recovery. Temporal is not the world's causality mechanism or an NPC gameplay tick |

An important technical boundary: low-level `EngineeringLoopService.record_iteration` accepts `accepted_evidence: bool` and nonempty mappings (`engineering_loop.py:132–158`); it is not itself an independent verifier. In current coding delivery, that value is justified by the preceding `EvaluationService` (`coding_delivery.py:1687–1705`). A new RSI consumer must preserve or strengthen this connection rather than call the low-level method with a self-declared `True`.

Likewise, `GovernedSkillService.review` checks structure, bounds, reviewer role, and the presence of evidence (`memory.py:299–324`); this is a useful lifecycle foundation, but a dictionary's structure does not prove an external run. Autonomous skill accumulation requires immutable external evaluation receipt IDs, producer/reviewer separation, and a case-sampling protocol first.

No separate generation/evolution manifest, meta-evaluator qualification, population selection, or holdout governance was found in the modules read and the text-source search. This is a specific boundary of this audit, not a claim that every other repository detail was exhaustively checked.

<a id="4-що-реально-є-в-lokiravia"></a>
## 4. What actually exists in Lokiravia

| Component | Presence and limitations | Implication for the plan |
| --- | --- | --- |
| Local idea and Game Brief | `src/agentfactory_cloud/game_briefs.py:140`, `brief_web.py`; `docs/game-brief-intake.md:4` | Reuse original text, idea versions, and owner edits; the new world concept must not be lost through automatic compression |
| First playable scope | `src/agentfactory_cloud/scope_plans.py:109`; `docs/first-playable-planning.md:31` | Currently bounded Godot 2D planning, with every result `execution_ready: false` (`:42`). Preserve the long-term vision and the first testable version separately |
| Proposed game team | `src/agentfactory_cloud/game_team.py:1`, `:65`, `:89` | Five roles, zero budget, empty candidates; do not call this a functioning multi-agent studio |
| Identity | `src/agentfactory_cloud/identity.py:57`, `identity_store.py:8`; the latest Core pin includes shared identity PR47 | Code and integration changes exist; old documents describing an unmounted component cannot be applied unconditionally to current HEAD. This does not establish hosted-game acceptance |
| PostgreSQL product storage | `src/agentfactory_cloud/hosted_store.py:86`; `docs/hosted-storage.md:3`, `:29`, `:49` | The document contains actual component-qualification claims for PostgreSQL 17.11/psycopg 3.3.5; this audit did not repeat them. Cloud stores product records; Core remains the execution authority |
| Private objects | `src/agentfactory_cloud/protected_objects.py:27`, `:122`; `docs/protected-objects.md:3`, `:48` | A real optional S3/Postgres component with an initial 1 byte–8 MiB profile. Do not equate it with large game builds or a finished CDN/Play |
| Worker admission seam | `src/agentfactory_cloud/worker_gateway.py:58`; `docs/server-workers.md:3` | Read-only inventory + optional authenticated loopback admission do not prove remote execution. Core AF-GC-043 is the current authority boundary for admitting a worker |
| Engine/target/evidence | `contracts/v1/engine-target-pack.json`, `evidence-policy.json`; `scripts/validate_engine_target_pack.py`, `validate_evidence_gates.py` | Versioned contracts and synthetic conformance exist; they do not accept a live Godot/Unreal pipeline |
| Unreal/NPC/world design | `docs/unreal-gameplay-plan.md:3`, `:51`, `:87`, `:136` | Existing preliminary design covers game-owned actions, memory, world revision, save/load, fallback, and proposed catalogue follow-ups. New planning should refine those follow-ups rather than write the same runtime twice |

The missing product outcome is already stated correctly: idea → small real game → exact Play artifact → feedback → verified v2 → restore/source export (`Lokiravia:README.md:34`). The living-world ambition should bring new quality to this cycle: causal consequences, strange but lawful opportunities, memory of relationships and events, and humor from interacting mechanics. It must not replace verification that the game itself can be produced and preserved.

The previous Unreal plan already separates slow asynchronous NPC planning from deterministic movement/combat (`docs/unreal-gameplay-plan.md:53`). An action proposal contains actor, world revision, expiry, and request ID, and passes validation (`:51`). Generated executable skills require development-time validation rather than installation from dialogue during gameplay (`:131`). This is a natural foundation for world RSI, where state evolution and rule/code evolution have different transactions and timescales.

<a id="5-поточний-беклог-ідентичності-та-пастки"></a>
## 5. Current backlog: identities and pitfalls

| Manifest | Actually present at HEAD | Status / source of truth |
| --- | --- | --- |
| `Core:examples/development-backlog.json` | 63 items: 6 epics + 57 tasks `AF-001…AF-057` | Historical platform requirements, not new claim IDs |
| `Core:examples/autonomous-mission-backlog.json` | 75 items: 9 epics + 18 stories + 48 tasks `AF-AMM-001…048` | `status:proposed`; stories/epics are containers |
| `Core:examples/game-creator-backlog.json` | **47 items: 4 epics + 43 executable** (34 task, 9 bug), `AF-GC-001…043` | All `status:proposed`; old “42” texts omit 043 |
| `Lokiravia:examples/agentfactory-cloud-backlog.json` | 74 items: 7 epics + 67 executable (66 task, 1 research), `AF-CLD-001…067` | All `status:proposed`; the manifest owns IDs/deps/criteria, `docs/backlog.md` is the readable view |

`AF-GC-043` is already occupied by **Atomically admit qualified workers with scoped attempts and shared capacity**, dependency `AF-GC-039` (`Core:examples/game-creator-backlog.json:2371`). It cannot be reused for a new RSI item. README/old capability-map references to 42 items should be marked as a historical count, not used to mechanically redefine all old evidence.

The canonical loader (`Core:src/agent_factory/backlog.py:264`) requires these fields in a schema v2 executable item: priority, assigned_role, dependencies, validation_method, required_components, required_infrastructure, expected_artifacts, definition_of_done; title/description/acceptance_criteria are required for every item. `:316` checks unique IDs, closed references, and a DAG containing dependency/parent links.

**A cross-repository reference cannot simply be inserted into the executable dependencies of another manifest.** The loader requires all referenced items to be present in the current document. Existing policy stores phase-specific upstream evidence in the capability map and planning metadata (`Core:docs/core-cloud-backlog.md:95`). The release owner must check pin/evidence separately; the scheduler does not turn that metadata into an automatic barrier.

When extending the system, the preferred approach is to preserve every old ID and gate, create separate explicitly proposed namespaces/manifests for evolution requirements, and provide traceability to existing AF/GC/CLD items. New IDs describe design requirements; they do not create runtime execution or automatic feature acceptance. If canonical manifests are expanded instead, the readable view, validator expectations, and bridge coverage must be updated together, including the already existing 043.

<a id="gates-які-не-слід-випадково-зламати"></a>
### Gates that must not be broken accidentally

- Core GC: M0—`001,002,003,004,005,006,039,041,042`; M1—`026`; M2—`031`; M3—`034,036,037,038` (`examples/game-creator-backlog.json:22`). These are existing gates; the presence of the new 043 does not authorize silently changing their historical semantics.
- Cloud M0—`001…006`; M1—`020`; M2—`034`; M3—`044`; M4—`051`; M5—`060`; M6—`067`.
- `AF-CLD-020` requires three real Godot games, Play, Windows/source export, feedback/v2/restore, truthfulness/cancellation, and an owner playtest (`docs/roadmap.md:80`). A humor hypothesis or schema validation does not pass it.
- Unreal `AF-CLD-054` depends on `052`, and `052` depends on `034`; new desk research may happen earlier, but that does not mean implementing Unreal before those prerequisites.
- Do not add `AF-CLD-040 → 043`: `043 → 040` already exists. Private remix checks rights to its input; later 043 integrates one Cloud rights policy (`docs/upstream-capability-map.md:190`).
- 059 consoles, 062 factory commerce, and 066 non-game offering are optional; advertised features have conditional gates. A new recursive feature must likewise have its own conditional acceptance rather than silently expanding the meaning of GA (`examples/agentfactory-cloud-backlog.json:78`).

<a id="6-мінімальний-набір-справді-нових-архітектурних-контрактів"></a>
## 6. Minimum set of genuinely new architectural contracts

These are proposed capabilities, not new claim IDs or completed tasks.

| New contract / extension | Sole owner | What it must prove |
| --- | --- | --- |
| Evolution subject + generation manifest | Core | Precisely identifies what changes: code/harness/config/skill/workflow; parent version, patch, protocol, authority, evidence, and rollback target |
| Experiment protocol / holdout registry | Core | Baseline and challenger have the same rules/budget; hidden cases do not reach the optimizer; the preregistered decision rule is not rewritten after the result |
| Comparison and promotion ledger | Core, over evaluation/candidate storage | The gain is not explained by a larger budget, benchmark changes, or selecting only successful attempts; negative and inconclusive results are retained |
| Core-on-Core improvement mission | Core | A game-independent task set shows a gain in real platform-task execution; separately tests non-game use, CLI/API compatibility, recovery, migrations, and UX |
| Meta-evaluator qualification | Core | A candidate may propose a new evaluator, but the current immutable baseline procedure assesses it; neither side approves itself simultaneously |
| Experience graph | Core, over memory/evidence | Provenance, hypothesis→experiment→outcome→consumer, contradiction/invalidation propagation; a bad skill is not multiplied through a shared library |
| Safe promotion / retained generations | Core | Shadow/replay→limited exposure→promote with exact scope; rejecting a change and returning to generation N-1 restore compatible state |
| Research portfolio / frame-revision proposal | Core | The system justifies what to work on; separately records uncertainty, value of information, abandonment, and owner revision of the objective |
| Causal event/world contract | Core optional pack | Immutable event IDs, world revision, actor authority, deterministic application/replay, causality lineage, idempotency, bounded propagation |
| World evolution policy / humour vocabulary | Lokiravia Games + original game pack | Which changes are acceptable in the authored world, which facts are remembered, and which unusual choices open new possibilities; no copying book characters/text |
| World-rule candidate evaluation | Core generic protocol, domain suite in game pack | A rule change does not replace the history of accepted events; seeds/replays/invariants + human playtests assess actual consequences and clarity |
| Creator-facing evolution controls | Lokiravia | The player/creator understands the nature of changes, can retain a chosen version, and defer or reject a rule update; import/export tools are preserved |

It is especially important to implement **Core-on-Core proof before depending on a complete game**. Otherwise, Core self-improvement will become another name for game-content generation. For example, three or more successive generations on predefined platform tasks, frozen external evaluation, retention of unfavorable results, one forced failed mutation, and a recovery drill form a sufficiently concrete experiment-design direction. The generation count and thresholds still need to be fixed as a protocol hypothesis; this audit does not claim they were executed.

For the world proof, use one small district/community with a limited number of NPCs, two ways to solve a problem, an unusual use of an object, and a consequence that appears later. Also show a small action with no large consequence, a disrupted long-term plan, and an unexpected but causally explainable result. This distinguishes living causality from a director forcing “every action changes the universe.” Semantic unpredictability for the player can coexist with reproducible evidence/replay for the developer.

<a id="7-evidence-статус-і-постійна-робота"></a>
## 7. Evidence, status, and continuous work

The existing Cloud gate model suits the new ambition: **Ready ≠ Playable ≠ Exportable ≠ Publishable ≠ Sellable** (`Lokiravia:docs/evidence-gates.md:14`). Evidence levels are different types, not one numeric ladder; owner acceptance does not replace a runtime test (`:39–55`). New `Improved`, `Stable across generations`, and `World change accepted` claims need their own scopes of applicability rather than new colors for the old “Ready.”

The Core README explicitly calls the product alpha (`:19`) and explains that Ready inventory does not certify an end-to-end route (`:100`). The old September 5 audit (`docs/product-audit-2026-09-05.md:3`) recorded bugs at that time; the later capability map acknowledges repairs 001/003/006 (`Lokiravia:docs/upstream-capability-map.md:13`). A new backlog must not reopen an already fixed bug solely because of an old audit article. Reopened work requires a new reproducible defect or a clear incremental acceptance gap.

The user's updated direct instruction cancels the previous three-PC coordination approach for this work. Therefore, the `AGENTS.md` rules about a prior claim are not a prerequisite for this documentation delivery; the root agent maintains the shared `docs/living-systems-rsi` branch in both repositories. Historical runtime gates and stable product IDs remain product content, not a reason to reinstate the process canceled by the user.

Continuous work should use short, reviewable iterations: hypothesis version → sources → concrete concept/contract increment → consistency check → commit → next uncertainty. Actual scheduled continuation requires a separately saved task and an active executor; a promise to “work continuously” alone is insufficient.

<a id="8-рекомендована-структура-першої-документаційної-поставки"></a>
## 8. Recommended structure of the first documentation delivery

1. A shared vision with clearly separate Core, creator-product, and living-world outcomes; a list of falsifiable promises.
2. A source/evidence register: nine books, the specific local PDF version, repository SHAs, and reading/verification level; borrow mechanical inspiration, not someone else's literary text.
3. ADR: “two products, shared evolution infrastructure, separate authority planes.”
4. Core RSI architecture with a state model, generation protocol, evaluator/holdout contract, cost model, failure/recovery, and Core-on-Core proof.
5. Lokiravia world design with an original setting, action affordances, causal chains, humor cases, memory, and versioned rule evolution; traceability to existing Unreal/gameplay design.
6. A new detailed proposed backlog with outcome, hypothesis, source, sole owner, reuse reference, prerequisite contract, acceptance, negative cases, evidence type, budget assumption, artifact, and stop criterion. Preserve old AF/GC/CLD IDs and release semantics.
7. A validation report: canonical schema, unique new IDs, internal DAG, a separate cross-repository bridge check, absence of cycles/duplicate capabilities, consistency between tables/JSON, source paths, and truthful claims/statuses.

This delivery does not need product code, external deployment, self-modification execution, or copying EPUB/PDF files into public Git. It needs a design that can already be critically reviewed, split into experiments, and implemented without losing its ambition.
