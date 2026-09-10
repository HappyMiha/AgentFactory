# Q02: що залишається тим самим після зміни

2026-09-10 · **E0 / proposed**. Спільний семантичний контракт Lokvetia Core і Lokiravia. [Q05 recovery](recovery-contract.md) визначає атомарність активації й відновлення; тут уточнено, **що саме дозволено переносити**. Узгоджені bytes і schema ще не доводять збереження сенсу прав, особи чи обіцянки. Це статична специфікація, не реалізована міграція.

## 1. Чотири різні зв’язки

| Поняття | Значення | Чого не надає саме по собі |
|---|---|---|
| Canonical entity identity | Чия історія та які предмети/домовленості стосуються цієї сутності в конкретному domain | Нових здібностей, згоди або автоматичного знання всіх NPC |
| Incarnation | Конкретне чинне втілення сутності; змінюється після оголошеної re-instantiation/destruction policy | Права виконувати старий незавершений proposal |
| Representation / state revision | Форма, назва, опис, тіло, фактичні властивості за чинними rules | Нової особи лише через нову форму; незмінних capabilities лише через старе ім’я |
| Execution generation | Exact source/harness/model/tool/role composition Core чи planner | Повноважень попередника поза чинним grant і згодою |

Principal/authority — окрема контрольна ідентичність. Гравець, персонаж, роль, Core process, модель і principal не є одним полем. Зв’язки між ними мають domain/scope, issuer, validity та policy version. Одна модель не доводить тотожність двох суб’єктів, різні model names не доводять незалежність оцінювачів, а одна назва персонажа не доводить спільність історії.

Попереднє поле `actor_generation` у action proposal звужується до **actor incarnation**, не до форми й не до версії LLM. `expected_revision` охоплює чинний стан, у тому числі form/capability revision. `generation_id`/`producer_version` позначають виробника proposal. Майбутня schema evolution може перейменувати неоднозначне поле в `actor_incarnation`; у поточному design record обидва імені не існують як незалежні лічильники. W0 використовує мінімум: сталий actor ID, incarnation, state revision та exact producer version; shapeshifting не є новою вимогою першого build.

## 2. Види переходу визначає policy, а не красивий опис

| Перехід | Історія та повноваження | Обов’язкова перевірка |
|---|---|---|
| Перейменування / інша форма тієї самої сутності | Canonical ID збережено; зміни capabilities описані окремим дозволеним переходом | Старий proposal не застосовується до несумісного стану; прийняті домовленості не зникають |
| Знищення й заміна | Старий ID tombstoned; нова сутність має новий ID, навіть зі старим ім’ям | Не переносити випадково reputation, grants, custody або чужу пам’ять |
| Restore / re-instantiation тієї самої сутності | Continuity визначена профілем; нова incarnation/session epoch | Відновлено accepted state/jobs за Q05; старі proposals і revoked grants не воскресають |
| Split / merge / clone | Явні predecessor/successor relations; lineage не є заявою тотожності | Кожне право, ресурс і зобов’язання отримує власну disposition; не копіювати consent або матеріали автоматично |
| Новий Core source/harness/evaluator | Нова immutable generation; logical product може залишитись тим самим | Exact subject, зовнішнє evidence та чинна authority; old generation approval не є новим grant |

Для supported transition потрібен **ContinuityPlan**: точні до/після identities і versions, тип переходу, allowed mapping, перелік state/contract records, unmapped/disputed records, authority для кожної передачі, visibility і rollback disposition. Inventory scope і обов’язкові класи записів задає qualified profile/authority до candidate; сам кандидат не виключає незручне як «незначуще». Невідомий reference або непокритий record class отримує explicit unresolved/unsupported disposition, а не мовчазний skip чи assumed success. Це концептуальний артефакт поверх наявних manifest/recovery services, не новий універсальний сервіс або runtime API.

Спільне походження не ділить один предмет на дві копії й не нав’язує кожному наступнику повний борг. Для зобов’язання дозволені explicit preserve/reassign-with-authority/settle/pause-for-resolution відповідно до domain contract. Відсутність рішення не означає accepted або fulfilled. Заміна виконавця не змінює непомітно зміст прийнятої послуги. Прийняття нової механіки й згода конкретного учасника на новий обов’язок — різні рішення.

Збереження ідентичності не гарантує збереження кожної здібності. Form/capability contract показує, які властивості збережені, змінені, втрачені або невідомі, а також необхідні залежності й поточну ціну підтримки. Частина конструкції може існувати, але не працювати без керуючого компонента чи ресурсу; валідна форма даних не замінює перевірки доступної дії. Перехід від тимчасового ефекту до постійного є окремою властивістю прийнятого переходу; назва старого тимчасового дозволу не надає права на приховане розширення. Невідомий результат лишається можливим усередині явно дозволеної області експерименту, без вигаданої повної гарантії.

Merge не об’єднує автоматично приватні memory scopes. Split не робить private evidence публічним і не скидає чинні обмеження. Збережене авторство або історія не є дозволом на нову дію. Політика видалення/утримання даних лишається чинною: continuity record не повинен повертати видалений приватний зміст через summary, старий save або sibling clone.

## 3. Сумісність має сенс, а не тільки формат

Candidate може зберегти старий рядок `reviewer`, `public`, `helper` або purpose label, але змінити його значення. Тому migration перевіряє semantic contract digest і перелік дозволених effect classes до/після. Старий дозвіл на читання не стає правом публікації; згода допомогти сьогодні не стає автоматичним обов’язком наступних днів. Без окремої authority на розширення профіль зберігає старий зміст, обмежує нову дію або зупиняє перехід.

Backward compatibility для даних не означає behavioral equivalence. Перенесений skill має окремо підтверджені scope/purpose/authority і придатність до нового середовища. Незмінний payload hash не доводить права використовувати його в іншому tenant, іншій ролі чи з іншим інструментом. Новий evaluator не переписує старі labels, verdicts або acceptance criteria; для застосування старого evidence до нового subject потрібна явна applicability decision, а не alias.

Comparison фіксує не тільки raw receipts, а й output schema, decoder/projection та значення labels. Якщо нова projection рахує cancelled разом з executed як completed, незмінні raw rows ще не роблять scores порівнюваними. Потрібне окремо перевірене відображення до спільного значення outcome за frozen protocol; за його відсутності результат not-comparable/inconclusive, не gain. Старий raw evidence та його первинне тлумачення зберігаються у дозволеній retention scope.

Для Core-on-Core source/harness/optimizer зміни зберігають budget lineage, unresolved effects та declared responsibility. Новий agent ID не обнуляє витрати й конфлікт обов’язків. Незалежність перевіряється за визначеною decision policy та походженням виробництва/оцінювання; імена чи кількість агентів її не доводять. Спільний operator або базова модель самі по собі не доводять ні незалежності, ні її порушення.

## 4. Світ знає більше, ніж його мешканці

Canonical identity служить engine для послідовності прав і причинності. NPC працює зі своєю дозволеною проєкцією: може не впізнати змінену форму, помилитися або почути неправдиву чутку. Показ hidden canonical ID в діалозі не є способом «виправити» таку невідомість. Водночас помилка NPC не змінює системний запис власності чи згоду.

Оригінальний авторський приклад: складна парасоля після дозволеної переробки стає навісом із новими властивостями. Майстерка може її впізнати за слідом ремонту, інший NPC — ні. Чи це та сама річ або новий виріб із витрачених деталей, визначено правилом переробки до final commit; нова назва сама цього не вирішує. Позика перевіряє, чи дозволено переробку, а не лише тимчасове користування. Це optional development fixture, не новий обов’язковий crafting або identity system у W0.

Для місцевої традиції «те саме місце» й «ті самі представники» теж різні речі. Заміна опікуна зберігає правдивий внесок попередників, але передає лише явно дозволені обов’язки й ресурси. Якщо наступник не прийняв роботу або бракує ресурсу, практика може припинитися; публічна пам’ять про неї не видається за діючу послугу.

## 5. Відкриті статичні контроли

Ці authored fixtures не виконувалися й не є hidden holdout. Потрібні лише переходи, які заявляє конкретний профіль; unsupported split/merge може бути явно відхилений. Прохід не додає edges до W0 або standalone Core gate.

| ID | Зміна / контрприклад | Очікуваний результат і майбутній доказ |
|---|---|---|
| Q02-I01 | Те саме ім’я, нова сутність після знищення | Старі grants/jobs/reputation не прив’язані до заміни за ім’ям; canonical/tombstone/authority records |
| Q02-I02 | Та сама сутність, нова форма з іншою доступною дією | Прийняті зобов’язання збережені; incompatible old proposal відхилено; capability dependencies, maintenance cost, temporary/permanent scope та state/contract delta перевірені |
| Q02-I03 | Schema читається, але `reviewer` тепер означає також `promoter`; decoder рахує cancelled як completed | Старий grant не розширено; permission semantics та output projection перевірені окремо; без common-meaning mapping scores не порівнювані |
| Q02-I04 | Merge двох установ або split одного виконавця | Повний per-record mapping: майно не дублюється, consent не union-иться, невирішене не приховано; inventory/obligation/privacy reconciliation |
| Q02-I05 | Skill/пам’ять скопійовані в новий tenant або successor | Повторна scope/purpose перевірка; lineage/hash не видають доступ; rejection або explicit qualified reuse |
| Q02-I06 | Producer перейменував агента й назвав його незалежним evaluator | Decision-policy перевірка походження й обов’язків; ні alias, ні інша модель не є достатнім proof |
| Q02-I07 | Rollback після зміни опікуна або правдивого виконання послуги | Минуле й чинні revocations збережено; recovery має coherent current binding за Q05, не стару копію повноважень |
| Q02-I08 | NPC не впізнав зміненого власника/предмет | Обмежена projection не відкриває таємницю, помилка belief не змінює canonical authority; окремі knowledge/state receipts |

Предмет експерименту лишається точним: краще впізнавання персонажа не є доказом кращого Core. Для нового Core потрібні [Q06 comparison](counterfactual-evaluation.md), окремі non-game задачі й перевірка самого методу; переосмислення product goal зберігає межу рішення власника за [Q01](experience-improvement.md).
