# Q07: від задуму автора до перевірного поліпшення Core

Дата: 2026-09-10. Статус: E0 / static source audit + proposed contract. Це уточнення чинного портфеля, без нового creator pipeline, backlog IDs або execution authority. Q07 не запускав застосунок, модель, рушій чи дослідження людей. Читання тестових assertions не означає нового test pass. Літературне й PDF coverage цього проходу не змінюється.

## 1. Рішення та межа наявного продукту

У Lokiravia з’єднано локальний шлях **saved brief → versioned scope → agreement → Core team gap assessment**. Це реальні записи й виклики Core. Assessment із порожнім пулом виконавців і нульовим бюджетом не виконує розробку. У цьому entry point немає підключеного шляху game build → PlaySession → feedback → перевірена V2 → restore. Окремий creator/operator prototype чесно показує Play unavailable; його localStorage recovery не є відновленням гри.

Звідси два продуктові рішення. Спершу можна дослідити зрозумілість збереження задуму, компромісів scope та причин недоступності наступного кроку. Доказ «автор самостійно отримав задуману гру» потребує окремо кваліфікованого Play/change/restore шляху. Для Core конкретний предмет поліпшення — як його власний source/harness переносить **погоджені вимоги та їхні версії** в наступний план, перевірку й пояснення. Вдале редагування Cloud UI або однієї сцени саме по собі не доводить самовдосконалення Core.

Збережений original text — доказ походження. Planned fidelity перевіряє, чи reviewed scope зберігає або явно погоджено змінює commitments задуму; вона не доводить реалізації. Realized fidelity перевіряє поведінку exact готової версії. Planning study використовує тільки planned fidelity, end-to-end claim потребує realized behavior evidence. Збережений original не замінює жодної з цих перевірок. Scope може чесно змінитися за рішенням автора; це створює нову версію задачі, а не виправляє заднім числом провал попередньої.

## 2. Джерельна матриця поточного шляху

Перевірені snapshots: Lokiravia `c3093b2edb9ccfafaaa0b68fa3681aec87832122`, Core `472b2a45bf0473b7d66a9067ed58ca5967da385c`. Їхні upstream main на момент проходу: відповідно `3d42cf9606d1100ebe0887306300b5fa4aaaea5e` та `c22954f144702fdf7a3da16cf58176baa345f7c4`. Посилання нижче незмінні; hashes використаних source files і межа аудиту записані в `sources.json`.

| Якір | Що перевірено в source | Що з цього не випливає |
|---|---|---|
| CP-01 · [entry point](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/brief_web.py#L84) | `create_app` створює BriefStore/ScopePlans, підключає team і guidance routes; API повертає `build_enabled=False`, `publish_enabled=False` | Hosted tenant isolation або готовий game build |
| CP-02 · [create/edit](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/game_briefs.py#L203) | Create передає original у Core DRAFT intake; edit зберігає Cloud revision, checksum, command/revision guards і людські уточнення | Подальший parse лише original уже врахував усі edits; create/edit дозволили execution |
| CP-03 · [scope](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/scope_plans.py#L62) | Bounded Godot template, шість leaf tasks, synthetic usage estimate; `write` прив’язує exact brief/scope revision; `execution_ready=False`, agreement без execution authority | Template загально розуміє довільний задум; CHF0 local API assumption є повною ціною; список checks є receipts |
| CP-04 · [navigation](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/static/scope.js#L31), [assessment](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/game_team.py#L78) | Scope → game-team уже підключено; snapshot перевіряється, `WorkforceComposer.compose` викликано з `candidates=()` та `budget=0`; view не дозволяє Start/Stop | Наявна працююча AI-команда або admission реального запуску |
| CP-05 · [prototype](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/prototypes/creator-operator/app.js#L8) | `restore()` читає localStorage draft; `play()` показує missing proof; fetch завантажує synthetic scenarios | Реальний gate service, Feedback record або відновлення SourceVersion/Build/checkpoint |
| CP-06 · [brief UI](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/static/brief.js#L52), [scope UI](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/src/agentfactory_cloud/static/scope.js#L36) | Actual editor має явне збереження й перегляд історичних revisions. Unsaved input може загубитися після browser refresh/close | Prototype autosave поширюється на actual editor; відкриття history вже пересунуло current pointer |
| CP-07 · [domain model](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/docs/domain-model.md#L35), [evidence gates](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/docs/evidence-gates.md#L79) | Run, SourceVersion, Build, PlaySession, Feedback та exact binding вже мають спільну контрактну модель; reference policy вимагає окремих gate evidence | Самі schema/fixtures забезпечують trusted receipt production, qualified engine або виконану дію |

Core має окремий local creator facade та загальні delivery/recovery сервіси. Їх не слід плутати з автоматично підключеними Cloud routes:

| Якір | Реалізований примітив | Межа інтеграції |
|---|---|---|
| CP-08 · [local intake / projection](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/local_games.py#L166), [HTTP caller](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/web.py#L544) | Frozen creation input, stable command, DRAFT mission; detail/project повертає `latest_working=None` та missing playable reason | Це не запущений workflow; local API не видає готової гри |
| CP-09 · [planning](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/game_planning.py#L143), [approval](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/autonomous_backlog_approval.py#L314) | Manual immutable HUMAN revision, source/revision guards; approval — окремий exact version/digest/owner boundary, `APPROVED_NOT_DISPATCHED` | П’ять template tasks Core не є шістьма Cloud scope tasks і не об’єднані автоматично; saved draft не проходить approval або dispatch |
| CP-10 · [child delivery](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/coding_delivery.py#L1099), [Temporal caller](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/orchestration/temporal/activities.py#L1332) | Current scope/fence, terminal provider stages, artifact/commit completion; integration evidence зберігає simulation flag | Generic accepted commit не є engine build/runtime/playtest. Autonomous child використовує bounded authority без per-item Founder gate; стандартний coding review має інший Founder path — це не Play promotion |
| CP-11 · [checkpoint](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/mission_checkpoints.py#L203), [recovery](https://github.com/HappyMiha/Lokvetia-Core/blob/472b2a45bf0473b7d66a9067ed58ca5967da385c/src/agent_factory/local_recovery.py#L573) | Mission/revision/Git identity, control evidence, disposition і окремі epoch/owner/fence guards | Mission recovery не доводить usable old game build або player-state restore; у перевірених local creator routes цього restore caller немає |

Для CP08–11 source-аудит порівняв десять `src/agent_factory` файлів із фактичним consumer pin: `local_games`, `game_planning`, `game_planning_web`, `mission_intake`, `coding_delivery`, `local_recovery`, `mission_checkpoints`, `autonomous_backlog_approval`, `web`, `workforce` (усі `.py`). Git diff цих файлів порожній. Temporal caller не включений у цю заяву про десять файлів. Наявні власники — Core AF-GC007/008/019/020/022/023, AF-AMM intake/approval/recovery та AF048–053; створювати їхні дублікати під назвою RSI не потрібно.

В actual dependency [pyproject.toml:11](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/pyproject.toml#L11) Core pin — `480849f78957bb6b2fd7ab341300d54955aeabb8`. У [intake guide:29](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/docs/game-brief-intake.md#L29) лишився інший `7ec9ff33f1c4e7f2980e4b121d05f3c366acedd1`. Це source/documentation drift; для qualification береться фактичний pin. Q07 не змінює dependency чи старий intake guide. Рівність окремих Core файлів між pin і HEAD не є доказом їх підключення до Cloud app.

Статично прочитані [brief tests](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/tests/test_game_briefs.py#L44), [scope tests](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/tests/test_scope_plans.py#L90), [team tests](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/tests/test_game_team.py#L36) описують persistence, stale guards, idempotent agreement та assessment без assignments/leases/attempts. [Prototype tests](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/tests/test_creator_flows.py#L122) очікують unavailable Play. Ці assertions корисні для визначення меж; у Q07 їх не запускали й не переносили на live game acceptance.

## 3. Тертя → чинний власник → reusable Core capability → приймання

Це acceptance deltas до наявних робіт, не нові задачі чи залежності. Core володіє загальним execution/evidence/experiment механізмом; Lokiravia — creator outcome та своїм UI; pack — причинними й художніми властивостями світу.

| Проблема або невизначеність | Наявний власник | Що має повторно використовуватися / перевірятися |
|---|---|---|
| В оригіналі одне, у reviewed brief/scope — уточнення, а execution читає лише original | AF-CLD-002/007/008/013; Core AF-009/013, RSI025 | Projection бере original digest **і** exact reviewed brief revision/content digest **і** agreed scope revision/policy/commitments. Tenant/Project/SourceVersion mapping явний. Stale або conflicting snapshot зупиняє handoff; human choice не зникає при повторному parse |
| Автор не розуміє, що саме збережено й що виключив малий scope | AF-CLD-004/007/008; RSI018/026 | Saved/unsaved/history різні стани; assumptions/exclusions видимі. Відхилення обох scope альтернатив зберігає початкову ідею. Fidelity перевіряється по погоджених commitments, а не лише checksum оригіналу |
| Agreement і Prepare сприймаються як Start або оплачена reservation | AF-CLD-009/013/019; Core routing/workforce/budgets, RSI008/018 | До реального dispatch потрібні actual qualified route/profile, exact scope, current execution/funding authority і cost envelope. Planned token shares не є reservation. UI відображає missing prerequisite, відмову та відсутність запуску |
| «Ready», task complete або гарна картинка підміняють зіграну версію | AF-CLD-006/010/011/014/015; Core evidence/coding delivery | Authenticated producers → exact SourceVersion/Build/profile receipts → gate decision → actual open/exit receipt. Eligibility відділена від execution і current availability/access. Private Play не чекає Publishable/Sellable |
| Відгук про V1 непомітно застосовано до V2/latest | AF-CLD-017/018; Core versioned context/intake, RSI025/026 | Feedback прив’язаний до фактичних PlaySession/Build і scope, change proposal має явну target source/version та conflict disposition. Нотатка без гри допустима як creator input, але не як playtest evidence. Feedback не є дозволом нового build |
| Restore повертає напис «успішно», але потрібний artifact недоступний | AF-CLD-012/018; Core recovery/checkpoints, RSI029 | Явний target і вид операції; completion після перевіреного usable target receipt. Unknown/failed не стає success. За CLD012 потрібні нова restore/version та audit records із явним target SourceVersion/Build, lineage й activation result; простого rewind pointer недостатньо. Історія, costs і current authority збережені; refresh історії не є artifact restore |
| Поліпшений score приховує втрату свободи NPC, тихої гри або задуму автора | AF-LW-001/013/024/025; RSI007/026/027 | Fidelity/consent/recovery floors поряд із task outcome. Вищий goal score через примус NPC відхиляється. Авторський, гравецький і Core outcomes мають окремий scope claim |
| Leaf tasks закриваються швидше, але автор не отримує потрібного результату | RSI025/026/027, AF-CLD-020 | Opportunity класифікує cause: UI/version binding, Core context, unsupported scope, evaluator чи unknown. Порівнюється точний candidate subject; можна відхилити напрям без переписування старого критерію |

Реальний source/build lifecycle належить CLD012/018. Hosted identity/serving додатково спирається на CLD021/030/031. W0 може використати вручну задану Godot-сцену через qualified Play/checkpoint adapter: універсальна автономна генерація, World023 rollout і World027 offline season не стають його prerequisites.

## 4. Projection і чотири різні відновлення

Перед build/change планом потрібен versioned input envelope з tenant/project, original source, reviewed brief, agreed scope, requirements/commitments, exact source target і evidence profile. Його authority бере чинний service context; сам envelope не створює grant. Downstream receipt відсилає до цього envelope та фактично виконаного artifact. Нова ревізія не переозначує попередні receipts. Restore за CLD012 створює новий version record і audit record, які посилаються на вибрані історичні SourceVersion/Build. Старий Build та його evidence лишаються прив’язаними до початкової SourceVersion. Якщо restore утворює нову SourceVersion, її Build/Playable qualification оформлюється окремо за чинним exact-binding contract; однакові bytes не дозволяють переписати старі receipts на новий ID. Feedback на V1 може бути корисний для V2, але переноситься явним versioned рішенням із перевіркою актуальності; «завжди latest» не є універсальним виправленням.

| Дія | Що відновлює | Необхідний майбутній доказ і межа |
|---|---|---|
| Draft resume / history view | Збережений brief/scope чи перегляд старого запису | Видима revision і saved status; unsaved input не обіцяється збереженим без механізму. View не змінює working artifact |
| Creator version restore | Working SourceVersion/Build selection | Нова version/audit record з exact target SourceVersion/Build, current permission, сумісний usable artifact/profile, завершений restore receipt і перевірка відкриття. Старі artifact receipts зберігають початкову source identity. Попередня failed V2 та її витрати лишаються в історії. Відсутній target потребує явного recovery disposition, а не фіктивного pass |
| World save/load | Domain checkpoint/state/rules/jobs/session | Qualified adapter за [Q05](recovery-contract.md) та [Q02](identity-continuity.md); пізня відповідь старої сесії відкидається на final apply; прийняті effects не дублюються. Source restore сам не обіцяє compatible save migration |
| Core generation rollback | Active source/harness/optimizer binding платформи | Окремий scope grant, coherent activation та recovery receipts. Не стирає витрати, revocations або історичні світові події; World/Cloud restore не має неявного права замінити Core |

Вимога нової version/audit record походить із [чинної AF-CLD-012](https://github.com/HappyMiha/Lokiravia/blob/c3093b2edb9ccfafaaa0b68fa3681aec87832122/docs/backlog.md#L401). Картка не вимагає саме нової SourceVersion для кожного restore; це визначає конкретний version contract, зберігаючи exact source/build identity та активну роботу.

Стара verified гра може лишатися доступною, поки нова будується. Якщо старий target тепер недоступний або несумісний, система правдиво показує цю межу й дозволені варіанти відновлення. «Одна дія» оцінюється через завершений результат і потребу ручного ремонту, а не кількість намальованих кнопок.

## 5. Один наскрізний паперовий прохід

Оригінальний fixture цього документа: автор хоче мирну 2D-сцену біля лавки з двома NPC, незвичним побутовим застосуванням предмета, правом NPC відмовити й можливістю зберегти гру. Це не brief учасника і не книжкова цитата. Погоджені для paper case commitments: мирний шлях; реальна зміна доступного стану; відмова без примусу. NPC logic може бути задана вручну; fixture не стверджує доступність нового agentic runtime в нинішньому scope template.

1. **Brief.** Зберегти задум, явно змінити одне поле, перевірити revision та original provenance. Розрізняти saved і unsaved. Це сценарій майбутньої перевірки actual component, не звіт Q07 про його запуск.
2. **Scope.** Challenger design пропонує два малих способи перевірити задум: лавка/накриття або майстерня/предмет. Обидва пояснюють commitments, exclusions та непідтримувані можливості. Дві альтернативи — пропозиція експерименту, не вже наявна функція. Маркери замість незвичного застосування не оголошуються еквівалентом без рішення автора.
3. **Agreement / handoff.** Погодити точну saved scope revision. Негативна гілка: brief змінено в іншій вкладці → stale agreement відхилено без втрати unsaved input. У current profile результат — погоджений план і missing execution readiness. **Тут проходить межа до майбутнього qualified build/Play.**
4. **V1 / Play.** У майбутньому відкрити exact verified V1 з controls/Exit та session receipt. У paper/prototype версії V1 лише умовна, Play evidence відсутнє. Фізичний стан, consent, explanation і goal outcome оцінюються окремо за Q06.
5. **Feedback / V2 proposal.** Authored feedback fixture: «хочу ясніше бачити причину відмови». Прив’язати його до V1; показати target source, affected commitments, scope/risk і новий estimate. Пропозиція поліпшує пояснення й доступний наступний вибір. Варіант, де NPC завжди погоджується, порушує fidelity floor.
6. **Failed V2 / restore.** Якщо V2 не проходить behavior check або автор її відхиляє, створити новий restore/version та audit record для повернення working selection на явну V1 за current authority, зберігаючи original SourceVersion/Build evidence binding. Потрібні actual target/restore/open receipts; V2, feedback і costs лишаються в історії. Окремий W0 save/load під час pending reply перевіряє Q05; він не підміняється source version restore.

Це відкритий authored walkthrough. Він не є прихованим benchmark, реальним user feedback, виконаною грою чи доказом market demand.

## 6. Як вимірювати поліпшення без підміни задачі

Перший study має два рівні. **Planning study** можливий після qualification поточного local profile: original/edited brief, saved status, scope tradeoffs, agreement і розуміння blocked next step. Немає показника «час до готової гри» для недоступного шляху. **End-to-end creator study** допускається після actual qualified build/Play/feedback/restore на exact baseline/challenger bundles. Пілотні 8–12 авторів у [delivery plan](delivery-plan.md) — план якісного пошуку проблем за участі людей, не power calculation або виконаний експеримент.

До початку обирається одна primary вісь: independent completion або менші зусилля за не гіршої fidelity відповідного рівня. Для planning — planned commitment review; для end-to-end — realized behavior exact build. Planning-only pass не вимагає ще не створеної гри й не отримує claim про її fidelity. Авторська зміна scope зберігається як окреме рішення. Floors і правила incomplete/inconclusive фіксуються до comparison; більша швидкість через непогоджене спрощення відхиляється.

| Вісь | Операційне визначення |
|---|---|
| Task / version | Початковий намір, погоджені commitments, brief/scope revision, baseline/challenger subject і qualified profile. Власні briefs різних людей не називаються ідентичними tasks лише через довжину |
| Completion | Окремо brief saved, scope agreed, build admitted, checked build opened, requested behavior прийнято, change/restore завершено. N/A, blocked, abandoned, failed, unknown і completed не зливаються; scope agreement не є зіграною грою |
| Fidelity | Для кожного commitment: збережено / змінено автором / порушено / unknown, з version-bound evidence та явним planned/realized рівнем. Правдиве збереження original не доводить втілення змісту |
| Допомога та час | Independent vs assisted outcome; що зробив фасилітатор. Active author effort, wall time, queue/build/model wait та interruption окремі; невдалі й незавершені спроби не виключаються задля кращої середньої |
| Recovery | Exact requested target, actual disposition/receipt, час до usable state, ручний ремонт, збереження потрібних records. Зелений UI без target proof — unknown, не success |
| Cost / missingness | Повна дозволена ціна з failed attempts/retries/retrieval/review та unresolved usage. Consent-scoped denominators start/finish/stop/feedback; missing/withdrawn не заповнюється оцінкою, відмова не погіршує доступ |

Baseline і challenger отримують зіставні starting states/права/бюджет. Для якісного within-person study контролюються порядок і навчання; однаковий brief після показу першого результату вже має carryover. Недоступний шлях не перетворюється на незалежне завершення через допомогу фасилітатора. Для статистичного claim потрібні окремі план вибірки та fresh confirmation; цей відкритий fixture до holdout не включається.

## 7. Конкретна гіпотеза самовдосконалення Lokvetia Core

**Гіпотеза, ще не перевірена:** нове покоління власного context-selection source/harness Core рідше використовує stale requirements у change plan, зберігає погоджені commitments і не перевищує прийняті cost/latency/regression floors.

Ланцюг: дозволений creator report → RSI025 opportunity із перевіркою cause → exact Core candidate → RSI003/007 protocol → baseline/challenger execution → external version/behavior evidence та RSI026 product signal → accept/reject/inconclusive → окремий promotion. Якщо cause — Cloud rendering, кандидат належить Cloud; якщо новий world rule — pack. Не можна приписати їхній gain незміненому Core.

Baseline і candidate бачать той самий доступний original/reviewed/scope/version context. Порівняння включає stale/conflicting feedback, недоступний target, погоджену зміну scope та простий manual/reference шлях. Додатковий retrieval, зміна моделі/середовища й review time враховуються як cost або confounder. Автоматичний вибір latest та необмежений контекст не приймаються за правильну стратегію наперед. Новий метод може не допомогти: тоді RSI027 пропонує кращі version explanations чи відмову від гіпотези, зберігаючи початковий verdict.

Цей creator case дає candidate motivation й consumer evidence. Standalone Core030 як і раніше потребує незалежних non-game families; рекурсія O0→O1→O2 — окремого method proof за [Q03](evaluator-succession.md). Q08 має визначити свіжі non-game task families, а не перейменувати цю сцену. Той самий receipt може мати кілька явно зазначених аналітичних ролей, але не рахується кількома незалежними спостереженнями.

## 8. Відкриті статичні controls

Очікування нижче написані, не виконані. P09 посилається на вже визначену W0/Q05 перевірку, не створює новий runtime механізм.

| ID | Контрприклад | Очікуване рішення |
|---|---|---|
| Q07-P01 | Scope швидший завдяки прихованому вилученню мирного незвичного розв’язку | Fidelity floor порушено; explicit нова задача не рятує результат старої |
| Q07-P02 | Фасилітатор сам виправив план, а результат позначено independent | Assisted outcome зберігається окремо; час і допомога видимі |
| Q07-P03 | Original збережено, але людські edits/agreed scope не ввійшли в execution projection | Handoff не прийнято без exact reviewed requirement binding; checksum original недостатній |
| Q07-P04 | Scope agreement або gap assessment запускає оплачуваний build | Відхилити dispatch без окремої current execution/funding authority та qualification |
| Q07-P05 | Play відкрив V1, feedback приписано V2, planner редагує latest | Зберегти played/feedback/target identities; явне conflict/transfer рішення, не тихе перенесення |
| Q07-P06 | V2 краще виконує goal, бо NPC не може відмовити | Порушено commitment/consent floor; score не виправдовує прийняття |
| Q07-P07 | Restore показав success, але exact V1 недоступна | Unknown/failed до usable target proof; показати допустимий recovery disposition |
| Q07-P08 | Restore лише пересунув pointer без нової version/audit record, стер V2 costs/feedback або неявно відкотив world save/Core | Нова restore/version та audit records посилаються на exact target; старі receipts не переприв’язані. Предмет/scope явні, історія/витрати/current authority збережені; інші restore операції окремі |
| Q07-P09 | Old model reply пройшов precheck, після load застосував повторний effect | Чинний Q05 final-apply fence і coherent state/event/job/dedup відхиляють stale apply |
| Q07-P10 | Unfinished сесії вилучено, missing feedback став позитивним, leaf completion названо грою | Denominators/невідомість і stage outcome збережено; product gain не доведено |

Q07 уточнює Core025/026 та World013/025 та evidence boundary World030 у чинних картках. IDs, dependencies, W0 і standalone scope збережені. CLD007/008/015/017/018/020 залишаються власниками creator delivery; цей контракт не переводить їх у done.
