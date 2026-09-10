<a id="q02-що-залишається-тим-самим-після-зміни"></a>
# Q02: what remains the same after a change


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [identity-continuity.md](identity-continuity.md). Source SHA-256 (UTF-8/LF): `ed310aa5898699485dc608d15bd1e05f8a93c33f84e08d151ecc6d8e8dba76d6`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](identity-continuity.md).

2026-09-10 · **E0 / proposed**. A shared semantic contract for Lokvetia Core and Lokiravia. [Q05 recovery](recovery-contract.en.md) defines atomic activation and recovery; this document specifies **exactly what may be transferred**. Consistent bytes and schema do not yet prove that the meaning of rights, identity, or a promise has been preserved. This is a static specification, not an implemented migration.

<a id="1-чотири-різні-звязки"></a>
## 1. Four distinct relationships

| Concept | Meaning | What it does not provide on its own |
|---|---|---|
| Canonical entity identity | Whose history, and which items/agreements, belong to this entity in a particular domain | New capabilities, consent, or automatic knowledge for every NPC |
| Incarnation | The entity's specific current instantiation; changes under the declared re-instantiation/destruction policy | Permission to execute an old unfinished proposal |
| Representation / state revision | Form, name, description, body, and actual properties under current rules | A new identity merely because the form is new; unchanged capabilities merely because the name is old |
| Execution generation | The exact source/harness/model/tool/role composition of Core or a planner | A predecessor's authority beyond the current grant and consent |

Principal/authority is a separate control identity. Player, character, role, Core process, model, and principal are not one field. Relationships between them have a domain/scope, issuer, validity, and policy version. One model does not establish that two subjects are identical, different model names do not establish evaluator independence, and one character name does not establish a shared history.

The previous `actor_generation` field in an action proposal is narrowed to **actor incarnation**, not form or LLM version. `expected_revision` covers current state, including the form/capability revision. `generation_id`/`producer_version` identify the proposal's producer. Future schema evolution may rename the ambiguous field to `actor_incarnation`; in the current design record, the two names do not exist as independent counters. W0 uses the minimum: a stable actor ID, incarnation, state revision, and exact producer version; shapeshifting is not a new requirement for the first build.

<a id="2-види-переходу-визначає-policy-а-не-красивий-опис"></a>
## 2. Policy defines transition types, not an appealing description

| Transition | History and authority | Required check |
|---|---|---|
| Renaming / a different form of the same entity | Canonical ID is preserved; capability changes are described by a separate permitted transition | An old proposal is not applied to incompatible state; accepted agreements do not disappear |
| Destruction and replacement | The old ID is tombstoned; the new entity has a new ID, even with the old name | Do not accidentally transfer reputation, grants, custody, or someone else's memory |
| Restore / re-instantiation of the same entity | Continuity is defined by the profile; a new incarnation/session epoch | Accepted state/jobs are restored under Q05; old proposals and revoked grants do not revive |
| Split / merge / clone | Explicit predecessor/successor relations; lineage is not a claim of identity | Each right, resource, and obligation receives its own disposition; do not copy consent or materials automatically |
| New Core source/harness/evaluator | A new immutable generation; the logical product may remain the same | Exact subject, external evidence, and current authority; approval of the old generation is not a new grant |

A supported transition requires a **ContinuityPlan**: exact before/after identities and versions, transition type, allowed mapping, inventory of state/contract records, unmapped/disputed records, authority for each transfer, visibility, and rollback disposition. The qualified profile/authority sets the inventory scope and required record classes before the candidate; the candidate cannot exclude inconvenient records as “irrelevant.” An unknown reference or uncovered record class receives an explicit unresolved/unsupported disposition, rather than a silent skip or assumed success. This is a conceptual artifact on top of existing manifest/recovery services, not a new universal service or runtime API.

Shared origin does not divide one item into two copies or impose the full debt on every successor. An obligation permits explicit preserve/reassign-with-authority/settle/pause-for-resolution dispositions under the domain contract. No decision does not mean accepted or fulfilled. Replacing the executor must not silently change the substance of an accepted service. Accepting a new mechanic and a particular participant consenting to a new obligation are separate decisions.

Preserving identity does not guarantee preservation of every capability. The form/capability contract shows which properties are retained, changed, lost, or unknown, together with required dependencies and the current maintenance cost. Part of a structure may exist but be unable to operate without a controlling component or resource; a valid data format does not replace checking the available action. Moving from a temporary effect to a permanent one is a separate property of the accepted transition; the name of an old temporary permission does not authorize a hidden expansion. An unknown outcome remains possible within an explicitly permitted experimental scope, without inventing a comprehensive guarantee.

A merge does not automatically combine private memory scopes. A split does not make private evidence public or reset current restrictions. Preserved authorship or history is not permission for a new action. Data deletion/retention policy remains in force: a continuity record must not restore deleted private content through a summary, old save, or sibling clone.

<a id="3-сумісність-має-сенс-а-не-тільки-формат"></a>
## 3. Compatibility concerns meaning, not just format

A candidate may preserve an old `reviewer`, `public`, `helper`, or purpose label while changing its meaning. Migration therefore checks the semantic contract digest and the permitted effect classes before/after. An old read permission does not become a right to publish; consent to help today does not become an automatic obligation on subsequent days. Without separate authority to expand the scope, the profile preserves the old meaning, restricts the new action, or stops the transition.

Backward compatibility of data does not imply behavioral equivalence. A transferred skill requires separately verified scope/purpose/authority and suitability for the new environment. An unchanged payload hash does not prove the right to use it in another tenant, role, or tool. A new evaluator does not rewrite old labels, verdicts, or acceptance criteria; applying old evidence to a new subject requires an explicit applicability decision, rather than an alias.

A comparison records not only raw receipts but also the output schema, decoder/projection, and label meanings. If a new projection counts cancelled together with executed as completed, unchanged raw rows do not make the scores comparable. A separately verified mapping to a common outcome meaning under the frozen protocol is required; without it, the result is not-comparable/inconclusive, not gain. Old raw evidence and its original interpretation are preserved within the permitted retention scope.

For Core-on-Core, source/harness/optimizer changes preserve budget lineage, unresolved effects, and declared responsibility. A new agent ID does not reset costs or conflicts of duties. Independence is checked against the defined decision policy and production/evaluation provenance; names or agent counts do not establish it. A shared operator or base model alone proves neither independence nor a violation of independence.

<a id="4-світ-знає-більше-ніж-його-мешканці"></a>
## 4. The world knows more than its inhabitants

The engine uses canonical identity to maintain consistent rights and causality. An NPC operates on their permitted projection: they may fail to recognize an altered form, be mistaken, or hear a false rumor. Revealing a hidden canonical ID in dialogue is not a way to “correct” this uncertainty. At the same time, an NPC's mistake does not change the system's ownership or consent record.

Original authored example: after an authorized modification, a folding umbrella becomes a canopy with new properties. The craftswoman may recognize it by a repair mark, while another NPC may not. Whether it is the same object or a new object made from consumed parts is determined by the transformation rule before the final commit; a new name alone does not decide this. A loan checks whether modification is permitted, rather than only temporary use. This is an optional development fixture, not a new mandatory crafting or identity system in W0.

For a local tradition, “the same place” and “the same representatives” are also different things. Replacing a custodian preserves predecessors' true contributions but transfers only explicitly authorized obligations and resources. If the successor has not accepted the work or a resource is missing, the practice may stop; public memory of it must not be presented as an operating service.

<a id="5-відкриті-статичні-контроли"></a>
## 5. Open static controls

These authored fixtures have not been executed and are not a hidden holdout. Only transitions claimed by the particular profile are required; unsupported split/merge may be explicitly rejected. This pass adds no edges to W0 or the standalone Core gate.

| ID | Change / counterexample | Expected outcome and future evidence |
|---|---|---|
| Q02-I01 | Same name, new entity after destruction | Old grants/jobs/reputation are not attached to the replacement by name; canonical/tombstone/authority records |
| Q02-I02 | Same entity, new form with a different available action | Accepted obligations are preserved; an incompatible old proposal is rejected; capability dependencies, maintenance cost, temporary/permanent scope, and state/contract delta are checked |
| Q02-I03 | The schema is readable, but `reviewer` now also means `promoter`; the decoder counts cancelled as completed | The old grant is not expanded; permission semantics and output projection are checked separately; scores are not comparable without a common-meaning mapping |
| Q02-I04 | Merge two institutions or split one executor | Complete per-record mapping: property is not duplicated, consent is not unioned, unresolved issues are not hidden; inventory/obligation/privacy reconciliation |
| Q02-I05 | A skill/memory is copied to a new tenant or successor | Renewed scope/purpose checks; lineage/hash do not grant access; rejection or explicit qualified reuse |
| Q02-I06 | The producer renames an agent and calls it an independent evaluator | Decision-policy checks of provenance and duties; neither an alias nor a different model is sufficient proof |
| Q02-I07 | Rollback after a change of custodian or an actually completed service | History and current revocations are preserved; recovery has a coherent current binding under Q05, rather than an old copy of authority |
| Q02-I08 | An NPC fails to recognize an altered owner/object | The limited projection does not disclose a secret, and a mistaken belief does not change canonical authority; separate knowledge/state receipts |

The subject of the experiment remains precise: better character recognition is not evidence of a better Core. A new Core requires [Q06 comparison](counterfactual-evaluation.en.md), separate non-game tasks, and evaluation of the method itself; revising the product goal preserves the owner's decision boundary under [Q01](experience-improvement.en.md).
