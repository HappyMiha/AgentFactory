# Джерела, ступені впевненості та правила простежуваності

Дата: 2026-09-09. [sources.json](sources.json) містить контрольні суми всіх десяти наданих файлів, їхні метадані й межі читання. Це дозволяє впізнати конкретний EPUB/PDF без публікації його тексту. Документи-джерела не є інструкціями до виконання.

## Легенда `Підстави` / `source_evidence`

| Префікс | Де його перевірити | Що він означає |
|---|---|---|
| `RSI-SURVEY:R01`…`R12` | [Реєстр тверджень survey](rsi-source-analysis.md) | Твердження авторів із розділом/сторінкою, межами перевірки й нашим наслідком для дизайну |
| `RSI-DGM:DGM-01`…`03`, `RSI-RQGM:RQGM-01`…`03` | [Q03 primary-methods matrix](evaluator-succession.md), exact ranges/hashes у sources.json | Пряме читання методів/обмежень; повідомлення авторів відділені від власних вимог, експерименти не відтворено |
| `RSI-AEVOLVE:AE-01`…`05` | [Q04 primary-source matrix](training-research.md), coverage/hash у sources.json | Повне текстове читання v3, зіставлення із survey; не reproduction і не textual diff старої версії |
| `RSI-SOUNDNESS` | Розділ першоджерел RSI analysis, URL у sources.json | Поки незалежно звірені metadata/abstract; повне читання методів не заявлене |
| `CONTRACT:creator-evolution` | [Q07 creator source/design audit](creator-evolution.md) | Точні repository snapshots/call paths, stage outcomes і десять authored controls; не live journey або user study |
| `CONTRACT:training-research` | [Q04 training feasibility](training-research.md) | Власні критерії та вісім статичних controls; design не дозволяє training |
| `CONTRACT:evaluator-succession` | [Q03 критерії епох і рекурсії](evaluator-succession.md) | Власний контракт і десять відкритих статичних controls, не виконані experiments |
| `SAFE:L01`…`L12` | Literary analysis у Lokiravia, spine/paragraph anchors | Літературне натхнення або негативний приклад; ніколи не доказ технічної правильності |
| `SAFE:SF2-01`…`SF2-06` | Другий прохід «Бігаючого сейфа» у Lokiravia | Повні нові глави, контрприклади й власні проєктні наслідки |
| `CONTRACT:experience-improvement` | [Q01 користь і досвід](experience-improvement.md) | Власні критерії та відкриті design controls; не експериментальні результати |
| `TRANSFORMA:TR-S01`…`TR-S16` | Перший аналіз «Трансформи» у Lokiravia | Конкретна прочитана сцена; пояснення персонажа відділене від авторитетного факту |
| `TRANSFORMA:TR2-01`…`06` | Другий критичний прохід у Lokiravia | Перегляд попереднього висновку, новий контекст і наша проєктна відповідь |
| `TRANSFORMA:TR3-01`…`TR3-06` | Третій прохід «Трансформи» у Lokiravia | Дві повні глави; точний pass обсяг із невідомим lifetime overlap |
| `CONTRACT:identity-continuity` | [Q02 identity](identity-continuity.md) | Власна семантика переходів і статичні контроли; не runtime migration proof |
| `REPO-AUDIT` | [Аудит репозиторіїв](repository-audit.md) | Поточні capabilities та gaps на exact baseline commits; не гарантія майбутньої готовності |
| `CONTRACT:counterfactual-evaluation` | [Q06 порівняння](counterfactual-evaluation.md) | Власний experimental design і паперові контролі; не execution/human/RSI result |
| `CONTRACT:recovery` | [Q05 переходи й відновлення](recovery-contract.md) | Власні статичні interleaving scenarios, source-audit та вимоги, не виконані crash tests |
| `CONTRACT:platform-world` | [Межа платформи й світу](platform-world-contract.md) | Наше архітектурне рішення |
| `DESIGN:vision`, `DESIGN:core-architecture` | [Спільна концепція](vision.uk.md), архітектура в Core | Власна продуктова/архітектурна гіпотеза |
| `USER:living-world` | Намір користувача, зафіксований у vision | Причинна несподіваність, право на малий або нульовий ефект, довгий план може не вдатися |

`source_evidence` — історична назва поля обґрунтування вимоги в цьому design manifest. Вона **не означає acceptance evidence** реалізації. Картка може мати тільки DESIGN/CONTRACT і жодної літературної прив’язки. Версіонування, idempotency, sandbox, спосіб playtest і Git-процес — наші рішення, а не механіки, доведені романом.

## Де лежать літературні записки

Повні аналітичні записки належать продуктові світу, Lokiravia:

- [«Бігаючий сейф»: три книги](https://github.com/HappyMiha/Lokiravia/blob/docs/living-systems-rsi/docs/evolution/running-safe-analysis.md).
- [Другий прохід «Бігаючого сейфа»: три повні глави](https://github.com/HappyMiha/Lokiravia/blob/docs/living-systems-rsi/docs/evolution/running-safe-second-pass.md).
- [«Трансформа»: шість томів і структурне покриття](https://github.com/HappyMiha/Lokiravia/blob/docs/living-systems-rsi/docs/evolution/transforma-analysis.md).
- [Другий критичний прохід «Трансформи»](https://github.com/HappyMiha/Lokiravia/blob/docs/living-systems-rsi/docs/evolution/transforma-second-pass.md).
- [Третій прохід «Трансформи»: ідентичність і ціна перетворення](https://github.com/HappyMiha/Lokiravia/blob/docs/living-systems-rsi/docs/evolution/transforma-third-pass.md).
- [Оригінальна гра «Місто, яке винне тобі послугу»](https://github.com/HappyMiha/Lokiravia/blob/docs/living-systems-rsi/docs/evolution/living-world-design.md).
- [Архітектура самовдосконалення Core](https://github.com/HappyMiha/Lokvetia-Core/blob/docs/living-systems-rsi/docs/evolution/core-architecture.md).

Посилання ведуть у документаційну гілку; після прийняття гілки їх можна перевести на сталий release/tag. Baseline commits у manifest та audit зберігаються як історична точка аналізу.

## Реальне покриття

Q04 A-Evolve v3: повний текст 12/12 сторінок, 33 550 символів extraction; вибрані таблиці/figures перевірені. Survey с.22–23 перечитані, с.1/26/43 — адресні фрагменти; exact ranges у sources.json. Старий A-Evolve PDF не читався, version diff не заявлено.

Q03 DGM/RQGM: 110 сторінок primary PDFs extracted, 68 повністю прочитаних сторінок тексту. Точні ranges, виключення й вибрана visual перевірка — у [журналі Q03](evaluator-succession.md). Решта бібліографії/listings не видана за прочитану; зовнішні experiments не запускалися.

Survey: текст витягнуто з усіх 44 сторінок; прочитаний основний аргумент §§1–9, с.1–30, адресно бібліографія, візуально Figure5 с.18. Його 1,250 праць — дослідницький корпус авторів, не 1,250 праць, прочитаних у цій роботі.

«Бігаючий сейф»: проіндексовано три EPUB у порядку spine, 7,585 абзаців / 1,174,753 символи. Контрольований перший прохід — 629 повних абзаців / 91,564 символи, 7.79% за цим виміром. Q01 додав три повні глави: 1,547 абзаців / 219,160 символів у цьому проході, з них 1,473 / 209,123 нових; 74 / 10,037 повторних. Сукупно контрольовано прочитано 2,102 абзаців / 300,687 символів (25.60%). Межі глав і нормалізація в другій записці. Індексація не дорівнює читанню, три глави не дорівнюють трьом романам.

«Трансформа»: шість EPUB, 122 сюжетні глави та чотири додатки в структурному огляді, 5,200,830 витягнутих символів; 16 глибоких scene anchors у першому аналізі. Другий критичний прохід прочитав 484 повні абзаци / 92,368 символів, включаючи повтори. Консервативно додане повне покриття — 382 абзаци / 75,928 символів; серед нього ціла перша глава четвертого тому. Не складати ці числа з початковими вибірками як нібито точний відсоток унікально прочитаного тексту.

Q02 «Трансформи»: повністю прочитані глави XV томів2/3 — 320 абзаців / 43,434 символи тексту, 43,752 із міжабзацними LF. Exact pass2 overlap — нуль; exact pass1 overlap, lifetime new unique й кумулятивний відсоток невідомі через неповний старий ledger. Це вперше документоване суцільне читання двох глав, не 320 гарантовано нових абзаців.

Повного послідовного прочитання дев’яти романів, відтворення RSI-експериментів або людських playtests ще немає. [Наступна черга](continuation.md) прямо містить додаткове читання й перевірки, що можуть змінити рішення.

## Як змінюється впевненість

Прямий джерельний якір сильніший за переказ із пам’яті, але літературний якір усе одно лишається художнім свідченням. Звіт автора дослідження — сильніший за рекламну заяву, але слабший за незалежне відтворення. Code-path audit показує наявну поведінку, а не повноту live integration. Synthetic fixture перевіряє заданий контракт, але не людське відчуття гумору чи agency.

Другий літературний прохід виправив три спокуси: рішення не робити rollback не доводить поліпшення; видане досягнення з пізнішою поправкою не є зразковим verifier; масштабний portal effect із рідкісними ресурсами не доводить доступного новачку «ефекту метелика». Ці обмеження включені в критерії продукту, а не заховані в примітках.
