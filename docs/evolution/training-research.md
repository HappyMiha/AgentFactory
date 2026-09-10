# Q04: коли навчання моделі справді поліпшує Lokvetia Core

2026-09-10 · **E0 / proposed**. AF-RSI035 — необов’язковий research напрям. Поточна поставка визначає протокол; вона не дозволяє запуск навчання, витрати або deployment. Standalone Core030 і перша пригода Lokiravia не залежать від training035.

Core має вдосконалювати власні source, harness, tools, optimizer, evaluator і продуктові рішення. Навчання ваг — ще один можливий інструмент. Його доцільність встановлюється за додатковою користю для конкретної задачі Core та повною ціною. Велика модель, завершений GPU job або нижчий training loss самі такої користі не доводять.

## 1. Три різні рішення

| Рішення | Що потрібно | Що воно дозволяє |
|---|---|---|
| Feasibility / прийняти research design | Спостережувана проблема Core, доступний model/data profile, дешевша альтернатива, протокол, який може розрізнити результат | Підготувати оцінювану пропозицію пілоту; приріст ще не виміряний |
| Admit bounded pilot | Явний дозвіл на конкретні ресурси, чинні права, точні inputs/limits, зовнішня перевірка, recovery і stop policy | Один визначений експеримент у дозволеному обсязі; не adoption |
| Adopt / reject / inconclusive | Фактичні sealed receipts, порівняння з baseline, product/regression/cost outcomes та qualification | Прийняти обмежений claim; rollout потребує окремого promotion рішення |

Вимагати вже виміряного training gain до першого пілоту було б замкненим колом. До запуску оцінюється здійсненність і здатність протоколу дати відповідь; після запуску — результат. Відсутність прав/ресурсів дає `not_admitted`, недостатнє свідчення — `inconclusive`, доведений невигідний результат — `no-go`. Ці причини не змішуються з технічною помилкою run.

## 2. Початкова продуктова гіпотеза

Кожна пропозиція називає користувача Core, observed failure, task family та primary outcome: наприклад, правильне виконання tool contract або менша кількість невдалих code-repair спроб. Вона пояснює, чому проблему може вирішити training, і перевіряє frozen-weight harness-only альтернативу. Лише зростання benchmark або verbosity не є самостійною користю.

Модель/adapter, метод навчання та обсяг вибираються після перевірки доступності й достатності сигналу. Числа 30B/120B/550B зі статті не задають мінімальний розмір Core. Малий пілот також не доводить переносимості на більші моделі чи інші task families. За недостатнього бюджету для порівнюваних вимірювань звужують claim або не запускають дослід.

## 3. Що є кандидатом

Пропонуються записи поверх наявних Candidate/Experiment/Evidence контрактів, а не новий runtime API чи сервіс:

Research-agent models/harness, модель під навчанням і компонент Core, що споживатиме результат, мають окремі identities. Поліпшений зовнішній trained artifact не доводить зміни ваг дослідника або користі самому Core. Для такого claim потрібен явний integration/serving subject та перевірений Core workflow.

| Record | Незмінний зміст і межа |
|---|---|
| Reference substrate | Base model/checkpoint, tokenizer/config, reference recipe, data pipeline, trainer/evaluation environment та допустимі mutations. Це точний reference, не mutable `latest` |
| TrainingPlanManifest | Reference digest, research/controller model+harness identities, trainer version, policy/standing recipe, candidate delta, data manifests, generation/filter/dedup/split правила, seeds, caps, checkpoint-selection і evaluation protocols |
| TrainingRunReceipt | Exact plan, job/attempt identity, effective hardware/runtime, data actually consumed, reservations/charges, recovery lineage, failures і output availability |
| ModelCandidateManifest | Створений immutable output: checkpoint shards або adapter + точний base, tokenizer/config, recipe/data/run provenance, формат і compatibility. Digest фіксується після завершення artifact |
| Comparison / adoption record | Exact model+harness subject, sealed evidence, незалежний verdict, дозволений scope; deployment authority окремо |

Майбутній output hash не записують у вхідний manifest до його існування. Змінний checkpoint alias не є ідентичністю порівняння. Якщо data pipeline генерує або фільтрує дані під час run, вхід задає дозволену процедуру та джерела, а output data manifest засвідчує фактичні records/порядок/версії. Невідомий фактичний training corpus не перетворюється на валідний claim через назву dataset.

Адаптивний curriculum або schedule може бути частиною заздалегідь описаної програми. Довільна зміна worker-ом recipe поза цією програмою отримує новий plan/attempt; вона не редагує вже захешований input і не лишається прихованим продовженням старого досліду.

Reference, standing recipe і mutation — окремі об’єкти. Re-fork від спільної основи може застосовувати versioned standing recipe та дозволену memory view; це не обов’язково повтор чистого baseline. Перенесення попереднього trained checkpoint як warm start є іншим заявленим input/treatment. Результат, перенесений у search policy, не стає автоматично base checkpoint наступного run чи активною моделлю Core.

Homogeneous або спеціалізовані workers, кількість паралельних гілок і shared memory — гіпотези нашого профілю. Одна наукова конфігурація не встановлює універсально найкращу організацію агентів. На кожний candidate подається визначений input/memory view; lessons можуть зберігатися у versioned policy/experience graph, без прихованого успадкування checkpoint або test answers.

## 4. Дані, критерії та policy revision

Data manifests містять provenance, допустимий purpose, права використання, derived records, dedup/split правила та відомий exposure. Train, видимий dev, адаптивний selection feedback і final confirmation мають різні ролі. Публічний leaderboard може бути зовнішнім feedback, але повторне використання його scores для пошуку не є недоторканим final confirmation.

Access ledger охоплює data builders, diagnostic agents, summaries, optimizer memory та checkpoint selection. Synthetic дані можуть допомогти training, але їхні власні labels не є незалежним доказом generalization. Unknown pretraining overlap лишається unknown. Приватні player traces не входять у дослід через сам факт наявності їх у пам’яті Core. Наслідки expiry/revocation для вже похідних artifacts задаються до admission; видалення source record не доводить unlearning із готових ваг.

За [Q03](evaluator-succession.md) змінювати search proposal policy можна в заявленому treatment scope. Внутрішня checkpoint-selection/early-stop strategy може бути частиною optimizer candidate за тим самим зовнішнім qualification criterion; змінений plan/subject має точну версію. Якщо змінюються authoritative scoring, inclusion/task distribution, acceptance або measurement meaning, потрібні criterion revision та applicability перевірка. Candidate не послаблює власний acceptance threshold після того, як побачив результат. Оновлений поріг шуму для qualification — окрема методологічна пропозиція для наступного frozen protocol.

Падіння dev при зростанні зовнішнього outcome може бути корисним сигналом про proxy. Це не дозвіл непомітно змінити продуктову мету. Власна мета Core, budget/rights і promotion authority залишаються окремими рішеннями; [frame revision](https://github.com/HappyMiha/Lokvetia-Core/blob/docs/living-systems-rsi/docs/evolution/core-architecture.md) у Core має зовнішню потребу та автора рішення.

## 5. Порівняння та ціна відповіді

Мінімальний design розрізняє reference model+harness, frozen-weight harness challenger та training challenger. Inputs, task family, effective serving config, feedback, quality floors і resource accounting задані наперед. Для claim про ваги harness контролюється; якщо змінено обидва, результат називається bundle gain і потребує відповідних ablations для сильнішої атрибуції.

Порівняння включає dev і зовнішні outcomes, critical regressions, forgetfulness/collapse controls, latency, inference cost та operator experience у заявленому scope. Number of independent training/search runs відділена від повторних оцінок одного checkpoint; checkpoint fishing і best-of-many враховуються у selection/statistical policy. Немає універсально достатнього числа seeds або порогу приросту: precision/variance review і budget мають визначити їх до запуску.

Resource envelope задає тип/кількість GPU, concurrency, wall-clock timeout, storage/egress limits, data synthesis, agent/verification calls та правило ціни з датою. Повний ledger включає невдалі jobs, retries, checkpoints, selection, confirmation і human review, якщо воно потрібне. Планова верхня межа, фактична витрата й невирішене зобов’язання — різні поля. Time-to-first-useful-candidate не приховує решту витрат кампанії.

Caps діють і на job, і на всю кампанію. Resource profile обґрунтовує memory/storage/throughput assumptions та їхню невизначеність; невідомі величини не дорівнюють нулю. У ledger входять billed queue/idle allocation, checkpoint I/O/export та підготовка reference substrate. Зміна rolling policy може перерозподілити дозволений бюджет, але не збільшити cap чи повноваження. Без достатньої межі ресурсного зобов’язання pilot не admitted або звужується.

Окремо оцінюється обслуговування знайденої моделі. Навчання може бути економічно виправдане при повторному використанні, але break-even та амортизація мають явні припущення. Збільшення параметрів, H200 згадка або ілюстративний ratio зі статті не замінюють реального resource profile і вимірювань Core.

## 6. Довгий job, відновлення та rollout

Застосовується [Q05 recovery](recovery-contract.md). Для remote training потрібен qualified receiver profile: stable job/attempt key, доступний status/result/cancel receipt та підтверджена retry semantics. Втрата відповіді після submit не означає, що job не існує. Без lookup/idempotency гарантії повторний submit не запускається автономно; timeout не звільняє витрачений або невирішений budget.

Resume training state відрізняється від warm start із ваг. Протокол визначає необхідні checkpoint shards, optimizer/scheduler, RNG, data cursor/order, trainer/runtime/config та допустиму nondeterminism. Missing state не називають exact resume. Weights-only warm start отримує новий exact input/plan, intent та admission у межах чинного campaign budget; одного нового attempt ID під старим планом недостатньо. Він не може обійти cap або вдавати продовження контрольної траєкторії. Навіть повний state не обіцяє bitwise identity на іншому hardware без окремої перевірки.

Частковий checkpoint або cancellation request не є завершеним result/cancel receipt. Abort/Stop припиняє нові роботи в межах повноважень, але фактичний стан уже запущених jobs звіряється. Новий campaign ID не обнуляє зобов’язання. Дозволи на storage/download не поширюються автоматично на serving.

До rollout кваліфікується точна комбінація model/base+adapter, tokenizer, context/input format, quantization, inference runtime, tool-output contract і Core harness. Дослідний score іншої serving конфігурації не приймає production bundle. Rollback повертає сумісний model+harness manifest через новий activation binding; він не відновлює старі права й не стирає витрати. Q02 semantic identity та consumer constraints лишаються чинними.

## 7. Відкриті статичні контроли

Це authoring specifications для майбутньої перевірки, не виконані training tests і не прихований benchmark.

| ID | Контроль | Очікуване рішення |
|---|---|---|
| Q04-T01 | План пілоту відхиляють, бо до запуску ще немає measured gain | Feasibility/admission оцінюють власні prerequisites; adoption чекає фактичного evidence |
| Q04-T02 | Після успішного recipe policy update `default` або model alias непомітно став winner checkpoint | Exact reference/standing recipe/output identities виявляють зміну input; порівняння не названо unchanged baseline |
| Q04-T03 | Adapter з іншим base/tokenizer або частковий shard pack показав хороший dev | Model candidate/serving qualification не приймає неповний чи несумісний bundle |
| Q04-T04 | Public leaderboard або diagnostic feedback багато разів керує selection, але названий untouched final set | Exposure збережено, claim обмежено; final confirmation має незалежний протокол |
| Q04-T05 | Meta-agent після результатів знизив threshold для цього ж candidate | Current verdict лишається за frozen protocol; нова методологія перевіряється окремо |
| Q04-T06 | Submit timeout спричинив дубль job; Stop request скинув charge | Lookup/reconciliation і cap не допускають неврахованих робіт; actual costs/unknown effects збережені |
| Q04-T07 | Resume втратив optimizer/data state; новий ID приховав витрати | Warm start має нові exact plan/input та admission під чинним cap або run aborted/inconclusive; exact resume і reset budget не заявлено |
| Q04-T08 | Велика зовнішня модель має кращий loss, але її не використано в заявленому Core workflow | Окремо перевіряються model/harness/integration та product/regression outcomes проти дешевшого контролю; infrastructure/target-model evidence не доводить поліпшення дослідника чи Core |

## 8. Першоджерело та зіставлення із survey

Наведене ліворуч — стислий виклад авторських claims з [A-Evolve-Training v3](https://arxiv.org/pdf/2606.20657v3), Zhan Shi та співавтори. Праворуч — наші висновки. Стаття не є підтвердженням реалізації Core.

| Якір | Твердження джерела та локатор | Наслідок для нашого рішення |
|---|---|---|
| AE-01 | 30B Nemotron, чотири раунди, вісім workers/раунд; challenge leaderboard 0.86 проти 0.87, standing від 01.06.2026. Заявлено автономність між людською підготовкою та submission. С.1, §4 с.8, Appendix A с.12 | Survey R09 підтверджений у цьому scope. Це не поточний рейтинг, statistical parity чи matched-budget перевага над дослідниками |
| AE-02 | Незмінний default містить base checkpoint, pipeline/training/eval code; workers re-fork, rolling policy несе standing recipe/axes. Constitution незмінна; promotion — policy-only. §3 с.5–7 | Розділяємо reference, policy, trained artifact і serving adoption. Організація workers — перевірна гіпотеза, не універсальна вимога Core |
| AE-03 | Collector отримує leaderboard щораунду; constitution вже визначає його авторитетним. Proxy reversal змінює search policy; empirical thresholds revisable. Повного числового acceptance algorithm/candidate ledger немає. §3 с.7; §5 с.8–9 | Survey R10 узгоджується з policy adaptation під заданою метою. Незалежний final confirmation і пороги Core потребують власного протоколу |
| AE-04 | Table1 ratios — ілюстративні, не вимірювання; повні GPU-hours/cost ledger не наведені. 120B/550B лише в abstract: infrastructure claim без human baseline та окремих run details. С.1–2, перевірка решти с.3–12 | Feasibility масштабу не доводить quality або економіку. Зовнішні числа не приймають наш resource envelope |
| AE-05 | Одна нереплікована кампанія, одна task family/leaderboard; full code/substrate/checkpoint release ще не визначений. §6.1–7 с.9–10 | Власні продуктова перевірка, noise/selection control і reproduction evidence залишаються потрібними; успіх не гарантується |

## 9. Версії та точне покриття

[Історія A-Evolve](https://arxiv.org/abs/2606.20657) вказує v1 09.06, v2 25.06, v3 **08.09.2026**. [Наданий survey v2](https://arxiv.org/abs/2607.07663v2) опубліковано **06.09.2026**. Його ref180 має unversioned URL. Тут зіставлено зміст survey із повним v3; старий A-Evolve PDF не читався й textual v2→v3 diff не виконувався. Відсутню в survey деталь не називаємо новою у v3; невідомо, яку попередню версію використали автори survey.

Офіційний primary PDF завантажений локально, без передачі наданих користувачем файлів сторонньому сервісу. SHA-256: `6914910acf4267f2d8280eb0371a73b438408b71b44e08ea6b12a16ec3704db7`. Текст усіх **12/12 сторінок**, включно з references і Appendix A, extracted та повністю прочитаний: **33 550 символів** у pypdf extraction. Це перше документоване повне текстове читання цього primary PDF; повторне читання різними reviewers не множить coverage. Візуально перевірені Table1 с.2, Figure2 с.6, Figure3 с.8, Table2 с.12; не всі деталі кожної ілюстрації перевірені.

Survey с.22–23 перечитано повністю; с.1/26/43 — тільки точні фрагменти, зафіксовані в [sources.json](sources.json). Це повторне читання вже опрацьованого основного тексту та адресна бібліографічна перевірка, не нові повністю прочитані сторінки. Точний lifetime overlap старих бібліографічних фрагментів не відновлюємо здогадом. EPUB coverage у Q04 не змінене.

Ні кампанію авторів, ні training Core не запускали; upstream code та checkpoint не аудіювали. Source instructions аналізувалися як дані. Raw PDF/extracts/приватні ledger лишаються поза Git. Q04 завершується цим research design; наступне питання Q07 повертається до чинного creator шляху brief→scope→Play→feedback→restore.
