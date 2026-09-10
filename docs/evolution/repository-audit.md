# Аудит Lokvetia Core та Lokiravia перед проєктуванням рекурсивного самовдосконалення

Дата: 9 вересня 2026 року. Це незалежний аналіз вихідного коду, контрактів і беклогів. Репозиторії в цьому аудиті не змінювались; тести продукту, провайдерів, рушіїв, серверів і CI повторно не запускались. Посилання `Core:path:line` означають шлях від кореня Lokvetia-Core, `Lokiravia:path:line` — від кореня Lokiravia. Номер позначає перевірений початок відповідного фрагмента, а не незмінну позицію в майбутніх версіях. Тексти прикладених книжок і статті аналізують інші дослідницькі потоки; цей документ не приписує їм неперевірених висновків.

Q07, 2026-09-10: [додатковий creator audit](creator-evolution.md) простежив actual brief/scope/team callers, Core delivery/recovery primitives і межу до Play/feedback/restore. Це окремий актуалізований source snapshot із точними commits та pin comparison; початковий аудит нижче зберігає свою дату.

Q08, 2026-09-10: [non-game evaluation design](non-game-evaluation.md) використовує шість конкретних Core failure classes із code/tests та історичного readiness gate. Synthetic fixtures, поточні guards і вузькі static limits розділені; нових live defects або виконаних experiments не заявлено.

## 1. Висновок для продуктового рішення

Основа вже значно серйозніша за прототип «агенти розмовляють між собою». Core містить реальні модулі незмінних кандидатів, детермінованих перевірок, незалежної оцінки, пам’яті, контрольованих skills, bounded repair, робочих дерев, політик, sandbox, кваліфікації та відновлення. Їх треба розширити до перевірюваної еволюції **самого продукту Lokvetia Core**. Створювати паралельні Evaluator, Skill Registry, scheduler чи evidence store в Lokiravia було б помилкою власності та інтеграції.

Водночас існування модулів не доводить безперервного самовдосконалення платформи або живого світу. Поточний engineering loop виправляє один кандидат за незмінною ціллю; він не порівнює покоління Core, не веде популяцію версій harness, не керує прихованим набором задач і не вимірює здатність поліпшувати сам процес поліпшення. Lokiravia має діючий локальний редактор ідей/планів та низку hosted-компонентів, але її видима команда наразі навмисно складається з порожніх пулів і не запускає створення гри.

Сильна нова концепція має розрізняти щонайменше три предмети зміни:

1. **Продукт Core:** його UX, планування, harness, routing, tools/skills, orchestration, runtime і власний код — через перевірені покоління та окремі релізні рішення.
2. **Продукт Lokiravia:** процес створення, перевірки, гри, пояснення наслідків, керування версіями та відгуками — споживач тих самих Core-механізмів.
3. **Авторський ігровий світ:** NPC, пам’ять, причинність подій і допустимі зміни правил — доменні контракти/ігрові пакети; вони не отримують повноважень змінювати control plane.

Рекурсивність означає, що успішна зміна допомагає виробляти наступні успішні зміни і цей ефект виміряно. Сам факт повторного запуску агента або накопичення його рефлексій цього не встановлює.

## 2. Зафіксовані версії та назви

| Предмет | Перевірене значення | Висновок |
| --- | --- | --- |
| Core HEAD | `c22954f144702fdf7a3da16cf58176baa345f7c4` | Поточний вихідний код аудиту; остання зміна про незмінні deployment image references, PR49 |
| Lokiravia HEAD | `3d42cf9606d1100ebe0887306300b5fa4aaaea5e` | Поточний вихідний код аудиту; PR22 про deployment images/archive recovery |
| Залежність Lokiravia від Core | `480849f78957bb6b2fd7ab341300d54955aeabb8` | Фактичний pin у `Lokiravia:pyproject.toml:11`; це Core PR47, не поточний HEAD |
| Історичний capability map | Core `d097ac0b04445183c647012a0c92a9d6348135b6`, Cloud `720c79b3530cf2dddfd8b0351094a0763f757a63` | `Lokiravia:docs/upstream-capability-map.md:9`; це інвентаризаційна база карти, а не нинішня package dependency |
| Старий consumer supplement | Core `7ec9ff33f1c4e7f2980e4b121d05f3c366acedd1` | `Lokiravia:docs/upstream-capability-map.md:226`, `docs/game-teams.md:15`, `docs/game-brief-intake.md:29`; описує попередній pin |

**AgentFactory Core → Lokvetia Core; AgentFactory Cloud → Lokiravia, by Lokvetia.** Це два продукти, не чотири. `Core`/`Cloud` зберігаються як архітектурні скорочення. `agent_factory`, `agentfactory_cloud`, `AGENT_FACTORY_*`, `core:`/`cloud:` та AF IDs зберігають сумісність (`Core:README.md:11`; `Lokiravia:README.md:15`, `:53`, `:82`). AgentFactoryBus — технічна назва транспортного механізму, а не альтернативна черга задач.

У новій концепції слід використати сучасні бренди та вказати compatibility IDs один раз. Оновлення документації має явно відокремлювати історичні джерела від актуального consumer pin. Не можна «освіжити» історичну карту підстановкою HEAD і перенести її докази на неперевірену версію.

## 3. Що реально є в Core та як це використати

| Здатність | Джерело і фактична межа | Рішення для RSI |
| --- | --- | --- |
| Спільний application boundary | `src/agent_factory/application.py`; `docs/architecture.md:45` визначає `AgentFactoryService` для CLI/UI над поточними сервісами | Розширити спільний API для evolution-сесій, не запускати CLI з нового веб-обробника й не копіювати transitions |
| Валідація кандидата | `src/agent_factory/validators.py:16` фіксує `test`, `lint`, `type_check`, `build`, `security_scan`; `:25` вимагає всі п’ять shell-free vectors | Зберегти software-контракт; додати версійовані дослідницькі протоколи, не називати статичний тест оцінкою користі чи гумору |
| Незалежна оцінка | `src/agent_factory/evaluation.py:85`: кандидат зв’язано з `codex_worker_results`; `:111` відкидає модель-виробника; `:115` реконструює точну п’ятірку доказів; `:148` забороняє прогалини criteria evidence | Розширити сумісним контрактом суб’єкта оцінювання: harness/config/skill/workflow/product-release. Не обмежувати всю RSI лише Codex diff і не обходити наявну незалежність |
| Незмінний кандидат і PR plan | `src/agent_factory/candidate_changes.py:60`, `:157`; `docs/candidate-changes.md` | Використати кандидата/окремий PR gate для змін власного коду Core; додати parent-generation, experiment і benchmark identity |
| Bounded engineering loop | `src/agent_factory/engineering_loop.py:76`, `:128`, `:185`; одна ціль, один run, історія plans/diffs/results, caps, replan/replace_worker | Використати як внутрішній repair loop. Над ним потрібен експериментальний цикл з baseline/challenger, holdout, cost-quality comparison та generation promotion |
| З’єднаний coding delivery | `src/agent_factory/coding_delivery.py:1683` створює кандидата й evaluation; `:1700` записує прийняту ітерацію після evaluation і створює окремий Founder gate | Зберегти lineage та розділення прийняття кандидата/релізу. Не вважати успішну ітерацію автоматичним deployment Core |
| Typed memory | `src/agent_factory/memory.py:105`, `:148`, `:203`; вісім stores, provenance, scope, validity та invalidation (`docs/typed-memory.md:3`) | Побудувати experience graph як похідні зв’язки між наявними evidence/memory IDs, а не другий memory authority |
| Governed skills | `src/agent_factory/memory.py:266` створює immutable draft; `:299` зберігає tests/security/evaluation; `:342` керує lifecycle | Прив’язати skill review до автентифікованих runner receipts і fixed protocol. Поширення нової skill потребує lineage, consumers, quarantine та відкату |
| Версійовані packs | `src/agent_factory/packs.py:177`, `:272`; install/disable/rollback; `docs/architecture.md:201` | Reuse для opt-in evolution capabilities, evaluator packs та game packs; не трактувати підпис як доказ якості |
| Worktrees і межа запису | `src/agent_factory/worktrees.py`; `docs/architecture.md:205`; `src/agent_factory/sandbox.py:61`, `:255` | Відокремити експериментальний Core від поточного контрольного процесу. Доказані ефекти мають потрапляти до незмінної candidate-версії |
| Sandbox | `src/agent_factory/sandbox.py:154` Bubblewrap; `:197` macOS; `:255` Windows повертає unavailable | Не заявляти загальносистемну Windows-ізоляцію на підставі process group. Кваліфікація native Codex writable profile та general sandbox — різні межі |
| ADR / frame changes | `src/agent_factory/adr.py:100`, `:190`, `:242`, `:299`; `docs/architecture.md:199` | Reuse impact analysis і версії. Агент може запропонувати зміну цілі або функції оцінки; вона створює новий протокол, а не переписує історію результатів |
| Telemetry / budgets | `src/agent_factory/execution_telemetry.py`, `observability.py`; `docs/architecture.md:229` | Додати cost per independently accepted improvement, failure recovery, user outcome і baseline comparison; не оптимізувати кількість змін/комітів |
| Durable mission / Temporal | `src/agent_factory/autonomous_mission.py`, `orchestration/temporal/`; `docs/architecture.md:185`, `:205` | Reuse long-running job recovery. Temporal не є механізмом причинності світу чи NPC gameplay tick |

Важлива технічна межа: low-level `EngineeringLoopService.record_iteration` приймає `accepted_evidence: bool` і непорожні mappings (`engineering_loop.py:132–158`); він сам не є незалежним verifier. У нинішньому coding delivery це значення обґрунтовується попередньою `EvaluationService` (`coding_delivery.py:1687–1705`). Новий RSI consumer має зберегти або посилити цей зв’язок, а не викликати low-level метод із самопроголошеним `True`.

Так само `GovernedSkillService.review` перевіряє структуру, bounds, reviewer role та наявність evidence (`memory.py:299–324`); це корисна lifecycle-база, але сама структура словника не доводить зовнішнього прогону. Перед автономним накопиченням skills потрібні незмінні зовнішні evaluation receipt IDs, producer/reviewer separation та протокол вибірки кейсів.

У прочитаних модулях і пошуку текстових джерел не знайдено окремого generation/evolution manifest, мета-evaluator qualification, population selection або holdout governance. Це точкова межа цього аудиту, а не твердження, що кожна інша деталь репозиторію вичерпно перевірена.

## 4. Що реально є в Lokiravia

| Частина | Наявність та обмеження | Наслідок для плану |
| --- | --- | --- |
| Локальна ідея і Game Brief | `src/agentfactory_cloud/game_briefs.py:140`, `brief_web.py`; `docs/game-brief-intake.md:4` | Reuse оригінального тексту, версій ідей та owner edits; нова концепція світу не повинна губитися при автоматичному стисканні |
| First playable scope | `src/agentfactory_cloud/scope_plans.py:109`; `docs/first-playable-planning.md:31` | Зараз bounded Godot 2D planning, усі результати `execution_ready: false` (`:42`). Окремо зберігати далеку візію й першу перевірну версію |
| Запропонована game team | `src/agentfactory_cloud/game_team.py:1`, `:65`, `:89` | П’ять ролей, нуль бюджету, empty candidates; не називати це працюючою multi-agent студією |
| Identity | `src/agentfactory_cloud/identity.py:57`, `identity_store.py:8`; найновіший Core pin включає shared identity PR47 | Є код і інтеграційні зміни; старі docs про немонтований компонент не можна безумовно переносити на нинішній HEAD. Hosted game acceptance від цього не виникає |
| PostgreSQL product storage | `src/agentfactory_cloud/hosted_store.py:86`; `docs/hosted-storage.md:3`, `:29`, `:49` | Документ містить реальні component qualification claims для PostgreSQL 17.11/psycopg 3.3.5; цей аудит не повторював їх. Cloud зберігає product records, Core залишається execution authority |
| Private objects | `src/agentfactory_cloud/protected_objects.py:27`, `:122`; `docs/protected-objects.md:3`, `:48` | Реальний optional S3/Postgres компонент, initial 1 byte–8 MiB profile. Не ототожнювати його з великими game builds чи готовим CDN/Play |
| Worker admission seam | `src/agentfactory_cloud/worker_gateway.py:58`; `docs/server-workers.md:3` | Read-only inventory + optional authenticated loopback admission не доводять remote execution. Core AF-GC-043 — нинішня межа authority для прийняття worker |
| Engine/target/evidence | `contracts/v1/engine-target-pack.json`, `evidence-policy.json`; `scripts/validate_engine_target_pack.py`, `validate_evidence_gates.py` | Є версійовані контракти та synthetic conformance; живий Godot/Unreal pipeline ними не приймається |
| Unreal/NPC/world design | `docs/unreal-gameplay-plan.md:3`, `:51`, `:87`, `:136` | Є попередній дизайн game-owned actions, memory, world revision, save/load, fallback та proposed catalogue follow-ups. Нове планування повинно уточнити ці follow-ups, не написати той самий runtime вдруге |

Результат, якого бракує продукту, вже сформульований правильно: idea → small real game → exact Play artifact → feedback → verified v2 → restore/source export (`Lokiravia:README.md:34`). Амбіція живого світу має дати цьому циклу нову якість: причинні наслідки, дивні, але закономірні можливості, пам’ять стосунків і подій, гумор з взаємодії механік. Вона не має підмінити перевірку здатності виготовити й зберегти саму гру.

Попередній Unreal-план вже відокремлює slow asynchronous NPC planning від deterministic movement/combat (`docs/unreal-gameplay-plan.md:53`). Action proposal містить actor, world revision, expiry, request ID і проходить validation (`:51`). Згенеровані executable skills потребують development-time validation, а не встановлення з діалогу під час гри (`:131`). Це природна основа для RSI світу, де state evolution і rule/code evolution мають різні транзакції та часові масштаби.

## 5. Поточний беклог: ідентичності та пастки

| Маніфест | Фактично в HEAD | Статус / джерело істини |
| --- | --- | --- |
| `Core:examples/development-backlog.json` | 63 items: 6 epics + 57 tasks `AF-001…AF-057` | Історичні platform requirements, не нові claim IDs |
| `Core:examples/autonomous-mission-backlog.json` | 75 items: 9 epics + 18 stories + 48 tasks `AF-AMM-001…048` | `status:proposed`; stories/epics — контейнери |
| `Core:examples/game-creator-backlog.json` | **47 items: 4 epics + 43 executable** (34 task, 9 bug), `AF-GC-001…043` | Усі `status:proposed`; старі тексти «42» не враховують 043 |
| `Lokiravia:examples/agentfactory-cloud-backlog.json` | 74 items: 7 epics + 67 executable (66 task, 1 research), `AF-CLD-001…067` | Усі `status:proposed`; manifest owns IDs/deps/criteria, `docs/backlog.md` — readable view |

`AF-GC-043` вже зайнятий задачею **Atomically admit qualified workers with scoped attempts and shared capacity**, dependency `AF-GC-039` (`Core:examples/game-creator-backlog.json:2371`). Його не можна використати для нового RSI-пункту. README/старий capability map по 42 items треба позначити як історичний count, а не механічно перевизначати всі старі докази.

Canonical loader (`Core:src/agent_factory/backlog.py:264`) вимагає у schema v2 executable item: priority, assigned_role, dependencies, validation_method, required_components, required_infrastructure, expected_artifacts, definition_of_done; title/description/acceptance_criteria потрібні всім. `:316` перевіряє унікальність IDs, замкнені references і DAG з dependency/parent links.

**Міжрепозиторний reference не можна просто вставити в executable dependencies чужого маніфесту.** Loader вимагає всі referenced items у поточному документі. Existing policy зберігає phase-specific upstream evidence у capability map та planning metadata (`Core:docs/core-cloud-backlog.md:95`). Release owner повинен окремо перевірити pin/evidence; scheduler не перетворює цей metadata на автоматичний бар’єр.

Під час розширення найкраще зберегти всі старі IDs і gates, створити окремі явно запропоновані namespaces/маніфести evolution-вимог та дати traceability до existing AF/GC/CLD. Нові IDs описують проектні вимоги; вони не створюють runtime execution або автоматичне прийняття фіч. Якщо натомість доповнювати canonical manifests, потрібно синхронно оновити readable view, validator expectations і bridge coverage, не забувши вже існуючий 043.

### Gates, які не слід випадково зламати

- Core GC: M0 — `001,002,003,004,005,006,039,041,042`; M1 — `026`; M2 — `031`; M3 — `034,036,037,038` (`examples/game-creator-backlog.json:22`). Це існуючі gates; наявність нового 043 не дає дозволу самовільно змінити їх історичну семантику.
- Cloud M0 — `001…006`; M1 — `020`; M2 — `034`; M3 — `044`; M4 — `051`; M5 — `060`; M6 — `067`.
- `AF-CLD-020` вимагає три реальні Godot games, Play, Windows/source export, feedback/v2/restore, truthfulness/cancellation і owner playtest (`docs/roadmap.md:80`). Це не проходиться гіпотезою гумору чи schema-validation.
- `AF-CLD-054` з Unreal залежить від `052`, а `052` — від `034`; новий desk research може йти раніше, але не означає реалізації Unreal до цих prerequisites.
- `AF-CLD-040 → 043` додавати не можна: уже є `043 → 040`. Private remix перевіряє права свого input; пізніший 043 інтегрує єдину Cloud rights-policy (`docs/upstream-capability-map.md:190`).
- 059 consoles, 062 factory commerce, 066 non-game offering — optional; advertised features мають conditional gates. Нова рекурсивна фіча також повинна мати свій conditional acceptance, а не тихо розширювати meaning of GA (`examples/agentfactory-cloud-backlog.json:78`).

## 6. Мінімальний набір справді нових архітектурних контрактів

Це запропоновані capabilities, а не нові claim IDs чи завершені задачі.

| Новий контракт / розширення | Єдиний власник | Що має довести |
| --- | --- | --- |
| Evolution subject + generation manifest | Core | Точно названо, що змінюється: code/harness/config/skill/workflow; parent version, patch, protocol, authority, evidence і rollback target |
| Experiment protocol / holdout registry | Core | Baseline і challenger мають однакові правила/бюджет; приховані кейси не потрапляють optimizer; preregistered decision rule не переписується після результату |
| Comparison and promotion ledger | Core, поверх evaluation/candidate storage | Приріст не пояснюється більшим бюджетом, зміною benchmark або вибором лише успішних спроб; негативні й inconclusive результати збережені |
| Core-on-Core improvement mission | Core | Незалежний від гри набір задач показує виграш у виконанні реальних platform задач; окремо перевіряє non-game use, CLI/API compatibility, recovery, migrations і UX |
| Meta-evaluator qualification | Core | Кандидат може запропонувати новий evaluator, але чинна незмінна baseline-процедура оцінює його; немає одночасного self-approval обох сторін |
| Experience graph | Core, над memory/evidence | Provenance, hypothesis→experiment→outcome→consumer, contradiction/invalidation propagation; неправильний skill не множиться через shared library |
| Safe promotion / retained generations | Core | Shadow/replay→limited exposure→promote з точним scope; відмова від зміни і повернення до generation N-1 відновлюють сумісний стан |
| Research portfolio / frame-revision proposal | Core | Система обґрунтовує, над чим працювати; окремо фіксує uncertainty, value of information, abandonment та перегляд цілі власником |
| Causal event/world contract | Core optional pack | Immutable event IDs, world revision, actor authority, deterministic application/replay, causality lineage, idempotency, bounded propagation |
| World evolution policy / humour vocabulary | Lokiravia Games + original game pack | Які зміни прийнятні в авторському світі, які факти пам’ятаються, які дивні рішення відкривають нові можливості; не копіювання персонажів/тексту книжок |
| World-rule candidate evaluation | Core generic protocol, domain suite in game pack | Зміна правила не підміняє історію прийнятих подій; seeds/replays/invariants + human playtest оцінюють дієві наслідки і зрозумілість |
| Creator-facing evolution controls | Lokiravia | Гравець/автор розуміє характер змін, може зберегти обрану версію, відкласти або відхилити rule update; інструменти для імпортування/експортування зберігаються |

Особливо важливо: реалізувати **Core-on-Core доказ раніше залежності від повної гри**. Інакше самовдосконалення Core стане лише іншою назвою генерації ігрового контенту. Наприклад, три або більше послідовних поколінь на заздалегідь визначених platform задачах, заморожена зовнішня оцінка, retention несприятливих результатів, одна примусова невдала мутація та recovery drill — достатньо конкретний напрям дизайну експерименту. Кількість поколінь і thresholds ще треба зафіксувати як гіпотезу протоколу; цей аудит не стверджує їх виконання.

Для world proof варто взяти один малий район/спільноту з обмеженою кількістю NPC, двома способами розв’язати проблему, незвичним використанням предмета і наслідком, який проявиться пізніше. Треба показати також дрібну дію без великого наслідку, зірваний довгий план і несподіваний, але причинно пояснюваний результат. Це розрізняє живу причинність і режисерське примусове «кожна дія змінює всесвіт». Семантична непередбачуваність для гравця може співіснувати з відтворюваністю evidence/replay для розробника.

## 7. Evidence, статус і постійна робота

Existing Cloud gate model добре підходить для нової амбіції: **Ready ≠ Playable ≠ Exportable ≠ Publishable ≠ Sellable** (`Lokiravia:docs/evidence-gates.md:14`). Evidence levels — це різні типи, не одна числова драбина; owner acceptance не замінює runtime test (`:39–55`). Нові `Improved`, `Stable across generations`, `World change accepted` мають бути окремими claims із власною сферою застосування, а не новими кольорами старого «Ready».

Core README прямо називає продукт alpha (`:19`) і пояснює, що Ready inventory не сертифікує end-to-end route (`:100`). Старий audit від 5 вересня (`docs/product-audit-2026-09-05.md:3`) зафіксував тодішні баги; наступний capability map визнає repairs 001/003/006 (`Lokiravia:docs/upstream-capability-map.md:13`). Новий backlog не повинен перевідкривати вже виправлений баг лише через стару статтю аудиту. Для reopened work потрібен новий reproducible defect або чіткий incremental acceptance gap.

Оновлена пряма вказівка користувача скасовує попередній підхід координації між трьома ПК для цієї роботи. Тому правила `AGENTS.md` про попередній claim не є prerequisite цієї документаційної поставки; root веде спільну гілку `docs/living-systems-rsi` у двох репозиторіях. Історичні runtime gates та стабільні product IDs залишаються змістом продукту, а не приводом відновлювати скасований користувачем процес.

У постійній роботі слід вести короткі reviewable ітерації: версія гіпотези → джерела → конкретний increment концепції/контракту → перевірка consistency → commit → наступна невизначеність. Справжня scheduled continuation потребує окремо збереженого завдання та активного виконавця; самої обіцянки «працюватиму безперервно» недостатньо.
## 8. Рекомендована структура першої документаційної поставки

1. Спільна візія з чіткими окремими outcomes Core, creator-продукту та живого світу; список фальсифіковуваних обіцянок.
2. Source/evidence register: дев’ять книг, конкретна локальна версія PDF, репозиторні SHA, рівень прочитання/перевірки; запозичується механічне натхнення, а не чужий художній текст.
3. ADR «два продукти, спільна infrastructure evolution, розділені authority planes».
4. Core RSI architecture зі state model, generation protocol, evaluator/holdout contract, cost model, failure/recovery і Core-on-Core proof.
5. Lokiravia world design з original setting, action affordances, causal chains, humour cases, memory і versioned rule evolution; traceability до вже існуючого Unreal/gameplay design.
6. Новий детальний proposed backlog із outcome, hypothesis, source, sole owner, reuse reference, prerequisite contract, acceptance, negative cases, evidence type, budget assumption, artifact і stop criterion. Старі AF/GC/CLD IDs і release semantics збережено.
7. Validation report: canonical schema, унікальність нових IDs, internal DAG, окрема перевірка cross-repo bridge, відсутність cycles/duplicate capabilities, consistency між tables/JSON, source paths і claim/status truthfulness.

У цій поставці не потрібні product code, зовнішній deployment, запуск self-modification або копіювання EPUB/PDF до public Git. Потрібен проект, який уже можна критично рев’ювати, розбивати на експерименти та реалізовувати без втрати його амбіції.
