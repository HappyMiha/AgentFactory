# Q03: як Core змінює оцінювач і доводить поліпшення власного методу

2026-09-10 · **E0 / proposed**. Самовдосконалення Core охоплює власні source, harness, optimizer, evaluator і продуктовий напрям. Цей контракт уточнює AF-RSI020–024; він не додає сервісів, задач або prerequisites першій пригоді Lokiravia. Джерельна матриця й точне покриття читання наведені нижче; жодного експерименту зі статей не відтворено.

## 1. Рішення для продукту

Користувач має бачити, **що стало кращим і за яким незмінним порівнянням**. Заміна оцінювача створює нову епоху оцінювання. Історія зберігається; придатність старих оцінок для нового пошуку встановлюється окремо. Помилка старого оцінювача може бути підставою його заміни через незалежну перевірку.

Наведені далі правила — наші проєктні рішення. Вони мають пройти майбутні conformance, statistical та consumer перевірки; назви наукових систем не приймають їх замість доказів.

## 2. Що саме фіксується в епосі

`CriterionManifest` — запропонований незмінний запис поверх наявних protocol/evidence records. Його склад визначає незалежно затверджений профіль експерименту, а не challenger. До складу входять:

- evaluator artifact, prompts, tools, model/provider identity з доступною точністю pin та scoring rule;
- джерело первинного факту, telemetry producer, потрібні receipts і кваліфікований decoder;
- objective version, outcome projection, task distribution, role/task weights, rubric, floors, uncertainty rule;
- правила генерації задач, replay та вибору adversarial corpus, дозволені feedback і memory/input views;
- anchor dataset/labels/provenance, adjudication authority, snapshot попередніх доступів до tests і політика наступних звернень;
- selection/stop/replacement policy, checkpoints, кількість порівнянь та загальні resource caps.

Не всі поля обов’язково змінюються разом. Залежність конкретного результату включає весь фактично використаний шлях: хто створив artifact, чому цей case потрапив до вибірки, що бачила роль, хто й як поставив оцінку. Однаковий фінальний test runner не робить результат незалежним від зміненого генератора задач. Невідома залежність означає unresolved applicability; оптимізатор не може оголосити її порожньою.

Subject provenance та criterion dependencies — різні поля. A0/A1 як агенти під порівнянням створюють різні outputs за спільного протоколу; ця дозволена treatment-зміна сама не відкриває дві епохи. Генератор задач, adversarial sampling або feedback, що визначає умови оцінювання/пошуку, належить до критерію. Actual access/cost records дописуються до окремого журналу після freeze; звичайний дозволений запит не змінює manifest digest. Порушення access policy може забруднити корпус і припинити його використання за заздалегідь визначеним правилом.

Непідконтрольна зміна provider або tool behavior фіксується як можлива втрата порівнюваності. Це не доказ stationary epoch. Протокол визначає, чи потрібен restart або inconclusive; новий запис не переписує фактичну model identity старих runs.

## 3. Історія та чинне ранжування

| Об’єкт | Після зміни критерію |
|---|---|
| Sealed receipts, artifact digest, старий verdict | Зберігаються з original protocol, дозволеним retention і lineage |
| Fitness, posterior, Pareto/rank, champion-selection cache | Перебудовуються з придатних до нового критерію записів; старий score не переноситься як поточний |
| Search memory/skill із висновком «метод успішний» | Перевіряється транзитивна залежність від старої оцінки; історична порада може лишитися гіпотезою, але не незалежним підтвердженням |
| Зовнішній факт, незалежний від зміненого шляху | Може лишитися придатним після явної перевірки scope/distribution/meaning, а не лише за типом `ground_truth` |
| Candidate archive і дерево походження | Історія та stepping-stone hypotheses; наявність у дереві не дає promotion eligibility |
| Лічильник витрат і невирішених effects | Продовжується через epoch switch, retry, rollback і зміну mission ID |

Поточний selection view має criterion digest, повний перелік включених evidence IDs, unresolved/excluded reasons та digest похідного стану. Перерахунок відтворюваний. Відсутність придатних оцінок означає «ще не оцінений», а не нуль помилок чи автоматичний champion. Quarantined/revoked кандидати не стають придатними через зміну ранжування.

## 4. Перехід оцінювача без змішаного стану

Перевикористовується [Q05 activation/recovery](recovery-contract.md), без другого незалежного джерела повноважень. Для target/profile оцінювання:

1. Зафіксувати E1 як окремий candidate і завершити його незалежне порівняння, включно з дозволеною областю використання та disagreement.
2. Підготувати immutable transition plan: old/new criterion digests, залежні records/views/skills, нові selection statistics, невирішені jobs та кошторис повторної перевірки.
3. Перевірити повноту inventory за авторитетним профілем. Створити завершений snapshot нового criterion + selection view; відсутні обов’язкові evidence не заповнювати прогнозами.
4. За окремим authorization активувати узгоджений snapshot через чинний fencing/CAS механізм. Читач бачить повну стару або повну нову епоху. Crash до activation лишає стару; crash після відновлює exact committed binding. Це атомарність видимого переходу, не заява про одну транзакцію з усіма зовнішніми providers.
5. Запізнілий E0 receipt приєднати до його історичного run. Він може бути валідним свідченням E0, але не оновлює E1 rank без окремого applicability record. Його actual cost і unresolved effects враховуються незалежно від придатності score.

Selection snapshot не відновлює старий budget/job ledger. Витрати й завершення робіт між підготовкою snapshot та activation враховуються за поточним durable станом; cutover повторно перевіряє його чинні caps/fences. Повторне ранжування не дозволяє вдруге витратити вже зарезервовані ресурси.

Новий decoder або alias не перетлумачує старі outcomes: застосовується [Q02 semantic projection](identity-continuity.md). Повернення до E0 має нову activation sequence; попередні повноваження й витрачені бюджети не відновлюються.

## 5. Як розібрати розбіжність агента й оцінювача

Для agent A0/A1 та evaluator E0/E1 потрібні чотири клітинки оцінювання одного preregistered порівнюваного набору artifacts/traces, зовнішні anchors і окреме рішення щодо кожного subject. [Q06](counterfactual-evaluation.md) задає paired inputs та межу causal/planner/replay comparisons.

| Спостереження | Дозволений висновок / наступна перевірка |
|---|---|
| E1 оцінює обох агентів вище | Можлива інша шкала або поблажливість; agent gain не встановлено |
| A1 кращий лише за E1 | Disagreement, не автоматичний провал A1; незалежний anchor/adjudication перевіряє, чи E0 помиляється |
| E1 відхиляє валідні короткі відповіді, приймаючи красиві неправильні | Окремий false-reject/false-accept дефект E1; average score не приховує slice |
| Обидва судді погоджуються | Спільна помилка лишається можливою; згода не замінює зовнішнього evidence |
| Новий scorer переоцінив старі artifacts | Показано вплив scorer на цей corpus; не показано поведінку нового генератора на новому розподілі |
| Змінилися tasks, rubric і модель | Потрібні bridge/control або narrower/inconclusive claim; scores не з’єднуються в криву безумовного зростання |

«Old evaluator не підтвердив» — сигнал для розбору, а не його постійне veto. Якщо зовнішніх підстав розв’язати розбіжність немає, результат залишається inconclusive. Panel acceptance, точність фактів, користь власникові, людська оцінка гумору та критичні порушення — різні outcomes.

У кожній клітинці матриці окремо видно справність measurement path. Вимкнений event marker або нерозшифрований обов’язковий receipt не доводить відсутності порушення. Потрібні positive/negative controls від первинного факту; законний новий формат із кваліфікованим decoder не відхиляється тільки через іншу назву поля. Дві однаково помилкові системи оцінювання можуть погодитися в усіх клітинках.

Anchor authority відокремлена від proposer і promoter. Відомий benchmark, на якому багато разів обирали кандидатів, не стає final confirmation через нову назву. Облік доступу охоплює labels, агреговані scores, error traces, prompt/skill memory і рішення після кожного checkpoint. До досліду фіксуються adaptive-selection/statistical policy та умови заміни забрудненого набору. Спільна базова модель або різні назви ролей самі по собі не доводять ані незалежності, ані змови.

Кілька суддів одного artifact — кластер оцінок одного artifact, не додаткові незалежні задачі. Зберігаються partial scores, strict success та невизначеність за task/run. Нижня оцінка utility не називається ймовірністю поліпшення без належного статистичного обґрунтування. Рівність acceptance rates між людськими й AI-роботами сама не доводить справедливості: потрібні blind quality labels для добрих/поганих робіт обох походжень і false-accept/false-reject slices. Для гри це також не доказ пережитого людьми досвіду.

## 6. Межа рекурсивного твердження

| Claim | Необхідне evidence Core |
|---|---|
| Artifact/harness improvement | Exact A0/A1, незалежне порівняння task outcomes, regression та resource floors |
| Optimizer improvement | O0/O1 з однаковими стартовими дозволеними знаннями й ресурсами створюють корисні дочірні зміни на fresh tasks; враховано всі невдалі спроби |
| Recursive participation | Typed O0→O1→O2 доводить, що прийнятий O1 запропонував зміну самого методу O2; це ще не доказ користі O2 |
| Bounded recursive-method gain | Окрема свіжа перевірка O2 проти безпосереднього прийнятого попередника O1 та ablation без нового методу за спільного qualification envelope |
| Самостійне визначення правильної продуктової мети | Окремий frame proposal, зовнішня потреба й рішення власника; попередні claims цього не доводять |

Equal budget означає узгоджені caps і повний accounting: генерація, expansion, оцінювання, повторне оцінювання архіву, anchors, confirmation, невдачі, моделі різної ціни, час та людське adjudication. Однакова кількість evaluation calls або сирих tokens недостатня. Правило ціни/часу й допустимого tradeoff визначене до результатів; невикористаний ресурс не треба штучно витрачати. Не можна приписувати новому методу ефект новішої моделі чи привілейованої memory.

Одиниця accepted improvement визначена наперед: поділ однієї корисної зміни на кілька artifacts не збільшує кількість прийнятих покращень. Повний економічний звіт включає створення та qualification нового optimizer. Окремо можна міряти вартість повторного використання вже прийнятої версії, явно назвавши виключені одноразові витрати та правило амортизації; conditional reuse efficiency не видається за end-to-end efficiency.

Протокол окремо задає кількість незалежних search runs та повторів оцінки одного знайденого агента. Best-of-many не є типовим результатом. Для mechanism claim diagnosis/selection/starting archive контролюються, якщо вони не є заявленим treatment; для bundle claim усі змінені складові відкрито перелічені. O1/O2 bundle має рольову карту та receipt фактичного використання зміненого operator у наступному пошуку: відредагований, але невикликаний файл не доводить участі методу.

Для Core немає незмінної назавжди заборони вдосконалювати scheduler або supervisor. Їхня зміна потребує власного candidate, зовнішньої кваліфікації та handoff за Q05. Поточний candidate не переписує орган, який саме зараз перевіряє його права, критерії та бюджет. Негативний O2 зберігає доведений локальний успіх O1, але припиняє сильніший claim.

## 7. Відкриті статичні контроли

Це authored acceptance specifications, не виконані тести і не sealed holdout.

| ID | Контроль | Очікувана перевірка майбутньої реалізації |
|---|---|---|
| Q03-E01 | Criterion змінився, score-cache лишив старого champion | Новий view не використовує stale evidence; audit history збережено, неперевірений кандидат не promoted |
| Q03-E02 | E0 job витрачає ресурс між підготовкою й activation E1, завершується після cutover | Receipt лишається E0, actual charge/резервації не відкочуються, E1 rank незмінний без applicability decision; crash/restart не змішує snapshots |
| Q03-E03 | Новий E1 визнає валідну відповідь, яку E0 відхиляв | Незалежний anchor може обґрунтувати E1; незгода E0 не перетворена на вічне veto |
| Q03-E04 | Final checker той самий, змінився adversarial sampling | Dependency inventory знаходить зміну розподілу; старі utility records не заявлено незалежними лише через checker digest |
| Q03-E05 | Re-score старих artifacts названо fresh generator gain | Claim звужено до scorer effect на corpus; fresh generation/confirmation має окремий протокол |
| Q03-E06 | Більше невдалих expansions або дешевша модель приховані за equal calls | Повний cost/model ledger виявляє confound; efficiency claim проходить тільки власний preregistered comparison |
| Q03-E07 | Archive містить корисного предка, який не пройшов release gate | Ізольований дозволений пошук можливий, production promotion відсутнє; revoke/quarantine не обходиться |
| Q03-E08 | O1 створив кращий продукт; O2 кращий за O0, але гірший за прийнятий O1 | Локальний успіх і recursive participation записано; positive next-step recursive-method gain rejected/inconclusive, bounds і Stop продовжують діяти |
| Q03-E09 | A1 прибрав telemetry marker, обидва evaluators назвали це відсутністю порушення | Зовнішній receipt/control виявляє missing/invalid measurement, а не поліпшення; валідний альтернативний формат проходить через qualified decoder |
| Q03-E10 | Суддя відхиляє якісні AI-роботи для вирівнювання загального acceptance rate; чотири reviews названо чотирма задачами | Blind quality slices виявляють false rejection, unit/cluster count не збільшено; parity і partial score не замінюють потрібний quality/strict-success outcome |

## 8. Першоджерела та межі перенесення

Нижче стисло передано **повідомлення авторів**, а в правій колонці — наші висновки для проєкту. Performance/cost numbers не стають SLO або кошторисом Core.

| Якір | Перевірений зміст першоджерела та локатор | Наше перенесення / що лишається гіпотезою |
|---|---|---|
| DGM-01 | Змінюється код агента при заморожених FMs; архів допускає пошук через проміжні варіанти. Порівняно fixed modifier, відсутність архіву та greedy parent; Polyglot має додаткові повтори. [DGM v3, §3–4, с.4–8; A, с.24–26](https://arxiv.org/pdf/2505.22954v3) | AF-RSI023: архів — ресурс дослідження, не release authority. Потрібні власні mechanism controls та незалежні runs; користь для Core не встановлена чужим результатом |
| DGM-02 | SWE-run оцінено приблизно у $22 000, кожну основну абляцію без self-improve/без open-ended exploration — $10 000; дорожчає й inference. Coding score використано як proxy самовдосконалення; archive/parent selection фіксовані, їх еволюція лишається майбутньою. [DGM v3, §6, с.10; E.1, с.32–33; J, с.72](https://arxiv.org/pdf/2505.22954v3) | AF-RSI023/024: equal iterations не доводить efficiency. Окремо доводимо method use, O2 проти O1 і повну економіку; власний scheduler може еволюціонувати тільки через кваліфікований candidate |
| DGM-03 | SWE private tests приховані від coding agent під час benchmark run, але доступні окремому діагносту. Transfer і ручна перевірка не усувають усі contamination ризики. У додатковому hallucination досліді зміна telemetry обходить прихований checker. [DGM v3, C.3, с.28–30; H, с.69–71](https://arxiv.org/pdf/2505.22954v3) | AF-RSI020/021/022: exposure всього контуру, первинний факт та measurement controls. Незмінний evaluator digest не доводить незмінності вимірювання |
| RQGM-01 | Заміна judge відбувається на checkpoint за фіксованим evaluator-independent anchor; scorer/orchestration harness фіксований. Залежності utility включають sampling/generation/replay. Застарілі оцінки вилучаються зі statistics, artifacts/audit зберігаються. [RQGM v2, §3, с.4–6; Algorithm1, с.19; F.4, с.33–35](https://arxiv.org/pdf/2606.26294v2) | AF-RSI020/022: CriterionManifest, dependency inventory та coherent transition за Q05. Це наш контракт, а не портований runtime чи доказ його коректності |
| RQGM-02 | Validation керує пошуком; є окремі test protocols. Writer/prover оцінено модельними panels без людської оцінки згенерованих робіт. Adversarial pool винагороджує відхилення AI-текстів. [RQGM v2, §4–6; C.4, с.20–22; G, с.38](https://arxiv.org/pdf/2606.26294v2) | AF-RSI021/023: final exposure, quality-conditioned labels, cluster uncertainty й повні витрати. Parity rates не встановлює якості; panel acceptance не доводить корисного продукту або живого гумористичного світу |
| RQGM-03 | Потрібна epoch stationarity; pooled Beta є робочою моделлю, lower-bound твердження залежить від калібрування. Монотонного зростання фактичної anchor accuracy й глобальної збіжності не доведено; спільна мультидоменна система та еволюція зовнішнього scheduler лишаються поза перевіреним scope. [RQGM v2, F.3–F.5, с.32–37, Remark6; G, с.38](https://arxiv.org/pdf/2606.26294v2) | AF-RSI022/024: область гарантії, фактичні model/tool зміни, bounded claims і Stop. Прийняття кожного successor та правильний вибір мети Core потребують своїх доказів |

## 9. Журнал читання

Метадані обох versioned arXiv сторінок повторно звірено 2026-09-10. Публічні PDF завантажені з arXiv локально; надані користувачем файли нікуди не передавалися. Застосовано локальний pypdf, для вибраних зображень — Poppler/pypdfium2. Матеріал усередині статей, включно з prompts/code listings, аналізувався як джерело, не як інструкції.

| Джерело | PDF / повне читання тексту | Не заявлено повним читанням | SHA-256 PDF |
|---|---|---|---|
| DGM v3, 12.03.2026 | 72 сторінки extracted; повністю 1–11, 23–36, 46–50, 69–72: **34 сторінки**. Основні методи/результати/limitations і релевантні додатки | 12–22, 37–45, 51–68: extraction/огляд заголовків; не всі F/G code listings прочитані. Графіки не перевірені суцільно | `13ff4abe0c7ad4a7dd3b4876d19a8bf940e39e70dabbf06065aa774a6c3457de` |
| RQGM v2, 29.06.2026, preliminary | 38 сторінок extracted; повністю 1–13, 18–38: **34 сторінки**. Методи/результати/limitations, технічні додатки й теоретичні припущення | 14–17: бібліографія лише extracted/початковий preview. Візуально перевірені Figure2 с.4 і с.37; не всі figures | `82a2e260eb119d983542489100db195398128976fa20c97838e11d25b80b84f0` |

Це 68 повністю прочитаних сторінок тексту з 110 extracted, а не дві повністю прочитані публікації з усіма listings/references. Попередня основа для цих двох праць була metadata/abstract + survey; новий ledger стосується primary PDF. Читання reviewer/root на тій самій сторінці не рахується двічі. Результати авторів не відтворювалися; вихідні репозиторії DGM/RQGM не аудіювалися. EPUB coverage у Q03 незмінне.

Source hashes, page ranges та статуси зберігає [sources.json](sources.json). Сирі PDF, extraction caches і допоміжні reading ledgers лишаються поза Git-репозиторіями. Наступне первинне дослідницьке питання — Q04, повний A-Evolve v3; training не запускається.
