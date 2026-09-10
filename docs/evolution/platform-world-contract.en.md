<a id="контракт-платформи-creator-продукту-та-живого-світу"></a>
# Contract between the platform, creator product and living world


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [platform-world-contract.md](platform-world-contract.md). Source SHA-256 (UTF-8/LF): `fa261eff891a61b44a93d5bf4f4b80877a72e82c1fbcd47b97a3b25fe7741e1a`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](platform-world-contract.md).

Shared design revision 2 · 2026-09-10. This document is mirrored in both repositories; consistency is verified by identical content. It is a design contract, not an implemented runtime API.

<a id="1-хто-відповідає-за-яку-істину"></a>
## 1. Who owns which truth

| Boundary | Owner | Canonical record | Outside its authority |
| --- | --- | --- | --- |
| Platform execution / evolution | Lokvetia Core | Identity, scope, run/attempt, budgets, candidates, receipts, Core generations | Deciding the fictional world's canon on the author's behalf |
| Creator product | Lokiravia | Brief, project, author decisions, Play artifact, feedback, product version | Declaring Core's external verification successful by itself |
| World runtime / game pack | Author's pack, engine runtime | Domain state, events, resources, actor permissions, world/rule epoch | Changing Core credentials, evaluators or spend limits through dialogue |
| Player knowledge | Authorised game projection | What a character observed, heard or believes | Replacing canonical facts or reading another NPC's hidden memory |

Game causality belongs to the game pack; Core may provide optional reusable event/replay contracts. Core's neutral scheduler acquires no knowledge of town councils, magic, debts or factions. Lokiravia does not create its own evolution engine: it calls Core through an accepted contract version.

<a id="2-три-види-змін"></a>
## 2. Three kinds of change

**State transition:** a permitted action under current rules. It may change the world forever in narrative terms, but it is not a code update. For example, forming a new civic association creates an entity of the existing institution type.

**Rule / ontology transition:** a new formula, affordance, resource type or institution type. It requires a candidate pack, domain suite, human evaluation and migration contract. If the schema lacks a type needed for an event, the runtime retains a proposal/observation instead of executing an invented rule.

**Platform transition:** a new generation of Core or the creator product. It has its own Core benchmark, compatibility tests, rollout and consumer pin. An improved game score does not authorise a hidden platform update.

<a id="3-запропонована-форма-action-proposal"></a>
## 3. Proposed action proposal structure

This is a list of design-schema fields, not executable code.

| Fields | Purpose |
| --- | --- |
| `proposal_id`, `request_id`, `causation_id`, `correlation_id` | Idempotency, response to a specific observation, causal branch |
| `world_id`, `session_epoch`, `rule_epoch`, `expected_revision` | Checks for world identity, save loading, rule version and concurrent change |
| `actor_id`, `actor_generation`, `authority_scope` | Canonical actor, current incarnation and permitted scope; actor_generation does not mean physical form or planner version |
| `action_type`, `typed_arguments`, `preconditions` | An action from a known bounded vocabulary, with typed parameters |
| `observed_facts`, `belief_refs`, `intent` | Why the actor proposes it; beliefs are not promoted to facts |
| `expires_at_tick`, `resource_limit`, `consequence_scope` | Validity period, costs, permitted scale of effects |
| `producer_version`, `generation_id` | Model/method provenance, not a right to self-approve |

The [Q02 identity contract](identity-continuity.en.md) separates entity, incarnation, representation/state revision and execution generation. Here, `actor_generation` means incarnation; a future rename to `actor_incarnation` would be a schema change, not a second independent counter. `expected_revision` covers form/capabilities; `generation_id` identifies the exact producer. A transition has a scope inventory and semantic compatibility, not merely valid bytes.

The engine validator checks identity, version, preconditions, domain permissions, resources and permitted scale. An accepted action creates a `WorldEvent` with an `event_id`, parents, tick, before/after revision, rule digest, typed delta, recorded random draws, validation receipt and visibility policy. A rejected action creates a rejection receipt; it does not change state or spend a game resource a second time.

<a id="4-replay-причинність-та-несподіваність"></a>
## 4. Replay, causality and surprise

Replay reproduces **accepted events, random choices and external inputs**; it does not ask an LLM to invent the same response again. For nondeterministic engine elements, the reproducibility boundary is specified precisely: a state hash or permitted tolerance for the particular profile. A new generation run receives a different run ID.

A counterfactual branch starts from a known checkpoint, removes/changes one action and retains the other controlled inputs. It shows causality **within our model**; it does not prove that a real player would behave identically under other uncontrolled events. Mixed causes and uncertainty are reported; a causal graph is not a graph of every correlation.

Large cascades must not be guaranteed. Domain preconditions, resources, topology, time and competing intentions determine whether a change propagates. An event horizon, fan-out cap, influence budget and offscreen aggregation bound computation; an unaccounted-for distant change is marked unknown rather than given an invented precise outcome. Budgets are allocated by domain conditions, not player spending or a hidden need to increase engagement.

The [Q06 protocol](counterfactual-evaluation.en.md) separates replay, action intervention, input sensitivity and planner/evaluator comparison. Dependent NPC choices are recomputed after an intervention; an identical seed does not substitute for declared random coupling. An encounter that also occurs without the player's action is not presented as its necessary consequence.

<a id="5-save-паралельні-дії-та-довгі-світи"></a>
## 5. Saves, concurrent actions and long-lived worlds

Loading a save changes `session_epoch`, invalidates outstanding proposals and restores the world/rule generation. Replies tied to an old save, actor generation or expired tick are rejected. Duplicate events do not grant rewards again. Concurrent attempts to spend the last resource are serialised by the authoritative runtime; one writer per world partition is sufficient for the pilot. Final commit rechecks epochs/fence/revision and atomically records delta/event/resource/job completion/dedup; a precheck before load does not permit stale apply after load.

In the first pilot, the world advances during an active session, with bounded, explained catch-up. An always-on economy and NPC activity while the player is absent are separate hypotheses, not hidden server requirements. Leaving is not punished, and players need not log in to protect their basic right to play.

A later distributed world needs contracts for partition ownership, cross-partition ordering, causal watermarks, conflict resolution and degradation mode. This revision neither selects global consensus for every tick nor promises unlimited MMO compatibility.

<a id="6-зміна-правил-і-операційне-повернення"></a>
## 6. Rule changes and operational recovery

A migration package contains old/new rule digests, state transformation rules, preserved invariants, a replay suite, a preview of affected entities, schema compatibility and a recovery plan. Preparation and validation operate on a checkpoint copy; the active epoch switch must coherently bind rule/schema/checkpoint/revision/writer with a monotonic activation sequence. An atomic alias change alone does not prove state compatibility; a candidate copy based on a stale revision must not erase subsequent legitimate actions. Clients see the version and reason for the change before entering the updated world.

A **historical consequence** is not reversed because it inconveniences the plot. A **technical defect** may require operational rollback. In a private world, the author may restore a checkpoint. In a shared world, blindly restoring an old snapshot would erase other people's subsequent legitimate actions: compatibility repair, compensating events, compensation for losses and a transparent incident record are preferred. Full restoration requires a separate, agreed shared-world policy.

Example: a broken pricing rule created duplicate rewards. Reverting the rule version stops future duplicates; it does not destroy every legitimate purchase since the first duplication. Remediation traces the origin of illegitimate gains, preserves valid events and informs affected participants. The exact algorithm is a future requirement, not evidence of readiness.

<a id="7-сходи-прийняття-й-bridge"></a>
## 7. Acceptance ladder and bridge

Audit state: Lokiravia pins Core at `480849f78957bb6b2fd7ab341300d54955aeabb8`; the Core audit HEAD is `c22954f144702fdf7a3da16cf58176baa345f7c4`. These are different versions. New contracts will require a newly verified pair.

`IntegrationReceipt` has a `subject_kind` and an `evidence_profile`. Shared fields identify the exact subject digest, Core commit/generation, contract versions, suite/runner receipts and supported envelope. The `core_contract_conformance` profile references exact fixtures; `domain_runtime_integration` adds the consumer commit, domain pack and runtime/engine versions; `packaged_game_integration` additionally requires a player-package hash and target version. A package hash must not be invented for a non-game contract fixture. The absence of a package does not invalidate demonstrated contract conformance, but it does not permit a Playable claim. If an upstream receipt required by the selected profile is missing, the outcome is design-ready/integration-blocked, not qualified. A JSON schema pass provides structural conformance evidence only.

We distinguish structural, runtime, human-quality and owner-decision evidence. `Ready`, `Playable`, `Exportable`, `Publishable` and `Sellable` retain their current meaning. Additional claims, `CoreImproved`, `MethodImproved` and `WorldEvolutionAccepted`, do not automatically open existing gates.

<a id="8-перевірки-меж-до-першого-живого-rollout"></a>
## 8. Boundary checks before the first live rollout

Addition following the critical literary pass: a narrative opportunity, proposed commitment, accepted commitment and fulfilment are separate states. A polite remark or inspecting an item does not accept a costly contract. Known costs, deadlines and classes of possible loss are disclosed before acceptance. A reward references a rule digest and a fulfilled precondition; novelty, completion and a resource grant do not substitute for one another. Expressing doubt does not authorise an optimiser to change rewards or access secretly. These are our design constraints, not claims about the fictional System's consistency.

- Different worlds/tenants, another NPC's memory, a prompt claiming invented permissions and replay of an old request must not grant access or produce an effect.
- Save/load, actor destruction, reconnect and retry must not apply expired intentions.
- Unavailable inference falls back to bounded deterministic behaviour; the frame loop remains operational.
- Corrupt/missing receipts are not accepted on the strength of an attractive narrative report.
- A revoked Core skill does not propagate into new game-pack generations; an already released pack has a known dependency and remediation path.
- Rule migration and rollback are tested against saves with legitimate concurrent actions; a rule does not change past causes of events.
- Private dialogue, access evidence and personal texts do not enter shared optimiser context without appropriate consent and purpose.

The [Q05 recovery contract](recovery-contract.en.md) defines final-commit checks, serialised revocation, ABA protection, effect profiles and RC01–16. It elaborates existing cards; it is not a new runtime capability.

Specific delivery IDs and dependencies are listed in both product backlogs. The research can be read as one programme; it does not execute code or background game processes.
