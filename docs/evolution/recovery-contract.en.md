<a id="q05-точні-переходи-поколінь-і-відновлення-після-збоїв"></a>
# Q05: precise generation transitions and recovery after failures


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [recovery-contract.md](recovery-contract.md). Source SHA-256 (UTF-8/LF): `446c278525a1a9ca643f6317781d47316673380621cc3211fd344fb247b723c5`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](recovery-contract.md).

Design specification · 2026-09-10, Europe/Zurich · **E0 / proposed**. This pass elaborates the [Core architecture](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/core-architecture.en.md) and [world contract](platform-world-contract.en.md). The tables describe future behavior; they are not executed crash tests or a new runtime API.

<a id="питання-яке-змінило-рішення"></a>
## The question that changed the decision

After a restart, can we unambiguously determine **which action has already occurred, under which current authority, and which version may be used next**? The previous “durable promotion ID + CAS expected incumbent” is insufficient: the same generation digest may return after rollback; permission may be revoked after a check; migration may finish only partially. A state transition needs a more precise subject and commit point.

Starting versions: Core `35c87b5331cf5da10a465b3c6b27caa1d1fa87a1`, Lokiravia `09946d05063ea61bc3d5a815af1fa527b1aad157`. After fetching, origin/main remained at `c22954f144702fdf7a3da16cf58176baa345f7c4` and `3d42cf9606d1100ebe0887306300b5fa4aaaea5e`, respectively. This pass includes no new EPUB/PDF reading; source coverage from previous passes does not increase. Its basis is static examination of documentation, existing code, and counterexamples to our own design.

The independent [Q05 implementation audit](https://github.com/HappyMiha/Lokvetia-Core/blob/main/docs/evolution/implementation-recovery-audit.en.md), with exact source locators, identified six specific limits: a generic driver does not always recover the outcome; the evaluation callback executes before a durable verdict; Git commit recovery checks structure without rebinding content; accepted loop/gate/delivery linkage may be recorded separately; a pack pointer is not installation of the Core runtime; a stop digest is not observation that an external effect has stopped. Meanwhile, a mission operation journal, starting-session reservation, and fenced autonomous completion already exist and must be reused.

<a id="1-незмінні-records-і-змінний-активний-покажчик"></a>
## 1. Immutable records and a mutable active pointer

| Record | When it is fixed | Required contents |
|---|---|---|
| CandidateManifest | Before candidate execution | Exact artifact/base/parent digests, change subject, input/memory view, protocol reference, scope, compatibility |
| ExperimentProtocol | Before baseline/challenger results | Eligible cases, expected receipt roles, costs, deadline, missing-evidence rules, comparison/stop rules |
| AttemptIntent | **Before** dispatching each attempt | Experiment/candidate/protocol, logical operation key, attempt ID, writer/authority epoch, input digest, budget reservation, permitted effect profile |
| AttemptReceipt | After an observable result | Issuer, exact attempt/input/effect identity, output/error, costs, and the limits of what the issuer actually observed |
| EvidenceSeal | After closing the attempt inventory | All admitted attempts, receipt digests or explicit missing/cancelled/invalid dispositions, inclusion policy, and closing time |
| ComparisonDecision | After sealing | Candidate/baseline, protocol, seal digest, accepted/rejected/inconclusive, claim boundary; not a release grant |
| GenerationManifest | After required qualification | Candidate + comparison + qualification receipts + runtime/state compatibility + rollout/recovery plan; no reference to its own future activation receipt |
| PromotionAuthorization | Before a specific activation | Exact GenerationManifest digest, target/profile, expected ActivationBinding, authority epoch, expiry, scope, and permitted recovery operation |
| ActivationReceipt | At activation commit | Promotion ID, authorization ID, previous/next ActivationBinding, commit sequence, and reference to prepared state |

`ActivationBinding` is the tuple `target_id, activation_seq, generation_manifest_digest, authority_epoch, writer_fence, state_binding`. `activation_seq` increases monotonically and **does not move backward during rollback**. `state_binding` identifies the exact storage/schema/checkpoint profile; for a stateful world, the world/rule epoch, checkpoint digest, and committed revision. In a stateless contract fixture, state binding is explicitly `not_applicable`, not an invented save hash.

CAS compares the complete binding identity required by the profile, including the sequence, rather than only the generation digest. A@41→B@42→A@43 does not restore the authority of an old grant for A@41. Repeating an already committed promotion ID returns the same ActivationReceipt, rather than creating A@44. A different target or different bytes under the same operation key is a conflict, not a retry.

A mutable status/revocation index references immutable records. It does not rewrite historical candidates, comparisons, or receipts. A cryptographic hash establishes byte identity; it does not itself prove an issuer's competence or independence.

Adopting a recovered Git artifact requires rebinding the actual commit/tree/diff content to the snapshot checked by validators. Identical parents, commit subjects, and filenames do not establish this. Different bytes require a new candidate or invalidation; an old validator receipt is not transferred along with a filename.

<a id="2-transition-table-експерименту"></a>
## 2. Experiment transition table

Phase, runtime disposition, and evidence reason remain separate axes from the main architecture. `unknown` means uncertainty about an external effect, not hidden evidence of failure or success.

| ID | Transition | Guard and durable record | After a crash or repetition |
|---|---|---|---|
| T01 | draft→protocol_frozen | Immutable protocol and candidate identity; inputs do not yet contain results | Dispatch is prohibited if the record is not committed; repetition with different bytes requires a new ID |
| T02 | protocol_frozen→admitted | Qualified runtime profile, scope, available aggregate budget; admission receipt | The reservation has one logical operation key; repetition does not reserve twice |
| T03 | admitted→running | AttemptIntent and reservation committed before external dispatch | After a crash, check receiver status by key; no local receipt does not permit blindly repeating an effect |
| T04 | running→running/reconciling | Receipt received or timeout/lost worker; accepted response bound to the exact intent | A stale writer cannot accept a new attempt's result; timeout only starts bounded reconciliation |
| T05 | running/reconciling→evidence_sealed | Every admitted attempt has a receipt/disposition, no outstanding effect is hidden; deadline policy completed | Missing evidence is explicit. Late evidence creates an amendment/new seal; a closed seal is not silently extended |
| T06 | evidence_sealed→compared | Seal integrity, issuer/scope validity, inclusion policy, and protocol prerequisites checked | Duplicate comparator input returns the same decision; a different seal/protocol requires a different comparison ID |
| T07 | compared→accepted/rejected/inconclusive | Comparison satisfies the preregistered decision rule; accepted result, decision/gate, and linkage have a replayable transition identity | One local transaction or explicit reconciliation/adoption joins already committed records; restart creates no new vote/gate and does not require an already accepted loop to be active again |
| T08 | Any nonterminal phase→aborted | Defined reason: changed subject, revoked scope, cap, etc.; dispatch stopped | Already possible effects are reconciled separately; aborted does not mean “nothing happened and nothing costs anything” |

A protocol may predetermine that a missing task response counts as failure if that is sufficient for a valid comparison; it cannot call a missing mandatory integrity/authority receipt successful. If prerequisites for a valid comparison are absent, retain a terminal inconclusive/aborted decision without an improvement claim. There is no obligation to artificially pass through `compared` with an unsuitable set.

Late evidence that refutes an already accepted comparison creates a claim challenge and blocks **new** promotions of the dependent manifest until resolution. The current release is handled through a separate incident/revocation process. The historical fact that “this decision was accepted” is preserved, but not presented as still-substantiated benefit.

<a id="3-межа-виконання-повтору-й-бюджету"></a>
## 3. Execution, repetition, and budget boundary

Every external effect profile must specify what the receiver actually supports: lookup by operation key, deduplication with payload-digest checking, cancellation acknowledgment, and a committed-effect receipt. An idempotency key in Core without corresponding receiver behavior does not provide exactly-once execution.

The dedup contract defines the retention/expiry horizon and policy for closed operation keys. Repeating an old intent after pruning does not become a new action merely because a cache row is absent: outside the verified horizon, it is rejected or reconciled against a durable tombstone/archive. A legitimate new logical operation requires new admission and identity. This rule also applies to the evaluator callback; database uniqueness of a completed verdict does not eliminate a repeated external review before its commit.

| Effect profile | Recovery after a lost response | Permissible claim |
|---|---|---|
| Read-only / isolated computation | New attempt within the overall budget; the previous attempt and its possible cost are recorded | Repeatable computational result within the declared envelope; not a guarantee of one provider charge |
| Receiver with durable dedup + outcome lookup | Reconcile key/payload; repeat delivery with the same key only under the receiver's contract | One committed domain effect within the verified scope; transport attempts may repeat |
| Receiver without reliable outcome lookup | Retain unknown; block repetition of a non-repeatable effect until reconciliation/an explicit recovery decision | No exactly-once claim; this capability is not admitted for an unattended promotion-critical effect |

A cancellation request or expired lease does not prove that an external action did not occur. Cancellation acknowledgment must denote a defined receiver state, rather than merely an accepted HTTP request. The worker fence checks the authoritative writer **at commit time**; an old process may still compute, but cannot alter current state through this path.

A reservation with unknown cost remains occupied until receipt/reconciliation under a predetermined bounded-exposure policy. If exact cost is unavailable, the ledger retains a known minimum and conservative upper bound; it does not automatically release budget on timeout. If a cap requires an upper bound that cannot be established, the next dispatch is blocked. Retries, verification, and compensation consume budget; cancellation does not reset an already possible charge.

<a id="4-promotion-revocation-і-rollback"></a>
## 4. Promotion, revocation, and rollback

The first qualified profile may have one authoritative writer. This document does not select distributed consensus or a particular DBMS. It requires **one serialized order** for authority verification, active-binding changes, and the corresponding activation record within the declared storage boundary. If a runtime cannot provide that order, its promotion profile is unqualified.

1. Prepare exact release artifacts and compatible candidate state in an isolated area. Readiness does not grant permission to serve authoritative writes.
2. Record PromotionAuthorization with the expected binding and current authority epoch. Shadow/canary use their own target/scope grants; their stages depend on an explicit profile and are not automatically required for an offline fixture.
3. Before commit, recheck grant validity/expiry/revocation, expected binding, artifact/state digests, qualified scope, and current writer fence. This check and the ActivationReceipt record share one serialization boundary.
4. Within it, commit the ActivationReceipt, the next binding with sequence+1, and the new writer's authority. Dispatch/readiness routing consumes this binding. The process, registry, and external load balancer are not declared physically one transaction: the profile must demonstrate that no user-accessible mixed writer/state exists between them.
5. If the process fails to start after commit, do not retroactively alter the receipt. Keep admission paused/degraded and execute an already authorized recovery transition or obtain a new specific grant. The old writer does not regain authority merely because it is still alive.

If revocation is serialized **before** activation commit, activation is rejected. If it is serialized **afterward**, the previous activation remains a historical fact; revocation prohibits new admissions/activations and triggers scoped quarantine/recovery. It is impossible to honestly promise that a future revocation not yet recorded cancelled an already committed event.

Final guards account for transitively revoked skills, tools, supporting evidence, and authority records in the declared dependency graph. Cached bytes do not bypass admission; rollback to an old artifact does not renew its revoked rights. An already committed effect remains history, while previously accepted jobs receive explicit dispositions under policy rather than silently executing through a revoked component.

For revocation by an external authority without a shared fencing/serialization contract, the profile must explicitly define bounded delay or disallow automatic activation. A cached “not yet revoked” check does not prove a zero race window. The first strong promotion claim uses a local authoritative boundary with verified ordering.

The writer fence must be checked in every authoritative commit path covered by the claim. An external receiver that does not consume the fence remains subject to the effect-profile limits in §3; locally rejecting an old writer does not cancel a remote effect already sent. An unsupported irreversible effect is not admitted for an unattended transition.

**Updating Core's supervisor/promoter itself:** a separate current promotion authority performs the committed transition; the candidate control process does not possess its write credentials and does not accept its own qualification. The profile describes drain/reconciliation, checkpointed control state, fenced handoff to the successor, and recovery if the successor is not ready. The authority mechanism itself may also evolve, but transfer of root authority is a separate qualified upgrade/recovery transition authorized by the current independent boundary, not hidden self-approval through a new runtime. This is a requirement for Core-on-Core source evolution, not merely a game pack.

Rollback is a new transition to a compatible old artifact, with a new activation sequence and authorization bound to the **current** state binding. Permission may be a prebounded recovery grant, but not an arbitrary right to erase new data. A revoked artifact does not become an eligible fallback merely because it was a former incumbent. If both versions are unsuitable, the correct outcome is paused/degraded operation, not an invented successful rollback.

A canary result may qualify a different, broader-scope GenerationManifest; that manifest has a new digest and grant. A manifest does not reference its own future receipt or gain broader scope through a field appended after hashing.

<a id="5-правила-світу-й-міграція-стану"></a>
## 5. World rules and state migration

An atomic alias update does not by itself establish atomic migration. For the first single-writer profile:

- Stop admitting new domain writes at a defined revision; reconcile already accepted jobs/effects and establish a watermark. Inference may finish, but old proposals gain no right to bypass the barrier.
- Build a candidate checkpoint from that exact revision. Record its parent checkpoint, event prefix/watermark, schema/rule digests, pending accepted jobs, resources, and random-state envelope. Validate it outside live state.
- If the live revision changes after the initial copy, old migration qualification is insufficient: repeat preparation/validation from the final quiesced revision or use a separately qualified catch-up procedure. The pilot may choose a pause; it may not silently lose the latest actions.
- Switch one coherent binding, `rule + schema + checkpoint + revision + writer_fence`, only after complete receipts. An incomplete checkpoint or mismatch leaves the old binding in place. No reader receives new rules with an old, unverified state representation.

Before switching, recovery removes/isolates the incomplete **candidate** copy; it does not “restore” the live world over genuine events. After switching, recovery follows the new activation record: compatible repair/compensation or separately authorized restore. Preserving the story does not mean refusing to fix a technical error.

On load, `session_epoch` is issued by new admission authority rather than taken from an old save as the current value. Otherwise, an A→B→A save would revalidate an old callback. Accepted domain jobs have stable IDs and provenance and resume in the new binding under checkpoint policy; pending model requests are not such jobs. An old reply is rejected; a new decision does not create a second effect for an already completed job.

Earlier response validation does not yet authorize application after load. The authoritative **commit** rechecks world/request binding, session/rule epoch, actor generation, expires_at_tick, expected revision, rights, and writer fence, and records the state delta, resource delta, WorldEvent, job completion, and dedup receipt in one local transition. The trace “precheck passed → load → apply” must reject the old apply. A crash cannot leave an issued resource without the corresponding effect/job record. A storage profile that cannot provide this local commit needs an equivalent recovery contract before qualification.

At a new rule epoch, every accepted job has an explicit migration disposition: preserve, compatible remap, or cancel with a reason and defined compensation/resource return. This is not permission to replay an old model response under new rules. Candidate migration does not complete such a job in live state before the corresponding binding is accepted.

Restoring a private save may replay **an internal alternative history** under the author's rules. It does not reset the register of already completed external effects, payments, or public grants. W0 introduces no such effects; a future profile must have a durable dedup/compensation boundary outside the rewindable save.

For an explicit rewind/fork, a new `history_branch_id` distinguishes the alternative local history; ordinary crash recovery or repeated loading of the current checkpoint does not create one merely to bypass deduplication. The local effect key includes world/history/job identity, while an external effect key retains its own irreversible identity. The session epoch fences responses; it is not a way to issue an external reward again.

<a id="6-набір-спростовних-сценаріїв"></a>
## 6. A set of falsifiable scenarios

All 16 rows are **static design scenarios**, not executed fixtures. Future acceptance requires actual receipts for the exact implementation/version, rather than this table alone.

| Case | Control trace | Expected observation | Minimum evidence for future verification |
|---|---|---|---|
| RC01 | Intent committed → worker disappears before/after external dispatch | One unresolved logical operation; absence of a receipt is not presented as failure without an effect | Intent, receiver lookup/unknown, reservation disposition |
| RC02 | Effect committed → response lost → delivery repeated; variant with key beyond retention horizon | A deduplicating receiver returns the same effect; different payload rejected; expired/pruned key creates no new action | Two attempts, one effect ID, receiver receipt, and expiry/tombstone policy |
| RC03 | Receiver without dedup/lookup, timeout | A non-repeatable effect is not repeated autonomously; scope marked unsupported/unknown | Capability profile and blocked recovery decision |
| RC04 | Lease expires/cancel sent → old worker returns | Old writer cannot commit; a possible external charge remains accounted for | Fence rejection, cost reconciliation, no second grant |
| RC05 | Seal committed → late conflicting receipt; variant: recovered commit has the same files but different bytes | Seal unchanged; amendment/challenge blocks new promotion; content mismatch is not adopted as a validated candidate | Actual tree/diff binding, both digests, challenge record, and refusal receipt |
| RC06 | Comparison accepted, PromotionAuthorization absent; crash between accepted loop/gate/linkage | Active binding unchanged; replay adopts existing records without a new gate/repeated acceptance | Transition identity, recovered linkage, activation denied without a release grant |
| RC07 | Grant issued → revocation → activation | Rejection under authority order, even if an earlier cached check succeeded | Revocation sequence, denied activation, unchanged binding |
| RC08 | Activation → revocation of generation or dependent cached skill/evidence | Historical activation preserved, new admissions closed, cached bytes do not renew rights, scoped recovery | Activation and revocation order, dependency guard, dispatch gate, recovery record |
| RC09 | A@41→B@42→A@43 → old grant for A@41 | ABA repetition rejected even though the artifact digest is A again | Expected/actual sequence mismatch |
| RC10 | Two candidates have grants for A@41 | Only one transition consumes A@41; the second is not silently rebased | One activation receipt, conflict, and new qualification/new grant when needed |
| RC11 | Activation committed → acknowledgment lost → promotion ID retried | Same receipt and sequence, not a second switch | Stable promotion ID and identical committed binding |
| RC12 | Migration copy at r10 → genuine action r11 → switch attempted | Stale snapshot rejected; r11 preserved | Quiesce watermark, expected revision mismatch, refreshed candidate |
| RC13 | Crash halfway through checkpoint write / between prepare and switch | Live binding remains coherent; incomplete candidate is not active | Checkpoint digest validation and old binding |
| RC14 | New binding committed → new runtime not ready | No mixed serving/writer; paused or authorized recovery with a new sequence | Admission/health record, fence, and recovery authorization |
| RC15 | Save/load with a pending reply and accepted scheduled job; separate precheck→load→apply interleaving | New session epoch; old reply also rejected at final commit; job completion/effect/resource/dedup atomic within this history | Old/new epoch, persisted job ID, commit/fence rejection, and dedup event receipt |
| RC16 | Rollback of old code after new state writes; old artifact revoked | Incompatible/revoked fallback rejected; repair or pause preserves truthful history | State compatibility, revocation index, scoped recovery record |

A useful negative result here is identifying an unsupported effect profile or the impossibility of a strong atomicity claim at the existing boundary. Replacing a test with an attractive report does not strengthen the claim.

<a id="7-рішення-цього-проходу-та-межа-наступного"></a>
## 7. This pass's decision and the next boundary

**EV-007 — activation is a versioned capability boundary.** Accepted in the design: monotonic ActivationBinding, serialized revocation/activation, separate immutable ActivationReceipt, explicit effect profiles, and coherent state switching. The weaker alternative, “compare only the current Git SHA, then inspect the log,” is rejected because of RC07/09/12. A different implementation may change the decision only with equivalent verifiable guarantees.

This elaborates existing AF-RSI002/004/008/011/017/029/032/033/034 and AF-LW023/030, rather than creating a new microservice or second execution queue. The portfolio remains at 65 cards. Core improves its own source/optimizer through the same verifiable lifecycle; the game pack receives domain adaptation without authority to rewrite the platform control plane.

Applicability is fixed **before** verification. Standalone Core029 uses applicable RC01–14/16 on neutral Core fixtures; stateful migration is checked only for a declared stateful profile. RC15 with world/action semantics belongs to optional C7 qualification and creates no hidden game dependency. W0 has only its own local checkpoint/final-apply/job/dedup slice, including applicable RC02/13/15 variants, and does not wait for live canary or multiplayer. A not-applicable/unsupported designation includes a reason and permissible claim boundary; it is not counted as a pass.

Remaining implementation work: select a concrete supported storage/runtime profile, build an executable crash harness, run receiver conformance tests, and measure the recovery-time/data-loss envelope. Static closure of Q05 means a sufficiently precise specification for these checks, not that they have passed.
