# Q05: точні переходи поколінь і відновлення після збоїв

Проєктна специфікація · 2026-09-10, Europe/Zurich · **E0 / proposed**. Цей прохід деталізує [архітектуру Core](https://github.com/HappyMiha/Lokvetia-Core/blob/docs/living-systems-rsi/docs/evolution/core-architecture.md) і [контракт зі світом](platform-world-contract.md). Таблиці описують майбутню поведінку; це не виконані crash tests і не новий runtime API.

## Питання, яке змінило рішення

Чи можна після перезапуску однозначно встановити, **яку дію вже виконано, за яким чинним правом і яку версію дозволено використовувати далі**? Попереднього «durable promotion ID + CAS expected incumbent» недостатньо: той самий generation digest може повернутися після rollback; дозвіл може бути відкликаний після перевірки; міграція може завершитися лише частково. Становий перехід потребує точнішого суб’єкта й точки фіксації.

Вихідні версії: Core `35c87b5331cf5da10a465b3c6b27caa1d1fa87a1`, Lokiravia `09946d05063ea61bc3d5a815af1fa527b1aad157`. Після fetch origin/main лишилися відповідно `c22954f144702fdf7a3da16cf58176baa345f7c4` і `3d42cf9606d1100ebe0887306300b5fa4aaaea5e`. У цьому проході немає нового читання EPUB/PDF; source coverage попередніх проходів не збільшується. Підстава — статична перевірка документації, наявного коду й контрприклади до нашого власного дизайну.

Незалежний [аудит реалізації Q05](https://github.com/HappyMiha/Lokvetia-Core/blob/docs/living-systems-rsi/docs/evolution/implementation-recovery-audit.md) з exact source locators виявив шість конкретних меж: generic driver не завжди відновлює outcome; evaluation callback виконується до durable verdict; recovery Git commit перевіряє структуру без повторного content binding; accepted loop/gate/delivery linkage можуть фіксуватися окремо; pack pointer не є встановленням Core runtime; stop digest не є спостереженням припинення зовнішнього ефекту. При цьому вже існують mission operation journal, starting-session reservation і fenced autonomous completion — їх потрібно перевикористати.

## 1. Незмінні records і змінний активний покажчик

| Record | Коли фіксується | Необхідний зміст |
|---|---|---|
| CandidateManifest | До запуску кандидата | Точні artifact/base/parent digests, предмет зміни, input/memory view, protocol reference, scope, compatibility |
| ExperimentProtocol | До результатів baseline/challenger | Eligible cases, очікувані receipt roles, витрати, deadline, правила missing evidence, comparison/stop rules |
| AttemptIntent | **До** dispatch кожної спроби | Experiment/candidate/protocol, logical operation key, attempt ID, writer/authority epoch, input digest, budget reservation, допустимий effect profile |
| AttemptReceipt | Після спостережуваного результату | Issuer, exact attempt/input/effect identity, вихід/помилка, витрати й межі того, що issuer справді спостеріг |
| EvidenceSeal | Після закриття переліку спроб | Усі admitted attempts, receipt digests або явні missing/cancelled/invalid dispositions, inclusion policy і час закриття |
| ComparisonDecision | Після seal | Candidate/baseline, protocol, seal digest, accepted/rejected/inconclusive, межа claim; це не release grant |
| GenerationManifest | Після потрібної кваліфікації | Candidate + comparison + qualification receipts + runtime/state compatibility + rollout/recovery plan; немає посилання на власний майбутній activation receipt |
| PromotionAuthorization | До конкретної активації | Exact GenerationManifest digest, target/profile, expected ActivationBinding, authority epoch, expiry, scope та дозволена recovery operation |
| ActivationReceipt | У момент фіксації активації | Promotion ID, authorization ID, previous/next ActivationBinding, commit sequence і посилання на підготовлений стан |

`ActivationBinding` — tuple `target_id, activation_seq, generation_manifest_digest, authority_epoch, writer_fence, state_binding`. `activation_seq` монотонно зростає і **не повертається назад при rollback**. `state_binding` визначає точний storage/schema/checkpoint профіль; для stateful світу — world/rule epoch, checkpoint digest і committed revision. У stateless contract fixture state binding явно `not_applicable`, не вигаданий save hash.

CAS порівнює всю потрібну для профілю binding identity, включаючи sequence, а не тільки generation digest. A@41→B@42→A@43 не повертає права старому grant для A@41. Повторний виклик уже committed promotion ID повертає той самий ActivationReceipt, не створює A@44. Інший target або інші bytes під тим самим operation key — conflict, не retry.

Mutable status/revocation index посилається на незмінні records. Він не переписує історичні candidate, comparison або receipt. Криптографічний hash підтверджує identity bytes; він сам по собі не доводить компетентності або незалежності issuer.

При adoption відновленого Git artifact потрібно повторно зв’язати фактичний commit/tree/diff content із snapshot, який перевіряли validators. Однакові parent, commit subject і filenames цього не доводять. Інші bytes дають новий candidate або invalidation; старий validator receipt не переноситься разом із назвою файлу.

## 2. Transition table експерименту

Phase, runtime disposition та evidence reason лишаються окремими осями з основної архітектури. `unknown` — невідомість зовнішнього ефекту, а не прихований доказ failure чи success.

| ID | Перехід | Guard і durable запис | Якщо crash або повтор |
|---|---|---|---|
| T01 | draft→protocol_frozen | Immutable protocol і candidate identity; inputs ще не містять результатів | Якщо запис не committed, dispatch заборонений; повтор з іншими bytes потребує нового ID |
| T02 | protocol_frozen→admitted | Qualified runtime profile, scope, доступний aggregate budget; admission receipt | Резервація має один logical operation key; повтор не резервує двічі |
| T03 | admitted→running | AttemptIntent і reservation committed до зовнішнього dispatch | Після crash перевірити receiver status за key; відсутність локального receipt не дозволяє повтор effect навмання |
| T04 | running→running/reconciling | Отримано receipt або timeout/lost worker; прийнята відповідь зв’язана з exact intent | Stale writer не може прийняти результат нової спроби; timeout лише запускає bounded reconciliation |
| T05 | running/reconciling→evidence_sealed | Кожен admitted attempt має receipt/disposition, жоден outstanding effect не приховано; завершено deadline policy | Missing записується явно. Late evidence створює amendment/new seal; закритий seal не доповнюється непомітно |
| T06 | evidence_sealed→compared | Seal integrity, issuer/scope validity, inclusion policy і protocol prerequisites перевірено | Дубль comparator input повертає те саме рішення; інший seal/protocol — інше comparison ID |
| T07 | compared→accepted/rejected/inconclusive | Порівняння задовольняє preregistered decision rule; accepted result, decision/gate і linkage мають replayable transition identity | Одна local transaction або explicit reconciliation/adoption зшиває вже committed records; restart не створює нового голосу/gate й не вимагає знову active статусу вже accepted loop |
| T08 | Будь-яка нетермінальна phase→aborted | Визначена причина: змінений subject, відкликаний scope, cap тощо; dispatch зупинено | Уже можливі effects звіряються окремо; aborted не означає «нічого не виконано й нічого не коштує» |

Protocol може наперед рахувати пропущену відповідь task як failure, якщо цього достатньо для валідного порівняння; не може називати відсутній обов’язковий integrity/authority receipt успішним. Якщо відсутні передумови валідного порівняння, зберігається terminal inconclusive/aborted decision без claim improvement. Немає обов’язку штучно проходити `compared` із непридатним набором.

Пізні докази, які спростовують уже прийняте порівняння, створюють claim challenge та блокують **нові** promotions залежного manifest до розв’язання. Поточний реліз обробляється через окремий incident/revocation процес. Історичне «таке рішення було прийнято» зберігається, але не подається як досі підтверджена користь.

## 3. Межа виконання, повтору й бюджету

Для кожного зовнішнього effect profile потрібно вказати, що реально підтримує receiver: lookup за operation key, dedup із перевіркою payload digest, cancellation acknowledgment, committed-effect receipt. Наявність idempotency key в Core без відповідної поведінки receiver не створює гарантії виконання рівно один раз.

Dedup contract задає retention/expiry horizon і policy закритих operation keys. Повтор старого intent після pruning не стає новою дією через відсутність рядка в кеші: поза підтвердженим горизонтом він відхиляється або звіряється із durable tombstone/archive. Новій легітимній logical operation потрібні нова admission та нова identity. Правило поширюється й на evaluator callback; database uniqueness готового verdict не усуває повторного зовнішнього review до його commit.

| Профіль ефекту | Recovery при втраті відповіді | Допустимий claim |
|---|---|---|
| Read-only / isolated computation | Новий attempt у загальному budget; попередня спроба й її можлива ціна записані | Повторюваний обчислювальний результат у declared envelope; не гарантія однієї provider charge |
| Receiver із durable dedup + outcome lookup | Звірити key/payload, повторити delivery з тим самим key лише за контрактом receiver | Один committed доменний effect у перевіреній області; transport attempts можуть повторюватися |
| Receiver без надійного outcome lookup | Залишити unknown; заблокувати повтор non-repeatable effect до reconciliation/явного recovery decision | Немає exactly-once claim; ця capability не admitted для unattended promotion-critical effect |

Cancel request чи прострочення lease не доводять, що зовнішня дія не відбулася. Cancel acknowledgment має означати визначений receiver стан, а не лише прийнятий HTTP-запит. Worker fence перевіряє authoritative writer **під час commit**; старий процес може ще обчислювати, але не може змінити поточний стан через цей шлях.

Резервація невідомої вартості лишається зайнятою до receipt/reconciliation за наперед визначеним bounded exposure policy. Якщо точна ціна недоступна, ledger зберігає відомий мінімум і консервативну верхню межу; не звільняє бюджет автоматично за timeout. Якщо верхня межа потрібна для cap, але її встановити неможливо, наступний dispatch блокується. Retry, verifier і compensation витрачають бюджет; скасування не обнуляє вже можливу charge.

## 4. Promotion, revocation і rollback

Кваліфікований перший профіль може мати одного authoritative writer. Цей документ не обирає distributed consensus або конкретну СУБД. Він вимагає **одного серіалізованого порядку** для перевірки повноваження, зміни active binding та відповідного activation record у declared storage boundary. Якщо runtime не забезпечує цей порядок, його promotion profile не кваліфікований.

1. Підготувати exact release artifacts і кандидатний сумісний стан у відокремленій області. Readiness не дає права обслуговувати авторитетні writes.
2. Зафіксувати PromotionAuthorization із expected binding та чинною authority epoch. Shadow/canary використовують свої target/scope grants; їхні stages залежать від явного profile, не автоматично потрібні для offline fixture.
3. Перед commit повторно перевірити grant validity/expiry/revocation, expected binding, artifact/state digests, qualified scope й актуальний writer fence. Ця перевірка та запис ActivationReceipt мають одну serialization boundary.
4. У ній committed ActivationReceipt, наступна binding із sequence+1 та право нового writer. Dispatch/readiness routing споживає цей binding. Процес, registry і зовнішній load balancer не оголошуються фізично однією транзакцією: profile має довести, що між ними немає доступного користувачу змішаного writer/state.
5. Якщо процес не запустився після commit, не виправляти receipt заднім числом. Утримати admission у paused/degraded стані й виконати вже дозволений recovery transition або отримати новий конкретний grant. Старий writer не відновлює права тільки тому, що він досі живий.

Якщо revocation serialized **до** activation commit — activation відхиляється. Якщо **після** — попередній activation лишається історичним фактом; відкликання забороняє нові admissions/активації й запускає scoped quarantine/recovery. Неможливо чесно обіцяти, що ще не зафіксоване майбутнє відкликання скасувало вже committed подію.

Final guards враховують транзитивно відкликані skills, tools, supporting evidence і authority records у declared dependency graph. Кешовані bytes не оминають admission; rollback до старого artifact не поновлює його відкликаних прав. Уже committed effect лишається історією, а ще прийняті jobs отримують явну disposition за policy, а не мовчки виконуються revoked компонентом.

Для revocation зовнішньої authority, яка не надає спільний fencing/serialization contract, profile мусить явно визначити bounded delay або не допускати автоматичну активацію. Кешована перевірка «ще не відкликано» не доводить нульового race window. Перший сильний promotion claim використовує локальну authoritative boundary із перевіреним порядком.

Writer fence має перевірятися в усіх authoritative commit paths, які охоплює claim. Зовнішній receiver, що не споживає fence, залишається під обмеженнями effect profile §3; локальне відхилення старого writer не скасовує вже надісланий remote effect. Непідтримуваний незворотний effect не admitted для unattended переходу.

**Оновлення самого supervisor/promoter Core:** committed перехід виконує окрема чинна promotion authority, а candidate control process не має її write credentials і не приймає власну кваліфікацію. Профіль описує drain/reconciliation, checkpoint control state, fenced handoff до successor та відновлення, якщо successor не ready. Можна еволюціонувати й сам механізм authority, але передача root authority — окремий кваліфікований upgrade/recovery transition, авторизований чинною незалежною межею; не прихований self-approval через новий runtime. Це вимога до Core-on-Core source evolution, не тільки до game pack.

Rollback — новий перехід до сумісного старого artifact, з новою activation sequence й authorization, прив’язаною до **поточного** state binding. Дозвіл може бути наперед обмеженим recovery grant, але не довільним правом стерти нові дані. Відкликаний artifact не стає допустимим fallback лише тому, що був старим incumbent. Якщо обидві версії непридатні, правильний результат — paused/degraded режим, а не вигаданий успішний rollback.

Результат canary може кваліфікувати інший broader-scope GenerationManifest; той має новий digest і новий grant. Manifest не посилається на власний майбутній receipt і не набуває broader scope через дописування поля після hash.

## 5. Правила світу й міграція стану

Atomic alias update сам по собі не доводить атомарної міграції. Для першого single-writer профілю:

- Зупинити приймання нових domain writes на визначеній revision; звірити вже прийняті jobs/effects і встановити watermark. Inference може закінчуватися, але старі proposals не отримують права обійти бар’єр.
- Побудувати кандидатний checkpoint від цієї exact revision. Записати parent checkpoint, event prefix/watermark, schema/rule digests, pending accepted jobs, ресурси та random-state envelope. Перевірити його поза live state.
- Якщо live revision змінилася після початкової копії, стара migration кваліфікація недостатня: повторити підготовку/перевірку від остаточної quiesced revision або використати окремо кваліфікований catch-up. Пілот може обрати паузу; непомітно загубити останні дії не може.
- Перемкнути один coherent binding `rule + schema + checkpoint + revision + writer_fence` лише після повних receipts. Недописаний checkpoint або mismatch залишає стару binding. Жоден читач не одержує нові правила зі старою неперевіреною формою стану.

Перед переключенням recovery прибирає/ізолює незавершену **кандидатну** копію; не «відновлює» live world поверх чесних подій. Після переключення recovery дотримується нового activation record: сумісний repair/compensation або окремо дозволений restore. Збереження сюжету не означає відмови виправити технічну помилку.

`session_epoch` при load видається новою admission authority й не береться як поточне значення зі старого save. Інакше A→B→A save відновить дійсність старого callback. Accepted domain jobs мають stable IDs і provenance та поновлюються в новій binding за checkpoint policy; pending model requests не є такими jobs. Old reply відхиляється, нове рішення не створює другий effect для вже виконаного job.

Попередня validation відповіді ще не дозволяє застосувати її після load. Authoritative **commit** повторно звіряє world/request binding, session/rule epoch, actor generation, expires_at_tick, expected revision, права та writer fence і одним локальним переходом записує state delta, resource delta, WorldEvent, job completion і dedup receipt. Trace «precheck пройдено → load → apply» повинен відхилити старий apply. Crash не може залишити виданий ресурс без відповідного effect/job record. Якщо storage profile не забезпечує такий local commit, він потребує еквівалентного recovery contract до кваліфікації.

При новій rule epoch кожен accepted job має явну migration disposition: preserve, сумісне remap або cancel із причиною й визначеною компенсацією/поверненням ресурсу. Це не дозвіл переграти стару model response під новими правилами. Кандидатна міграція не завершує такий job у live state до прийняття відповідної binding.

Відновлення приватного save може повторювати **внутрішню альтернативну історію** за правилами автора. Воно не скидає реєстр уже виконаних зовнішніх ефектів, платежів або публічних grants. W0 не вводить таких ефектів; future profile мусить мати durable dedup/compensation boundary поза rewindable save.

Для явного rewind/fork нова `history_branch_id` розрізняє альтернативну локальну історію; ordinary crash recovery або повторний load поточного checkpoint не створюють її лише заради обходу dedup. Local effect key має world/history/job identity, а зовнішній effect key зберігає власну незворотну identity. Session epoch є fencing для відповіді, не способом заново видати зовнішню нагороду.

## 6. Набір спростовних сценаріїв

Усі 16 рядків — **статичні design scenarios**, не виконані fixtures. Для майбутнього прийняття потрібні реальні receipts exact implementation/version, а не лише ця таблиця.

| Case | Контрольний trace | Очікуване спостереження | Мінімальний доказ майбутньої перевірки |
|---|---|---|---|
| RC01 | Intent committed → worker зник до/після зовнішнього dispatch | Один unresolved logical operation; відсутність receipt не видається failure без effect | Intent, receiver lookup/unknown, reservation disposition |
| RC02 | Effect committed → відповідь втрачена → повтор delivery; варіант key після retention horizon | Receiver із dedup повертає той самий effect; інший payload відхилений; expired/pruned key не створює нову дію | Два attempts, один effect ID, receiver receipt та expiry/tombstone policy |
| RC03 | Receiver без dedup/lookup, timeout | Non-repeatable effect не повторюється автономно; scope позначено unsupported/unknown | Capability profile й blocked recovery decision |
| RC04 | Lease expired/cancel sent → старий worker повернувся | Старий writer не commit; можлива зовнішня charge все ще врахована | Fence rejection, cost reconciliation, жодного другого grant |
| RC05 | Seal committed → пізній conflicting receipt; variant recovered commit має ті самі файли, але інші bytes | Seal не змінений; amendment/challenge блокує нову promotion; content mismatch не adopt-иться як validated candidate | Фактичний tree/diff binding, обидва digests, challenge record і refusal receipt |
| RC06 | Comparison accepted, PromotionAuthorization відсутній; crash між accepted loop/gate/linkage | Active binding незмінна; replay adopt-ить наявні records без нового gate/повторного приймання | Transition identity, recovered linkage, denied activation без release grant |
| RC07 | Grant видано → revocation → activation | Відхилення за authority order, навіть якщо попередня cached перевірка була успішна | Revocation sequence, denied activation, unchanged binding |
| RC08 | Activation → revocation generation або залежної cached skill/evidence | Історична activation збережена, нові admissions закриті, cached bytes не поновлюють права, scoped recovery | Activation і revocation order, dependency guard, dispatch gate, recovery record |
| RC09 | A@41→B@42→A@43 → старий grant для A@41 | ABA-повтор відхилений, хоча artifact digest знову A | Expected/actual sequence mismatch |
| RC10 | Два кандидати мають grant для A@41 | Лише один перехід споживає A@41; другий не rebased мовчки | Один activation receipt, conflict і нова кваліфікація/новий grant за потреби |
| RC11 | Activation committed → ack lost → retry promotion ID | Той самий receipt і sequence, не друге переключення | Stable promotion ID і identical committed binding |
| RC12 | Migration copy на r10 → чесна дія r11 → спроба switch | Stale snapshot не прийнято; r11 збережена | Quiesce watermark, expected revision mismatch, refreshed candidate |
| RC13 | Crash після половини checkpoint write / між prepare і switch | Live binding лишається цілісною; incomplete candidate не active | Checkpoint digest validation й old binding |
| RC14 | Commit new binding → новий runtime не ready | Немає змішаного serving/writer; paused або авторизований recovery з новою sequence | Admission/health record, fence та recovery authorization |
| RC15 | Save/load при pending reply та accepted scheduled job; окремий interleaving precheck→load→apply | New session epoch; old reply відхилено також на final commit; job completion/effect/resource/dedup атомарні у цій history | Старий/new epoch, persisted job ID, commit/fence rejection та dedup event receipt |
| RC16 | Rollback старого коду після нових state writes; старий artifact revoked | Несумісний/revoked fallback відхилений; repair або пауза зберігає правдиву історію | State compatibility, revocation index, scoped recovery record |

Корисний негативний результат тут — виявити непідтримуваний effect profile або неможливість сильного atomicity claim на наявній boundary. Заміна тесту красивим звітом не робить claim сильнішим.

## 7. Рішення цього проходу та межа наступного

**EV-007 — activation є версійованою capability boundary.** Прийнято в проєкті: monotonic ActivationBinding, serialized revocation/activation, separate immutable ActivationReceipt, explicit effect profiles і coherent state switch. Слабшу альтернативу «порівняти тільки поточний Git SHA й потім перевірити журнал» відхилено через RC07/09/12. Рішення може змінитися при іншій реалізації лише з еквівалентними перевірними гарантіями.

Це деталізація існуючих AF-RSI002/004/008/011/017/029/032/033/034 і AF-LW023/030, а не новий microservice або друга execution queue. Портфель лишається 65-картковим. Core самовдосконалює власний source/optimizer через той самий перевірний lifecycle; game pack отримує доменну адаптацію без влади переписати platform control plane.

Applicability фіксується **до** перевірки. Standalone Core029 використовує застосовні RC01–14/16 на neutral Core fixtures; stateful migration перевіряється лише для заявленого stateful профілю. RC15 з world/action semantics належить optional C7 qualification і не створює прихованої залежності від гри. W0 має тільки свій локальний checkpoint/final-apply/job/dedup зріз, зокрема застосовні варіанти RC02/13/15, і не чекає live canary чи multiplayer. Позначення not-applicable/unsupported має причину й межу дозволеного claim; воно не зараховується як pass.

До реалізації лишаються: вибір конкретного supported storage/runtime profile, executable crash harness, receiver conformance tests і виміряне recovery time/data-loss envelope. Статичне закриття Q05 означає достатньо точну специфікацію для цих перевірок, не їхнє проходження.
