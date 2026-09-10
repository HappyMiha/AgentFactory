<a id="q05--фактичні-межі-recoveryevidence-у-lokvetia-core"></a>
# Q05 — actual recovery/evidence boundaries in Lokvetia Core


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [implementation-recovery-audit.md](implementation-recovery-audit.md). Source SHA-256 (UTF-8/LF): `245a4f5f102cc34d22cc7ac370f0933b1169a54916f34bb268ddbfa4e76a2f6a`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](implementation-recovery-audit.md).

Date: 2026-09-10, Europe/Zurich. Checked Core HEAD: `35c87b5331cf5da10a465b3c6b27caa1d1fa87a1` (checked again at the end of the reading). This is an independent **static, read-only review** of source code and the current design draft. No provider, product, crash harness, or test was run; the repository was not edited. The `src/...:line` references below refer to that Core commit. The current `docs/evolution/recovery-contract.md` was still a Q05 working document, not an implemented API.

Core already has useful durable primitives; the new evolution lifecycle must extend them. The presence of one primitive does not establish an end-to-end guarantee connecting an external effect, evidence, an accepted result, and installation of a new Core runtime.

This is a historical record of an independent review. Both additions in the final section were incorporated into the final [Q05 specification](recovery-contract.en.md): independent control-process handoff and the receiver-fencing boundary. The other findings became receipt/adoption/reconciliation requirements and RC01–06 variants. Source code was not fixed during this pass.

Primary code for verification: [worker runtime](../../src/agent_factory/worker_runtime.py), [durable operations](../../src/agent_factory/durable_workflow.py), [recovery](../../src/agent_factory/local_recovery.py), [candidate adoption](../../src/agent_factory/candidate_changes.py), [delivery completion](../../src/agent_factory/coding_delivery.py), [evaluation](../../src/agent_factory/evaluation.py), [worker admission](../../src/agent_factory/worker_admission.py). Every line cited below is tied to the stated baseline commit, not an unknown future version of those files.

<a id="що-вже-є-й-підлягає-повторному-використанню"></a>
## What already exists and should be reused

| Boundary | Verified implementation | Practical limit of the claim |
|---|---|---|
| Mission-operation identity | `durable_workflow.py:319` reserves `(mission_id, operation_key)`, canonical request digest, class, reconciliation policy, and mission/revision/epoch/checkpoint/fence scope; a repeat with different bytes/scope is rejected at `:345–374` | Stable intent identity exists; this is not proof of receiver-side deduplication |
| Unresolved effect | `durable_workflow.py:728–808`: observer for `UNKNOWN`; `PRESENT→RECONCILED`, `ABSENT→RETRY_READY` only under an allowed policy, uncertainty/conflict→`NEEDS_ATTENTION` | A sound fail-closed foundation; the specific observer is responsible for the truth of the actual observation |
| Admission before dispatch | `worker_runtime.py:401–445` commits the starting session and exact launch digest before the side effect. A repeat returns the same session rather than calling the driver again (`:422–429`, `:521–525`) | Do not create a second queue or replace this protocol with a new generic retry |
| Recovery snapshot | `local_recovery.py:573`, `:1083–1101`, `:1128–1167`: integrity/actual-state checks, snapshot digest, decision, and a second mission-version check before commit | Repeating the same recovery key returns the stored historical decision (`:592–597`); it is not a fresh check of current authority for any subsequent action |
| Admission/fencing/occupancy | `worker_admission.py:506–524` binds assignment/attempt/lease/fence; `:546–568` ends the exact admission and records immutable stop evidence; expiry does not mean the worker has physically been released | Preserve the distinction between a logical lease and physical occupancy |
| Autonomous coding completion | `coding_delivery.py:1099–1140` requires persisted child authorization and current mission fence/epoch/policy; `:1221–1264` checks a clean Git branch/ancestry and binds evidence; `:1278–1319` rechecks the fence in the completion commit | This is a stronger existing boundary than a simple `accepted_evidence=True`; it completes authorized child delivery, but does not install a new Core supervisor |
| Accepted-artifact immutability | Candidate/evaluation/verdict triggers: `storage.py:1020–1023`, `:1076–1083`; pack version/qualification/event triggers: `:2644–2687` | History is not rewritten, but an immutable DB row does not make a preceding external effect atomic with the DB |

The table abbreviates the prefix: all modules are under `src/agent_factory/`.

<a id="шість-конкретних-прогалин-для-майбутнього-transition-contract"></a>
## Six concrete gaps for the future transition contract

<a id="g1-durable-start-reservation-ще-не-забезпечує-відновлення-результату-generic-driver"></a>
### G1. Durable start reservation does not yet recover a generic driver's result

**Existing behavior.** Admission is persisted before the driver call—this already protects against a blind repeat. However, `DirectCLIProviderDriver.start` ignores `control_session_id`, creates a local UUID, and calls the injected `provider.execute` before returning (`src/agent_factory/worker_runtime.py:185–195`). Results/events live in `self._sessions` (`:181–183`, `:238–243`), and the external ID is stored only after the driver returns (`:553–556`; `storage.py:8482–8503`). `collect_events` clears the in-memory list before the durable append (`worker_runtime.py:265–269`, `:698–707`); `storage.py:8566–8602` assigns a new local sequence without a receiver event ID/dedup acknowledgment parameter.

**Crash trace.** The provider has already performed/charged for the work → the process crashes before binding the external ID or appending events → the starting session exists, but output/charge may be unknown. Repeating admission does not launch the driver again, but does not itself recover the lost result.

**Contract clarification.** Specify durable identity, outcome lookup, event persistence/acknowledgment, and cost observation for every driver/effect profile. Do not attribute these properties to all adapters. Default recovery handlers currently cover WORKTREE, GIT_INTEGRATION, CHECKPOINT, REVISION_TRANSITION, EPOCH_TRANSITION (`local_recovery.py:811–819`); unknown PROVIDER_CALL/COMMAND/SERVICE/MODEL_LIFECYCLE/GITHUB operations need a configured typed observer, otherwise they remain indeterminate (`:932–945`). RC01–03 must test the advertised profile specifically. A new attempt is allowed for repeatable computation only while preserving the old unresolved effect/cost.

<a id="g2-evaluation-verdict-dedup-не-є-durable-evaluation-attempt"></a>
### G2. Evaluation-verdict deduplication is not a durable evaluation attempt

**Existing behavior.** `src/agent_factory/evaluation.py:97–99` checks for a completed evaluation; the injected `review(...)` is called at `:156`, while evaluation/verdict persistence begins at `:192–227`. Uniqueness at `storage.py:1059` protects the persisted evaluation, not the callback itself.

**Crash trace.** Review finishes → a crash occurs before commit → no evaluation row exists → the same public method calls review again. If the callback uses an external model provider, this may produce another charge or a different verdict. The source does not establish which provider, if any, backs the injected function.

**Contract clarification.** Separate the evaluation's logical operation, every admitted attempt, and the stable sealed result. Persist intent/budget before the call; after an unknown outcome, apply the G1 capability policy. Acceptance references the exact protocol/input/issuer/attempt receipt, not merely the last returned verdict. A future negative case is a crash after the callback but before the evidence commit; do not automatically claim “one evaluator vote / one charge” without this boundary.

<a id="g3-recovery-candidate-commit-перевіряє-структуру-але-не-повторно-звязує-content-digest"></a>
### G3. Recovery of a candidate commit checks structure but does not rebind the content digest

**Existing behavior.** `src/agent_factory/candidate_changes.py:81–92` finds validators by the stored worker diff digest; Git add/commit occurs at `:107–108`, and the DB artifact at `:134–153`. **Recovery already exists:** `:110–120` allows a clean tracked worktree with the expected parent, commit subject, and file list. Recovery is not absent.

**Gap.** This path does not recompute the digest of the content actually committed. At `:144`, the new `head_sha` is recorded alongside the old `result['diff_digest']`. Different bytes in the same files with the same parent/subject can pass the structural check even though they are no longer the validated snapshot. Such a change can result from concurrent writing or incorrect recovery; an attacker need not be assumed.

**Contract clarification.** The candidate-adoption receipt must prove the exact artifact bytes/tree and their correspondence to the validated subject. A commit SHA identifies Git content, but does not prove that the validator checked that content. Before manifest/seal, perform another authoritative content binding or create a new candidate/invalidation; include the negative trace “same filenames/subject, different content.”

<a id="g4-стандартний-accepted-delivery-та-його-gate-фіксуються-різними-транзакціями"></a>
### G4. Standard accepted delivery and its gate are recorded in separate transactions

**Existing behavior.** Public `CodingDeliveryService.process` directly calls the standard implementation (`src/agent_factory/coding_delivery.py:163–185`). Deduplication at `:1648–1653` sees the coding-delivery iteration/status. On the success path, `loops.record_iteration(...accepted_evidence=True)` comes first (`:1700–1705`), then the Founder gate is created (`:1707`), and only afterward does the coding-delivery iteration transaction begin (`:1735–1751`). The loop itself has already committed `status='accepted'` in `engineering_loop.py:185–186`, `:217–249`; a new call for an inactive loop is rejected at `:166–167`.

**Crash trace.** A crash after the accepted-loop commit but before the coding-delivery iteration → delivery appears active/unprocessed → retry reaches the already accepted loop and may fail with an error. A crash after the Founder gate can also leave a gate without delivery linkage. A similar boundary exists in `candidate_changes.py:177–185`: the plan/gate is created before `candidate_pr_plans`; `storage.py:11200` creates a new gate in a separate transaction. These are local approval records; the calls do not publish a PR.

**Contract clarification.** The logical accepted evidence→linked decision/gate transition needs a replayable transition identity and a declared commit/reconciliation boundary. Retry must adopt the already committed result/gate rather than require an active loop again or create another approval. Reuse the stronger autonomous-completion pattern with a second scope/fence check; do not call the standard path already atomic. `accepted_evidence` is a caller-supplied bool with consistency checks (`engineering_loop.py:151–160`), so it does not replace an independent receipt.

<a id="g5-наявні-approvalpack-primitives-не-є-authorization-на-встановлення-нового-core-generation"></a>
### G5. Existing approval/pack primitives do not authorize installation of a new Core generation

**Existing behavior.** `evaluation.py:186` is a verdict. Standard delivery separately requires a Founder decision and prepares a PR plan (`coding_delivery.py:1707`, `:1800–1805`); the event explicitly states `external_mutation_executed=False` (`:1820`); `candidate_pr_plans` has `CHECK(dry_run=1)` (`storage.py:1031`). This usefully separates evaluation from external action.

`src/agent_factory/packs.py:177–207` checks manifest/signature/dependencies and **caller-supplied booleans** for qualification. `:208–253` atomically records the version, qualification, active metadata pointer, and event. The method does not run the declared migrations/evaluations or replace the running Core process; rollback at `:272–291` changes a DB pointer. The existing version column is useful, but these APIs are not a Q05 PromotionAuthorization with exact expected ActivationBinding, serialized revocation, and successor-writer activation.

**Contract clarification.** Do not map an accepted evaluation, approved PR gate, autonomous child completion, or active pack pointer to “Core G1 deployed.” Generation qualification, a scoped release grant, an activation receipt, and runtime/state readiness have separate meanings. For a Core source change affecting the supervisor/promoter, the profile must identify the current independent activation authority and fenced successor. A candidate never receives incumbent credentials merely because of its verdict. Updating the authority itself requires a separately qualified handoff/recovery transition; it cannot approve itself or depend on an already stopped process completing its own swap.

<a id="g6-stop-evidence-digest-і-fence-у-core-не-доводять-припинення-всіх-зовнішніх-effects"></a>
### G6. A stop-evidence digest and fence in Core do not prove that all external effects have stopped

**Existing behavior.** `src/agent_factory/worker_admission.py:546–568` correctly binds stop evidence to the exact admission/fence, makes a repeat with the same evidence/actor/reason idempotent, and transactionally releases occupancy. However, `_digest` (`:134–137`) checks only the SHA-256 format. The method accepts a ready-made hash/actor/reason; it does not itself observe the process tree, provider operation, or settled charge. `worker_runtime.py:719–731` calls driver cancel, records status, and ends the session; this is not automatic external proof-of-stop either.

**Crash trace.** A lease expires/cancel is accepted locally → the old worker or provider effect is still running → prematurely equating “cancelled” with stopped/released capacity creates concurrent execution or hidden budget exposure. The existing occupancy distinction already prevents part of this; it must be preserved.

**Contract clarification.** Define a trusted producer and verifiable stop/reconciliation receipt content: exact launch identity, fence, processes/descendants within the claimed boundary, external effect IDs, cancellation/outcome state, and unresolved cost. A Core writer fence protects only paths whose authoritative commit receiver actually checks it (for example, admitted runtime events at `storage.py:8580–8583`); it does not stop an arbitrary external action. An unsupported receiver profile is blocked or remains unknown. A recovery receipt is a historical observation; current authority epoch and fence must be rechecked before a new dispatch/activation.

<a id="перевірка-нового-q05-draft"></a>
## Review of the new Q05 draft

`docs/evolution/recovery-contract.md:3`, `:99`, `:128` correctly identify the design as proposed and the scenarios as unexecuted. §3 (`:52–62`) correctly separates receiver capability, possible duplicate charges, and unknown effects. §4 (`:66–78`) does not declare the process/load balancer part of a SQLite transaction. RC06–11 correctly separate comparison, grant, activation sequence, and ABA.

Two concrete additions for the root agent:

1. Add an explicit **control-process upgrade profile** with the authority/successor handoff from G5 to the own-source Core self-improvement claim (`:126`). The current generic promotion table does not specify who survives a crash and is authorized to finish replacing the supervisor itself.
2. Next to the coherent writer switch (`:70–72`), explicitly reference receiver conformance in §3 and limit the fencing guarantee to commit paths that actually check it. A local lease or supplied stop digest alone does not prove external termination of an effect.

These clarifications elaborate existing cards and receipts. They do not now require a new service, code, an active queue, or reinstating the three-PC workflow canceled by the user.
