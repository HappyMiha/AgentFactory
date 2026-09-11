# Що саме випускаємо спочатку

Редакція 2026-09-10 · документаційний план. Жоден описаний тут реліз ще не прийнятий. Позначення C-/L-/W- — планові назви, не нові task IDs або SemVer tags. [Єдиний порядок 280 вимог](implementation-order.md) та [точні набори й dependencies](implementation-order.json) є спільними для обох репозиторіїв.

Перші поставки дають п’ять конкретних результатів: Core виконує контрольовану інженерну задачу; автор зберігає й погоджує задум; workbench порівнює версії Core; creator створює три малі реальні гри з повним циклом змін; окрема жива сцена доводить причинність, свободу дій і пам’ять. Повна самозміна продукту Core і рекурсія його методу йдуть далі власними перевірюваними релізами.

| Пріоритет | Перший результат | Точна карта вимог | Межа приймання |
|---|---|---|---|
| 1 · C-PILOT | Корисний patch зовнішнього проєкту через контрольований Core | 36 legacy tasks у closure | Кваліфікований Windows capability path; не full completion усіх36 |
| 2 · L-PREVIEW | Збережений задум, узгоджений scope, чесний blocked next step | closure CLD009: 001–005,007–009; повний M0 окремо включає006 | Підмножини CLD004/007/008/009; не Play і не M1 |
| 3 · C-WORKBENCH | Перевірюване порівняння версій, ціна й чесний reject | RSI001–011,015; 12 карток | Усі criteria closure та W01–W07; самопросування Core ще немає |
| 4 · L-CREATOR | Три ігри: Play, експорт, feedback, v2, restore | CLD001–020; 20 карток | Повний чинний CLD020 і integration receipts |
| 5 · W-FIRST | Один гравець проживає малу причинну історію | 12 LW +10 RSI; 22 картки | Повний LW030, окремий world profile та actual gameplay |

Пріоритет не створює бар’єру між незалежними роботами. L-CREATOR і W-FIRST споживають спільні build/Play capabilities, але мають різні acceptance gates. Core030 не чекає жодної з цих ігор. Числа closure не підсумовуються як обсяг нового коду: спільні вимоги враховуються один раз у 280-item view.

## Фактична основа та незакрита кваліфікація

Статичний baseline: Core `38280160e8cabfcb64f325cd5c1c5f8aa6f67ab7`, Lokiravia `24ecb1e931d7df6c90900bb31e08a1e5faa13ce1`; вони містять попередні source-аудити й очищення джерел. Snapshot canonical manifests зафіксовано в JSON. Під час цього проходу продуктові програми, моделі та рушії не запускались.

| Наявне | Як використовуємо | Що ще не доведено |
|---|---|---|
| Core durable execution, candidate/worktree/validator, approvals, routing, cost/recovery primitives | Інспекція exact implementation, повторна qualification потрібного path, доповнення прогалин під чинними AF/GC IDs | Історичні claims про57 реалізованих AF tasks не є current live GA; Windows writable blocker наведено нижче |
| Autonomous Mission foundations001–019 та пізніші часткові seams | Перевикористання lifecycle/authority/evidence components | Не всі48 AMM requirements прийняті; full once-approved autonomy має окрему поставку |
| Lokiravia saved brief→scope→agreement→Core team gap assessment | Завершення й qualification наявного editor; без дублювання Core planner/runtime | Actual dispatch/Build/Play/feedback/usable restore ще не доведені; unsaved persistence gap лишається явним |
| 35 RSI +30 LW proposed design cards | Реалізація за exact dependencies, staged experiments і gates | Документація й synthetic checks не доводять самовдосконалення або живу гру |

Package Lokiravia фактично pin-ить Core `480849f78957bb6b2fd7ab341300d54955aeabb8`. Це identity залежності, не qualification новішої Core branch. Перед інтеграцією CLD003 звіряє потрібні capabilities із цим pin; майбутня зміна pin потребує окремого consumer evidence. Застаріле installation prose у game-brief-intake виправлено; історичні capability maps не переписано без нового аудиту.

## Що власник отримує по черзі

| Реліз | Видимий результат | Що має стати доведеним |
|---|---|---|
| **C-PILOT** | «Я описую невелику зміну програми й отримую перевірений результат, пояснення та контроль». | Core виконує реальну non-game роботу у конкретному підтримуваному середовищі; помилка не ховається за красивим звітом. |
| **C-WORKBENCH** | «Я можу перевірити, чи одна версія Core краща за іншу, і побачити ціну, невдачі та невизначеність». | Є відтворюваний експеримент і незалежні докази; результатом може бути відмова від зміни. |
| **C-SELF** | «Core знайшов, перевірив і зберіг корисні зміни власного коду та способу роботи». | Повний AF-RSI-019: own-source і own-harness, реальні tools/providers, measured benefit, failed candidate та recovery. |
| **C-METHOD** | «Core поліпшує також спосіб, яким шукає наступне поліпшення». | Повний AF-RSI-024: метод O1 реально бере участь у створенні O2, користь не пояснюється підміною evaluator. |
| **C-RSI** | «Самовдосконалення Core стало перевіреною властивістю окремого продукту». | Повний AF-RSI-030: користь на двох незалежних non-game сім'ях, власний source/harness/optimizer, потреби користувачів і довга надійність. |

Lokiravia, playable world та model training не є передумовами цих п'яти результатів. Core може використовувати дозволеного AI provider, не залежачи від продукту Lokiravia; «standalone» не означає автоматичний local-only inference.

## C-PILOT — контрольована engineering робота на Windows

**Цільове середовище:** Windows, один локальний оператор, одна Core instance/SQLite authority, локальний Git/Python проєкт, встановлені й явно кваліфіковані tools, bounded writable worker і незалежний reviewer. Exact Windows/Python/Core/Hermes/Codex/model/profile versions, resources і sandbox записуються в release evidence. Це target, а не вже підтримувана комбінація.

**Початковий обсяг:** невелика зміна зовнішнього fixture repo: наприклад, виправити поведінку утиліти нормалізації даних за погодженим правилом. Результат — конкретний candidate commit, застосовний output, primary checks, незалежний review та окреме рішення власника. Стандартний guarded engineering path; без самостійного встановлення програм, auto-merge, широкої once-approved Autonomous Mission Mode або гри.

### Два записи, які не можна об'єднати в один done

**Task closure —36 IDs:** AF001–013,017,020,044–046,048–049,051–053,055–057; GC001–006,039,041–043. Це повне hard closure25 обраних seeds:26 AF +10 GC. Воно не містить AF032–035 GA gates, AMM tasks, game acceptance gates або RSI tasks. Повний список, транзитивні prerequisites і порядок містить [спільний JSON](implementation-order.json), release C-PILOT.

**Release capability acceptance:** для кожного використаного компонента — exact criterion/capability, source commit, фактичний profile, issuer, receipt, outcome та незакритий залишок. Це приймання визначеного продуктового шляху, а не автоматичне повторне приймання всіх36 широких tasks. Статуси tasks не змінюються лише тому, що pilot працює. Якщо майбутній план прямо вимагає повного completion36 tasks, потрібна повна coverage їхніх criteria та prerequisites.

Наприклад, AF049 має hard dependency **AF045 Hermes ACP**. Чинний MVP передбачає scoped Hermes session, що делегує Codex (`docs/development-roadmap.md:53,60–67`). Для C-PILOT плануємо саме цей шлях. Direct CLI-only experiment можна окремо кваліфікувати, але він не закриває AF045 і не дає права оголосити весь closure прийнятим.

### Поточний Windows blocker

`src/agent_factory/sandbox.py:255–261` за замовчуванням повертає Windows `UnavailableSandboxBackend`; `411–426` відхиляє execution до запуску. `validators.py:127–134` використовує цей sandbox. `codex_worker.py:25–36` окремо задає native `workspace-write` profile — його наявність **не** кваліфікує автоматично validator/Hermes/whole-process sandbox.

Тому перша робота C-PILOT — кваліфікувати потрібний Windows backend/adapter через existing AF017/044/045/049/052 responsibilities і довести complete path. Заборонено перетворити unavailable у ready, вимкнути enforcement або пропустити validator заради демонстрації. Якщо придатного Windows path немає, C-PILOT має стан blocked/not-qualified; зміна target environment є окремим явним product decision, а не прихованою підміною.

### Точні сценарії приймання

Це case recipes, які ще треба матеріалізувати та виконати. Кожен case має exact fixture/version, очікуваний oracle, дозволені effects, ліміти та evidence issuer до запуску. Номери P01–P09 — локальні назви сценаріїв, не backlog IDs.

| Case | Дія власника / контрольована подія | Потрібний результат |
|---|---|---|
| P01 · допуск середовища | Почати з fresh named Windows profile, по черзі забрати потрібний tool, змінити model/profile, прострочити receipt, повернути справний стан. | Missing/stale/wrong-profile не запускають writable роботу. Після explicit actual-state check готовність доведена для потрібного route. Simulated result не стає live qualification. |
| P02 · точні вимоги й approval | Зберегти brief, погодити exact version, змінити одне суттєве правило; окремо закрити confirmation dialog та повторити стару команду. | Нове джерело видно, старий grant не дає права на інший scope; dismiss не є approval; replay не дублює роботу. Незмінені вимоги й незбережена чернетка не губляться. |
| P03 · реальний корисний patch | Виконати bounded change у зовнішньому repository через qualified Hermes→Codex path. | Artifact має exact base/head/diff. Незалежний behavior oracle підтверджує requested результат; усі п'ять declared software validator categories мають valid receipts. Product completion не дорівнює «Core unit tests passed». |
| P04 · незалежний verdict | Спробувати producer self-review, подати неповний validator set або criterion без primary evidence; потім використати qualified reviewer. | Невалідний candidate відхилено до model verdict. Valid review фіксує criterion/rubric/version/evidence; release decision власника окремий. Інша назва тієї самої effective model не обходить independence. |
| P05 · помилка та bounded repair | Незалежний verifier знаходить відому помилку candidate; однаковий failure повторюється; інший case вичерпує accepted budget. | Bounded repair/replan/replacement поводяться за policy; caps реально зупиняють роботу. У ledger лишаються failures, витрати та причина завершення. Постійна відмова не зараховується як корисний patch. |
| P06 · Stop та невідомий запуск | Після admitted operation дати Stop; окремо втратити відповідь runtime start і відновити Core. | Немає нового неавторизованого admission/повторного start. Already admitted effect має explicit outstanding/completed/unknown disposition. Capacity не звільняється лише через timeout; точний host stop evidence потрібен для reuse. |
| P07 · restart і candidate integrity | Зупинити Core після commit до candidate record; replay тієї самої logical attempt; окремо підмінити committed bytes при схожих metadata. | Немає duplicate candidate/effect; accepted bytes повторно зв'язані з validated snapshot або recovery блокується. Одного збігу message/files чи count=1 недостатньо. Це residual existing AF051/057 і RSI004, а не новий candidate engine. |
| P08 · sandbox і stale authority | Спробувати запис поза worktree, недозволений command/network effect, діяти старим fence після restart/lease replacement. | Заборона enforced поза prompt; primary denial evidence збережено. Native Codex та validator/Hermes paths перевіряються за своїми реальними boundaries. |
| P09 · видача й відновлення | Власник читає результат, відхиляє або приймає candidate, відновлює попередній usable state на supported boundary. | Видимі exact output, перевірки, limits, costs і наступна дія. Rejected candidate не стає чинним; PR лишається gated, auto-merge немає. Відновлення перевіряє artifacts/audit та не відроджує стару authority. |

Для проходження C-PILOT потрібні усі mandatory applicable cases, непротирічні receipts і owner acceptance саме запропонованого Windows scope. Coverage crash/sandbox boundaries визначають до запуску; один P07 не є proof усіх AF057 boundaries. No-go також є коректним результатом кваліфікації, але не релізом.

### Reuse, потрібна зміна та куди йде решта вимог

| Existing основа | Delta до першої поставки | Залишок, який pilot не закриває автоматично |
|---|---|---|
| AF017/044/045/049/052 | Працездатний enforced Windows chain з перевіреним Hermes resume/cancel і Codex/validator scope. | Інші OS/runtime profiles; AF047 full runtime matrix/fallback, AF050 alternative worker. AF045 лишається prerequisite, а не optional прикрасою. |
| AF009/013; GC003/004/005 | Exact source/approval/replay через реальний operator path. | Повні Blueprint amendment cases лишаються AF013; broader browser launch/accessibility — AF036–043; game-specific intake fidelity — відповідні GC/consumer criteria. |
| AF020/051/052/053 | Candidate byte binding, primary-evidence closure, effective reviewer, owner packet. | General non-code evaluator — RSI006; repeated generation evidence — RSI004; full game delivery не доведено. |
| AF056/057; GC043 | Named budget, admission, host stop, local restart boundaries та повний failure ledger. | Непокриті AF057 boundaries; remote/multi-tenant host qualification; generation promotion/soak — RSI017/029. |
| GC001/002/006/039/041/042 | Current source/profile/roles/auth та truthful readiness в intended flow. | GC001 решта multi-OS/Python matrix або explicit justified restriction; GC041/042 непокриті live stages/roles; full AMM qualification — AMM047/048. |
| AF032/033/034/035 | Можна використати структуру evidence/runbooks, не створюючи другу систему. | NFR/72-hour soak/3-provider reference mission/GA handover gates лишаються окремими і не вважаються пройденими через малий pilot. |

## C-WORKBENCH — інструмент чесного порівняння

**Видимий результат:** власник задає bounded hypothesis, подає exact incumbent/challenger subjects, бачить порівняння, повну ціну, missing/failed evidence та accept/reject/inconclusive recommendation. Система ще не замінює чинний Core сама. Вхідні candidates можуть бути підготовлені й окремо авторизовані; автоматичне own-source/harness generation і activation — наступний C-SELF.

**Нові IDs:** AF-RSI-001–011 плюс015. Це exact closure015 з12 карток; усі dependencies незмінні. Спочатку authority/generation/protocol/lineage001–004; далі custody005, adapters006, budget008; comparator007 після005/006; arena009→candidate plan010→paired runner011; незалежні tasks/oracles015. Design research015 може йти раніше, але його completion потребує своїх dependencies.

**Приймання W01–W07:**

| Case | Доказ, який має з'явитися |
|---|---|
| W01 · protocol freeze | Exact hypothesis, primary axes, floors, budgets, stop/analysis rules, selected profiles і incumbent/challenger manifests записані до output. Зміна threshold після score створює інший protocol, не «виправлений pass». |
| W02 · два різні work products | F1 — usable external software patch; F2 — requirements-to-decision packet з незалежного corpus/root. F2 не є просто planning stage того самого F1. Для кожного — свій oracle й outcome semantics; usability claim потребує належного незалежного review. |
| W03 · evidence adapters | П'ять existing software validators збережені для F1; F2 має typed document evidence adapter. Неправильний subject/version, self-review, forged/неповний receipt не приймаються; модельний список URL не є primary evidence. |
| W04 · рівне порівняння | Paired starting inputs/permissions/resource envelope однакові, а рішення agent можуть різнитись. Planned scripted actions перевіряють лише conformance, не planner gain. Stochastic coupling та retries визначені наперед. |
| W05 · чесний no-gain | На independently defined no-gain/degraded candidate система видає reject/inconclusive за protocol; не змінює task split, labels, baseline чи denominators до потрібного score. Відсутній результат зберігається, а не стає нулем cost. |
| W06 · custody й повна ціна | Public recipes/tests позначено D; adaptive selection S окремо від final F. Усі queries, candidates, failures/retries/costs/exposures збережено. Перейменований public fixture не стає fresh holdout. |
| W07 · interruption | Restart відновлює exact run/protocol/evidence identities, не подвоює charge/effect/decision. Пізній conflicting receipt створює challenge/amendment, не переписує accepted history. Optimizer не змінює current authority/evaluator під час власної перевірки. |

**Exit:** Windows arena та F1/F2 adapters кваліфіковані, comparison replayable, failures/unknown чесно видимі. Workbench може бути корисним і без позитивного gain. Це ще не019: немає claim, що Core уже сам знайшов, зберіг та просунув власні source/harness зміни.

## Наступні три релізи

**C-SELF:** додати012/013/014/016/017/018/019; closure019 = усі001–019. Приймаються щонайменше одна own-source та одна own-harness зміна через baseline→proposal→run→comparison→decision→retained generation. Обов'язкові failed candidate, current-authority recovery, state/API compatibility, visible owner decision та measured benefit. Source-only demo не закриває019; зміна чинного supervisor самим candidate заборонена.

**C-METHOD:** додати020–024 після їхніх dependencies; closure024 =001–024. Окремо кваліфікуються evaluator succession і optimizer comparisons. O0 створює O1, прийнятий O1 реально бере участь у створенні O2; downstream benefit підтверджено незалежно від evaluator drift і додаткового search budget. Одна вдала зміна коду не доводить кращого методу.

**C-RSI:** додати025–030 за DAG; product-signal025/026 можна розвивати одразу після012/015/018, не чекаючи завершення всіх робіт C4. Gate030 потребує користі в обох наперед визначених non-game families, власного source/harness/optimizer, реального owner outcome, challenge/failure/rollback/soak, supported envelope та handover. Якщо evidence не підтверджує gain, gate не пройдено.031–034 і035 не додаються до цього closure.


## L-PREVIEW — зберегти задум і погодити малий план

**Продуктова обіцянка:** автор зберігає власний задум, бачить окремо припущення та deferred roadmap, редагує короткий brief і scope, погоджує exact saved revision та розуміє, що може зробити далі. Це локальний internal preview для одного довіреного оператора, а не hosted account service.

**Scope:** original українською або англійською, immutable saved history, focused clarification, edited GameBrief, versioned first-playable scope, estimate з позначеним походженням, stale/conflict handling, scope agreement, team gap assessment. Наявний template — одна Godot 2D кімната, один гравець і bounded goal. Вибір непідтримуваного engine зберігає задум, але не створює execution readiness.

**Reuse:** CLD007/008 реалізують реальний local шлях `saved brief → scope → agreement`; частини CLD004/009 дають навігацію та gap assessment. `game_briefs.py:203–308` зберігає original, revisions та окремі AI suggestion attempts; `scope_plans.py:152–203` зв’язує brief digest, plan revision та agreement; `game_team.py:42–98` створює Core composition assessment. Повторно писати ці компоненти не потрібно.

**Acceptance цієї вузької поставки:**

- Автор може зберегти original і людські зміни, відкрити саме збережену revision після перезапуску та відрізнити її від незбереженого тексту.
- Зміна brief робить старий scope stale. Conflicting edits не перезаписують одну одну мовчки. Scope agreement прив’язаний до exact versions, має `execution_authority=false` і не витрачає бюджет.
- Planned fidelity перевіряє збереження або явно погоджену зміну вимог. Original checksum не замінює змістовного review; planned fidelity не видається за поведінку ще не створеної гри.
- Status і наступний крок відповідають actual readiness: `execution_ready=false`, відсутня verified playable version, gap assessment не Start. Template estimate не називається фактичною ціною обраного execution route.
- Current local access/profile та relevant UI behavior мають власне qualification evidence; independent review і owner decision прямо називають обмежений scope.

**Незакритий delta:** actual editor має explicit save, але unsaved input може загубитися після refresh/close (`docs/first-playable-planning.md:21–24`). Prototype localStorage не доводить autosave actual editor. Повна CLD004 AC про draft persistence лишається відкритою до реалізації й перевірки; warning не зараховується як її виконання. Потрібні source-to-plan fidelity/usability evidence та точний downstream requirements bridge.

**Gate і виключення:** L-PREVIEW — scoped component acceptance record щодо частин CLD004/007/008/009, не новий milestone і не pass M0/M1 чи повне приймання всіх цих карток. Build/Play/Feedback/v2/restore/export/publish, actual AI team execution, hosted tenants і minors pilot не входять. Для наявного preview немає показника «час до готової гри». Повне M0, коли його приймають, як і раніше потребує всіх CLD001–006.

## L-CREATOR — три справжні гри з повним циклом змін

**Продуктова обіцянка:** автор отримує малу гру, грає exact перевірену версію, описує зміну, отримує перевірену v2 і може повернути working selection на v1 зі збереженням історії.

**Scope і canonical gate:** це чинний M1, entry M0; gate **AF-CLD-020**. Повне транзитивне CLD closure — **001–020**, рівно 20 work items. Reference set: **platformer, top-down collector, puzzle**. Godot/GDScript 2D; qualified Web target, clean supported Windows run та source reopening поза Lokiravia. Один complete game journey — ранній integration checkpoint, а не pass трьох required games.

**Implementation order:**

1. CLD001 → {002,003} → {004,005,006}; звірити наявні contract artifacts і missing acceptance, qualified upstream reference через 003.
2. CLD007→008; паралельно CLD012 після 002/006. Після 005/008 — CLD009 і 010, потім 011.
3. CLD013 і 014; далі 015/016/019 за їхніми dependency branches. Budget/sandbox/cancel foundations потрібні до першого actual dispatch, хоча повне acceptance019 перевіряє інтегрований runtime пізніше.
4. CLD017→018→020. Повторити всю процедуру на всіх трьох іграх, а не підмінити diverse outputs трьома однаковими starter templates.

**Acceptance:** exact reviewed requirements потрапили в immutable authorized task context; qualified worker справді змінив source; independent effective reviewer identity збережена при fallback/retry; exact source/build має engine checks, actual runtime і graphical Play evidence. Feedback посилається на зіграну Build/PlaySession, proposal показує target, affected requirements, scope/risk і додаткову ціну до work authorization. Нова SourceVersion/Build перевіряє requested behavior. Failed v2 не забирає Play v1. Restore створює новий generic version/restore та audit record, зберігає original SourceVersion/Build evidence binding і завершується usable target receipt. Якщо конкретний restore створює нову SourceVersion, потрібна її окрема qualification; old receipt не переприв’язується до нового subject.

Повний 020 також потребує clean Windows package run, source archive reopening, failure/restart/Stop і budget reconciliation, private fork власної або явно remixable гри, denied no-remix case, unchanged original, attribution/lineage, independent review та owner gameplay. Публічний Remix тут не відкривається. Правильний digest без фактичного Play не завершує user journey.

**Reuse і delta:** current early editor та Core foundations споживаються через exact pin. Ще потрібні reviewed scope→execution projection, real dispatch, engine evidence producers, build registry/gate consumer, PlaySession, Feedback/change workflow, v2 та usable restore. Окремий prototype чесно блокує Play; history GET не restore. CLD role/team assessment має `candidates=()`, `budget=0`, `can_start=false`, `can_stop=false` і не доводить виконання.

**Виключення:** hosted private alpha CLD034, public publishing/discovery, public Remix, payments, нові engines/stores, multiplayer, arbitrary-game generation і full RSI не prerequisites M1. Проте мінімальні права, секрети, sandbox, незалежний review та bounded budget для actual local execution не відкладаються до M2. Internal qualification — adults/synthetic data; any minor pilot має окремі CLD004/021 gates.

## W-FIRST — перший доказ живої сцени

**Продуктова обіцянка:** за 20–30 хвилин один гравець виконує незвичну дію з реальним локальним ефектом, спостерігає короткий причинний розвиток або чесне згасання, стикається з видимою причиною невдалого плану й повертається через save/load у ту саму узгоджену історію.

**Scope і canonical gate:** чинний **AF-LW-030 / W0**. Лавка або інше мале місце, два NPC з власними намірами, кілька предметів, bounded vocabulary дій, causal traces, один supported local runtime profile. Сцену й властивості дозволено задати вручну; actual state transitions потрібні навіть тоді, коли generation немає.

Exact evolution closure — **22 картки**:

- 12 World: **LW001,002,003,004,005,008,009,010,011,012,014,030**.
- 10 Core: **RSI001,002,003,004,006,008,009,031,032,033**.

Core005/007/019/024/030/034/035 не входять до цього closure. Existing CLD010/011/012/015 refs означають reuse потрібних accepted starter/adapter/checkpoint/Play capabilities, не вже виконані завдання й не автоматичну вимогу чекати повний CLD020. W-FIRST користується одним shared build/Play pipeline; власний незалежний registry не створюється.

**Окремий W-FIRST profile обов’язковий для чесного scope:** чинний `small-2d-scope-v1` виключає `new agentic runtime systems` (`docs/first-playable-planning.md:33–42`). Текстове редагування exclusion не робить його W-FIRST generator. Вузький game pack/domain profile має свою qualification; пізніша integration в CLD008/LW013 може зберегти той самий creator UI та authority boundaries.

**Acceptance:**

- Реальна незапланована дія використовує перевірні властивості предмета. За належних місцевих умов виникають 2–3 переходи; paired/control cases показують no-cascade, інший розклад, NPC refusal і доречну альтернативну дію без hidden author fiat.
- Багатокроковий план у C09 провалюється через відому часову умову; причина доступна гравцеві, наступний вибір залишається. Seasonal C10 не потрібний.
- C08 half-action save зберігає progress/reservations: незавершене накриття ще не захищає лавку, cover/wear з’являються лише на completion. У W0 pause clock не рухається.
- Checkpoint зберігає world/rule/schema identity, committed revision, витрати, NPC knowledge та stable accepted jobs. Load створює новий session epoch. Old pending reply і окремо `precheck → load → old apply` відхиляються на authoritative final commit. Effect/resource/event/job-completion/dedup узгоджені; немає double reward через звичайний restart.
- Fact, belief та accepted obligation відрізняються. Відмова NPC не переписується в приховане погодження; UI не вигадує зміну, нагороду чи домовленість для заповнення історії.
- Observer фіксує, чи людина зрозуміла причину, побачила власний вибір та пережила доречний комічний момент. Це якісний session evidence; proposed 12-person pilot не стає прихованим minimum AF-LW-030 або статистичним proof.
- Core031/032/033 та consumer receipts відповідають actual supported profile: no LLM wait on frame, bounded async/outage behavior, correct late-reply/cost disposition. Synthetic conformance не називається full runtime qualification.

**Виключення:** весь район E01–E08, seasonal bridge, crafting/economy World006/007, лабораторія 013, інституції/довгі традиції, autonomous rule/ontology evolution, production canary/migration, always-on world, multiplayer та весь standalone Core gate. W-FIRST бере local checkpoint/final-apply/job/dedup зріз recovery, зокрема застосовні RC02/13/15; повний W3 rollout не prerequisite.

Manual W-FIRST не отримує CLD020 acceptance автоматично. Для зарахування до одного з трьох reference outputs ця сама гра повинна відповідати потрібному genre та пройти повну idea→worker change→Play→export→feedback→v2/restore процедуру. І навпаки, три звичайні creator games не доводять W-FIRST causal/identity/save semantics.

## Дев’ять спільних integration seams

Ролі нижче називають implementation/acceptance ownership, не людей чи пристрої. Одна reusable Core capability має одну реалізацію; Lokiravia приймає її product integration.

| Seam | Existing owner/IDs | Exact prerequisite → evidence; current delta |
|---|---|---|
| I-01. Reviewed brief/scope → execution | Cloud product-engineer/game-producer: CLD002/007/008/013; Core intake/approval; later LW013 | Original + reviewed revision/digest + agreed scope/policy + principal/project → immutable authorized task context. Current human edits/six-task Cloud plan ще не автоматичний execution bridge; original-only parse втрачає зміст |
| I-02. Team assessment → actual work | Core route/runtime; Cloud agent-systems/runtime: CLD009/013/019 | Qualified coding/reviewer identities, lease, scope, real caps → intent-before-dispatch, actual diff/commit/review/usage і reconciled retry. Current gap assessment не Start |
| I-03. Pack/toolchain → checked build | Core optional Godot/target pack; Cloud godot-engineer/QA: CLD005/010/011/014 через 003 | Exact versions, licenses, sandbox/profile → probe/import/build/validator/runtime receipts, good/broken fixture outcomes і process Stop. Contracts не замінюють actual producer |
| I-04. Source/Build → Play | Core worktree/delivery primitives; Cloud backend/fullstack: CLD006/012/015 | Immutable source/commit/build binding, current gate/access/availability → actual PlaySession/open/run/exit/crash. Current packaged creator не має connected launch path |
| I-05. Play feedback → verified v2 | Cloud product/workflow: CLD017/018; Core execution consumer | Exact played version → scoped reviewed change/extra budget decision → new SourceVersion/Build з requested behavior. No-play note не gameplay evidence; feedback не authority |
| I-06. Working version → restore | Cloud backend/workflow: CLD012/018; Core recovery/authority | Explicit target/current grant → new generic restore/version+audit, atomic selection, usable target; original receipt bindings незмінні. History/localStorage не restore; new SourceVersion qualification лише якщо вона створена |
| I-07. Intent → world state | Core031/033; World runtime/game designer: LW002/005/008/009/011/030 | Typed proposal/epoch/revision/expiry/permission → authoritative domain delta/event або rejection. Provider text не канон; потрібні bounded runtime/outage/fallback receipts |
| I-08. State → checkpoint/replay/load | Core032; World save/runtime/QA: LW002/012/030 | Coherent state/rules/schema/jobs/watermark → new session epoch і final commit fence/dedup; replay recorded inputs. Game save, source restore і Core rollback різні objects |
| I-09. Evidence → release decision | Independent QA/reviewer + owner; CLD020 і LW030 окремо | Exact criterion-linked primary receipts + relevant real human experience → scoped decision. Structural/runtime/human/owner evidence не взаємозамінні |

IntegrationReceipt з `platform-world-contract.md:72` розрізняє `core_contract_conformance`, `domain_runtime_integration` та `packaged_game_integration`. Exact Core/consumer revisions, contract/pack/runtime/target versions, suite/runner і supported envelope потрібні для відповідного claim; player-package hash не вигадується для neutral fixture. Ready/Playable/Exportable/Publishable/Sellable залишаються окремими gates; eligibility не є receipt фактично виконаної дії.

## Всі пізні CLD/LW bands і їхні gates

| Band | IDs | Entry / exit та межа |
|---|---|---|
| M0 foundation | CLD001–006 | Всі шість прийняті; L-PREVIEW не закриває їх автоматично |
| M1 / L-CREATOR | CLD007–020 | Entry M0; exit020, closure001–020 |
| M2 private hosted alpha | CLD021–034 | Entry M1; exit034, closure001–034. Accounts/state/objects, remote jobs/isolation, credentials/quotas, hosted portal/protected Play/export і ops recovery |
| M3 public creator beta/Remix | CLD035–044 | Entry M2; exit044. Releases/visibility, profiles, game pages, Discover/share, public Remix, metrics, moderation і asset rights. Marketplace не відкритий |
| M4 marketplace | CLD045–051 | Entry M3; exit051. Seller eligibility, listings, checkout, entitlement, ledger/payouts, refund/fraud qualification |
| M5 engines/targets | CLD052–060 | Entry M2 + feature prerequisites; exit060 потребує 052–058. SDK, Unity, Unreal, Android, Apple, Steam/PC packaging.059 console optional; no-go required engine не pass повного 060 |
| M6 defined GA/expansion | CLD061–067 | Entry M3 + accepted scope; exit067 requires034/044/061/063/064/065.062 factory commerce і 066 non-game optional. Templates/API/model budgets/hybrid qualification — власні capabilities |
| W0 / W-FIRST | LW001–005,008–012,014,030 | Gate030 із exact 22-card evolution closure та applicable existing integration receipts |
| W1 deeper scene/relationships | LW006,007,013,015,016,017,018 | Craft/error alternatives, author laboratory, contextual comic choice, shared-history objects, NPC collaboration, institutions; dependency-qualified delivery. Окремого загального W1 acceptance ID у manifest немає |
| W2 local social change | LW019,020,021,022 | Traditions, negotiations, rebuilding, rumors/correction; Core034 applicable. Не означає multiplayer |
| W3 evolved district | LW023–028 | Rule publication/migration, game improvement campaign, human experience, abuse/recovery, return to world; exit028 через 025/026/027. Core closure001–011,014–017,031–034; не весь Core030 |
| W4 optional human co-operation | LW029 | Dependencies017/025/028; окреме research/authority/network qualification, не initial multiplayer release |

M6 conditional gates зберігаються: paid marketplace→051; expanded engine/store support→060; factory commerce→051+062; non-game offering→066; any console support→059. Any minor pilot→004+021; any public Remix→040+042+043+044. Вужчий реліз не pass ширшого legacy gate без явної versioned scope revision.

**Послідовність W-FIRST→depth — рекомендована release policy**, не існуючий dependency edge: LW030 не є ancestor LW028 у чинному DAG. Пізні implementation cards можуть готуватися за власними prerequisites; broad experience acceptance не варто рекламувати до вузького proof. Нових edges ця редакція не додає. L-CREATOR та W-FIRST можуть рухатися паралельно після відповідних спільних foundations; жоден не очікує full recursive-method acceptance Core024/030.


## Реєстр capability prerequisites

Ці записи є integration obligations, не новими backlog tasks або прихованими hard edges. Їхні власники — чинні вимоги. Кожен release із посиланням у JSON має отримати applicable exact receipts до приймання. Вони не замінюють canonical task prerequisites.

| ID | Потрібна capability / власник | Межа |
|---|---|---|
| I-CORE | Enforced Windows execution, approvals, exact context/candidate, independent review, validators, budget/Stop/recovery; AF017/044/045/049/051–053/055–057, GC001–006/039/041–043 | C-PILOT P01–P09; для workbench — додатково exact evaluator/arena profiles. Task closure36 і broader residuals збережені |
| I-REUSE | Criterion-level qualification спожитих legacy capabilities до відповідного RSI/LW consumer | Матриця нижче; full-task залишок може мати пізнішу allocation, потрібний receipt — ні |
| I-PREVIEW | Persisted brief/scope/agreement, conflict handling, truthful assessment; CLD004/007/008/009 та consumed Core contracts | Preview cases у секції L-PREVIEW; не підміняє повний M0 або downstream execution |
| I-WPROFILE | Вузький living-world game pack/profile; LW001/002/030, Core031–033, CLD005/010/011 | Не прибирати exclusion з existing small-2d template для видимості підтримки; кваліфікувати окрему комбінацію |
| I-WDEPTH | Спочатку accepted W-FIRST як продуктова policy, далі повний gate LW028 та exact Core034 rule activation/migration capabilities | Це explicit release policy; не задекларована legacy dependency LW030→028 |

I-01–I-09 визначено в таблиці дев’яти спільних точок інтеграції вище. Core Godot pack responsibilities GC016/017 і generic worktree/runtime/evidence лишаються в Core; CLD010/011/014/015 приймають product integration. Повний Core game-onboarding gate GC026 не додається до CLD020 через одне reuse посилання. Друга реалізація engine adapter, verifier або build registry не створюється лише через інший продукт.

## I-REUSE — що кваліфікувати до першого споживача

Пізня full-task allocation не відкладає потрібну раніше capability. Перед її фактичним використанням або acceptance claim записують `consumer`, `required_before`, `legacy_id`, `criterion_pointer`, `coverage_scope`, `component/profile binding`, `primary_receipt`, `remaining_criteria`, `residual_destination`. Для E0-дизайну достатня звірка контрактів; таблиця не дозволяє запускати моделі зараз.

Кожне existing_work_ref у JSON потребує disposition: consumed capability або reference-only з поясненням. `not_applicable` допускається лише з обґрунтуванням обраного альтернативного профілю. Відсутня потрібна capability блокує її consumer. До пізнього C-PLATFORM переходить тільки залишок поза спожитим scope. Складені IDs у таблиці означають чинні AF-/GC-/AMM- IDs із трьома цифрами.

| Required before consumer | Legacy refs | Scope і primary evidence |
|---|---|---|
| RSI001 | AF004/013/018/022 | Policy, exact approval, Tool Gateway, ADR authority; матриця дозволених записів та denial при розширенні authority |
| RSI002 | AF001/016/024/048/055 | Identity/version, memory/pack composition, context/worktree binding; exact digests і відмова stale/latest substitution |
| RSI003 | AF020/027/032 | Rubric, measurement і cost provenance; frozen protocol та сумісні measurement receipts |
| RSI004 | AF002/003/051 | Ledger/issuer/artifact/candidate integrity; replay та actual-byte binding без duplicate decision |
| RSI005 | AF015/016/021/029 | Context/memory isolation, contamination, storage/privacy; negative retrieval/log/export cases й access ledger |
| RSI006 | AF020/052, GC006/041/043 | Software evidence closure, effective identities, admission і нові subject adapters; conformance та reject неповного evidence до review |
| RSI007 | AF027/032 | Однакові measurement/cost/missingness semantics; raw paired observations і відтворюваний comparison |
| RSI008 | AF008/027/056 | Campaign reservations/caps/retries/full costs; ledger відкинутих attempts і enforced stop нової роботи |
| RSI009 | AF017/044/048/055, GC043 | Exact arena host/sandbox/context/worktree/admission; enforced denial, trusted Stop/reconciliation |
| RSI010 | AF008/013/022/051 | Bounded plan/authority/impact/candidate binding; changed-scope та stale-plan denial |
| RSI011 | AF006/044/052 | Durable paired execution/validators/interruption; complete run receipts без duplicate effect |
| RSI012 | AF015/016/021 | Governed persistence/retrieval/poisoning/invalidation; negative lineage збережено, revoked experience не повертається через cache |
| RSI013 | AF010/011/012/016/024 | Exact role/routing/pool/skill/pack harness; versioned admission та authority-preserving activation/rollback |
| RSI014 | AF049/050/051/052/053/054 | Обраний writable worker/role pack/validator/review/repair; immutable own-source candidate без зміни supervisor authority; AF050 тільки для обраного Claude profile |
| RSI015 | AF025/032/034, GC001 | Reference/benchmark/reporting/environment contracts; незалежні corpora/oracles та actual receipts; envelope reuse не full AF034 |
| RSI016 | AF001/026/028/057, AMM046 | Спожиті schema/API/state/migration/recovery; old→new matrix, restore та stale-authority rejection |
| RSI017 | AF024/031/057 | Pack activation, обраний deployment profile, generation recovery; shadow/canary/rollback із чинною authority |
| RSI018 | AF036/038/043/056 | Actual operator path/accessibility/telemetry/Stop; exact target, pending effects і збережена чернетка |
| RSI019 | AF020/034 | Independent verdict/release-envelope traceability; own-source і own-harness, failed candidate/recovery/measured benefit |

C-WORKBENCH потребує рядків001–011/015 перед відповідними consumers; C-SELF додає решту001–019. Подальші C-METHOD/C-RSI та W-FIRST/W-DEPTH застосовують те саме правило до своїх `existing_work_refs`. C-PILOT має власні P01–P09; якщо використовує AF036–043 UI, спожитий scope кваліфікують до P02/P09. I-REUSE не додає dependency edges.

AF029 означає фактичний storage/privacy profile, а не обов’язковий PostgreSQL. AF032/034 reference/reporting reuse не втягує повний NFR або трипровайдерний GA gate. AF028/031/AMM046 потребують саме обраного compatibility/activation/recovery scope, не всіх topology/AMM profiles. Критерії широких tasks залишаються незмінними.

## Що має містити рішення про випуск

Один versioned release dossier містить scope/exclusions; exact commit і installed bundle; підтримуваний environment/model/tool/authority profile; усі mandatory cases та primary receipts; незалежний verdict; failures/unknown/full costs; usable recovery; рішення власника. Для кожної використаної вимоги окремо записують `canonical_id`, `criterion_pointer`, `coverage_scope`, `subject_hash`, `profile`, `receipt`, `verdict`, `remaining_criteria`, `residual_destination`. Тут визначено потрібний dossier; успішних receipts не вигадано.

`coverage_scope=capability_subset` не змінює task status, не доводить full dependency completion і не дозволяє починати залежну повну task без її prerequisites. Лише AF obligations поза спожитим раннім scope повертаються до C-PLATFORM; потрібні ранні capabilities проходять I-REUSE до consumer, GC до їхніх C-GODOT/C-LOCAL/C-EXPAND gates; непокриті preview CLD — до L-CREATOR/M0. Вужчий scope підтримки показують до запуску й у release notes; unsupported профіль не отримує загального ready.

До реалізації потрібні actual resources, придатні tools/models, незалежні reviewers та матеріал для людських сесій. Це вхідні дані qualification, а не привід відкладати нинішній план. Дати й оцінки додаються після gap sizing; перші релізи не розширюються довільно заради optimistic schedule. Будь-який no-go зберігає результат досліду, але не перетворюється на прийнятий продукт.
