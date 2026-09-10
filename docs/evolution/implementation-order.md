# Один порядок реалізації Lokvetia Core та Lokiravia

Редакція 2026-09-10 · запропонований план реалізації, не звіт про готові продукти.

Почати з кваліфікованого локального Core і завершення наявного редактора задуму. Далі побудувати workbench доказів, наскрізний creator шлях та першу живу сцену. Core-on-Core і рекурсія методу мають власні gates; гра їх не блокує. [Точні межі перших релізів](first-releases.md) визначають, що користувач отримає й чим це перевірити.

## Як користуватися планом

1. Знайти найранішу доступну вимогу в таблиці. Номер — рекомендований вибір наступної роботи, а не наказ виконувати незалежні задачі послідовно.
2. Відкрити її canonical manifest за source pointer у [JSON](implementation-order.json). Перевірити наявний код/артефакт і точне evidence. Повторно використовувати придатне; реалізувати тільки прогалини. Перше розміщення broad legacy task у пізньому релізі не відкладає qualification її capability, потрібної ранішому споживачу: діє I-REUSE із first-releases.
3. Перед новою реалізацією перевірити всі hard prerequisites. Перед використанням capability перевірити її exact profile та integration receipts. `existing_work_refs` — місце reuse, не готовність і не нове hard edge.
4. Вести окремо реалізацію, criterion coverage, live qualification та рішення про реліз. Підмножина capability не завершує широку task. Невідповідність baseline/checkpoint потребує повторної qualification.
5. Приймати реліз за його gates, а не за кількістю закритих карток. Негативний дослід може завершити research роботу без shipping claim.

Є 280 вимог: Core 57 AF + 43 GC + 48 AMM + 35 RSI; Lokiravia 67 CLD + 30 LW. Epics/features/stories лишаються hierarchy containers, не додатковими виконуваними задачами. `examples/backlog.json` Core є прикладом і не дублюється в цьому плані. Префікс `cloud:` означає Lokiravia, не обов’язковий hosted deployment.

## Релізи та наступні напрями

Порядок рядків — продуктова перевага за однакової готовності, не бар’єр між усіма напрямами. L-CREATOR і W-FIRST можуть рухатися паралельно; W-FIRST не чекає повного CLD020 або Core030. Вибір W-FIRST перед прийманням W-DEPTH — явна політика цього плану; чинний DAG не має такого edge. Пізні optional напрями запускаються лише за потреби та проходження їхніх gates.

`Closure` включає seeds і всі оголошені hard prerequisites, навіть якщо частина вже реалізована. `Нові` — перше планове розміщення вимоги, не обсяг нового коду. Для C-PILOT/L-PREVIEW closure є повною картою зобов’язань вихідних tasks, а приймання релізу обмежене вказаними capabilities.

| Порядок | Поставка | Closure | Нові | Приймання |
|---|---|---:|---:|---|
| 1 | **C-PILOT** — Core: кваліфікований локальний engineering pilot | 36 | 36 | Вузький capability шлях; повні tasks окремо |
| 2 | **L-PREVIEW** — Lokiravia: збережений задум і погоджений план | 8 | 8 | Preview scope; повні M0/M1 окремо |
| 3 | **C-WORKBENCH** — Core: порівняння кандидатів із доказами | 12 | 12 | Усі критерії closure та сценарії workbench |
| 4 | **L-CREATOR** — Lokiravia: три реальні гри та цикл змін | 20 | 12 | Чинний gate та всі його prerequisites |
| 5 | **W-FIRST** — Lokiravia: перша жива сцена | 22 | 15 | Чинний gate та всі його prerequisites |
| 6 | **C-SELF** — Core поліпшує власний source і harness | 19 | 7 | Чинний gate та всі його prerequisites |
| 7 | **C-METHOD** — Core поліпшує наступний метод дослідження | 24 | 5 | Чинний gate та всі його prerequisites |
| 8 | **C-RSI** — Standalone продукт із доказовим RSI | 30 | 6 | Чинний gate та всі його prerequisites |
| 9 | **W-DEPTH** — Глибший район і перевірена еволюція правил | 47 | 18 | Чинний gate та всі його prerequisites |
| 10 | **C-PLATFORM** — Повна заявлена Core platform / legacy GA | 57 | 31 | Повні AF034/035 та всі критерії заявленого scope |
| 11 | **C-GODOT** — Повний чинний Core Godot creator шлях | 30 | 21 | Повні застосовні GC milestone gates |
| 12 | **C-AUTONOMY** — Повний once-approved autonomous mission | 48 | 48 | Повні AMM047/048 та їхні prerequisites |
| 13 | **L-HOSTED** — Приватна hosted alpha | 34 | 14 | Чинний gate та всі його prerequisites |
| 14 | **C-LOCAL** — Кваліфікований local-only / hybrid game path | 36 | 5 | Повні застосовні GC milestone gates |
| 15 | **L-PUBLIC** — Обмежена публічна creator beta | 44 | 10 | Чинний gate та всі його prerequisites |
| 16 | **L-MARKET** — Marketplace | 51 | 7 | умовний напрям; Чинний gate та всі його prerequisites |
| 17 | **C-EXPAND** — Повний заявлений Core game creator scope | 43 | 7 | Повні застосовні GC milestone gates |
| 18 | **L-ENGINES** — Додаткові рушії й цільові платформи | 54 | 8 | умовний напрям; Чинний gate та всі його prerequisites |
| 19 | **L-GA** — Визначена Lokiravia GA / factory scope | 50 | 5 | Чинний GA gate і conditional gates обраних функцій |
| 20 | **L-CONSOLE** — Умовна console support feasibility | 36 | 1 | умовний напрям; Умовний партнерський gate; no-go не є випуском |
| 21 | **L-FACTORY-MARKET** — Умовний продаж Factory packs | 54 | 1 | умовний напрям; Marketplace і права на Factory packs |
| 22 | **L-NONGAME** — Умовний Lokiravia non-game pack | 38 | 1 | умовний напрям; Окрема non-game qualification |
| 23 | **W-COOP** — Дослідження співпраці гравців | 48 | 1 | умовний напрям; Дослідження; допустимий no-go |
| 24 | **C-TRAINING** — Необов’язковий training research | 29 | 1 | умовний напрям; Окремо допуск досліду та adoption/no-go |

У JSON кожен release містить точні `seed_ids`, `task_closure`, `newly_allocated` і `capability_prerequisites`. Перші п’ять поставок деталізовано в first-releases; пізніші gates успадковують повні canonical критерії. C-PLATFORM зберігає AF034/035 і їхні ширші вимоги, C-GODOT/C-LOCAL/C-EXPAND — чинні GC milestone gates, C-AUTONOMY — повні AMM047/048. L-GA не вмикає продаж, console або новий engine без conditional gates, перелічених у JSON. Optional не означає автоматичний pass у разі no-go.

## Єдина черга вимог

Точні dependencies та source locations містить JSON; назви нижче дослівні з canonical manifest. `Перший розгляд` — де вперше перевірити reusable результат або реалізувати прогалину. Вимога може брати участь у кількох релізах; membership не дублює її реалізацію.

| № | ID | Перший розгляд | Вимога |
|---:|---|---|---|
| 1 | `core:AF-001` | C-PILOT | Versioned domain model and compatibility migration |
| 2 | `core:AF-002` | C-PILOT | Transactional event outbox and tamper-evident audit chain |
| 3 | `core:AF-003` | C-PILOT | Content-addressed artifact and criterion-evidence ledger |
| 4 | `core:AF-004` | C-PILOT | Deterministic policy plane, autonomy modes, and emergency stop |
| 5 | `core:AF-005` | C-PILOT | Normalized adapter contract, qualification, and agent lifecycle |
| 6 | `core:AF-006` | C-PILOT | Durable workflow execution, checkpoints, and resume |
| 7 | `core:AF-007` | C-PILOT | Dependency scheduler, TTL/fenced leases, and conflict domains |
| 8 | `core:AF-008` | C-PILOT | Persistent Loop Engineering and no-progress control |
| 9 | `core:AF-009` | C-PILOT | Mission intake, source authority, clarifications, and readiness verdict |
| 10 | `core:AF-010` | C-PILOT | Provider-neutral Role Definitions and compatibility contracts |
| 11 | `core:AF-011` | C-PILOT | Evaluation-aware Agent Router, independent reviewer rotation, and qualification history |
| 12 | `core:AF-012` | C-PILOT | Role pools, arbitration strategies, and Workforce Composer |
| 13 | `core:AF-013` | C-PILOT | Factory Blueprint generation, alternatives, approval, and amendments |
| 14 | `core:AF-017` | C-PILOT | Local sandbox subset for writable workers |
| 15 | `core:AF-044` | C-PILOT | Worker Runtime abstraction |
| 16 | `core:AF-046` | C-PILOT | Per-stage live execution approvals |
| 17 | `core:AF-048` | C-PILOT | Worktree manager |
| 18 | `core:AF-052` | C-PILOT | Deterministic validator runner |
| 19 | `core:AF-055` | C-PILOT | Execution Context Package MVP |
| 20 | `core:AF-020` | C-PILOT | Independent evaluation service and criterion verdicts |
| 21 | `core:AF-045` | C-PILOT | Hermes adapter and session lifecycle |
| 22 | `core:AF-049` | C-PILOT | Codex CLI implementation worker |
| 23 | `core:AF-051` | C-PILOT | Candidate change artifact and approval-gated PR plan |
| 24 | `core:AF-053` | C-PILOT | End-to-end coding delivery loop |
| 25 | `core:AF-056` | C-PILOT | Minimal execution telemetry and enforced budgets |
| 26 | `core:AF-057` | C-PILOT | Local recovery and orphan reconciliation |
| 27 | `core:AF-GC-001` | C-PILOT | Відновити відтворюваний CI на трьох ОС |
| 28 | `core:AF-GC-002` | C-PILOT | Показувати готовність лише після реальних перевірок |
| 29 | `core:AF-GC-003` | C-PILOT | Закриття діалогу ніколи не підтверджує дію |
| 30 | `core:AF-GC-004` | C-PILOT | Зберігати чернетки та фокус під час автооновлення |
| 31 | `core:AF-GC-005` | C-PILOT | Не втрачати зміст звичайного опису гри |
| 32 | `core:AF-GC-006` | C-PILOT | Прив’язати вибрану модель до фактичного запуску |
| 33 | `core:AF-GC-039` | C-PILOT | Узгодити авторизацію локального API з обіцяною політикою |
| 34 | `core:AF-GC-041` | C-PILOT | Зберігати ролі та незалежність reviewer у live mission |
| 35 | `core:AF-GC-042` | C-PILOT | Кваліфікувати ролі planning та bootstrap для провайдерів |
| 36 | `core:AF-GC-043` | C-PILOT | Atomically admit qualified workers with scoped attempts and shared capacity |
| 37 | `cloud:AF-CLD-001` | L-PREVIEW | Agree on the Core and Cloud product boundaries |
| 38 | `cloud:AF-CLD-002` | L-PREVIEW | Define the shared data model and API contracts |
| 39 | `cloud:AF-CLD-003` | L-PREVIEW | Map Cloud work to the existing Core backlog |
| 40 | `cloud:AF-CLD-004` | L-PREVIEW | Design separate Creator and Operator views |
| 41 | `cloud:AF-CLD-005` | L-PREVIEW | Define engine, build target, and game pack interfaces |
| 42 | `cloud:AF-CLD-007` | L-PREVIEW | Turn a plain-language idea into a Game Brief |
| 43 | `cloud:AF-CLD-008` | L-PREVIEW | Keep the first playable version small |
| 44 | `cloud:AF-CLD-009` | L-PREVIEW | Assemble a visible AI game team |
| 45 | `core:AF-RSI-001` | C-WORKBENCH | Розділити повноваження оптимізатора, оцінювача та чинного Core |
| 46 | `core:AF-RSI-002` | C-WORKBENCH | Описати незмінний суб’єкт і покоління еволюції |
| 47 | `core:AF-RSI-003` | C-WORKBENCH | Зафіксувати протокол порівняння до запуску кандидатів |
| 48 | `core:AF-RSI-004` | C-WORKBENCH | Зв’язати покоління, спроби, докази та рішення |
| 49 | `core:AF-RSI-005` | C-WORKBENCH | Розділити навчальні приклади, validation і прихований holdout |
| 50 | `core:AF-RSI-006` | C-WORKBENCH | Узагальнити evidence-first evaluator поза Codex diff |
| 51 | `core:AF-RSI-007` | C-WORKBENCH | Порівнювати реальну користь з урахуванням витрат і шуму |
| 52 | `core:AF-RSI-008` | C-WORKBENCH | Резервувати bounded бюджет повного експерименту |
| 53 | `core:AF-RSI-009` | C-WORKBENCH | Кваліфікувати ізольовану арену для змін Core |
| 54 | `core:AF-RSI-010` | C-WORKBENCH | Перетворити ідею поліпшення на точний candidate plan |
| 55 | `core:AF-RSI-011` | C-WORKBENCH | Виконати baseline і challenger за одним протоколом |
| 56 | `core:AF-RSI-015` | C-WORKBENCH | Побудувати незалежний benchmark продукту Core |
| 57 | `cloud:AF-CLD-006` | L-CREATOR | Define evidence levels and release gates |
| 58 | `cloud:AF-CLD-010` | L-CREATOR | Prepare a small Godot 2D starter pack |
| 59 | `cloud:AF-CLD-011` | L-CREATOR | Connect a real Godot engine adapter |
| 60 | `cloud:AF-CLD-012` | L-CREATOR | Keep source versions and working game checkpoints |
| 61 | `cloud:AF-CLD-013` | L-CREATOR | Connect live coding workers to game tasks |
| 62 | `cloud:AF-CLD-014` | L-CREATOR | Check the rules of the generated game |
| 63 | `cloud:AF-CLD-015` | L-CREATOR | Build a Web version and add Play |
| 64 | `cloud:AF-CLD-016` | L-CREATOR | Export a Windows game and the full source |
| 65 | `cloud:AF-CLD-017` | L-CREATOR | Turn play feedback into a change plan |
| 66 | `cloud:AF-CLD-018` | L-CREATOR | Create version 2, restore version 1, and try a private remix |
| 67 | `cloud:AF-CLD-019` | L-CREATOR | Show progress and enforce budget and stop controls |
| 68 | `cloud:AF-CLD-020` | L-CREATOR | Accept three real reference games |
| 69 | `cloud:AF-LW-001` | W-FIRST | Конституція досвіду живого світу |
| 70 | `core:AF-RSI-031` | W-FIRST | Типізувати дозволену дію агента у зовнішньому домені |
| 71 | `core:AF-RSI-032` | W-FIRST | Задати нейтральний контракт replay та доменного checkpoint |
| 72 | `cloud:AF-LW-002` | W-FIRST | Ігрова модель подій і наслідків |
| 73 | `cloud:AF-LW-003` | W-FIRST | Версійована книга законів і відкритих можливостей |
| 74 | `cloud:AF-LW-004` | W-FIRST | Палітра композиційних можливостей для авторів |
| 75 | `cloud:AF-LW-005` | W-FIRST | Розгляд незапланованої дії гравця |
| 76 | `cloud:AF-LW-008` | W-FIRST | Область впливу та зрозумілий ризик пригоди |
| 77 | `cloud:AF-LW-009` | W-FIRST | Перспективна пам’ять NPC і свідків |
| 78 | `cloud:AF-LW-010` | W-FIRST | Сліди, за якими гравець може відновити причинність |
| 79 | `cloud:AF-LW-014` | W-FIRST | Режисура гумору як налаштування досвіду |
| 80 | `core:AF-RSI-033` | W-FIRST | Кваліфікувати повільні agent decisions поза ігровим tick |
| 81 | `cloud:AF-LW-011` | W-FIRST | Каскади з порогами, затримкою та згасанням |
| 82 | `cloud:AF-LW-012` | W-FIRST | Контрфактичний перегляд світового сценарію |
| 83 | `cloud:AF-LW-030` | W-FIRST | Перший однокористувацький доказ за 30 хвилин |
| 84 | `core:AF-RSI-012` | C-SELF | Накопичувати перевірений досвід як граф існуючих доказів |
| 85 | `core:AF-RSI-013` | C-SELF | Еволюціонувати harness, routing і skills через existing registries |
| 86 | `core:AF-RSI-014` | C-SELF | Готувати зміни власного коду Core як звичайні immutable candidates |
| 87 | `core:AF-RSI-016` | C-SELF | Перевіряти сумісність стану, API і міграцій між поколіннями |
| 88 | `core:AF-RSI-017` | C-SELF | Просувати й відкочувати generation через shadow/canary stages |
| 89 | `core:AF-RSI-018` | C-SELF | Показати людині стан і причину самовдосконалення |
| 90 | `core:AF-RSI-019` | C-SELF | Прийняти перший Core-on-Core цикл без заяви про повний RSI |
| 91 | `core:AF-RSI-020` | C-METHOD | Подавати новий evaluator як окремий candidate subject |
| 92 | `core:AF-RSI-021` | C-METHOD | Кваліфікувати калібрування й систематичні помилки evaluator |
| 93 | `core:AF-RSI-022` | C-METHOD | Розділити agent gain та evaluator drift при коеволюції |
| 94 | `core:AF-RSI-023` | C-METHOD | Порівнювати покоління самого optimizer |
| 95 | `core:AF-RSI-024` | C-METHOD | Замкнути перший bounded рекурсивний цикл |
| 96 | `core:AF-RSI-025` | C-RSI | Виводити можливості поліпшення з реальних failures і friction |
| 97 | `core:AF-RSI-026` | C-RSI | Ввести незалежний продуктовий сигнал від користувачів Core |
| 98 | `core:AF-RSI-027` | C-RSI | Пропонувати research portfolio та перегляд product goal |
| 99 | `core:AF-RSI-028` | C-RSI | Перевіряти нові інструменти й топології як пояснювані експерименти |
| 100 | `core:AF-RSI-029` | C-RSI | Випробувати довгу еволюцію на poisoning, drift і відновлення |
| 101 | `core:AF-RSI-030` | C-RSI | Прийняти самовдосконалення Lokvetia Core як окремий продукт |
| 102 | `cloud:AF-LW-006` | W-DEPTH | Ремесло з матеріальною ціною та співучастю |
| 103 | `cloud:AF-LW-007` | W-DEPTH | Продуктивна помилка і вторинне застосування |
| 104 | `cloud:AF-LW-013` | W-DEPTH | Авторська лабораторія однієї сцени |
| 105 | `cloud:AF-LW-015` | W-DEPTH | Комічний наслідок із новим вибором |
| 106 | `cloud:AF-LW-016` | W-DEPTH | Тиха сесія та речі зі спільною історією |
| 107 | `cloud:AF-LW-017` | W-DEPTH | Рівноцінні внески гравця та NPC в експедицію |
| 108 | `cloud:AF-LW-018` | W-DEPTH | Установи з потребами та обов’язками |
| 109 | `core:AF-RSI-034` | W-DEPTH | Оцінювати domain-rule candidates без присвоєння художньої влади |
| 110 | `cloud:AF-LW-019` | W-DEPTH | Народження й згасання місцевої традиції |
| 111 | `cloud:AF-LW-020` | W-DEPTH | Переговори про зміни спільного простору |
| 112 | `cloud:AF-LW-021` | W-DEPTH | Відбудова з вибором майбутнього місця |
| 113 | `cloud:AF-LW-022` | W-DEPTH | Чутки, репутація та можливість спростування |
| 114 | `cloud:AF-LW-023` | W-DEPTH | Публікація еволюції світу з історією версій |
| 115 | `cloud:AF-LW-024` | W-DEPTH | Ігрова кампанія перевірюваного самовдосконалення |
| 116 | `cloud:AF-LW-025` | W-DEPTH | Плейтест несподіванки, справедливості й бажання залишитися |
| 117 | `cloud:AF-LW-026` | W-DEPTH | Набір зловживань гравців і авторів світу |
| 118 | `cloud:AF-LW-027` | W-DEPTH | Повернення в світ, який жив без гравця |
| 119 | `cloud:AF-LW-028` | W-DEPTH | Повний еволюційний квартал: пізніше приймання |
| 120 | `core:AF-014` | C-PLATFORM | Idempotent mission bootstrap, manifests, and rollback point |
| 121 | `core:AF-015` | C-PLATFORM | Immutable Context Packages, provenance, broker, and compaction |
| 122 | `core:AF-016` | C-PLATFORM | Typed memory, bounded retrieval, invalidation, and governed skills |
| 123 | `core:AF-018` | C-PLATFORM | Tool Registry, Tool Gateway, MCP manager, and connector lifecycle |
| 124 | `core:AF-019` | C-PLATFORM | Short-lived scoped credential broker with zero prompt/log exposure |
| 125 | `core:AF-021` | C-PLATFORM | Prompt-injection red team, tripwires, quarantine, and incidents |
| 126 | `core:AF-022` | C-PLATFORM | ADR governance and transactional Blueprint impact propagation |
| 127 | `core:AF-023` | C-PLATFORM | Audited parallel, generator-critic, quorum, debate, and red/blue patterns |
| 128 | `core:AF-024` | C-PLATFORM | Signed pack SDK and install/upgrade/disable/rollback manager |
| 129 | `core:AF-025` | C-PLATFORM | Software Engineering reference pack and release evidence |
| 130 | `core:AF-026` | C-PLATFORM | REST operations API, idempotency/ETags, webhooks, and SDK contracts |
| 131 | `core:AF-027` | C-PLATFORM | OpenTelemetry and cost ledger |
| 132 | `core:AF-029` | C-PLATFORM | PostgreSQL/object storage migration and end-to-end tenant isolation |
| 133 | `core:AF-031` | C-PLATFORM | Single-node, clustered, hybrid, and air-gapped deployment definitions |
| 134 | `core:AF-028` | C-PLATFORM | Full chaos recovery and verified restore |
| 135 | `core:AF-036` | C-PLATFORM | Shared application-service boundary for CLI and web |
| 136 | `core:AF-037` | C-PLATFORM | Local FastAPI host and read-only operations API |
| 137 | `core:AF-038` | C-PLATFORM | Live development dashboard and navigation shell |
| 138 | `core:AF-039` | C-PLATFORM | Backlog, work-item, and workflow run controls |
| 139 | `core:AF-040` | C-PLATFORM | Agent, provider, and reviewer routing controls |
| 140 | `core:AF-041` | C-PLATFORM | Review inbox and founder approval workspace |
| 141 | `core:AF-042` | C-PLATFORM | Audit explorer, runtime settings, and GitHub sync preview |
| 142 | `core:AF-043` | C-PLATFORM | Windows launch experience, accessibility, and end-to-end qualification |
| 143 | `core:AF-030` | C-PLATFORM | Human Control Plane for evidence, approvals, incidents, cost, and intervention |
| 144 | `core:AF-032` | C-PLATFORM | NFR, performance, accessibility, isolation, and recovery qualification suite |
| 145 | `core:AF-033` | C-PLATFORM | 72-hour fault-injection soak with bounded resource growth |
| 146 | `core:AF-034` | C-PLATFORM | Full heterogeneous-agent reference acceptance mission |
| 147 | `core:AF-035` | C-PLATFORM | Runbooks, clean install, restore exercise, GA evidence, and handover |
| 148 | `core:AF-047` | C-PLATFORM | Hermes qualification and controlled fallback |
| 149 | `core:AF-050` | C-PLATFORM | Claude Code implementation worker |
| 150 | `core:AF-054` | C-PLATFORM | Software engineering role pack |
| 151 | `core:AF-GC-007` | C-GODOT | Додати головний екран «Мої ігри» і покроковий старт |
| 152 | `core:AF-GC-008` | C-GODOT | Перетворити ідею на зрозумілий план першої гри |
| 153 | `core:AF-GC-010` | C-GODOT | Зберігати й відкликати доступ до AI без витоку ключів |
| 154 | `core:AF-GC-011` | C-GODOT | Перевіряти можливості ПК до вибору моделі та рушія |
| 155 | `core:AF-GC-012` | C-GODOT | Рекомендувати реалістичний рушій і конфігурацію AI |
| 156 | `core:AF-GC-013` | C-GODOT | Показувати точний план встановлення з перевірених джерел |
| 157 | `core:AF-GC-014` | C-GODOT | Виконувати та відновлювати встановлення програм |
| 158 | `core:AF-GC-015` | C-GODOT | Запускати локальну інфраструктуру однією дією |
| 159 | `core:AF-GC-016` | C-GODOT | Створити Godot pack для першої 2D гри |
| 160 | `core:AF-GC-017` | C-GODOT | Перевіряти Godot-проєкт і створювати реальний build |
| 161 | `core:AF-GC-025` | C-GODOT | Визначити доступний шлях для 12+ та участь дорослого |
| 162 | `core:AF-GC-009` | C-GODOT | Підключати хмарний AI через зрозумілий майстер |
| 163 | `core:AF-GC-018` | C-GODOT | Дозволяти обмежену cloud-сесію з прозорим бюджетом |
| 164 | `core:AF-GC-019` | C-GODOT | Підключити справжню розробку до ігрового плану |
| 165 | `core:AF-GC-020` | C-GODOT | Зберігати останню перевірену ігрову версію |
| 166 | `core:AF-GC-021` | C-GODOT | Запускати «Грати» для конкретної робочої версії |
| 167 | `core:AF-GC-022` | C-GODOT | Перетворювати відгук після гри на наступну версію |
| 168 | `core:AF-GC-023` | C-GODOT | Пояснювати прогрес і надійно зупиняти роботу |
| 169 | `core:AF-GC-024` | C-GODOT | Зробити основний шлях доступним українською та англійською |
| 170 | `core:AF-GC-040` | C-GODOT | Перевірити зрозумілість із користувачами 12–15 років |
| 171 | `core:AF-GC-026` | C-GODOT | Прийняти повний Godot-шлях на чистому ПК |
| 172 | `core:AF-AMM-001` | C-AUTONOMY | Autonomous Mission aggregate, configuration, and lifecycle migration |
| 173 | `core:AF-AMM-002` | C-AUTONOMY | Rich backlog schema, immutable revisions, and impact projection |
| 174 | `core:AF-AMM-003` | C-AUTONOMY | Mission Execution Epoch and supersession model |
| 175 | `core:AF-AMM-004` | C-AUTONOMY | Typed mission checkpoint model and integrity contract |
| 176 | `core:AF-AMM-005` | C-AUTONOMY | Autonomous authorization resolver and revocation |
| 177 | `core:AF-AMM-006` | C-AUTONOMY | Provider execution-location and local capability model |
| 178 | `core:AF-AMM-007` | C-AUTONOMY | Autonomous mission specification intake and source artifact |
| 179 | `core:AF-AMM-008` | C-AUTONOMY | Autonomous planning role pack and role-to-model manifest |
| 180 | `core:AF-AMM-009` | C-AUTONOMY | Structured multi-role architecture and backlog generation pipeline |
| 181 | `core:AF-AMM-010` | C-AUTONOMY | Deterministic backlog and architecture proposal verifier |
| 182 | `core:AF-AMM-011` | C-AUTONOMY | Approve Backlog - Start Mission and revision authority service |
| 183 | `core:AF-AMM-012` | C-AUTONOMY | AutonomousMissionWorkflow contracts, queries, client, and Worker registration |
| 184 | `core:AF-AMM-013` | C-AUTONOMY | Pre-approval analysis/generation phases and durable approval wait |
| 185 | `core:AF-AMM-014` | C-AUTONOMY | Post-approval phase and child work-item orchestration |
| 186 | `core:AF-AMM-015` | C-AUTONOMY | Mission-wide pause, resume, stop, and retry control fence |
| 187 | `core:AF-AMM-016` | C-AUTONOMY | Checkpoint restart and backlog-revision Signal contracts |
| 188 | `core:AF-AMM-017` | C-AUTONOMY | Continue-as-new, history thresholds, visibility, and Worker versioning |
| 189 | `core:AF-AMM-018` | C-AUTONOMY | Mission operation journal and authoritative recovery reconstruction |
| 190 | `core:AF-AMM-019` | C-AUTONOMY | Mission epoch branch and worktree manager |
| 191 | `core:AF-AMM-020` | C-AUTONOMY | Per-item worktree and autonomous local integration path |
| 192 | `core:AF-AMM-021` | C-AUTONOMY | Checkpoint materialization, validation, and epoch restart service |
| 193 | `core:AF-AMM-022` | C-AUTONOMY | Apply Backlog Changes - Restart domain service |
| 194 | `core:AF-AMM-023` | C-AUTONOMY | Installed local model inventory and role selection |
| 195 | `core:AF-AMM-024` | C-AUTONOMY | Durable global local-inference scheduler |
| 196 | `core:AF-AMM-025` | C-AUTONOMY | Ollama dynamic model and lifecycle adapter |
| 197 | `core:AF-AMM-026` | C-AUTONOMY | Writable local LLM Worker Runtime through Tool Gateway |
| 198 | `core:AF-AMM-027` | C-AUTONOMY | Fresh isolated role contexts and mission memory integration |
| 199 | `core:AF-AMM-028` | C-AUTONOMY | MODEL_INDEPENDENT and LOGICALLY_INDEPENDENT review routing |
| 200 | `core:AF-AMM-029` | C-AUTONOMY | Autonomous Local telemetry and non-monetary safety policy |
| 201 | `core:AF-AMM-030` | C-AUTONOMY | Required-vs-current environment discovery artifact |
| 202 | `core:AF-AMM-031` | C-AUTONOMY | Versioned environment and service manifests |
| 203 | `core:AF-AMM-032` | C-AUTONOMY | Policy-bound bootstrap planner and idempotent executor |
| 204 | `core:AF-AMM-033` | C-AUTONOMY | Environment health convergence, service recovery, and NEEDS_HUMAN_ACTION |
| 205 | `core:AF-AMM-034` | C-AUTONOMY | Windows local long-run profile and orchestration preflight |
| 206 | `core:AF-AMM-035` | C-AUTONOMY | Active-revision ready selector and technical subtask creation |
| 207 | `core:AF-AMM-036` | C-AUTONOMY | Autonomous work-item coding-delivery integration |
| 208 | `core:AF-AMM-037` | C-AUTONOMY | Bounded autonomous repair and strategy escalation chain |
| 209 | `core:AF-AMM-038` | C-AUTONOMY | Architecture evolution, ADR propagation, and scope guard |
| 210 | `core:AF-AMM-039` | C-AUTONOMY | Accepted-work checkpoint and mission-memory progression |
| 211 | `core:AF-AMM-040` | C-AUTONOMY | Final mission validation and COMPLETED transition |
| 212 | `core:AF-AMM-041` | C-AUTONOMY | Autonomous Mission application service and persisted projections |
| 213 | `core:AF-AMM-042` | C-AUTONOMY | Autonomous Mission REST API |
| 214 | `core:AF-AMM-043` | C-AUTONOMY | Autonomous Mission CLI command group |
| 215 | `core:AF-AMM-044` | C-AUTONOMY | Control Center mission creation, planning, approval, status, and controls |
| 216 | `core:AF-AMM-045` | C-AUTONOMY | Control Center backlog editor, checkpoints, architecture, environment, and activity |
| 217 | `core:AF-AMM-046` | C-AUTONOMY | Domain migration, authorization, compatibility, and security qualification |
| 218 | `core:AF-AMM-047` | C-AUTONOMY | Temporal, local-runtime, environment, and end-to-end mission qualification |
| 219 | `core:AF-AMM-048` | C-AUTONOMY | Fault/reboot soak, resource-growth gate, documentation, and release evidence |
| 220 | `cloud:AF-CLD-021` | L-HOSTED | Add account boundaries, roles, and the 12+ access gate |
| 221 | `cloud:AF-CLD-022` | L-HOSTED | Use PostgreSQL for hosted state |
| 222 | `cloud:AF-CLD-023` | L-HOSTED | Store source, builds, and assets as protected objects |
| 223 | `cloud:AF-CLD-024` | L-HOSTED | Qualify server resources and register remote workers |
| 224 | `cloud:AF-CLD-025` | L-HOSTED | Make hosted workflows survive restarts |
| 225 | `cloud:AF-CLD-026` | L-HOSTED | Isolate agent and build jobs |
| 226 | `cloud:AF-CLD-027` | L-HOSTED | Guide creators through AI connections |
| 227 | `cloud:AF-CLD-028` | L-HOSTED | Keep Cloud credentials outside game work |
| 228 | `cloud:AF-CLD-029` | L-HOSTED | Enforce Cloud quotas and track usage |
| 229 | `cloud:AF-CLD-030` | L-HOSTED | Provide the hosted Creator Portal |
| 230 | `cloud:AF-CLD-031` | L-HOSTED | Serve protected playable builds |
| 231 | `cloud:AF-CLD-032` | L-HOSTED | Export a portable ownership package |
| 232 | `cloud:AF-CLD-033` | L-HOSTED | Add operations visibility and recovery drills |
| 233 | `cloud:AF-CLD-034` | L-HOSTED | Accept the private Cloud alpha |
| 234 | `core:AF-GC-027` | C-LOCAL | Встановлювати та перевіряти локальні моделі |
| 235 | `core:AF-GC-028` | C-LOCAL | Дати локальному AI кваліфікований інструмент розробки |
| 236 | `core:AF-GC-029` | C-LOCAL | Ділити ресурси ПК між AI, рушієм та грою |
| 237 | `core:AF-GC-030` | C-LOCAL | Маршрутизувати cloud/local за явними правилами |
| 238 | `core:AF-GC-031` | C-LOCAL | Кваліфікувати local-only та hybrid створення гри |
| 239 | `cloud:AF-CLD-035` | L-PUBLIC | Add releases and visibility controls |
| 240 | `cloud:AF-CLD-036` | L-PUBLIC | Add creator profiles and libraries |
| 241 | `cloud:AF-CLD-037` | L-PUBLIC | Add game pages with browser Play |
| 242 | `cloud:AF-CLD-038` | L-PUBLIC | Add Discover, search and tags |
| 243 | `cloud:AF-CLD-039` | L-PUBLIC | Add share links and embed controls |
| 244 | `cloud:AF-CLD-040` | L-PUBLIC | Add Remix and Fork with source history |
| 245 | `cloud:AF-CLD-041` | L-PUBLIC | Add likes, bookmarks and basic play statistics |
| 246 | `cloud:AF-CLD-042` | L-PUBLIC | Add age-aware moderation and reporting |
| 247 | `cloud:AF-CLD-043` | L-PUBLIC | Check asset origin and licences before release |
| 248 | `cloud:AF-CLD-044` | L-PUBLIC | Approve a limited public creator beta |
| 249 | `cloud:AF-CLD-045` | L-MARKET | Add seller setup and adult or guardian approval |
| 250 | `cloud:AF-CLD-046` | L-MARKET | Add sale listings, prices and licence choices |
| 251 | `cloud:AF-CLD-047` | L-MARKET | Add checkout through a payment provider |
| 252 | `cloud:AF-CLD-048` | L-MARKET | Add purchase access and the buyer library |
| 253 | `cloud:AF-CLD-049` | L-MARKET | Add the revenue ledger, fees and payouts |
| 254 | `cloud:AF-CLD-050` | L-MARKET | Add refunds, disputes and fraud review |
| 255 | `cloud:AF-CLD-051` | L-MARKET | Approve the marketplace release |
| 256 | `core:AF-GC-032` | C-EXPAND | Підключати Unity Hub, Editor і потрібні модулі |
| 257 | `core:AF-GC-033` | C-EXPAND | Додати Unity pack, тести та build adapter |
| 258 | `core:AF-GC-034` | C-EXPAND | Прийняти повний Unity-шлях для новачка |
| 259 | `core:AF-GC-035` | C-EXPAND | Керувати походженням та імпортом ігрових ресурсів |
| 260 | `core:AF-GC-036` | C-EXPAND | Розширювати складність через вимірювані зразки ігор |
| 261 | `core:AF-GC-037` | C-EXPAND | Експортувати гру та ділитися нею окремою дією |
| 262 | `core:AF-GC-038` | C-EXPAND | Оновлювати застосунок і збирати зрозумілу діагностику |
| 263 | `cloud:AF-CLD-052` | L-ENGINES | Publish an EngineAdapter SDK and compatibility tests |
| 264 | `cloud:AF-CLD-053` | L-ENGINES | Qualify the Unity adapter |
| 265 | `cloud:AF-CLD-054` | L-ENGINES | Prove Unreal feasibility and qualify its adapter |
| 266 | `cloud:AF-CLD-055` | L-ENGINES | Add Android builds and Google Play preparation |
| 267 | `cloud:AF-CLD-056` | L-ENGINES | Add Apple builds and App Store preparation |
| 268 | `cloud:AF-CLD-057` | L-ENGINES | Add Steam release preparation |
| 269 | `cloud:AF-CLD-058` | L-ENGINES | Add a shared PC store packaging contract |
| 270 | `cloud:AF-CLD-060` | L-ENGINES | Approve the multi-engine and multi-target release |
| 271 | `cloud:AF-CLD-061` | L-GA | Package reusable Agent Teams and Factory templates |
| 272 | `cloud:AF-CLD-063` | L-GA | Let creators choose qualified models and team budgets |
| 273 | `cloud:AF-CLD-064` | L-GA | Publish an API, SDK and signed webhooks |
| 274 | `cloud:AF-CLD-065` | L-GA | Qualify self-hosted and hybrid deployment |
| 275 | `cloud:AF-CLD-067` | L-GA | Approve the defined general-availability scope |
| 276 | `cloud:AF-CLD-059` | L-CONSOLE | Plan optional console support behind partner approval |
| 277 | `cloud:AF-CLD-062` | L-FACTORY-MARKET | Add an optional marketplace for Factories and packs |
| 278 | `cloud:AF-CLD-066` | L-NONGAME | Explore a later non-game executable pack |
| 279 | `cloud:AF-LW-029` | W-COOP | Необов’язкове дослідження людської кооперації |
| 280 | `core:AF-RSI-035` | C-TRAINING | Перевірити доцільність training-time self-iteration |

## Джерело правди й оновлення

Це derived design view, не сьомий виконувальний backlog. Шість source manifests з exact commit/SHA-256 перелічено в JSON. Кожна вимога має JSON pointer і digest canonical item; критерії не переписуються в коротшу версію. Нові RSI/LW картки й надалі синхронізуються між Markdown і JSON. Legacy IDs, source labels, hierarchy, dependencies та acceptance criteria не змінено.

Алгоритм відтворення: прочитати source items; зберегти hierarchy окремо; кваліфікувати локальні IDs; відхилити duplicate/missing IDs або cycles; обчислити closure кожного seed set; призначити найраніший release membership; серед доступних DAG nodes вибирати мінімальні `(priority_band, id)`. Source SHA-256 рахується від bytes Git blob указаного commit, а не від platform-specific checkout; зіставлення checkout нормалізує CRLF до LF. При змістовній зміні source digest view вважається застарілим до повторного обчислення, перевірки та рев’ю. Обидва репозиторії містять ідентичну копію view.

`declared_status` переносить raw label (або null), а `completion`, `live_qualification` і `release_acceptance` навмисно не підвищені. Історичні release notes про реалізацію та поточний proposed label можуть співіснувати; матриця reuse у first-releases пояснює наявні зрізи. Календар і фактичний кошторис додаються після оцінювання прогалин та кваліфікації середовища, без зміни обіцянок перших релізів.
