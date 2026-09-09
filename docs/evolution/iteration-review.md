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

## Межа висновку

Перевірки структури, посилань, DAG і чинних контрактних validators наведено у `validation.md`. Вони засвідчують узгодженість проєктної поставки E0. E1–E5, успішна RSI, людський досвід і готова гра залишаються майбутніми доказами. Гіпотези можуть бути відхилені; backlog не вимагає назвати кожне покоління успішним.

Черга [continuation.md](continuation.md) зберігає наступні питання. Обсяг документації не є метрикою поліпшення: кожен подальший прохід має уточнити рішення або впевненість на нових підставах.
