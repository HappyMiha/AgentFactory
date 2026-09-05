# Core and Cloud backlog ownership

Status: proposed plan. This file assigns work and explains dependencies. It is not another implementation backlog and does not create competing task IDs.

Core is maintained in this repository. The canonical Cloud specification, roadmap, and `AF-CLD-*` manifest belong to [HappyMiha/AgentFactory-Cloud](https://github.com/HappyMiha/AgentFactory-Cloud). See [Core and Cloud boundaries](core-cloud-boundaries.md) for the product and architecture decisions.

## Sources and current evidence

- `AF-001` through `AF-057` remain the historical platform requirements. Their original IDs and evidence references are preserved.
- `AF-AMM-001` through `AF-AMM-048` remain the autonomous-mission requirements. They do not prove that every described mission capability is implemented.
- `AF-GC-001` through `AF-GC-042` remain stable upstream requirements from the September game-creation audit. Many address general Core gaps; some describe product acceptance of a game pack.
- The supplied Cloud planning package has 67 executable items, `AF-CLD-001` through `AF-CLD-067`, and seven epics. Its schema-v2 manifest passes the current canonical loader. Its dependencies refer only to items inside that manifest.

No existing requirement becomes complete because it is reused by another project, mentioned in a roadmap, or translated into English. The audit, a source-code observation, a passing simulation, and a working deployed product are different types of evidence.

## The delivery sequence

| Stage | Required result | Boundary |
|---|---|---|
| M0 — Agree the contracts | Two-repository ownership, a supported Core integration contract, rights/evidence states, and an age/privacy design. | Documentation and qualified baseline references; no claim of a deployed consumer service. |
| M1 — Prove private creation and remix | Three small Godot examples support idea or authorized sample → private fork/change → real build → Play → feedback → v2/restore and export. | A private demonstration. Use only owned or explicitly licensed remix samples. |
| M2 — Qualify hosted private alpha | Isolated accounts and workers, verified server capacity, private artifact delivery, credits/limits, backups and recovery. | Admit only the cohort supported by the account, privacy and age controls. |
| M3 — Open the public loop | Discover → Play → permission-checked Remix → Create → explicit Publish → Play, with rights checks and moderation. | A private preview is never treated as publication. |
| M4 — Qualify commerce | Eligible sellers, exact release/license listings, orders, entitlements, refunds, revenue and payout reconciliation. | Prices and fees remain proposals until the commercial gate is accepted. |
| M5 — Qualify selected engines and targets | A published evidence matrix for each offered engine/target, plus portable packaging. | Partner-restricted console work is optional. Unqualified targets remain unavailable. |
| M6 — Accept the supported service | Reliability, portability, recovery, support and security evidence for the advertised product scope. | Factory commerce and a non-game product are optional expansion tracks, not automatic prerequisites for a useful game service. |

Dependencies define what work can start. A release gate defines what may be offered to users. Independent design and research can proceed in parallel; a later optional capability must not silently become a prerequisite for the first Godot result.

## Ownership of the 42 upstream game-creator requirements

“Shared” means Core owns a reusable capability and Cloud owns the product-specific use and acceptance. It does not mean shared database ownership or duplicate implementation.

| Existing IDs | Primary ownership | Treatment |
|---|---|---|
| AF-GC-001–006 | Core | Reproducible checks, truthful readiness, safe confirmation, preserved drafts and intent, effective model identity. Cloud adds consumer regression coverage. |
| AF-GC-007–008 | Cloud with Core intake | The creator home, short questions and first-playable plan consume neutral project/intake/revision contracts. |
| AF-GC-009–011 | Shared | Core connection, credential and hardware capabilities; Cloud's supported connection/setup flow and explanations. |
| AF-GC-012 | Shared | Core reports model and hardware capability; the game pack recommends engines; Cloud presents the tradeoffs. |
| AF-GC-013–015 | Core | Tool catalog, approved/resumable setup and orchestration preflight. Cloud supplies product profiles and qualifies managed deployment separately. |
| AF-GC-016–017 | Core game pack | Godot templates, engine operations and deterministic validation. Cloud accepts the resulting user journey and artifact delivery. |
| AF-GC-018 | Core with Cloud budgets | Bounded cloud-session authorization. Customer credit pricing and payment state remain Cloud concerns. |
| AF-GC-019–020 | Shared | Core real delivery, accepted snapshots and artifact promotion; game packs supply build rules; Cloud presents working versions. |
| AF-GC-021–022 | Cloud with Core version APIs | Play the exact build and turn feedback into an approved revision. |
| AF-GC-023–024 | Shared | Core control/progress and reusable accessibility behavior; Cloud's terminology, language and complete creator flow. |
| AF-GC-025–026 | Cloud acceptance | Young-user/adult participation policy and the full Godot journey. Generic prerequisites retain their own Core tests. |
| AF-GC-027–030 | Core with Cloud choices | Local model setup, writable local runtime, resource limits and explicit routing. Cloud qualifies any offered local/hybrid product route. |
| AF-GC-031 | Cloud acceptance | Local-only/hybrid game qualification against the supported Core and pack versions. |
| AF-GC-032–033 | Core game/target pack | Unity setup recipe and engine/build/test adapter, with a supported interactive licensing handoff. |
| AF-GC-034 | Cloud acceptance | Complete Unity creator journey. It must not block the initial Godot route. |
| AF-GC-035 | Shared | Generic artifact provenance in Core; game-asset rules in the pack; release, remix and marketplace rights decisions in Cloud. |
| AF-GC-036–037 | Cloud acceptance with packs | Larger game examples, portable export and explicit sharing. Public release controls remain Cloud-owned. |
| AF-GC-038 | Shared | Core update/recovery/diagnostic support and Cloud service support, with separate deployment evidence. |
| AF-GC-039 | Core | Consistent application authentication and authorization. Cloud must add and prove tenant/role boundaries. |
| AF-GC-040 | Cloud | Observed usability with the intended young-user cohort after the participation and privacy conditions are satisfied. |
| AF-GC-041–042 | Core | Effective role separation, independent review and provider qualification for planning/bootstrap roles. |

These assignments preserve the historical IDs. A later implementation plan may split a mixed task into small changes, but it must keep a trace to the original requirement and avoid counting the same outcome twice.

## Reuse of the earlier platform and mission work

| Existing requirements | Core capability to reuse or complete | Cloud use |
|---|---|---|
| AF-001–008 | Durable identities, evidence, policy, workflow, scheduling and bounded repair. | Controlled customer jobs with observable results. |
| AF-009–016 | Intake, roles, composition, plans, context and memory. | Game Brief and creator-selected scope. |
| AF-017–021 | Sandbox, tools, credentials, evaluation and untrusted-input controls. | Qualified managed workers; no direct tenant access to privileged host tools. |
| AF-022–025 | Change governance, optional coordination, pack lifecycle and software reference pack. | Versioned game/factory capabilities; broader marketplace trust still requires qualification. |
| AF-026–031 | API, telemetry, recovery, storage and deployment contracts. | A managed profile with proven account/tenant boundaries, service limits and restores. Historical contracts are not deployment evidence. |
| AF-032–035 | Qualification and operational evidence formats. | Service-specific acceptance using actual workloads and failures. |
| AF-036–043 | Existing operator application/API/UI foundation. | Separate Creator Portal; reuse behavior through supported contracts. |
| AF-044–057 | Worker lifecycle, worktrees, candidates, validators, reviews, coding loop and recovery. | Real game generation and repair through a qualified worker/pack combination. |
| AF-AMM-001–022 | Mission state, revisions, authority, recovery and epoch/checkpoint work. | Resumable customer projects and safe versions. |
| AF-AMM-023–029 | Local model, execution and resource-control requirements. | Optional local/hybrid offerings, qualified separately from managed inference. |
| AF-AMM-030–034 | Discovery, environment planning, bootstrap and service recovery. | Managed profiles and any supported local setup route. |
| AF-AMM-035–040 | Ready work selection, delivery, repair, evidence and completion. | Verified game milestones rather than successful agent messages alone. |
| AF-AMM-041–045 | Shared application/transport/operator projections. | Thin product integration with its own account and creator interaction model. |
| AF-AMM-046–048 | Compatibility, failure and longer-run qualification. | Evidence appropriate to each offered service profile. |

Generic research or artifact tasks must not require a game engine or a Git code mutation. Core's generic task model remains neutral; the chosen pack defines the actual work and validators.

## Cloud backlog groups and their Core dependencies

| Cloud items | Product outcome | Upstream contract |
|---|---|---|
| AF-CLD-001–006 | Product boundaries, domain/API model, evidence and integration map. | Documented Core capability and artifact/approval contracts. |
| AF-CLD-007–014 | Brief, scope, team, Godot pack, real worker and validators. | Intake, role/model identity, safe worker, game-pack and source-version qualification. |
| AF-CLD-015–020 | Private Play, export, feedback, licensed sample remix, v2 and acceptance. | Exact build identity, safe preview, neutral fork/checkpoint and bounded control. |
| AF-CLD-021–034 | Hosted private alpha. | Scoped API, worker lifecycle, provider credentials, usage and recovery. Cloud owns server qualification and customer state. |
| AF-CLD-035–044 | Releases, discovery, community remix, provenance and moderation. | Immutable artifacts and authorized operations; Cloud owns the permission/license and publication decisions. |
| AF-CLD-045–051 | Marketplace transactions and seller/payout flow. | Evidence and scoped connectors. Financial ownership and ledgers remain in Cloud. |
| AF-CLD-052–060 | Engine SDK and selected target qualification. | Core pack/engine/target compatibility. No inference that every planned target is supported. |
| AF-CLD-061–065 | Portable factory manifests, optional factory commerce, advanced routing, API and hybrid deployment. | Versioned pack/runtime interfaces and the appropriate local/remote profile. |
| AF-CLD-066–067 | Optional non-game expansion and scoped service qualification. | Domain-neutral contracts plus evidence for each advertised capability. |

## Cross-repository dependencies without circular acceptance

The canonical backlog loader validates one manifest at a time. All `dependencies` and `parent_id` references must exist in that manifest. It does not resolve GitHub repositories. Runtime readiness ignores dependencies on non-executable containers.

Therefore, Cloud `dependencies` remain executable `AF-CLD-*` IDs. Core/`AF-GC-*` references are an integration map with evidence requirements, not foreign dependency strings. Root-level planning metadata can preserve those references, but the current runtime does not enforce that metadata as a scheduling gate.

`AF-CLD-003` owns the integration map. For each needed capability, it must record:

1. The owning repository and stable requirement IDs.
2. The pinned Core release/commit, pack version, and interface version used by the consumer.
3. Whether the capability is reused, extended, newly implemented, or still unavailable.
4. The upstream evidence and the separate Cloud integration test required for this phase.
5. The handling of an incompatible upgrade or missing evidence.

The bridge is phase-specific. `AF-GC-026` concerns full Godot acceptance, `AF-GC-031` local/hybrid, `AF-GC-034` Unity, and `AF-GC-037` export/share. Godot work must not wait for the local-only or Unity gate. Nor should the bridge wait for a complete legacy product journey when the specific lower-level capabilities needed by a Cloud task can be independently qualified.

An upstream implementation task is accepted against its own Core contract and evidence. Cloud then accepts the integration against a pinned upstream version. Core must not require Cloud product acceptance as evidence that its own generic API or worker is complete. A link from Core documentation to the Cloud plan is navigation, not an executable dependency.

Full consumer journeys such as `AF-GC-026` remain historical/product acceptance references. They must not be copied into both repositories as independently billable implementation work or used as a circular prerequisite for the Cloud gate that demonstrates the same journey.

## Corrections applied to the English plan

The English Cloud plan preserves the source package's IDs and includes these corrections. These are changes to requirements, not completed software:

- `AF-CLD-001` describes two repositories. Game packs and the marketplace are layers inside them.
- `AF-CLD-004` includes the young-user/adult-participation and privacy design. `AF-CLD-021` must qualify the account controls before any pilot admits minors; seller task `045` does not replace this.
- `AF-CLD-018` includes a private remix of an owned or explicitly licensed sample, using the existing snapshot and revision dependencies. `040` remains the complete community remix/rights/lineage task.
- `AF-CLD-024` starts with the reported server's read-only inventory and gaps, then separately qualifies workers. No deployment is inferred from availability.
- `AF-CLD-044` includes analytics task `041` as a required M3 capability.
- `AF-CLD-060` includes generic PC packaging `058`. Console task `059` is an optional partner-capability report; an unavailable SDK or absent partner access is not a successful console build.
- `AF-CLD-061` no longer requires all multi-engine/store work in `060` merely to define a portable factory manifest.
- `AF-CLD-067` accepts the declared service scope. Factory-commerce task `062`, non-game task `066`, and unoffered engine/store targets are outside the mandatory dependency chain; enabled features have explicit conditional gates.

For reference, the source package's original gate closure covered every same-phase task except `AF-CLD-041` in M3 and `AF-CLD-058`/`AF-CLD-059` in M5. The revised plan includes `041` and `058` and explicitly classifies `059`, `062`, and `066` as optional tracks.

## Dependency changes recorded in Cloud

These changes are present in the English Cloud manifest, which remains authoritative. This table records why they were made without creating another backlog.

| Item | Recorded change | Reason |
|---|---|---|
| AF-CLD-018 | Retained `013`, `014`, `017`; added the licensed private-remix criteria. | The `013 → 012` path already supplies immutable source/version behavior. No community-profile dependency is needed for a private sample. |
| AF-CLD-044 | Added `AF-CLD-041`. | Closes the M3 gate omission. |
| AF-CLD-060 | Added `AF-CLD-058`; kept `059` outside the mandatory target gate and marked it optional. | Includes advertised PC packaging without promising console availability. |
| AF-CLD-061 | Removed `AF-CLD-060`; retained `009`, `052`. | A portable factory manifest can be qualified with the supported Godot pack. |
| AF-CLD-067 | Uses `034`, `044`, `061`, `063`, `064`, `065` as the baseline dependencies. | Removes mandatory multi-engine expansion, factory commerce and non-game development from scoped service acceptance. |

For `067`, enabled features add explicit conditions: a paid marketplace requires `051`; an advertised expanded engine/target requires the relevant `060` qualification; factory commerce requires `051` and `062`; an offered non-game vertical requires `066`. The Cloud manifest records these conditional gates, along with gates for minors, public remix, and console support. A release reviewer must enforce the accepted scope and checklist; the current scheduler does not enforce this planning metadata.

Do not add `040 → 043`: the source package already has `043 → 040`, so that change would create a cycle. The remix task itself must check its input rights; the later provenance gate integrates those checks across publication and sales.

## Validation for this planning change

This change contains descriptions, roadmap and backlog analysis only. It does not implement code, deploy services, move source, configure billing, or activate external providers.

Before publishing the plan:

1. Load each JSON manifest with the existing canonical schema-v2 loader. Check required execution fields, unique IDs, internal references, and the relationship DAG.
2. Compare the English task table with the canonical Cloud manifest. Preserve all source IDs and trace changes to the source package.
3. Check release-gate coverage, optional tracks, and transitive dependencies. A mandatory earlier phase must not depend on a later phase's unfinished capability.
4. Check every `AF-GC-*`, `AF-*` and `AF-AMM-*` reference against its upstream manifest, and every local source link against its repository.
5. Confirm that the two repositories assign one owner per capability, keep the Core dependency direction one-way, and distinguish baseline qualification from consumer acceptance.
6. Search for claims of completed deployment, real users, revenue, provider access, console eligibility, legal rights or current prices. Keep only supported facts; label the rest as proposed or unknown.

The existing game-backlog validator is specific to the `AF-GC-*` manifest and its milestone range. It should not be presented as a validator for all Cloud phases without a separate, authorized change. Read-only canonical loading and the documented consistency review are sufficient for this descriptions-only delivery.
