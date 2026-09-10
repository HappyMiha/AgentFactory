# Перевірка документаційної поставки

Дата: 2026-09-09. Обсяг — E0: узгодженість концепції, архітектури й портфеля. Нового продуктового коду немає; ігрові engines, provider experiments, model training та rollout не запускалися.

## Структурні перевірки нового портфеля

Перевірено обидва `backlog.md` і `backlog.json` разом:

- 65 унікальних qualified IDs: 35 Core, 30 Lokiravia; всі proposed.
- 239 dependency edges; невідомих IDs, повторних edges і циклів немає.
- Outcomes, acceptance, негативні сценарії, артефакти, підстави та точні залежності текстових карток збігаються зі структурованим JSON.
- Historical reuse IDs існують у чинних manifest; AF/AF-AMM/AF-GC належать Core, AF-CLD — Lokiravia.
- Standalone Core030 має рівно 29 Core prerequisites001–029 і жодного Cloud/world dependency.
- World030 має 11 світових і 10 Core prerequisites; у ньому немає full-world acceptance, людського multiplayer, повної Core RSI або training.
- Джерельні SAFE/TR/RSI IDs існують у відповідних записках. Їхню семантичну доречність додатково переглянуто незалежно; це не перевірка достовірності всіх художніх пояснень.
- Відносні Markdown-посилання й парність fenced blocks перевірено. Десять спільних файлів між репозиторіями побайтово однакові.
- Сукупний diff від audit baselines обмежений README та `docs/evolution/`, тільки `.md`/`.json`. Чинні runtime manifests, код і dependency pins збережені. `git diff --check` пройдено.

Структуру перевірено локальним допоміжним скриптом поза репозиторіями; його не видано за нову runtime capability. Тексти карток є джерелом змісту; JSON синхронізовано з ними. Процедура перевірки для наступного проходу: зіставити всі поля, з’єднати qualified dependencies двох manifest, перевірити acyclic graph і наведені closures, звірити reuse із чинними manifest, джерела зі словником, relative links із файлами та scope через Git.

## Чинні repository validators

| Перевірка | Фактичний результат | Межа |
|---|---|---|
| Core `scripts/validate-game-creator-backlog.py` | Passed: 47 items / 43 executable, schema-v2 round-trip, labels, references, DAG, milestone order, release gates, roadmap agreement | Планувальна узгодженість старого беклогу, не завершення tasks |
| Lokiravia `scripts/validate_engine_target_pack.py` | Passed: 18 synthetic operation results | Engine не запускався; live target не кваліфіковано |
| Lokiravia `scripts/validate_evidence_gates.py` | Passed: 13 synthetic scenarios / 5 separate gates | Жодний реальний build не прийнято |

Ці checks відповідають документаційній зміні. Повний runtime test suite не потрібний для висновку, що концепція записана узгоджено, і його не запускали заради вигляду ширшої перевірки.

## Q05, 2026-09-10

Повторно перевірено парність Markdown/JSON, unchanged 65 IDs/239 edges, DAG/closures, legacy refs, relative links, docs-only scope та whitespace. Recovery contract дзеркально однаковий у двох репозиторіях. Незалежне source review і interleaving review уточнили final-commit, external effect і control-process handoff semantics. T01–08 та RC01–16 перевірено як статичні специфікації, а не виконано проти runtime. Чинні validators повторені для цієї документаційної редакції з тими самими межами synthetic evidence.

## Q06, 2026-09-10

Перевірено 10 унікальних paper scenario IDs та парність їхніх полів Markdown/JSON, межу W0/extended і valid control references. Це schema/authoring consistency, не виконання expected traces. Повторно перевірено backlog parity, 65 IDs/239 edges, DAG/closures, legacy/source refs, links та docs-only scope. Shared counterfactual-evaluation.md однаковий у двох репозиторіях. Незалежне рев’ю перевірило temporal/causal assumptions та допустимі claims Core. Чинні static/synthetic repository validators повторені; engine і model runs не виконувалися.

## Q01, 2026-09-10

Джерельне coverage перераховане за множинами spine/paragraph anchors проти незміненого pass1 ledger; file hashes і точні межі трьох глав перевірені. Перевірено Markdown/JSON parity, 65 IDs/239 edges, DAG/closures, source/legacy refs, links, shared docs і docs-only scope. Q01-E01–06 — статичні authoring controls, не зіграні сцени чи виконані Core experiments. Релевантні чинні repository validators повторені з їхніми попередніми static/synthetic межами.

## Q02, 2026-09-10

Дві повні глави звірені з original EPUB XML/NCX і hashes. Paragraph-text/LF counts розділені; невідомий pass1 overlap збережено як unknown, не нуль. Перевірено source manifest parity, Markdown/JSON, 65 IDs/239 edges, DAG/closures, refs/links, shared docs і docs-only scope. Q02-I01–08 — authored static controls; source audit обмежений roles/memory paths, не повним execution stack. Чинні repository validators повторені з їхніми static/synthetic межами; model/engine/human runs не виконувалися.

## Q03, 2026-09-10

PDF hashes, pypdf metadata/version/page counts і exact reading ranges звірено з приватними ledger; extraction відділена від читання. Перевірено шість primary-source anchors, десять унікальних static controls, source manifest parity, Markdown/JSON, unchanged 65 IDs/239 edges, DAG/closures, refs/links, 15 identical shared docs та docs-only scope. Незалежні рецензії звірили джерельні межі й criterion/treatment/access/activation semantics. Чинні repository validators повторені з їхніми static/synthetic межами. Q03-E01–10 не виконувалися проти runtime; Core, model, engine, training та human experiments відсутні.

## Q04, 2026-09-10

Звірено PDF hash/version/page count, 12/12 full-text pages і 33 550 extraction characters; два reading ledgers узгоджені, повторне читання не множить coverage. Survey ranges/hash і version chronology перевірені; старий A-Evolve textual diff відсутній. Перевірено п’ять source anchors, вісім static controls, Markdown/JSON parity, 65 IDs/239 edges, DAG/closures, refs/links, 16 shared identical docs та docs-only scope. Чинні validators повторені з їхніми static/synthetic межами. Q04-T01–08 не виконувалися; навчання, serving і людські експерименти не запускалися.

## Q07, 2026-09-10

Звірено 24 cited source files на exact repository snapshots: commit/blob/content hashes, наявність line anchors та actual consumer pin. Десять перелічених Core source files однакові на pin і audited HEAD; caller qualification і повна рівність репозиторію з цього не випливають. Перевірено 11 source-matrix anchors, шість paper steps і десять унікальних authored controls. Це authoring/source consistency, а не виконання expected outcomes.

Уточнено лише Core025/026, World013/025 і evidence boundary World030; titles/status/phase/priorities/dependencies збережені. Markdown/JSON parity, 65 IDs/239 edges, DAG/closures, legacy/source refs, relative links, 17 identical shared docs, whitespace та docs-only scope пройшли перевірку. Незалежні Core/World/product рецензії звірили фактичні call paths і закрили зауваження до planned/realized fidelity та restore version/audit/evidence identity.

Чинні validators повторені: Core — 47 items / 43 executable, World — 18 synthetic engine-operation results та 13 synthetic evidence scenarios / 5 gates. Source/browser/runtime tests цього creator шляху тільки прочитані, не запускалися. Q07 не виконував app/model/engine/provider/training/user experiments і не збільшував literary/PDF coverage.

## Q08, 2026-09-10

Звірено 14 cited Core source/test files на exact snapshot: commit/blob/content hashes і line anchors; окремо перевірено SHA, дату й subject історичного readiness commit. Шість failure classes відділено від live incident claims. Перевірено дві user-work families, шість public development recipes і десять authored controls; реального task corpus/final set не створено, їхні outcomes не виконувалися.

Змінено п’ять чинних Core карток003/005/007/015/030; World-картки незмінні. Markdown/JSON parity, 65 IDs/239 edges, DAG/closures, titles/status/phase/priorities/dependencies, refs/links, 18 identical shared docs, docs-only scope та whitespace пройшли перевірку. Незалежне рев’ю закрило cumulative final-history, semantic fault applicability і точність interrupted adoption boundary; уточнення harness AND source gate019 не змінює залежностей.

Чинні validators повторені: Core47/43, World18 synthetic engine-operation results та13 synthetic scenarios/5 gates. App/model/provider/engine/training/user runs і повторне виконання source/browser/runtime tests цього аудиту не проводилися. Literary/PDF coverage незмінне. Рішення про паузу автоматичних проходів зафіксоване після завершення доступної Q01–Q08 черги; це не acceptance продуктів.

## Незалежне рев’ю

Окремі рецензії перевірили архітектурні повноваження, lifecycle і recursive claim; standalone/MVP залежності; семантичне походження літературних прив’язок. Усі конкретні зауваження враховані в [журналі виправлень](iteration-review.md). Другий прямий літературний прохід додав контрприклади та змінив критерії приймання.

Ця поставка не доводить зростання якості Core, довгострокової стабільності RSI, ринкового попиту чи задоволення гравців. Для цих висновків портфель задає майбутні протоколи, зовнішні докази та критерії no-go.


## D01 — анонімізація поточного дерева

Перевірки: дев’ять source identities без назв/авторів/імен файлів; незмінні SHA-256, bytes, Q01/Q02 coverage; парність джерел в обох репозиторіях; нові літературні шляхи й anchors; відсутність ebook-файлів; ignore guards із позитивним контролем продуктового PDF. Посилений пошук ловить стару назву корпусу в приватному шляху й назву книги в chapter anchor. Перевірка доступної історії не виявила наданих книжкових файлів, але історичні бібліографічні згадки зберігаються. Продуктовий runtime не запускався.
