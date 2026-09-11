# Q05 — фактичні межі recovery/evidence у Lokvetia Core

Дата: 2026-09-10, Europe/Zurich. Перевірений Core HEAD: `35c87b5331cf5da10a465b3c6b27caa1d1fa87a1` (повторно звірено наприкінці читання). Це незалежне **статичне read-only рев’ю** вихідного коду й поточного design draft. Жоден provider, продукт, crash harness або тест не запускався; repo не редагувався. Посилання `src/...:line` нижче стосуються цього Core commit. Поточний `docs/evolution/recovery-contract.md` — ще робочий документ Q05, не реалізований API.

Core уже має корисні durable primitives; новий evolution lifecycle повинен розширювати їх. Наявність одного з primitive не доводить наскрізної гарантії між зовнішнім ефектом, доказом, прийнятим результатом і встановленням нового Core runtime.

Це історичний запис незалежного рев’ю. Обидва доповнення з останнього розділу враховані у фінальній [специфікації Q05](recovery-contract.md): незалежний control-process handoff і межа receiver fencing. Інші знахідки перенесені в receipt/adoption/reconciliation вимоги та варіанти RC01–06. Вихідний код у цьому проході не виправлявся.

Первинний код для перевірки: [worker runtime](../../src/agent_factory/worker_runtime.py), [durable operations](../../src/agent_factory/durable_workflow.py), [recovery](../../src/agent_factory/local_recovery.py), [candidate adoption](../../src/agent_factory/candidate_changes.py), [delivery completion](../../src/agent_factory/coding_delivery.py), [evaluation](../../src/agent_factory/evaluation.py), [worker admission](../../src/agent_factory/worker_admission.py). Усі наведені нижче рядки прив’язані до зазначеного baseline commit, не до невідомої майбутньої версії цих файлів.

## Що вже є й підлягає повторному використанню

| Межа | Перевірена реалізація | Практична межа твердження |
|---|---|---|
| Ідентичність місійної операції | `durable_workflow.py:319` резервує `(mission_id, operation_key)`, canonical request digest, class, reconciliation policy та mission/revision/epoch/checkpoint/fence scope; повтор з іншими bytes/scope відхиляється на `:345–374` | Є стабільна ідентичність наміру, а не доказ receiver-side dedup |
| Незавершений ефект | `durable_workflow.py:728–808`: observer для `UNKNOWN`; `PRESENT→RECONCILED`, `ABSENT→RETRY_READY` лише за дозволеною policy, невизначеність/конфлікт→`NEEDS_ATTENTION` | Правильна fail-closed основа; істинність фактичного спостереження належить конкретному observer |
| Admission перед dispatch | `worker_runtime.py:401–445` комітить starting session і digest exact launch до side effect. Повтор повертає ту саму session, а не викликає driver вдруге (`:422–429`, `:521–525`) | Не треба створювати другу чергу або підміняти цей протокол новим загальним retry |
| Recovery snapshot | `local_recovery.py:573`, `:1083–1101`, `:1128–1167`: integrity/actual-state checks, snapshot digest, рішення, повторна перевірка mission version перед commit | Повтор того самого recovery key повертає збережене історичне рішення (`:592–597`); це не нова перевірка чинного права на будь-яку наступну дію |
| Admission/fencing/occupancy | `worker_admission.py:506–524` прив’язує assignment/attempt/lease/fence; `:546–568` припиняє exact admission, незмінно фіксує stop evidence; expiry не дорівнює фізичному звільненню worker | Зберегти окремість logical lease й physical occupancy |
| Autonomous coding completion | `coding_delivery.py:1099–1140` вимагає persisted child authorization, чинний mission fence/epoch/policy; `:1221–1264` перевіряє clean Git branch/ancestry та bind-ить evidence; `:1278–1319` повторно звіряє fence у completion commit | Це сильніша наявна межа, ніж простий `accepted_evidence=True`; вона завершує authorized child delivery, але не встановлює новий supervisor Core |
| Незмінність accepted artifacts | Candidate/evaluation/verdict triggers: `storage.py:1020–1023`, `:1076–1083`; pack version/qualification/event triggers: `:2644–2687` | Історія не переписується, але immutable DB row не робить попередній зовнішній ефект атомарним із DB |

У таблиці скорочено префікс: усі модулі — `src/agent_factory/`.

## Шість конкретних прогалин для майбутнього transition contract

### G1. Durable start reservation ще не забезпечує відновлення результату generic driver

**Наявна поведінка.** Admission зберігається до виклику driver — це вже захист від сліпого повтору. Але `DirectCLIProviderDriver.start` ігнорує `control_session_id`, створює локальний UUID і викликає injected `provider.execute` до повернення (`src/agent_factory/worker_runtime.py:185–195`). Результат/події живуть у `self._sessions` (`:181–183`, `:238–243`), а зовнішній ID зберігається тільки після повернення driver (`:553–556`; `storage.py:8482–8503`). `collect_events` очищує in-memory список до durable append (`worker_runtime.py:265–269`, `:698–707`); `storage.py:8566–8602` дає нову локальну sequence, без параметра receiver event ID/dedup acknowledgment.

**Crash trace.** Provider уже виконав/оплатив роботу → process crash до binding external ID або до append events → starting session існує, а output/charge може бути невідомим. Повтор admission не запускає driver ще раз, але сам по собі не повертає загубленого результату.

**Уточнення контракту.** Для кожного driver/effect profile вказати durable identity, outcome lookup, спосіб persist/ack events і cost observation. Не приписувати всім адаптерам ці властивості. Default recovery handlers сьогодні охоплюють WORKTREE, GIT_INTEGRATION, CHECKPOINT, REVISION_TRANSITION, EPOCH_TRANSITION (`local_recovery.py:811–819`); невідомі PROVIDER_CALL/COMMAND/SERVICE/MODEL_LIFECYCLE/GITHUB потребують configured typed observer, інакше лишаються indeterminate (`:932–945`). RC01–03 мають перевіряти саме advertised profile. Повтор із новим attempt дозволений для repeatable computation лише зі збереженим unresolved старим effect/cost.

### G2. Evaluation verdict dedup не є durable evaluation attempt

**Наявна поведінка.** `src/agent_factory/evaluation.py:97–99` перевіряє готовий evaluation; injected `review(...)` викликається на `:156`, а evaluation/verdict persistence починається на `:192–227`. Унікальність `storage.py:1059` захищає persisted evaluation, а не сам callback.

**Crash trace.** Review завершився → до commit стався crash → evaluation row відсутній → той самий публічний метод повторно викликає review. Якщо callback використовує зовнішній model provider, це може дати додаткову charge або інший verdict. Джерело не доводить, який саме provider стоїть за injected функцією.

**Уточнення контракту.** Відокремити evaluation logical operation, кожний admitted attempt і стабільний sealed result. Persist intent/budget до виклику; після unknown застосовувати capability policy G1. Acceptance посилається на exact protocol/input/issuer/attempt receipt, а не лише останній returned verdict. Майбутній negative case — crash після callback до evidence commit; жодної автоматичної заяви про «один evaluator vote / одну charge» без цієї межі.

### G3. Recovery candidate commit перевіряє структуру, але не повторно зв’язує content digest

**Наявна поведінка.** `src/agent_factory/candidate_changes.py:81–92` знаходить validators за stored worker diff digest; Git add/commit відбувається на `:107–108`, DB artifact — на `:134–153`. **Recovery уже є:** `:110–120` допускає чистий tracked worktree з expected parent, commit subject і переліком файлів. Це не «відсутнє recovery».

**Прогалина.** У цьому шляху не перераховується digest фактично committed content. На `:144` новий `head_sha` записується поруч зі старим `result['diff_digest']`. Інші bytes тих самих файлів із тим самим parent/subject можуть пройти структурну перевірку, хоча це вже не validated snapshot. Така зміна може бути наслідком конкурентного запису або некоректного відновлення; не потрібне припущення про зловмисника.

**Уточнення контракту.** Candidate adoption receipt повинен доводити exact artifact bytes/tree і відповідність validated subject. Commit SHA сам ідентифікує Git content, але не доводить, що validator перевіряв саме його. До manifest/seal — повторне authoritative content binding або new candidate/invalidation; negative trace «same filenames/subject, different content».

### G4. Стандартний accepted delivery та його gate фіксуються різними транзакціями

**Наявна поведінка.** Public `CodingDeliveryService.process` прямо викликає standard implementation (`src/agent_factory/coding_delivery.py:163–185`). Dedupe на `:1648–1653` бачить coding delivery iteration/status. У success path спочатку `loops.record_iteration(...accepted_evidence=True)` (`:1700–1705`), далі створюється Founder gate (`:1707`), і лише потім починається transaction coding delivery iteration (`:1735–1751`). Сам loop уже комітить `status='accepted'` у `engineering_loop.py:185–186`, `:217–249`; новий виклик для неактивного loop відхиляється на `:166–167`.

**Crash trace.** Crash після accepted loop commit, але до coding delivery iteration → delivery виглядає active/необробленим → повтор доходить до вже accepted loop і може зупинитися помилкою. Crash після Founder gate також може лишити gate без delivery linkage. Подібна boundary є в `candidate_changes.py:177–185`: plan/gate створюються до `candidate_pr_plans`; `storage.py:11200` створює новий gate в окремій транзакції. Це локальні approval records; ці виклики не публікують PR.

**Уточнення контракту.** Логічний перехід accepted evidence→linked decision/gate має replayable transition identity та declared commit/reconciliation boundary. Повтор повинен adopt-ити вже committed result/gate, а не знову вимагати активного loop або створювати нове схвалення. Reuse stronger autonomous completion pattern з повторною scope/fence перевіркою; не називати standard path уже атомарним. `accepted_evidence` — caller-supplied bool із consistency checks (`engineering_loop.py:151–160`), тому не замінює незалежного receipt.

### G5. Наявні approval/pack primitives не є authorization на встановлення нового Core generation

**Наявна поведінка.** `evaluation.py:186` — verdict. Standard delivery окремо вимагає Founder decision і готує PR plan (`coding_delivery.py:1707`, `:1800–1805`), event прямо має `external_mutation_executed=False` (`:1820`); `candidate_pr_plans` має `CHECK(dry_run=1)` (`storage.py:1031`). Це корисне відокремлення оцінки від зовнішньої дії.

`src/agent_factory/packs.py:177–207` перевіряє manifest/signature/dependencies і **передані caller booleans** qualification. `:208–253` атомарно записує version, qualification, active metadata pointer та event. Метод не запускає declared migrations/evaluations і не замінює запущений Core процес; rollback на `:272–291` змінює DB pointer. Наявна version колонка корисна, але ці API не є Q05 PromotionAuthorization із exact expected ActivationBinding, serialized revocation та successor-writer activation.

**Уточнення контракту.** Не мапити accepted evaluation, approved PR gate, autonomous child completion або pack active pointer на «Core G1 deployed». Generation qualification, scoped release grant, activation receipt і runtime/state readiness мають окремі значення. Для Core source change, що зачіпає supervisor/promoter, profile повинен визначити чинного незалежного activation authority й fenced successor. Candidate ніколи не отримує incumbent credentials лише через свій verdict. Оновлення самого authority потребує окремо qualified handoff/recovery transition; воно не може схвалити себе або залежати від того, що вже зупинений процес завершить власний swap.

### G6. Stop-evidence digest і fence у Core не доводять припинення всіх зовнішніх effects

**Наявна поведінка.** `src/agent_factory/worker_admission.py:546–568` коректно прив’язує stop evidence до exact admission/fence, робить повтор із тими самими evidence/actor/reason idempotent і транзакційно звільняє occupancy. Але `_digest` (`:134–137`) перевіряє тільки формат SHA-256. Метод приймає готовий hash/actor/reason; сам не спостерігає process tree, provider operation або settled charge. `worker_runtime.py:719–731` викликає driver cancel, записує status і завершує session; це теж не автоматичний зовнішній proof-of-stop.

**Crash trace.** Lease сплив/cancel прийнятий локально → старий worker або provider effect ще виконується → передчасне прирівнювання «cancelled» до stopped/released capacity створює одночасне виконання чи прихований budget exposure. Existing occupancy distinction вже запобігає частині цього; її треба зберегти.

**Уточнення контракту.** Визначити trusted producer та перевірний зміст stop/reconciliation receipt: exact launch identity, fence, процеси/descendants у claimed boundary, зовнішні effect IDs, стан cancellation/outcome і unresolved cost. Core writer fence захищає тільки шляхи, де authoritative commit receiver реально його перевіряє (наприклад, admitted runtime events на `storage.py:8580–8583`); він не зупиняє довільну зовнішню дію. Непідтримуваний receiver profile блокується або лишається unknown. Recovery receipt — історичне спостереження, перед новим dispatch/activation повторно перевіряються поточна authority epoch та fence.

## Перевірка нового Q05 draft

`docs/evolution/recovery-contract.md:3`, `:99`, `:128` коректно називають design proposed і сценарії невиконаними. §3 (`:52–62`) правильно розділяє receiver capability, possible duplicate charges і unknown effects. §4 (`:66–78`) не проголошує процес/load balancer частиною SQLite transaction. RC06–11 правильно відокремлюють comparison, grant, activation sequence та ABA.

Два конкретні доповнення для root:

1. До твердження про self-improvement власного Core source (`:126`) додати явний **control-process upgrade profile** з authority/successor handoff із G5. Поточна загальна promotion table не визначає, хто переживає crash і має право завершити заміну саме supervisor.
2. Поруч із coherent writer switch (`:70–72`) прямо послатися на receiver conformance §3 і обмежити fencing guarantee commit paths, що справді його перевіряють. Local lease або supplied stop digest самі не доводять зовнішнє припинення ефекту.

Ці уточнення деталізують існуючі картки й receipts. Вони не потребують зараз нового сервісу, коду, активної черги або повернення до скасованого користувачем workflow трьох ПК.
