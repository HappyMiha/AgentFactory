# Контракт платформи, creator-продукту та живого світу

Спільна проєктна редакція 2 · 2026-09-10. Цей документ дзеркально зберігається в обох репозиторіях; узгодженість перевіряється за однаковим вмістом. Це design contract, не реалізований runtime API.

## 1. Хто відповідає за яку істину

| Межа | Власник | Канон | Не є її повноваженням |
| --- | --- | --- | --- |
| Platform execution / evolution | Lokvetia Core | Identity, scope, run/attempt, budgets, candidates, receipts, покоління Core | Вирішувати за автора, що є каноном художнього світу |
| Creator product | Lokiravia | Brief, проєкт, author decisions, Play artifact, feedback, product version | Самопроголошувати зовнішню перевірку Core успішною |
| World runtime / game pack | Авторський pack, engine runtime | Доменний стан, події, ресурси, права акторів, world/rule epoch | Змінювати Core credentials, evaluator або spend limits через діалог |
| Player knowledge | Авторизована game projection | Що персонаж спостерігав, почув або вважає правдою | Підміняти канон факту або читати приховану пам’ять іншого NPC |

Ігрова причинність належить game pack; Core може надати optional reusable event/replay contracts. Нейтральний scheduler Core не набуває знань про міську раду, магію, борги чи фракції. Lokiravia не створює власний engine еволюції: викликає Core через прийняту версію контракту.

## 2. Три види змін

**State transition:** дозволена дія за чинними правилами. Вона може змінити світ назавжди в сюжетному сенсі, але не є оновленням коду. Наприклад, утворення нового громадського об’єднання — нова сутність чинного типу institution.

**Rule / ontology transition:** нова формула, affordance, тип ресурсу або інституції. Вимагає candidate pack, domain suite, людської оцінки й міграційного контракту. Якщо для події бракує типу у схемі, runtime зберігає пропозицію/спостереження, а не виконує вигадане правило.

**Platform transition:** нове покоління Core або creator-продукту. Воно має окремий Core benchmark, compatibility tests, rollout і consumer pin. Покращення game score не дозволяє приховано оновити платформу.

## 3. Запропонована форма action proposal

Це перелік полів design schema, не executable code.

| Поля | Призначення |
| --- | --- |
| `proposal_id`, `request_id`, `causation_id`, `correlation_id` | Idempotency, відповідь на конкретне спостереження, причинна гілка |
| `world_id`, `session_epoch`, `rule_epoch`, `expected_revision` | Перевірка світу, завантаження save, версії правил і конкурентної зміни |
| `actor_id`, `actor_generation`, `authority_scope` | Чия це дія, чи існує актор, що він має право змінити |
| `action_type`, `typed_arguments`, `preconditions` | Дія з відомого bounded vocabulary та типізованими параметрами |
| `observed_facts`, `belief_refs`, `intent` | Чому актор її пропонує; beliefs не підвищуються до facts |
| `expires_at_tick`, `resource_limit`, `consequence_scope` | Час актуальності, витрати, дозволений масштаб ефекту |
| `producer_version`, `generation_id` | Походження моделі/методу, не право самосхвалення |

Engine validator перевіряє identity, version, preconditions, domain permissions, ресурси й дозволений масштаб. Прийнята дія створює `WorldEvent` із `event_id`, parents, tick, before/after revision, rule digest, typed delta, recorded random draws, validation receipt і visibility policy. Відхилена дія створює rejection receipt; не змінює стан і не витрачає ігровий ресурс вдруге.

## 4. Replay, причинність та несподіваність

Replay відтворює **прийняті події, випадкові вибори та зовнішні inputs**, а не просить LLM вдруге вигадати ту саму відповідь. Для недетермінованих engine elements задається точна межа відтворюваності: state hash або допустимий tolerance для конкретного профілю. Нове генерування має інший run ID.

Counterfactual branch починається з відомого checkpoint, прибирає/змінює одну дію та зберігає решту контрольованих inputs. Вона показує причинність **у нашій моделі**, не доводить, що за інших неконтрольованих подій реальний гравець зробив би те саме. Звітуються змішані причини й невизначеність; причинний граф не є графом усіх кореляцій.

Великі cascades не мають бути гарантовані. Domain preconditions, ресурси, topology, час і конкуренція намірів визначають, чи пошириться зміна. Event horizon, fan-out cap, influence budget і offscreen aggregation обмежують обчислення; невраховану далеку зміну система позначає як невідому, а не домальовує точний результат. Бюджет розподіляється за доменними умовами, не за оплатою гравця або прихованою потребою підвищити engagement.

## 5. Save, паралельні дії та довгі світи

Load save змінює `session_epoch`, інвалідує outstanding proposals і відновлює world/rule generation. Reply зі старого save, actor generation або простроченим tick відхиляється. Duplicate event не видає повторну нагороду. Одночасна витрата останнього ресурсу серіалізується authoritative runtime; у пілоті достатній один writer на world partition. Final commit повторно звіряє epochs/fence/revision і атомарно фіксує delta/event/resource/job completion/dedup; precheck перед load не дозволяє stale apply після load.

Перший пілот: світ рухається під час активної сесії, з обмеженим і поясненим catch-up. Always-on економіка та NPC за відсутності гравця — окрема гіпотеза, не прихована серверна вимога. Немає покарання за вихід або потреби заходити, щоб захистити базове право на гру.

Пізніший distributed world потребує contracts для partition ownership, cross-partition ordering, causal watermark, conflict resolution і degradation mode. Ця редакція не обирає глобальний consensus для кожного tick і не обіцяє необмежену MMO-сумісність.

## 6. Зміна правил і операційне повернення

Migration package містить old/new rule digest, правила перетворення стану, збережені інваріанти, replay suite, preview affected entities, schema compatibility і recovery plan. Підготовка та validation відбуваються на копії checkpoint; active epoch switch має coherent rule/schema/checkpoint/revision/writer binding із монотонною activation sequence. Одна лише атомарна зміна alias не доводить сумісності стану; кандидатна копія від stale revision не може стерти пізні чесні дії. Клієнт бачить версію і причину зміни до входу в оновлений світ.

**Історичний наслідок** не скасовується через невигідність для сюжету. **Технічний дефект** може вимагати operational rollback. У приватному світі автор може відновити checkpoint. У спільному світі сліпий restore старого snapshot зітре чесні пізні дії інших людей: перевага — compatibility repair, compensating events, компенсація втрат і прозора incident record. Повний restore допускається лише за окремою погодженою політикою спільного світу.

Приклад: зламаний pricing rule створив дублікати винагород. Повернення rule version припиняє майбутні дублікати; воно не знищує всі легальні покупки після першого дублювання. Remediation відстежує походження незаконного приросту, зберігає валідні події й повідомляє заторкнутих учасників. Exact algorithm — майбутня вимога, а не доведена готовність.

## 7. Сходи прийняття й bridge

Становище в аудиті: Lokiravia pin на Core `480849f78957bb6b2fd7ab341300d54955aeabb8`; Core audit HEAD `c22954f144702fdf7a3da16cf58176baa345f7c4`. Це різні версії. Нові контракти потребуватимуть нової перевіреної пари.

`IntegrationReceipt` має `subject_kind` та `evidence_profile`. Спільні поля — точний subject digest, Core commit/generation, contract versions, suite/runner receipts і supported envelope. Профіль `core_contract_conformance` посилається на exact fixtures; `domain_runtime_integration` додає consumer commit, domain pack і runtime/engine versions; `packaged_game_integration` додатково потребує player-package hash та target version. Package hash не вигадують для non-game contract fixture. Відсутність package не спростовує доведену contract conformance, але не дозволяє claim Playable. Якщо бракує upstream receipt, потрібного саме обраному профілю, результат — design-ready/integration-blocked, не qualified. JSON schema pass дає лише structural conformance evidence.

Розрізняємо structural, runtime, human-quality та owner decision evidence. `Ready`, `Playable`, `Exportable`, `Publishable`, `Sellable` зберігають чинне значення. Додаткові claims `CoreImproved`, `MethodImproved`, `WorldEvolutionAccepted` не відкривають старі gates автоматично.

## 8. Перевірки меж до першого живого rollout

Доповнення після критичного літературного проходу: сюжетна можливість, запропоноване зобов’язання, прийняте зобов’язання та виконання — окремі стани. Репліка ввічливості або перегляд предмета не приймають витратного контракту. Відома ціна, строк і клас можливої втрати повідомляються до прийняття. Нагорода посилається на rule digest і виконану передумову; novelty, completion і ресурсний grant не підміняють один одного. Висловлений сумнів не дає оптимізатору права приховано змінити нагороду або доступ. Це наші проєктні обмеження, а не твердження про послідовність книжкової Системи.

- Різні worlds/tenants, чужа NPC memory, prompt із вигаданими правами та replay старого request не дають доступу або effect.
- Save/load, actor destruction, reconnect і retry не застосовують прострочені наміри.
- Відсутність inference повертає bounded deterministic поведінку; frame loop залишається працездатним.
- Пошкоджені/відсутні receipts не приймаються через гарний narrative report.
- Відкликана Core skill не поширюється в нові game-pack generations; уже випущений pack має відому залежність і remediation path.
- Rule migration і rollback перевіряються на save з чесними паралельними діями; правило не змінює минулу причину подій.
- Приватні діалоги, evidence доступу й персональні тексти не потрапляють у shared optimizer context без відповідної згоди та purpose.

[Q05 recovery contract](recovery-contract.md) задає final-commit перевірки, serialized revocation, ABA protection, профілі ефектів та RC01–16. Це деталізація чинних карток, не нова runtime capability.

Конкретні delivery IDs і залежності перелічені в беклогах обох продуктів. Дослідження можна читати як єдину програму; воно не запускає код або фонові ігрові процеси.
