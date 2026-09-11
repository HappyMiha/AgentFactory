# Q08: на яких задачах Core має довести власне поліпшення

Дата: 2026-09-10. Статус: E0 / source-informed evaluation design. Це специфікація майбутнього набору, а не готовий benchmark або виконаний експеримент. Нових test programs, fixture repositories, моделей чи запусків немає. Усі приклади цього документа відкриті й придатні тільки як development/design матеріал. Приховані задачі, відповіді й приватні reports до Git не додаються.

## 1. Рішення: дві сім’ї результатів, окремі перевірки надійності

Core має довести користь на задачах, що не потребують Lokiravia, Godot або game pack. Початкові «контекст, tool use, code repair, recovery, planning, user-facing evidence» були шістьма різними вимірами перевірки; одна задача може охопити їх усі. Q08 не рахує їх шістьма незалежними сімействами.

| Family | Робота користувача і результат | Що перевіряється зовні | Що не є завершенням |
|---|---|---|---|
| NG-F1 · bounded software maintenance | За exact brief змінити невеликий зовнішній fixture repo: виправити поведінку або додати обмежену функцію, зберігши сумісність. Результат — exact patch/commit, виконуваний artifact та чесний звіт | Ізольований verifier виконує незалежно підготовлені behavior/regression checks на фактичному output; перевіряє дозволений diff, provenance і delivery status | Змінені лише tests або звіт; успіх unit suite самого Core; правильний commit іншої задачі; «готово» без artifact |
| NG-F2 · requirements-to-decision planning | Із версійованих non-game вимог, уточнень і обмежень підготувати план, придатний до рішення: що робимо, що не знаємо, залежності, критерії й питання. Результат — reviewable requirements/plan packet, не реалізований продукт | Deterministic checks звіряють sources/revisions, вимоги й суперечності, references, DAG, scope та authority. Незалежний review оцінює змістовну достатність і зрозумілість; кілька допустимих планів дозволені | Валідний JSON із загубленою потребою; вигадане owner approval; довгий план без decisive questions; planned fidelity видано за реалізовану функцію |

Сім’ї мають різні input corpora, work products і outcome rubrics. F2 не є тим самим F1 завданням, оціненим до написання коду: для двосімейного claim їхні root tasks і вихідні матеріали не перетинаються. Це operational independence, не припущення статистичної незалежності всіх observations. Спільне походження fixture, solution strategy або джерела лишається dependency/cluster у плані аналізу.

У кожній сім’ї перевіряються **cross-cutting slices**: актуальність вимог/контексту; tool/permission boundaries; retry/recovery; artifact/evidence provenance; failure/unknown handling; operator usability. Жоден slice сам не додає нової family або independent task. Обидві сім’ї включають звичайні здійсненні задачі, очікувано заблоковані й неоднозначні випадки. Стратегія «завжди відмовляти» не проходить outcome floor на здійсненних задачах.

Поточні Core bugs/fixtures допомагають обрати slices, але не доводять репрезентативності потреб користувачів. NG-F1/F2 — початкові гіпотези для RSI015/030, які потребують qualification та product-signal evidence RSI026.

## 2. Підстави з поточного Core

Snapshot: Core `1147d72195d390ac16e15e466ca5f8313d055b8b`; Lokiravia для меж shared portfolio — `23704f316948a50aba724ede5d461ecbd8cdaaea`. Upstream main повторно звірено: Core `c22954f144702fdf7a3da16cf58176baa345f7c4`, Lokiravia `3d42cf9606d1100ebe0887306300b5fa4aaaea5e`. Нижче — прочитані конкретні code paths, assertions та один історичний commit. Тести не запускалися; назва regression не доводить реального інциденту користувача.

| Якір / клас | Прочитаний evidence і його статус | Наслідок для нового task design |
|---|---|---|
| NG-D01 · stale requirements | [Intake test](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_autonomous_mission_intake.py#L267) очікує invalidation старої proposal після зміни source; [intake source](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/mission_intake.py#L1311) має supersession/invalidation. Synthetic fixture + current guard, не встановлений live incident | Denial старої версії — floor. Корисний новий work product також правильно змінює залежні вимоги та зберігає чинні commitments; checksum не доводить розуміння |
| NG-D02 · mandatory context / dispatch | [Context fixtures](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_context_packages.py#L147), [source](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/context_packages.py#L414) перевіряють mandatory budget, stale required content і інший dispatch; [runtime binding](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/worker_runtime.py#L373). Synthetic cases + явні поточні перевірки | Зберегти позначене required не означає правильно виявити всі важливі умови. Перевіряти content sufficiency, допустиме додаткове читання й actual final result |
| NG-D03 · wrong-plan / stale / simulated readiness | [Readiness source](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/environment_readiness.py#L239), [caller](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/coding_delivery.py#L481), [fixtures](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_environment_readiness.py#L40). [Історичний commit cf7896b](https://github.com/HappyMiha/Lokvetia-Core/commit/cf7896b66f202ba537e62b6a15f7ee3f7bc614a0) додав current route gate перед development | Historical gate correction і synthetic negative cases не означають нову поломку. F2 потребує тільки свого capability profile, не автоматично coding/GPU route. Readiness не замінює outcome |
| NG-D04 · persuasive review без primary evidence | [Evaluator](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/evaluation.py#L100) вимагає validators/digest/criterion evidence та відкидає same-model review; [worker fixtures](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_codex_worker.py#L389) мають штучно позитивний reviewer | Це concrete software-candidate gate, не універсальний document evaluator. RSI006 має кваліфікувати document adapter; інша назва моделі не гарантує незалежності, primary refs не доводять правильного oracle mapping |
| NG-D05 · interrupted commit / artifact adoption | [Local-Git fixture](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_codex_worker.py#L289) очікує adoption одного HEAD після commit, до запису candidate artifact; [adoption branch](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/candidate_changes.py#L105) перевіряє parent/message/набір files | У цій вузькій прочитаній гілці немає повторного actual committed bytes rehash проти validated snapshot; це не доказ доступної експлуатації й уже враховано RSI004. Новий task перевіряє exact output bytes/receipt, а не тільки один commit або ім’я файла |
| NG-D06 · Pause / unknown effect | [Control fixture](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_autonomous_mission_control.py#L373) використовує simulation child і synthetic provider; [runtime operation gate](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/src/agent_factory/worker_runtime.py#L324); [recovery fixtures](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_autonomous_mission_recovery.py#L60) мають test observer | Уже прийнятий effect і новий dispatch різні. Mission-bound gate не є доказом remote fencing усіх sinks. Qualified receiver profile має чесно розрізняти completed/absent/unknown і наслідок Pause |

Додатково прочитано [proposal verifier assertions](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_autonomous_proposal_verifier.py#L208): golden document fixtures і specific findings; [stale source case](https://github.com/HappyMiha/Lokvetia-Core/blob/1147d72195d390ac16e15e466ca5f8313d055b8b/tests/test_autonomous_proposal_verifier.py#L492) зберігає immutable report. Це підтримує NG-F2 structural/revision slices, а не claim про якість людського планування. Наявні служби AF055, AF020/051/052/057, AF-AMM intake/approval/recovery повторно використовуються; нової реалізації під іншою назвою не потрібно.

## 3. TaskCase: що має бути визначено до запуску

Це логічні поля для чинних dataset/protocol/evidence служб RSI003/004/005/015, не новий store або runtime schema import.

| Група | Обов’язкові відомості |
|---|---|
| Identity / lineage | Case ID/version/digest, family, root-task ID, parent/source/generator/solution ancestry, mechanism і challenge slices, rights/provenance. Зв’язок із відомим defect seed явний |
| Початковий стан | Exact non-game repo/document bundle, source/requirement revisions, objective, accepted constraints, allowed tools/actions, granted scope і qualified environment. Same name або random seed не робить inputs однаковими |
| Доступність задачі | Supported і здійсненна / навмисно blocked / неоднозначна за відомими facts; допустимий тип результату. Oracle не може вимагати факту, якого немає серед дозволених inputs або можливостей |
| Outcome / verifier | Об’єктивні acceptance facts, допустимі альтернативи й hard floors, qualified verifier/decoder version, checker fixtures і external review rubric. Human usefulness/clarity не замінюється schema check |
| Exposure | Split, allowed readers/diagnostics, prior-access snapshot, subsequent access ledger, inherited memory/skill/retrieval/optimizer lineage, contamination status і межа впевненості |
| Execution / analysis | Baseline/challenger bundles, pair/attempt/repetition IDs, workload/environment/fault schedule, caps, missing/outage/retry policy, unit of analysis, decision/stopping rule та known limitations |

Task roots групуються до split, а не після результату. Сусідні seeds, перейменовані документи, інші schedules тієї самої помилки, повтори моделі та голоси кількох reviewers не стають незалежними roots. Зв’язок виявлено пізніше — applicability/analysis переглядається з явним amended protocol; старий verdict не переписується тихо.

Публічна oracle specification описує дозволене розв’язання, а не hardcoded єдину відповідь. Для F1 приховані checks оцінюють поведінку під контрольованим runner і не можуть бути змінені candidate. Для F2 відсутність required dependency або неврахована версія може мати зовнішньо перевірний verdict; художня переконливість плану чи користь для власника потребує окремого review. `READY_FOR_REVIEW`, `APPROVED`, `DISPATCHED` і фактично завершена робота лишаються різними станами.

## 4. Як створювати нові задачі й не називати копію прихованим тестом

1. **Зареєструвати відкритий seed.** Existing tests, bug reports, цей документ і Q05–Q07 сценарії мають статус exposed development. Вони корисні для debugging, механізму та regression, але не як докази незнайомої задачі.
2. **Вибрати declared transfer claim.** Нова instance відомого механізму, нове джерело/solution lineage, новий mechanism або нова family — різні рівні. `freshness` є цим вектором плюс exposure status, а не boolean. Незалежний автор або нова дата самі не роблять задачу новою.
3. **Підготувати task roots окремо від candidate search.** Інший fixture repo/документний корпус, структурно інші взаємодії та constraints, явна ancestry. Не копіювати Core test body зі зміненими іменами. Секретність відповідей не замінює нового походження задачі.
4. **Перевірити solvability та oracle.** Custodian/independent reviewer перевіряє, що valid solution існує в qualified scope, а contradictory/blocked cases оцінюються чесно. Known-good і known-bad controls кваліфікують measurement path. Видимий candidate не створює собі final labels або критерій прийняття.
5. **Розділити по roots, звірити подібність і prior access.** Зіставити sources, graph/constraint structure, expected solution, tasks/answers у logs, artifacts, skills, distilled summaries, retrieval і попередніх judge diagnostics. Подібність — сигнал для розбору, не автоматична гарантія clean. Невідоме pretraining exposure записується unknown.
6. **Seal до selection і вести наступний доступ.** Immutable TaskSetManifest/digest і exposure snapshot належать qualified evaluator scope. Actual task agent отримує дозволений task input під час final run; optimizer та майбутні generations не отримують необмежений replay цього input, відповідей або діагностів через спільну memory. Доступ task agent — дозволена частина evaluation, не доказ довічної невідомості цього case.
7. **Retire/reclassify після використання.** Aggregate score також є information. Усе, що спрямувало подальший пошук, переходить у adaptive/development evidence для відповідної lineage. Final tasks не стають знову fresh через Pause, rollback, новий candidate ID або видалений log.

Цей прохід не створив final set і не перевірив приватність такого середовища. Нові source families не проголошуються зовнішньою популяцією користувачів без дослідження їхньої відповідності реальній роботі.

## 5. Три набори і три різні reference ролі

| Набір | Доступ і призначення | Межа claim |
|---|---|---|
| D · development / calibration | Відкриті recipes, known regressions, debugging, baseline noise/runner checks. Дозволені repeated diagnostics у межах ресурсу | Пояснює механізм і роботу на відомих cases; не fresh transfer |
| S · adaptive selection | Окремі roots, bounded queries, declared feedback detail, повний access ledger. Candidate search може використовувати результати | Sealed custody не робить адаптивний selection score незалежною final confirmation |
| F · final confirmation | Незалежні від D/S roots у заявленому transfer scope; custodian утримує labels; protocol і обраний candidate заморожені до відкриття результатів | Одна заздалегідь визначена confirmation процедура для обраного candidate. Подальша зміна candidate/threshold після F потребує нової процедури та нового придатного F |

Final procedure може містити наперед зафіксовані кілька arms/looks за відповідною correction/stopping policy. Це не дозволяє необмежено вибирати «кращий» candidate на final score. Навіть acceptance-only або aggregate feedback входить у exposure ledger. Усі exploratory candidates, невдалі перевірки та costs збережені, winner не вдає єдину спробу. До кампанії задається скінченний final-gate/retest allowance; новий F, mission, candidate або criterion epoch не скидає cumulative selection/comparison history. Після вичерпання — stop/inconclusive або окремо дозволений новий experiment зі збереженою історією, а не автоматичний пошук щасливого final-набору.

| Роль reference | На яке питання відповідає |
|---|---|
| Frozen founding reference R0 | Чи є накопичена користь проти визначеної вихідної версії? Exact source/harness/model/tool/memory/profile зафіксовані; старий historical score не порівнюється напряму з новою task/criterion епохою |
| Immediate accepted predecessor Rn | Чи кращий candidate Rn+1 за версію, яку він збирається замінити? Required comparator для incremental adoption; кращий за R0, але гірший за Rn не проходить як поліпшення |
| Bounded no-evolution / compute / ablation control | Чи пояснюється gain самим extra compute, resampling, накопиченим доступом до досвіду або іншою моделлю? Ablation перевіряє claimed mechanism; не підміняє кінцевий product outcome |

Rn та candidate виконують зіставні root tasks за current спільним CriterionManifest, resource/authority envelope та starting state. Для накопиченого claim R0 запускається на сумісному current protocol; historical output re-score не замінює fresh execution нового workload. Якщо R0 не може працювати в профілі, це окремий compatibility limit; його старий score не масштабується довільно.

Коли memory/context strategy є treatment, однаковими є **дозволений experience pool та бюджет**, а не обов’язково згенеровані представлення memory. Відмінність має бути задекларована; future/final data не додається жодному arm. Модель, runtime, scheduler, dependency/toolchain змінилися — це controlled factor або confounder. Немає attribution власному source Core лише за одночасного встановлення кращої моделі.

Для O0→O1→O2 порівнюються не тільки готові патчі: потрібні фактична участь O1 у створенні O2, кілька незалежних search runs за declared plan, downstream product outputs і benefit O2 проти безпосереднього O1 з обліком усього пошуку. Один удачний patch не є доказом кращого optimizer. Зміна evaluator/criterion має окремий Q03 protocol; власний candidate не послаблює current acceptance.

## 6. Вибірка, outcomes, шум і вартість

Раніше запропоновані **60 paired tasks** лишаються планувальною гіпотезою: для одного future confirmation block це 60 root-task pairs, початково 30 NG-F1 і 30 NG-F2. D/S preparation та search runs — окремий обсяг і повна ціна; вони не входять непомітно в denominator цих 60. Це не готовий task inventory, power calculation або дозвіл на compute. До admission precision/noise review на D визначає придатні root counts, повтори, margins та caps у конкретному protocol. Зміна до запуску допустима як versioned design; після outcomes не можна докуповувати cases до бажаного pass.

Три повтори stochastic case — вихідна гіпотеза для variance estimation, не три незалежні задачі. За 60 roots, двох arms і трьох повторів це 360 executions до retries, development, selection, review чи третього reference arm. Deterministic cases не потребують повторів заради лічильника. Фактичний repeat plan приймається до запуску; числа тут не обіцяють достатньої точності.

Обирається одна primary вісь на family: accepted outcome за cost/latency floors або повна ціна за non-inferior quality. Core030 потребує benefit у **наперед названих обох** сім’ях, а не вибору двох найкращих slices постфактум. Ефект, dispersion/interval, non-inferiority margins, family/multiple-candidate comparisons і sequential looks мають метод, зафіксований до evidence. Широкий interval або недостатня вибірка дають `inconclusive`; саме це є чесним результатом обмеженого пілоту.

Окремі поля outcomes: artifact/plan validity; achieved user goal; коректне handling unknown/blocked scope; fidelity; operator clarity/assistance; latency; total cost; permissions/integrity/recovery. Correct abstention у blocked case не видається виконаною функцією. Hard invariant violation блокує прийняття, навіть якщо середня utility зросла. Для F2 детермінована correctness не дає claim про незалежну human usability без людей.

Pair identity зберігає starting inputs і exogenous/fault schedule. Дії candidate можуть відрізнятися від predecessor. Crash «після accepted external effect, перед локальним receipt» має бути прив’язаний до semantic boundary кожного arm, якщо це заявлений slice; неможливе парування не приховується під однаковим seed. Якщо arm законно досягає user goal без цієї дії, його не примушують до effect і root не вилучають: task outcome зберігається, fault exposure/applicability оцінюється окремо. Якщо effect потрібний за початковою задачею, його відсутність оцінюється як невиконання goal, а не зручне N/A. Same task root залишається кластером через repeats/sibling variants/reviewer votes.

Timeout, cancelled, failed, unsupported, environment-invalid і missing evidence мають окремі dispositions. До запуску визначено eligibility, retry cap і розбір інфраструктурного збою. Розрізняються запланований stochastic repeat, незалежно встановлений invalid measurement і валідний final без позитивного gain; третій випадок не ремонтується повтором до pass. Немає ad hoc вилучення baseline failure або складного candidate case. Environment-invalid зберігається у flow counts і cost ledger, paired missingness обмежує inference. Відсутність доказаного gain не означає practical equivalence: для `equivalent` потрібен окремий наперед заданий criterion. Відсутня charge не рахується нульовою, а нуль accepted improvements не дає нульову ціну кампанії.

Budget охоплює task/oracle preparation, qualification, усі candidate search runs, failures/retries, model/retrieval, verifier/human review, storage/I/O та serving/measurement. Generation/mission ID, rollback або Stop не скидають campaign obligations. Candidate utility і повна campaign efficiency — два окремі звіти. Власник ресурсів задає реальні caps; цей design не створює кошторис із чужих paper ratios.

## 7. Відкриті recipes та статичні controls

Recipes нижче — нові авторські текстові приклади, не створені fixture repos, не приховані tasks і не опис фактичних збоїв користувачів. Вони показують, як клас помилки може перевірятися в різних work products.

| Recipe | Family / slice | Приклад та очікувана межа |
|---|---|---|
| NG-O01 | F1 / scope-version | У локальному parser utility автор уточнив правило порожнього рядка. Зміна має спожити exact reviewed requirement, зберегти старі сумісні cases й дати перевірений patch; stale brief не «перемагає», бо коротший |
| NG-O02 | F1 / artifact provenance | Worker повідомляє успіх export utility, але receipt належить іншому commit. Зовнішній checker не приймає звіт без output правильного source; це не вимога скопіювати тест Core |
| NG-O03 | F1 / interrupted effect | Після запису patch artifact губиться відповідь. Retry має узгодити accepted output і актуальні права, не дублювати side effect. Receiver profile визначає, що можна перевірити, а що лишається unknown |
| NG-O04 | F2 / ambiguity | План локального архіву документів має суперечливі retention вимоги та непогоджений export. Результат показує конфлікт, залежності й питання; вигаданий компроміс не стає рішенням власника |
| NG-O05 | F2 / source revision | Reviewed план спирається на старий ресурсний ліміт; новий source змінив допустимий обсяг. Потрібне явне applicability/review рішення; immutable старий verdict не переписується |
| NG-O06 | F2 / semantic adequacy | План валідний структурно, але забув шлях користувача після невдалої операції. Independent review відділяє змістовну прогалину від DAG/schema pass; гарний стиль не є компенсацією |

| ID | Контрприклад | Очікуване рішення |
|---|---|---|
| Q08-N01 | Той самий Core unit fixture перейменовано й покладено в final | Залишається exposed root/lineage; fresh claim відхилено |
| Q08-N02 | Шість checks одного patch названо шістьма families | Один task root із slices; не пройдено двосімейний gate |
| Q08-N03 | Candidate кращий за R0, гірший за актуальний Rn | Немає incremental improvement/adoption на цій підставі |
| Q08-N04 | Після десятків selection queries aggregate score названо незалежним final | Exposure враховано; потрібна придатна окрема confirmation, пошук/cost не приховані |
| Q08-N05 | Task agent побачив F input, summary потрапив у shared optimizer memory | Lineage забруднена для майбутнього fresh claim; reclassification/новий set, не новий ID |
| Q08-N06 | Три stochastic retries і п’ять reviewer votes збільшили n одного root до 15 | Cluster/unit of analysis збережено, uncertainty не стискається штучно |
| Q08-N07 | Schema-valid F2 packet оголошено корисним продуктом без human evidence | Structural evidence лишається у своїй області; usability/product-signal gate відкритий |
| Q08-N08 | Усе відхилено «з міркувань надійності», supported tasks теж | Handling і achieved goal різні; outcome floor не пройдено |
| Q08-N09 | Challenger змінив final checker або обрав зручні дві families після score | Новий criterion/selection experiment, не чинне Core030 acceptance |
| Q08-N10 | Звіт прибрав failures, unknown costs та ранні search candidates | Порівняння не приймається; denominator, lineage і campaign price відновлюються з належних receipts |

## 8. Admission, claims та наступне рішення

Перед будь-яким майбутнім виконанням потрібні qualified local model/tool/runner profile, дозволені fixture/data rights, owner budget/caps, independent custodian/reviewer, TaskSetManifest із реально підготовленими roots, зафіксований protocol і recovery/stop envelope. Calibration/admission не потребує вже виміряного improvement; **adoption** потребує його після execution. Code/test harness реалізуються тільки після окремого рішення про початок реалізації.

Окремий локальний proof однієї source **або** harness mutation може бути раннім технічним зрізом. Повне приймання RSI019 вимагає принаймні однієї harness-зміни **і** однієї source-зміни, failed candidate та recovery. RSI024 — наступний recursive-method proof. RSI030 — окремий продукт із benefit у двох незалежно побудованих non-game families, людським product signal, evaluator challenge і rollback. Жоден з цих gates не отримує pass від цього документа або public recipes.

Q08 уточнює чинні RSI003/005/007/015/030 та план доказів; IDs і dependencies збережені. W0 не отримує нових prerequisites. Q01–Q08 завершені як обмежені source/design проходи, а не як реалізація або повне читання дев’яти романів. У поточній черзі залишаються Q09 (учасники/реальний досвід) і Q10 (ресурси/profile/порядок реалізації). Автоматичні проходи призупиняються після цієї поставки до зміни цих умов або нового дослідницького питання.
