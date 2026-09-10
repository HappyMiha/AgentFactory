# Q06: що саме доводить порівняння двох проходів

Спільний проєктний протокол · 2026-09-10 · **E0 / proposed**. Документ відділяє причинну перевірку світу від самовдосконалення **самого Lokvetia Core**. Паперові сценарії не виконувалися проти engine чи model provider. Джерела: [чинна концепція](vision.uk.md), [RSI: межі claims](rsi-source-analysis.md), [межа платформи й світу](platform-world-contract.md), [recovery](recovery-contract.md).

Конкретний авторський набір — [десять сценаріїв міста](https://github.com/HappyMiha/Lokiravia/blob/docs/living-systems-rsi/docs/evolution/causal-scenarios.md) та його [JSON](https://github.com/HappyMiha/Lokiravia/blob/docs/living-systems-rsi/docs/evolution/causal-scenarios.json). Ці відкриті картки є development/design evidence, а не прихованим test set. Вони уточнюють вимоги; не доводять, що майбутній Core уже кращий.

## 1. П’ять різних питань

| Вид перевірки | Що фіксується | Що змінюється | Який висновок допустимий |
|---|---|---|---|
| Replay | Прийнята історія, rules, recorded inputs/random decisions, declared state envelope | Лише запуск відновлення/відтворення | Та сама історія відновлена в заявленій області; не кращий planner |
| Action intervention | Initial state, rules, зовнішні умови, політики інших actors | Одна названа дія або player action policy; її downstream effects перераховуються | Причинний внесок дії **в цій моделі й контексті** |
| Input sensitivity | Правила, player policy і контрольовані інші inputs | Погода, початкова вологість, availability або інша названа умова | Чи вимога витримує зміну умови; це не автоматично ефект player action |
| Planner comparison | Task/goal, initial observable inputs, rules, permission/time/cost envelope, exogenous profile | Exact Core planner/harness/source candidate; його дії й залежні рішення можуть різнитися | Кандидат корисніший на цьому протоколі лише після незалежного виконаного порівняння |
| Evaluator comparison | Один frozen artifact/trace corpus, blind order, зовнішньо adjudicated labels і uncertainty | Exact evaluator version | Краща якість оцінювання corpus у заявлених slices; не автоматично кращий planner чи гра |

Пара C01/C02 змінює дію при тому самому дощі. C03 додає dry-weather контроль і показує, що meeting може відбутися без накриття. C04/C05/C06 змінюють передумови. C08 порівнює recovery paths. C09 перевіряє конкретний запізнілий план, а не примушує реального гравця програти. Підміна цих питань однаковим заголовком «before/after» робить висновок неоднозначним.

## 2. Ключ пари і заборона підміни наслідків

`ComparisonPair` як design record містить: protocol/version, case family/version, initial state digest, goal/constraint digest, observable-view policy, exogenous tape/profile, random coupling plan, action/subject intervention, horizon, budgets, baseline/challenger identities, expected artifact roles та run references. Два різні inputs не стають paired лише від однакового case name.

У planner comparison baseline P0 і challenger P1 мають однакові **початкові доступні їм** спостереження; їм не підкладають прихований стан NPC лише для кращого результату. Після різних дій їхні нові спостереження можуть законно відрізнятися. Ця відмінність — частина результату, а не причина примусово підганяти гілки до однакової історії.

Після втручання перераховуються вологість, маршрути, присутність, пропозиції й реакції, що залежать від зміненого стану. Не можна прибрати парасолю, але залишити з baseline готові downstream рішення NPC «сидіти на сухій лавці». Прийняті events незмінної replay-гілки використовуються тільки для replay; вони не є готовою відповіддю для нового causal branch.

Погода чи незалежне прибуття можуть бути exogenous у малому профілі. У майбутній грі, де гравець може змінити погоду або транспорт, той самий input перестає бути незалежним. Protocol декларує causal boundary; не приписує глобальної незалежності всім подіям зі словом weather/arrival.

## 3. Випадковість без прихованої підгонки

Один числовий seed не гарантує коректної пари: різні плани можуть викликати різну кількість випадкових рішень. Спільний stream, зміщений додатковою реплікою, здатен порівняти різні зовнішні обставини замість двох planner versions.

У deterministic paper profile S0/R1–R7 випадковість не потрібна. Майбутній stochastic profile до запуску визначає: незалежні stream roles, keys для зіставних decision events, distributions/rule versions, occurrence identity, horizon і policy unmatched draws. Спільний random input можна зіставляти лише для заявлено порівнюваних подій; нова дія, що змінила умови чи ймовірності, має перерахувати наслідок за новими умовами. Не слід примусово зберігати той самий outcome лише тому, що draw був paired.

Неспівставні downstream випадкові рішення мають окремі inputs; вони не приховуються й не оголошуються «тим самим seed». Аналіз показує, які частини paired, а які stochastic/unmatched. Ефект спроби оцінюється в межах цього coupling plan; для узагальнення потрібні наперед визначені незалежні повтори й невизначеність, а не одна вдала гілка.

## 4. Від goal до outcome без культу каскаду

Перед спробою визначено actor goal, права, відомі обмеження й умови виконання. У кожного результату окремі поля:

| Поле | Що спостерігаємо |
|---|---|
| Physical effect | Парасоля встановлена; лавка суха/мокра; фактичні ресурси й час |
| Opportunity | Чи були придатне місце та одночасне вікно NPC |
| Consent / obligation | Що запропоновано, ким прийнято, на яких умовах |
| Goal outcome | Заявлене читання відбулося / не виконане / лишається невизначеним |
| Adaptation | Нова допустима пропозиція після відмови; не перейменування провалу старої мети на її успіх |
| Contribution | Яка різниця між control/intervention у declared causal model; можливий нуль |
| Cost / integrity | Усі attempts, retries, inference/verifier/human costs, час, wrong/stale/unauthorized effects |
| Human experience | Зрозумілість, agency, доречність гумору, розповідь учасника; лише з реального дослідження людей |

Якщо C05 не допускає спільного читання через відмову, правильна обробка відмови є виконанням відповідної **handling requirement**, а не виконаним читанням. Primary task objective і fallback handling оцінюються окремо. Якщо goal infeasible тільки через приховане від planner знання, не вимагати пророчого рішення: оцінити допустиме отримання відомостей, дотримання меж і чесність результату. Oracle feasibility label має зазначати, що було спостережуваним.

Новий Core не приймається через більше подій, примусові згоди NPC або більшу довжину звіту. Протокол наперед обирає primary axis — task success, reliability або total cost — з non-inferiority margins та hard invariants для інших осей. Domain quality і людський досвід залишаються окремими доказами. Правила statistical confidence задаються до реальних даних; десять паперових карток не є розміром достатньої statistical sample.

## 5. Вісім кроків майбутнього Core experiment

1. **Назвати власну зміну Core.** Candidate може змінити його planner, context selection, tool interface, harness або source; exact version/mutation scope зафіксована. Нова краща історія без зміни такого subject не є self-improvement Core.
2. **Розділити корпус.** Опубліковані C01–C10 — development. Sealed comparison tasks і незалежний final confirmation set мають власне походження, права/доступ, family separation та contamination record. Нові назви NPC/IDs/seeds не роблять копію holdout новою.
3. **Заморозити протокол.** Goal, observable views, paired inputs, exogenous/coupling plan, budgets, horizon, floors, evaluator version, expected receipts, stopping/unknown rules фіксуються до outputs. Немає нового обсягу роботи без обґрунтованого budget.
4. **Виконати P0/P1 незалежно.** Їхні дії не мають бути однаковими. Execution/domain validator перевіряє фактичні transitions; planner не редагує world rules або scorer своєї спроби. Не qualified effect profile з Q05 не запускається під виглядом безпечного retry.
5. **Зібрати й sealed-нути докази.** Attempt identities, actual inputs/actions, event/resource/job receipts, time/cost, missing/error cases і privacy scope. Обидві гілки мають повний облік, включаючи невдалі запити й відмови.
6. **Порівняти outcomes за наперед заданим правилом.** Окремо validity, achieved goal, handling infeasibility, costs і людські дані за їх наявності. Інший scope або забруднений набір знижує/блокує claim; незручні cases не видаляються.
7. **Перевірити переносимість.** Навіть корисний consumer-game результат не замінює standalone non-game suite Core, його regression/compatibility checks і fresh confirmation. Accept comparison не означає promote generation.
8. **Відокремити method claim.** Для recursive improvement потрібні O0→O1→O2 та користь на нових задачах за рівного бюджету з попередньої архітектури. C01/C02 самі по собі цього не доводять. No-gain/inconclusive зберігається, не перефарбовується в «еволюцію».

Формат доменного прикладу може перевикористовувати Core comparison/receipt infrastructure, але не робить гру обов’язковою для незалежного Core gate. Базова модель, model revision, hardware і environment changes записуються як контрольовані фактори або confounders; їх не приписують автоматично новому коду Core.

## 6. Окремий evaluator experiment

E0 та E1 evaluators отримують **той самий frozen corpus** traces/artifacts у blind order; не створюють кожен власну зручну гру. Зовнішні labels мають provenance, критерії, неоднозначність та adjudication path. У корпусі присутні wet-bench false success, dry independent meeting, missing consent, stale apply, unmet-but-renamed goal, narrative-only claim і справді валідна альтернатива.

Оцінюються false acceptance критичних порушень, false rejection допустимих рішень, calibration/abstention та disagreements за slices. Hard validity facts звіряються з execution/state receipts там, де доступні; художня доречність лишається людським судженням. Незалежний adjudicator може помилитися, тому labels оскаржувані, але їхня зміна створює нову version/порівняння, не переписує старий score непомітно.

Паралельна зміна planner й evaluator потребує окремого preregistered 2×2 design з incumbent/challenger оцінками та зовнішніми anchors. Факт, що новий evaluator краще оцінив власний planner, не доводить приросту ні одного з них.

[Q03 succession](evaluator-succession.md) додає criterion dependency inventory, придатність історичних scores після переходу та integrity measurement path. Заміна A0/A1 як treatment не є автоматично зміною спільного критерію. Незгода E0 потребує незалежного розбору, а re-score старих artifacts не доводить fresh generator gain. Усі чотири оцінки можуть погодитися через той самий пошкоджений telemetry channel; первинні receipts залишаються окремою перевіркою.

## 7. Що змінилося в беклозі та чого ще немає

Уточнення лягають у чинні AF-RSI003/005/007/011/034 та AF-LW002/011/012/025/030. Нових IDs/edges немає. Для W0 обов’язкові тільки його domain contract та development fixtures; AF-RSI019/024/034 і AF-LW024/025 не стають новими prerequisites AF-LW030. Сезонний C10 лишається поза W0.

Письмовий trace є достатнім, щоб спростувати неузгоджене правило **в нашій специфікації**. Він недостатній для заяви про виконану гру, покращений Core, calibrated evaluator чи досвід людей. Майбутній experiment bundle повинен прямо показувати і силу, і межу кожного з цих висновків.
