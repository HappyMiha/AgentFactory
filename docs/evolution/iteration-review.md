# Журнал проходів і незалежних виправлень

2026-09-09. Одна спільна документаційна робота для двох продуктів. Продуктовий код, dependency pins, активні backlog manifests і release gates цим портфелем не змінюються.

## Прохід 1 — встановити фактичну основу

Зіставлено поточний код і roadmap обох репозиторіїв; явно відділено alpha capabilities від майбутніх promises. Створено спільну концепцію, дослідницький аналіз RSI й літературні меморандуми зі сталими якорями. Початкові коміти: Core `9c3b696`, Lokiravia `e5f5405`.

Головне рішення: самовдосконалення **продукту Lokvetia Core** — окремий центральний контур із власним acceptance, включаючи source/harness, tools, optimizer/evaluator і перегляд дослідницького напряму. Воно не залежить від готовності світу. Lokiravia додає creator experience і доменний світ, споживаючи Core contracts.

## Прохід 2 — перетворити задум на спростовний портфель

Основні портфельні коміти: Core `39dd5ca`, Lokiravia `bb1b5f3`. Далі окремою поставкою додано навігацію, спільний delivery plan, цей журнал, перевірки й чергу продовження.

35 карток Core, 30 карток світу, 239 кваліфікованих dependency edges. Обидва портфелі мають acceptance, negative cases, artifacts, reuse та explicit research/delivery distinction. Пріоритетна послідовність і межа першої гри описані в [delivery plan](delivery-plan.md). Власний design schema не імпортується в чинну execution queue.

Незалежне архітектурне рев’ю виявило сім неоднозначностей; усі враховано:

| Зауваження | Прийняте виправлення |
|---|---|
| Прихований multiplayer у першому MVP | Single-player Godot із NPC; human coop лише optional AF-LW029 |
| Acceptance завжди вимагає більшого completion rate | Preregistered primary superiority axis + non-inferiority floors; корисна економія може бути результатом |
| Experiment accepted читається як release grant | Окремі comparison decision та scoped promotion authorization; recovery CAS потребує другого |
| Immutable manifest містить ще не наявні результати | Pre-run CandidateManifest, ExperimentRecord, post-run Decision/Generation envelopes |
| Lifecycle не вміщує unknown/recovery | Ортогональні phase, runtime disposition та evidence verdict/reason |
| Третє покоління не визначає recursive method | Typed O0→O1→O2; дочірні product artifacts оцінюються окремо |
| Неіснуючий quarantine enum у skills | Existing draft state + окремий blocking admission verdict |

Додатково Core gate перевіряє вже підтримувані consumer contracts; майбутній full game gate не утворює зворотної залежності.

## Прохід 3 — шукати спростування і перевірити стики

Другий прямий прохід «Трансформи» прочитав новий контекст, включно з повною главою четвертого тому. Він змусив відділити художню правдоподібність від незалежної перевірки. До вимог додано lifecycle зобов’язань, стабільний reward contract, повний облік прихованих передумов, відмінність proposal від ontology migration і перевірку кандидата, який поліпшує engagement ціною неприйнятого примусу. Докладні локатори — у літературній записці другого проходу.

Незалежне фінальне рев’ю портфеля дало ще три виправлення:

- Exact cross-repo prerequisites тепер видимі в кожній світовій Markdown-картці й синхронні з JSON.
- Save/load зберігає прийняті domain jobs, але інвалідує pending model proposals старого session epoch; новий request не дублює ефект.
- IntegrationReceipt має профілі contract conformance / domain runtime / packaged game; package hash обов’язковий для відповідного game claim, а не вигадується для Core fixture.

Окреме семантичне рев’ю джерел прибрало декоративні SAFE/TR посилання. Для дев’яти суто інфраструктурних або складених карток світу немає SAFE-motif; пряме походження позначено DESIGN/CONTRACT/USER/RSI. Виправлено historical refs AF016/024 на namespace `core`.

## Прохід 4 — Q05: відновлюваність поколінь (2026-09-10)

Перевірено final-commit межі самовдосконалення Core і переходу правил світу. Незалежне source review підтвердило наявні journals/fences, але відкинуло універсальний receipt lookup для будь-якого provider. Прийнято EV-007: monotonic ActivationBinding, serialized revoke/activation, explicit effect profiles, coherent checkpoint/rule switch і незалежний handoff при зміні самого supervisor. [Специфікація](recovery-contract.md) містить T01–08 та 16 статичних RC-сценаріїв; це не виконані crash tests.

Уточнено 9 існуючих Core-карток та AF-LW023/030, синхронізовано JSON. 65 IDs і 239 залежностей збережено. Нового читання EPUB/PDF не було; літературне coverage незмінне. Q05 закрито як design pass; наступне питання з практичною користю — Q06, паперові причинні/контрфактичні сценарії міста.

## Прохід 5 — Q06: внесок дії та чесний контроль (2026-09-10)

Паперові проходи міста виявили: накриття не сушить мокре; dry weather не виключає незалежної зустрічі; W0 бракувало власного багатокрокового провалу. Створено 10 scenario specs у Markdown/JSON, S0/R1–7 та [shared protocol](counterfactual-evaluation.md). C08 конкретизує half-action save, C09 — локальний late plan, C10 лишає сезонний місток поза W0. Full E06/E07 тепер мають material/work inputs і ReadingCompleted evidence; null-return UX не вигадує події.

Уточнено 5 Core та 5 world карток без нових IDs/edges. Core planner/evaluator comparison відділене від replay/intervention, visible authored fixtures — від holdout, domain benefit — від standalone/recursive claim. Незалежно переглянуто world causality та protocol boundaries. Не запускалися engine/provider/playtests; нового читання книжок/наукових PDF не було. Q06 закрито як paper design pass. Наступний прохід повертається до нових первинних даних: Q01, повні нові глави «Бігаючого сейфа» й перевірка гумору/ціни/невдач.

## Прохід 6 — Q01: гумор, праця й право змінити напрям (2026-09-10)

Повністю прочитано по одній новій главі кожного тому «Бігаючого сейфа»; exact нове/повторне/сукупне покриття наведене в джерельній записці та sources.json. Успішна повторна робота може не вести до потреби героя; добрий намір жарту не скасовує реакції адресата; косметична обіцянка не дозволяє прихованого functional effect. Ремонт із переданою стороннім ціною та формальна кнопка виходу не доводять відновлення.

Додано [experience criteria](experience-improvement.md) й Q01-E01–06 як відкриті статичні контроли. Уточнено 6 Core та 7 world карток, без нових IDs/edges. Core переглядає власні source/harness/evaluator/product direction через незалежне evidence й owner proposal, не через збільшення активності. Незалежне рев’ю перевірило межу domain policy, missing/withdrawn feedback та claims про повтор/економіку. Коду й реальних model/engine/human runs немає. Q01 закрито; наступний прохід — Q02: нові повні глави томів2/3 «Трансформи», стабільність ідентичності та ціна вибору.

## Прохід 7 — Q02: ідентичність і семантика переходів (2026-09-10)

Прочитано повні глави XV томів2/3 «Трансформи»: 320 абзаців / 43 434 символи тексту. Pass1 не має точного overlap ledger, тому lifetime приріст/відсоток не вигадано; pass2 не мав цих томів. Новий контекст дав збереження біографії здібності, залежності самозміни, temporary/permanent межу, persona проти особи та ресурсну ціну підтримки.

[Q02 contract](identity-continuity.md) уточнив actor_generation як incarnation, per-record ContinuityPlan, semantic grants і versioned outcome projection; 8 статичних controls не є виконаними міграціями. Статично перевірено вузькі source paths Core roles/memory. Уточнено 4 Core та 4 world картки, без нових IDs/edges чи W0 scope. Незалежне рев’ю прибрало можливість candidate самому скорочувати inventory та переозначувати immutable receipts новим decoder. Q02 завершено; наступний прохід — Q03, повні методи/limitations DGM і RQGM для fixed/evolving evaluator.

## Прохід 8 — Q03: епохи оцінювання й межа рекурсії (2026-09-10)

Прочитано методи/результати/limitations DGM v3 і RQGM v2 та релевантні технічні додатки: 68 сторінок із 110 extracted, з точними ranges/hashes, без твердження про всі listings/references. Первинна матриця відділяє повідомлення авторів від нашого дизайну; EPUB coverage незмінне, зовнішні experiments не відтворено.

[Evaluator succession](evaluator-succession.md) та Q03-E01–10 уточнюють criterion dependencies, snapshot/cutover, stale ranking без втрати історії, measurement path, непрямий test exposure, quality-conditioned evaluator labels, повні витрати й O2 comparison з прийнятим O1. Незалежне рев’ю відділило treatment A0/A1 від criterion generation та prior-access snapshot від нового access ledger. Зміна самого supervisor лишається можливою через окрему qualification; власний candidate не переписує чинну перевірку себе.

Уточнено п’ять чинних Core-карток AF-RSI020–024; 65 IDs/239 edges та scope W0 збережено. Спільний контракт узгоджено в обох продуктах, код не змінювався. Q03 завершено як primary-source/design pass. Далі Q04: повний A-Evolve v3 та перевірка меж training claims без запуску training.

## Прохід 9 — Q04: training як перевірна гіпотеза Core (2026-09-10)

Прочитано весь текст A-Evolve v3: 12 сторінок / 33 550 символів, вибрані таблиці й figures звірені візуально. Survey с.22–23 перечитані, адресні фрагменти й version chronology записані окремо. Старий v2→v3 diff не виконувався; текстові доповнення конкретної версії не вигадано. EPUB coverage незмінне.

[Training research](training-research.md) розділяє feasibility/admission/adoption, research agent і target model, reference/policy/checkpoint/serving identities, exact resume та warm start, adaptive feedback і final confirmation. Уточнено AF-RSI035 з вісьмома відкритими статичними controls та повним cost/resource envelope. Незалежне рев’ю прибрало кругову вимогу measured gain до пілоту й відділило внутрішній selection treatment від authoritative criterion revision.

65 IDs/239 edges та optional C8/незалежність W0 і standalone Core збережено. Зовнішній post-training результат не видано за виконану самоеволюцію Core; runtime/training/code не запускалися й не змінювалися. Q04 завершено як source/design pass. Далі Q07: фактичний creator шлях brief→scope→Play→feedback→restore та evidence gaps без дублювання AF-CLD.

## Прохід 10 — Q07: задум, фактична версія й відновлення (2026-09-10)

Статично простежено actual Lokiravia brief→scope→Core team gap assessment і окремі Core intake/planning/approval/delivery/recovery paths. Pin480849… звірено з dependency; десять перевірених Core source files однакові на pin і HEAD. Intake guide має застарілий інший pin. Наявність primitives відділена від caller wiring, generic completion — від actual Play, prototype draft recovery — від usable game/world/Core restore. EPUB/PDF coverage незмінне.

[Creator evolution](creator-evolution.md) визначає projection reviewed human requirements, version-bound feedback, чотири restore subjects, fidelity/assistance/missingness та окремі planning/end-to-end study prerequisites. Шість кроків paper walkthrough і Q07-P01–10 не є реальними сесіями. Конкретна ще не перевірена Core hypothesis — version-aware context selection у власному source/harness, а не приписування Core поліпшення окремої сцени.

Незалежне рев’ю розділило planned fidelity scope та realized fidelity гри й повернуло явну вимогу CLD012 про нові restore/version та audit records без переприв’язки старого evidence. Core source/pin reviewer підтвердив вузьку межу висновків.

Уточнено Core025/026, World013/025 і evidence boundary World030; чинні owners збережені, немає нових IDs/edges. Q07 завершено як source/design pass. Далі Q08: fresh non-game task families з Core defect classes, baseline/holdout і contamination policy без запуску нового продуктового коду.

## Прохід 11 — Q08: незалежність non-game задач і чесний final (2026-09-10)

Статично прочитані шість Core defect classes: stale requirements, mandatory context/dispatch, readiness binding, primary evidence, interrupted artifact adoption і Pause/unknown effects; окремо звірено historical readiness commit. Existing fixtures не названо живими інцидентами, literary/PDF coverage незмінне. Source/hash/line anchors збережені в manifest.

[Non-game evaluation](non-game-evaluation.md) замінює помилковий підрахунок шести вимірів як шести families на дві різні user-work families. Task-root/source/solution ancestry, D/S/F exposure, R0/Rn/ablation controls, finite final allowances, outcome/fault applicability та full campaign cost визначено до майбутніх запусків. Шістдесят root-pairs і repeats лишаються неперевірною без precision/resources review гіпотезою, а шість public recipes — design, не hidden corpus.

Незалежне рев’ю уточнило cumulative final-selection history, законне уникнення injected-effect boundary і точний момент interrupted candidate adoption. Усунуто неузгодженість delivery plan: повний RSI019 потребує власних harness і source змін; один mutation proof — ранній зріз. Уточнено Core003/005/007/015/030, 65 IDs/239 edges та W0/standalone scope збережено.

Q08 завершено як source/design pass. Для поточної черги лишилися Q09/Q10; прийнято рішення призупинити автоматизацію після поставки до реальних даних/profile/resources/учасників або нового дослідницького питання. Код і фактичні benchmark tasks не створювалися.

## Межа висновку

Перевірки структури, посилань, DAG і чинних контрактних validators наведено у `validation.md`. Вони засвідчують узгодженість проєктної поставки E0. E1–E5, успішна RSI, людський досвід і готова гра залишаються майбутніми доказами. Гіпотези можуть бути відхилені; backlog не вимагає назвати кожне покоління успішним.

Черга [continuation.md](continuation.md) зберігає наступні питання. Обсяг документації не є метрикою поліпшення: кожен подальший прохід має уточнити рішення або впевненість на нових підставах.
