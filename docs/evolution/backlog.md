# Пропозиція беклогу: самовдосконалення самого Lokvetia Core

Дата редакції: 10 вересня 2026. Q05 уточнює існуючі картки; IDs і залежності збережені. Проектні вимоги для майбутнього `docs/evolution/backlog.json`, а не активна runtime-черга. Всі `AF-RSI-*` мають статус **proposed**; цей документ не дозволяє запускати код, витрачати кошти або приймати реліз. Згідно з уточненням користувача, трьохкомп’ютерний claim workflow не є prerequisite цієї роботи.

Власник усіх нижченаведених reusable capabilities — **Lokvetia Core**. Lokiravia споживає прийняті контракти й додає власні продуктову оцінку та ігрові правила. RSI Core має працювати й доводити користь без гри, Cloud-акаунта чи Lokiravia runtime. Старі AF, AF-AMM, AF-GC і AF-CLD IDs/gates зберігаються. `AF-GC-043` вже існує й не перевикористовується.

`Залежності` нижче — внутрішні AF-RSI design/delivery prerequisites. `Reuse` — traceability до існуючих capabilities; наявність ID не означає прийняття відповідної runtime-інтеграції. Перед імплементацією фіксується accepted upstream commit і виміряна готовність використаного профілю. Будь-який зовнішній alias — посилання, не foreign dependency у старому schema-v2 manifest.

Робочі фази: **C0** контракти; **C1** зовнішньо перевірні експерименти; **C2** власний harness і source; **C3** контрольоване прийняття поколінь; **C4** evaluator/optimizer evolution; **C5** дослідницький вибір і product direction; **C6** доведена рекурсивність. C0–C6 — фази робіт Core; спільні E0–E5 у vision — рівні доказів. C0–C3 готують E1, C4–C6 — E2/E5; жодна фаза не змінює GC/CLD M0–M6. Пріоритет P0/P1 читається всередині фази; це не вимога виконувати всі P0 одночасно.

**Простежуваність:** поле «Підстави» позначає джерело вимоги або власне рішення, не evidence виконаної роботи. Легенда — [source-guide.md](source-guide.md). Текстові картки є джерелом змісту; усі залежності й підстави синхронізуються з JSON.

## C0 — визначити, що означає «Core поліпшився»

### AF-RSI-001 — Розділити повноваження оптимізатора, оцінювача та чинного Core

- **Залежності:** немає. **Reuse:** AF-004 policy, AF-013 Blueprint, AF-018 tools, AF-022 ADR; `policy.py`, `blueprint.py`, `tools.py`, `adr.py`.
- **Результат:** ADR і authority matrix для change proposer, experiment runner, evidence issuer, evaluator, promotion authority та активного control plane.
- **Приймання:** для code, harness, evaluator і product-goal зміни визначено допустимі записи; optimizer не змінює чинні objective, evidence, budget або authorization власним candidate; кожна нова влада є окремою версією рішення. Scope класифікує фактичний effect surface: названа косметичною/інформаційною зміна не отримує прихованого права змінити поведінку, capabilities або контроль. Невизначений експеримент має явно дозволену область невідомого результату.
- **Негативні перевірки:** підміна policy через prompt/skill/retrieval; candidate оголошує себе accepted; service identity видає себе за власника. Усі сценарії залишають чинний control plane без змін. Перейменування behavior mutation на formatting обходить належну перевірку.
- **Артефакт:** decision table, state transitions, attack/denial fixtures. **Фаза/пріоритет:** C0/P0.
- **Підстави:** RSI-SURVEY:R04, RSI-SURVEY:R06, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:experience-improvement

### AF-RSI-002 — Описати незмінний суб’єкт і покоління еволюції

- **Залежності:** 001. **Reuse:** AF-001 identities, AF-016 skills, AF-024 packs, AF-048 worktrees, AF-055 context.
- **Результат:** `EvolutionSubject` і `GenerationManifest`: kind, parent generation, Core commit, harness/role/tool/skill/config digests, runtime/profile, dependencies, mutation scope і rollback target.
- **Приймання:** один generation digest однозначно визначає виконуваний склад; старий manifest відтворюється після registry update; source/harness/model-weight зміни розрізняються. Model weights — окремий research profile, не обіцянка доступного training. ActivationBinding містить target, монотонну activation_seq, manifest digest, authority epoch, writer fence і exact state binding; immutable GenerationManifest не посилається на власний майбутній ActivationReceipt. Canonical entity, incarnation, mutable representation і execution generation мають різні ролі; lineage не є новою authority. Для comparison зафіксовані output schema, decoder/projection і label semantics; common-meaning mapping версій перевірено або результат not-comparable.
- **Негативні перевірки:** floating latest, змінений pack під тим самим version, підміна parent, невідомий component, повторне використання digest для інших bytes. ABA A@41→B@42→A@43 не дозволяє старий grant для A@41; replay promotion ID не збільшує sequence. Та сама назва підміняє іншу сутність; immutable raw receipts переоцінені новим decoder як gain без спільного значення outcome.
- **Артефакт:** versioned schema, три non-game приклади, compatibility matrix. **Фаза/пріоритет:** C0/P0.
- **Підстави:** RSI-SURVEY:R02, RSI-SURVEY:R03, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery, CONTRACT:identity-continuity

### AF-RSI-003 — Зафіксувати протокол порівняння до запуску кандидатів

- **Залежності:** 001, 002. **Reuse:** AF-020 evaluation, AF-032 qualification, AF-027 telemetry.
- **Результат:** `ExperimentProtocol`: гіпотеза, baseline, контрольований change surface, datasets, primary outcome, non-regression floors, budget, seeds/repetitions, comparison rule, stopping rule.
- **Приймання:** protocol digest зафіксований до challenger output; зміна metric/threshold створює новий експеримент; documented failed/inconclusive — валідні завершення. Правила statistical confidence і мінімально корисного ефекту обираються для конкретної задачі до вимірювання. Protocol явно класифікує replay/action intervention/input sensitivity/planner comparison/evaluator comparison; pair identity фіксує initial observable inputs, goal, rules, exogenous/coupling plan і horizon.
- **Негативні перевірки:** підвищення cap лише challenger, вибір metric після результату, викидання невдалих seeds, зниження non-regression floor заднім числом. Після втручання downstream NPC choices не копіюються з baseline; різні задачі не стають paired через однакову назву.
- **Артефакт:** protocol template і acceptance decision examples. **Фаза/пріоритет:** C0/P0.
- **Підстави:** RSI-SURVEY:R04, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:counterfactual-evaluation

### AF-RSI-004 — Зв’язати покоління, спроби, докази та рішення

- **Залежності:** 002, 003. **Reuse:** AF-003 evidence, AF-002 events, AF-051 candidates; поточний SQLite evidence ledger.
- **Результат:** append-only lineage `hypothesis → protocol → baseline/challenger run → receipts → comparison → decision → generation` з rejected і inconclusive branches.
- **Приймання:** restart не створює другого promotion; query пояснює походження чинної версії й показує всі спроби; ні experiment runner, ні review text не змінюють acceptance history. EvidenceSeal фіксує весь admitted attempt set і явні missing/invalid dispositions; пізній receipt створює amendment/challenge, а не змінює seal. Hash не підміняє перевірку issuer. Adoption відновленого Git commit повторно зв’язує actual tree/diff bytes із validated snapshot; accepted result/gate/linkage мають replayable transition identity й reconciliation без другого gate.
- **Негативні перевірки:** duplicate receipt, чужий tenant, неправильний generation, повторення команди після crash, спроба стерти негативний результат. Пізній conflicting receipt не переписує accepted comparison і не допускає нову promotion до розв’язання challenge.
- **Артефакт:** data/API contract, state diagram, replay fixtures. **Фаза/пріоритет:** C0/P0.
- **Підстави:** RSI-SURVEY:R03, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery

## C1 — отримати зовнішній сигнал, який не можна вигадати рефлексією

### AF-RSI-005 — Розділити навчальні приклади, validation і прихований holdout

- **Залежності:** 003, 004. **Reuse:** AF-015 context, AF-016 memory, AF-021 injection defense, AF-029 storage.
- **Результат:** dataset/benchmark registry із provenance, rights, task family, split, version, access scope, contamination tracking та retired-case policy.
- **Приймання:** optimizer бачить дозволені training diagnostics, final holdout працює в окремому evaluator scope; запам’ятований кейс не рахується новим; будь-яка зміна split змінює protocol. Опубліковані паперові Q06-C01–C10 мають статус development/design; fresh holdout потребує незалежного походження та contamination audit, а не лише нових імен або seeds.
- **Негативні перевірки:** витік через logs/memory/error output, перейменування training case у holdout, синтетична копія holdout, retrieval за його приватним ID. Public expected trace чи його синтетичний переказ не оголошується прихованим зовнішнім grounding.
- **Артефакт:** benchmark registry contract, доступи, provenance/contamination receipts. **Фаза/пріоритет:** C1/P0.
- **Підстави:** RSI-SURVEY:R06, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:counterfactual-evaluation

### AF-RSI-006 — Узагальнити evidence-first evaluator поза Codex diff

- **Залежності:** 002, 004. **Reuse:** AF-020 `evaluation.py`, AF-052 `validators.py`, AF-GC-006/041 effective identity, AF-GC-043 admission.
- **Результат:** evaluation subject adapter для harness/config/skill/workflow/Core release, який використовує чинний evidence ledger та reviewer independence.
- **Приймання:** software candidate продовжує вимагати свою п’ятірку validators; інші subjects мають явно версійований набір необхідних receipts; acceptance ніколи не спирається лише на `accepted_evidence=True` або список URL від моделі.
- **Негативні перевірки:** producer/reviewer aliases тієї самої моделі, callback до deterministic failure, forged receipt, replay proof від іншої версії subject.
- **Артефакт:** compatible evaluator contract, adapter conformance і old-path regression evidence. **Фаза/пріоритет:** C1/P0.
- **Підстави:** RSI-SURVEY:R04, REPO-AUDIT, DESIGN:core-architecture

### AF-RSI-007 — Порівнювати реальну користь з урахуванням витрат і шуму

- **Залежності:** 003, 005, 006. **Reuse:** AF-027 telemetry/cost ledger, AF-032 qualification.
- **Результат:** comparator для paired baseline/challenger outcome, dispersion, confidence, cost/latency, sample size, aborts і non-regression floors.
- **Приймання:** рішення `better`, `worse`, `equivalent`, `inconclusive` відтворюється з receipts; failed runs і витрати всіх кандидатів збережено; sequential selection/multiple comparisons враховано за declared protocol. Краща новизна, прибутковість або нижча ціна не компенсують порушений hard invariant; зміна критерію після результату створює новий protocol. Окремо оцінюються виконання початкової мети, правильне handling відмови/невідомості, causal contribution, integrity та повна ціна. Evaluator comparison використовує один frozen corpus із зовнішніми labels і blind order. Declared consumer slices показують вигоду й повну відому ціну для різних ролей, включаючи exit/restore; missing cost не вважається нульовим. Якщо висновок спирається лише на тих, хто залишився, його область прямо обмежено.
- **Негативні перевірки:** більше tokens маскується як intelligence gain, один lucky seed, переоптимізація середнього з критичним tail regression, нескінченне підглядання в holdout. Невиконане читання не стає виконаним через гарне пояснення відмови; більше cascades не компенсує порушену згоду або більші витрати. Середній приріст приховує ціну, перенесену на іншу роль, або порушення її зафіксованого hard floor.
- **Артефакт:** decision report із прикладами adoption/no-go. **Фаза/пріоритет:** C1/P0.
- **Підстави:** RSI-SURVEY:R04, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:counterfactual-evaluation, CONTRACT:experience-improvement

### AF-RSI-008 — Резервувати bounded бюджет повного експерименту

- **Залежності:** 003, 004. **Reuse:** AF-008 loop, AF-027/056 budgets, AF-AMM recovery; чинні authorization/reservation services.
- **Результат:** єдиний experiment budget охоплює baseline, усі challengers, reviewers, retries, tooling і rejected branches.
- **Приймання:** preflight блокує нову роботу поза reservation; Pause/Stop діє й на optimizer/reviewer; restart зберігає спожите й дозволяє лише ті самі залишкові межі; hard expansion потребує нової authority. Reservation існує до dispatch; невідомий effect/charge після timeout має bounded exposure disposition, а не автоматичне повернення бюджету.
- **Негативні перевірки:** розбиття однієї дороговартісної мутації на дочірні безлімітні runs; retry обнуляє counter; підвищення budget через artifact text; missing usage не рахується нульовим. Cancel request або lease expiry не обнуляє вже можливу charge; без потрібної верхньої межі вартості наступний dispatch заблокований.
- **Артефакт:** budget accounting contract і cancel/restart traces. **Фаза/пріоритет:** C1/P0.
- **Підстави:** RSI-SURVEY:R08, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery

### AF-RSI-009 — Кваліфікувати ізольовану арену для змін Core

- **Залежності:** 001, 002, 008. **Reuse:** AF-017 sandbox, AF-044 runtime, AF-048 worktrees, AF-055 context, AF-GC-043 admission.
- **Результат:** isolated experiment profile з окремою Core instance/database, worktree, temporary resources, fixed tools і evidence export.
- **Приймання:** candidate не пише до працюючого Core, evaluator datasets, credentials або accepted artifacts; teardown зберігає evidence; supported OS/backend названі точно. Непідтверджений Windows general sandbox лишається unsupported.
- **Негативні перевірки:** path escape, symlink/junction, inherited secret, background process після cancel, network access поза approved profile, kill під час export.
- **Артефакт:** arena qualification report і confinement receipts. **Фаза/пріоритет:** C1/P0.
- **Підстави:** RSI-SURVEY:R03, RSI-SURVEY:R06, REPO-AUDIT, DESIGN:core-architecture

### AF-RSI-010 — Перетворити ідею поліпшення на точний candidate plan

- **Залежності:** 002, 003, 009. **Reuse:** AF-013 Blueprint, AF-022 ADR, AF-051 candidates, AF-008 repair.
- **Результат:** mutation proposal з причиною, affected surfaces, diff/patch, dependencies, очікуваним ефектом, ризиком, необхідними checks і rollback class.
- **Приймання:** proposal не виконується до protocol/authority match; механічне переформулювання без зміни поведінки не називається improvement; обраний patch пояснюється через конкретні prior failures або гіпотезу.
- **Негативні перевірки:** прихована зміна evaluator, unchecked config widening, модифікація source поза manifest, несумісна залежність під виглядом prompt edit.
- **Артефакт:** reviewable mutation manifest і affected-surface diff. **Фаза/пріоритет:** C1/P0.
- **Підстави:** RSI-SURVEY:R02, REPO-AUDIT, DESIGN:core-architecture

### AF-RSI-011 — Виконати baseline і challenger за одним протоколом

- **Залежності:** 005, 006, 008, 009, 010. **Reuse:** AF-006 workflows, AF-044 runtime, AF-AMM checkpoints/epochs, AF-052 validators.
- **Результат:** experiment runner, який викликає чинний execution boundary і повертає primary receipts, а не власну чергу/worker implementation.
- **Приймання:** відомі seeds, model/runtime versions, hardware profile і budgets збережено; replay використовує accepted inputs; варіативність model calls чесно відокремлена від детермінованого replay accepted actions. AttemptIntent persist до dispatch; receiver capability profile визначає допустимий lookup/dedup/retry. Unknown non-repeatable effect не повторюється без reconciliation, згідно з RC01–04 recovery contract. Same seed не є достатньою paired гарантією: зафіксовані stream roles/event mapping, unmatched-draw policy та перерахунок distributions після зміни дії. Planner outputs можуть відрізнятися; replay має інший claim.
- **Негативні перевірки:** baseline випадково на новому harness, shared mutable cache заражає іншу групу, dropped failed run, partial result после restart оголошено complete. Provider без outcome lookup не оголошується exactly-once; cancel acknowledgment не підміняє observed stopped/no-effect receipt. Додаткова model репліка не має непомітно зміщувати зовнішню погоду в парі; різні causal conditions не примушують до однакового random outcome.
- **Артефакт:** baseline/challenger execution bundle і comparison-ready index. **Фаза/пріоритет:** C1/P0.
- **Підстави:** RSI-SURVEY:R05, RSI-SURVEY:R08, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery, CONTRACT:counterfactual-evaluation

## C2 — навчитися змінювати власний harness і власний source

### AF-RSI-012 — Накопичувати перевірений досвід як граф існуючих доказів

- **Залежності:** 004, 005, 006, 011. **Reuse:** AF-015 context, AF-016 typed memory, AF-021 quarantine.
- **Результат:** experience graph зв’язує гіпотези, результати, skills, consumers і contradictions через існуючі immutable IDs.
- **Приймання:** failed/inconclusive outcomes впливають на наступний hypothesis selection; revoked/stale memory перестає входити в нові context packages, історичні consumers лишаються доступні; tenant/purpose isolation збережено.
- **Негативні перевірки:** reflection без evidence піднімається до fact, кругове цитування підсилює confidence, invalidated skill продовжує propagation, private task data стає global memory.
- **Артефакт:** graph schema/projections і contamination/revocation trace. **Фаза/пріоритет:** C2/P0.
- **Підстави:** RSI-SURVEY:R03, RSI-SURVEY:R06, REPO-AUDIT, DESIGN:core-architecture

### AF-RSI-013 — Еволюціонувати harness, routing і skills через existing registries

- **Залежності:** 007, 010, 011, 012. **Reuse:** AF-010 roles, AF-011 routing, AF-012 composition, AF-016 skills, AF-024 packs.
- **Результат:** один обмежений профіль mutation для prompts/context policy/tool choice/role topology/skills із versioned manifests.
- **Приймання:** змінений harness дає verified benefit на зовнішньому наборі задач; route fallback не руйнує producer/reviewer independence; skill transitions відбуваються у чинному registry з primary evaluation receipts. Reuse skill/memory у новому runtime, tenant або purpose проходить окремі scope/authority/applicability checks; hash і lineage не видають права. Alias/model name не доводять незалежність reviewer за declared decision policy.
- **Негативні перевірки:** виробник набуває reviewer duty, routing приховує дорогі fallback calls, auto-install tool без capability approval, skill оцінюється лише на власних прикладах. Новий agent ID приховує producer lineage чи конфлікт duties; copied memory scope мовчки розширено; latest role lookup підміняє qualified version.
- **Артефакт:** accepted або rejected harness generation, ablation без кожної ключової зміни. **Фаза/пріоритет:** C2/P0.
- **Підстави:** RSI-SURVEY:R02, RSI-SURVEY:R03, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:identity-continuity

### AF-RSI-014 — Готувати зміни власного коду Core як звичайні immutable candidates

- **Залежності:** 009, 010, 011. **Reuse:** AF-049/050 workers, AF-051 candidates, AF-052 validators, AF-053 delivery, AF-054 software roles.
- **Результат:** Core може вибрати свій repository як target і створити scoped candidate source change через існуючий coding pipeline.
- **Приймання:** candidate вирішує відтворену platform-задачу, має exact base/head/diff, незалежний review і release plan; активний Core не підміняється під час свого експерименту. Affected surface включає залежні зміни capabilities, required components і maintenance cost. Для supported schema migration перевірені semantic permission/role/purpose contracts та outcome projections, а не лише читабельність даних; failure/partial state визначений до активації.
- **Негативні перевірки:** patch змінює tests, щоб приховати failure; самовільний push/merge/install; зміна worker authority; developer database потрапляє до candidate artifacts. Компонент A покращено непогодженою зміною B; старий permission label набув ширшого змісту; preview або тимчасовий дослід сам активує постійний Core.
- **Артефакт:** Core-on-Core candidate branch/patch і повний delivery receipt. **Фаза/пріоритет:** C2/P0.
- **Підстави:** RSI-SURVEY:R02, RSI-SURVEY:R03, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:identity-continuity

### AF-RSI-015 — Побудувати незалежний benchmark продукту Core

- **Залежності:** 003, 005, 007, 011. **Reuse:** AF-025 reference pack, AF-032 qualification, AF-034 acceptance mission, AF-GC-001 checks.
- **Результат:** фіксований benchmark реальних non-game задач: баг/feature у зовнішньому fixture repo, планування з неоднозначними вимогами, обробка відмови/перезапуску, читабельність operator result.
- **Приймання:** success визначається зовнішніми tests і людською оцінкою там, де вона потрібна; tool use, time/cost, ручні виправлення та failed attempts рахуються; benchmark не складається лише з unit tests самого Core.
- **Негативні перевірки:** task identity leakage, hardcoded answer, текстовий «готово» без артефакту, non-game task потребує Godot або Cloud.
- **Артефакт:** versioned benchmark suite і baseline report. **Фаза/пріоритет:** C2/P0.
- **Підстави:** RSI-SURVEY:R08, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture

### AF-RSI-016 — Перевіряти сумісність стану, API і міграцій між поколіннями

- **Залежності:** 002, 014, 015. **Reuse:** AF-001 migrations, AF-026 API, AF-028/057 recovery, AF-AMM-046 compatibility.
- **Результат:** generation compatibility contract для active missions, paused runs, pending gates, evidence, configured integrations і local user data.
- **Приймання:** upgrade зберігає IDs/authority; старі consumer contracts працюють у заявленому compatibility envelope; rollback або forward repair має перевірений state plan; несумісна версія блокується до switch.
- **Негативні перевірки:** schema downgrade губить data, approved old gate запускає нові ширші tools, змінився digest після migration, interrupted upgrade залишає змішаний runtime.
- **Артефакт:** upgrade/restore drill з old/new snapshots і exact compatibility verdict. **Фаза/пріоритет:** C2/P0.
- **Підстави:** RSI-SURVEY:R03, REPO-AUDIT, DESIGN:core-architecture

## C3 — приймати покоління без втрати працюючого продукту

### AF-RSI-017 — Просувати й відкочувати generation через shadow/canary stages

- **Залежності:** 004, 007, 008, 016. **Reuse:** AF-024 pack lifecycle, AF-031 deployment profiles, AF-057 recovery; existing immutable release images/autodeploy plans.
- **Результат:** release lifecycle `candidate → qualified → shadow → canary → promoted → superseded | revoked` із protected ActivationBinding. Обов’язкові shadow/canary stages задає profile; rejection лишається comparison outcome, rollback — нова authorized activation, не стан для стирання старої історії.
- **Приймання:** shadow не чинить повторних зовнішніх effects; canary audience/profile має explicit scope; failure до commit залишає binding незмінною, після commit виконується scoped recovery за ActivationReceipt; несумісний/revoked fallback веде до paused/degraded режиму; дані канарки не губляться мовчки при restore. Grant/revocation і activation serialized в одній qualified authority boundary; final commit перевіряє exact ActivationBinding і immutable state readiness. Root supervisor upgrade має independent authority, quiesced control state і fenced handoff. Supported identity/role/schema transitions мають ContinuityPlan з inventory класів, визначеним qualified profile/authority, per-record rights/obligations/resources/privacy dispositions і unknown/unmapped outcomes. Зміна покоління не скидає unresolved effects, budget lineage, чинні revocations або відповідальність; одноразове approval не розширює scope наступника.
- **Негативні перевірки:** two concurrent promotions, crash після pointer switch, rejected generation повертається як latest, старе approval переноситься на нові bytes, canary виходить за audience. RC06–11/14/16: grant revoke race, ABA, concurrent candidates, lost ack, unreadied successor, revoked fallback; жоден candidate не завершує self-approval. Candidate виключає незручний запис із migration inventory; split/merge копіює grants або private memory без authority; rollback відновлює старі права поверх чинної revocation.
- **Артефакт:** promotion receipt, rollback drill, previous-generation availability proof. **Фаза/пріоритет:** C3/P0.
- **Підстави:** RSI-SURVEY:R03, RSI-SURVEY:R06, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery, CONTRACT:identity-continuity

### AF-RSI-018 — Показати людині стан і причину самовдосконалення

- **Залежності:** 004, 007, 008, 017. **Reuse:** AF-036 application services, AF-038/043 operator UI, AF-056 telemetry.
- **Результат:** operator view «що Core намагається поліпшити, чому, скільки витрачено, що доведено, що буде застосовано» з generation comparison і Pause/Stop.
- **Приймання:** evaluation, proposal, accepted candidate і active release мають різні зрозумілі стани; failed experiment видимий; primary next action не вимагає JSON; current good generation і rollback доступні. За чинною consumer policy реальний Stop/opt-out до ефекту інвалідує несумісну queued поведінку; current policy/version check на остаточній authoritative show/dispatch boundary серіалізований з прийняттям opt-out; stale output denied/re-rendered, уже доставлене не оголошується скасованим. Потрібні state/effect receipts, ціна й стан виходу/повернення, а не лише видима кнопка.
- **Негативні перевірки:** missing receipts відображають green success, refresh стирає незбережену owner decision, stale UI дозволяє інший promotion, paused workflow витрачає бюджет у дочірніх runs. Стара запланована відповідь обходить нове обмеження; style change приховує необхідну причину відмови чи шлях відновлення.
- **Артефакт:** UI/API acceptance scenarios, accessibility та interruption walkthrough. **Фаза/пріоритет:** C3/P1.
- **Підстави:** RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:experience-improvement

### AF-RSI-019 — Прийняти перший Core-on-Core цикл без заяви про повний RSI

- **Залежності:** 013, 014, 015, 016, 017, 018. **Reuse:** AF-034 acceptance mission, AF-020 independent review.
- **Результат:** end-to-end proof для принаймні однієї harness-зміни й однієї source-зміни власного Core.
- **Приймання:** baseline→proposal→execution→comparison→decision→retained generation виконується з реальними providers/tools; передбачено один навмисно невдалий кандидат і recovery. Positive improvement потребує measured gain; якщо його немає, результат — no-go/iteration, не примусове pass.
- **Негативні перевірки:** зміна тільки narrative, відсутній holdout, локальна unit-pass видається за product gain, збережено лише переможців.
- **Артефакт:** independently reviewed Core-on-Core report, active scope і remaining limits. **Фаза/пріоритет:** C3/P0.
- **Підстави:** RSI-SURVEY:R04, RSI-SURVEY:R08, REPO-AUDIT, DESIGN:core-architecture

## C4 — вдосконалювати optimizer та метод оцінки, не замикати самопідтвердження

### AF-RSI-020 — Подавати новий evaluator як окремий candidate subject

- **Залежності:** 001, 002, 005, 006, 019. **Reuse:** AF-020 evaluation, AF-022 ADR, AF-024 evaluation packs.
- **Результат:** evaluator manifest з rubric, tools, dataset construction, judgment method, cost і known failure envelope.
- **Приймання:** чинний frozen protocol та незалежна holdout authority перевіряють challenger evaluator; evaluator не приймає власну заміну й не змінює historical verdicts; CriterionManifest фіксує не тільки judge, а generation/sampling/replay/scoring dependencies, outcome meaning, prior-access snapshot, політику наступних звернень і qualification envelope; профіль задає повний inventory, невідомі залежності залишаються unresolved; нова епоха активується з узгодженим criterion/selection snapshot за Q05; джерело первинного факту, telemetry producer і decoder кваліфіковані окремо від judge.
- **Негативні перевірки:** evaluator/optimizer одночасно послаблюють metric; champion переписано під час comparison; новий evaluator або його діагност отримує sealed labels; той самий checker помилково приховує змінений task sampler; crash перемикає evaluator без його selection view.
- **Артефакт:** evaluator candidate, CriterionManifest та comparison/transition report проти незалежних anchors. **Фаза/пріоритет:** C4/P0.
- **Підстави:** RSI-SURVEY:R04, RSI-SURVEY:R06, RSI-RQGM:RQGM-01, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:evaluator-succession

### AF-RSI-021 — Кваліфікувати калібрування й систематичні помилки evaluator

- **Залежності:** 007, 020. **Reuse:** AF-020 criterion evidence, AF-021 hostile cases, AF-023 independent coordination.
- **Результат:** eval-of-eval suite з зовнішньо перевірними outcomes, blinded human labels для qualitative cases, calibration і false-accept/false-reject analysis.
- **Приймання:** упередженість на користь автора, довгих відповідей, престижної моделі й оптимістичного proposal виміряна; abstain/inconclusive — дозволені; reviewer disagreement збережено; frozen qualitative corpus включає відмінності між наміром автора, досвідом адресата, повтором-парафразом і неповними відповідями; зовнішній розбір перевіряє uncertainty та область claim; anchor exposure audit охоплює діагностів, feedback, aggregate scores і memory, а final confirmation відділена від adaptive selection; panel acceptance та зовнішня фактична правильність мають різні labels і permitted claims; blind quality slices перевіряють добрі/погані роботи різного авторства, parity rates не дорівнює fairness, кілька reviews одного artifact рахуються як кластер, partial/strict outcomes збережені окремо.
- **Негативні перевірки:** красивий неправильний research plan, short correct answer, самопосилання на confidence, протилежні labels після перестановки імен моделей; позитивні відповіді тільки тих, хто залишився, підміняють якість для всіх; solver не бачить tests, але test-aware diagnostic передає їх у skill, після чого corpus названо untouched holdout; збіг суддів названо ground truth; missing telemetry marker названо відсутністю порушення, valid compatible format безпідставно rejected або якісний artifact відхилено заради parity.
- **Артефакт:** calibration report і permitted evaluation envelope; thresholds fixed before run. **Фаза/пріоритет:** C4/P0.
- **Підстави:** RSI-SURVEY:R04, RSI-SURVEY:R06, RSI-DGM:DGM-03, RSI-RQGM:RQGM-02, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:experience-improvement, CONTRACT:evaluator-succession

### AF-RSI-022 — Розділити agent gain та evaluator drift при коеволюції

- **Залежності:** 019, 020, 021. **Reuse:** AF-027 comparison telemetry, AF-022 methodology versioning.
- **Результат:** 2×2 cross-evaluation: old agent/new agent × old evaluator/new evaluator плюс зовнішній sentinel suite.
- **Приймання:** видно, чи поліпшився task result, чи лише змінився спосіб оцінки; prior released generations зберігають original protocols/verdicts; methodology upgrade має separate decision; stale fitness/posteriors/ranks та залежні distilled conclusions виключаються з нового selection view за criterion dependency inventory, raw receipts не стираються; нові оцінки мають нові records, старий corpus не названо fresh generation; запізнілі результати лишаються historical до applicability decision і не обнуляють витрати; незалежна adjudication може встановити помилку incumbent evaluator.
- **Негативні перевірки:** gain зникає на old evaluator і без зовнішнього розбору проголошено провал challenger; новий evaluator приймає poisoned candidates; drift маскується aggregate score або selective cross-cell omission; criterion switch залишає stale champion; re-score старих outputs видано за нову поведінку генератора.
- **Артефакт:** cross-evaluation matrix, criterion dependency inventory, rebuilt selection view, dissent та methodology adoption/rejection receipt. **Фаза/пріоритет:** C4/P0.
- **Підстави:** RSI-SURVEY:R04, RSI-SURVEY:R06, RSI-RQGM:RQGM-01, RSI-RQGM:RQGM-03, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:evaluator-succession

### AF-RSI-023 — Порівнювати покоління самого optimizer

- **Залежності:** 007, 010, 012, 019. **Reuse:** AF-011 routing, AF-023 tournament/coordination, AF-008 bounded loop.
- **Результат:** optimizer subject має versioned proposal policy, search strategy, mutation operators, memory retrieval і experiment selection.
- **Приймання:** optimizer N і N+1 стартують з однакового дозволеного knowledge/budget на відкладених задачах; вимірюються independent accepted improvements per total cost і time-to-useful-change, включно з невдалими пошуками; одиниця корисного improvement, resource caps, ціна та adaptive-selection policy фіксуються до досліду; облік включає creation/qualification, expansions, judges, archive re-evaluation, anchors і confirmation; conditional reuse efficiency позначається окремо; архівований stepping stone не отримує release eligibility від самого search score; незалежні search runs відділені від повторів оцінки одного агента, starting archive/diagnosis/selection контрольовані або відкрито включені в treatment bundle.
- **Негативні перевірки:** challenger отримав training traces тестового періоду; більше parallel compute без обліку; score за кількістю proposals/commits або поділ однієї зміни на кілька accepted artifacts; копіювання готового challenger solution; equal evaluation calls приховали дорожчу модель, додаткові перевірки або creation cost; revoked predecessor повернуто через новий rank.
- **Артефакт:** optimizer-generation benchmark і counterfactual ablation. **Фаза/пріоритет:** C4/P0.
- **Підстави:** RSI-SURVEY:R08, RSI-DGM:DGM-01, RSI-DGM:DGM-02, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:evaluator-succession

### AF-RSI-024 — Замкнути перший bounded рекурсивний цикл

- **Залежності:** 017, 019, 022, 023. **Reuse:** AF-AMM epochs/checkpoints, AF-008 loop, AF-053 delivery.
- **Результат:** Core запускає optimizer N; той пропонує N+1; зовнішня процедура приймає/відхиляє N+1; прийнятий N+1 бере участь у створенні наступного Core/harness покоління.
- **Приймання:** typed lineage O0→O1→O2 показує, що прийнятий optimizer O1 запропонував зміну самого optimizer/method O2; product artifacts оцінюються окремо на fresh tasks; користь O2 порівнюється з безпосереднім прийнятим O1 за спільного protocol/knowledge/resource envelope та ablation без нового методу; stopping/depth/cost bounds фіксовані, а зовнішній anchor незалежний; qualification/supervisor не змінюється власним candidate під час його перевірки, власна зміна control process має окремий handoff за Q05; без виміряної користі O2 зберігається як відхилена/невизначена зміна, локальний успіх O1 і recursive participation не перетворюються на positive next-step gain; рольова карта й execution receipt підтверджують фактичне використання зміненого operator, а не тільки наявність його файла.
- **Негативні перевірки:** самопризначення N+1 чемпіоном; незавершений epoch оголошено successor; depth/cost limit обходиться новим mission ID; цикл триває після Stop; O2 кращий лише за O0, але гірший за O1; benchmark або panel curve названо доказом автономної еволюції всього control loop чи правильної продуктової мети.
- **Артефакт:** recursive lineage bundle з відтворюваним rejection/recovery path. **Фаза/пріоритет:** C4/P0.
- **Підстави:** RSI-SURVEY:R08, RSI-SURVEY:R12, RSI-DGM:DGM-02, RSI-RQGM:RQGM-03, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:evaluator-succession

## C5 — поліпшувати вибір задач і напрям розвитку самого продукту

### AF-RSI-025 — Виводити можливості поліпшення з реальних failures і friction

- **Залежності:** 012, 015, 018. **Reuse:** AF-027 telemetry, AF-009 intake, AF-AMM backlog analyzer/revisions.
- **Результат:** opportunity records містять observed failure/friction, affected users/tasks, source evidence, frequency/impact uncertainty і candidate hypothesis.
- **Приймання:** система відрізняє bug, usability gap, unsupported scope, evaluator problem і research unknown; згортає дублікати за cause/evidence, зберігаючи початкові reports; не створює бажання користувача з telemetry. Для creator-сигналу прив’язано точні product/profile, brief/scope, фактичний stage і доступні source/build/session identities. Припущення про cause відділено від перевіреного дефекту. Непідключений Play не рахується невдалою зіграною сесією, authored paper fixture не стає observed user report. Projection перевіряє reviewed human requirements поряд з original source, а не лише збереження оригіналу.
- **Негативні перевірки:** один noisy incident стає roadmap mandate; private content витікає в shared hypothesis; уже виправлений issue без нової evidence відкривається знову. Source checksum збігається, але людські edits/agreed scope втрачено в execution context. Cloud UI або world-only candidate отримує claim про поліпшений незмінений Core.
- **Артефакт:** ranked opportunity register з provenance і uncertainty. **Фаза/пріоритет:** C5/P1.
- **Підстави:** RSI-SURVEY:R07, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:creator-evolution

### AF-RSI-026 — Ввести незалежний продуктовий сигнал від користувачів Core

- **Залежності:** 003, 015, 018, 025. **Reuse:** AF-009 intent, AF-015 provenance, AF-016 preferences, AF-029 scoped storage.
- **Результат:** consent-scoped feedback/user-study protocol для task completion, зрозумілості, кількості ручних виправлень, довіри до пояснення та керованості.
- **Приймання:** qualitative evidence пов’язане з точним продуктом/версією/сценарієм; simulation і synthetic users не видаються за дослідження людей; часові/географічні/вибіркові обмеження видимі. У дозволеному обсязі показано denominators для початку, завершення, зупинки й наданого feedback. Withdrawn/missing не заповнюється вигаданою оцінкою; відмова відповідати не погіршує доступ. Без дозволу на облік denominator позначено невідомим. Planning і end-to-end study мають окремі prerequisites/outcomes. Для creator case stage completion не підміняє finished game. Planned fidelity reviewed scope відділено від realized fidelity поведінки exact build, кожна застосовується на своєму study рівні. Fidelity commitments і scope decisions, actual played/source/target versions, independent/assisted outcome, active/wall/wait time та usable restore receipt визначено до comparison. Менші зусилля через непогоджене спрощення не проходять floor. Недоступний runtime не оцінюється як time-to-Play, зміна task meaning створює нову versioned hypothesis.
- **Негативні перевірки:** optimizer фабрикує голос користувача, vanity engagement замінює task success, невдоволені сесії виключено, приватні тексти автоматично потрапляють у training. Причина виходу приписана без evidence; відкликання згоди ігнорується заради повного журналу; невідповідь прирівняна до задоволення. Допомога фасилітатора прихована, history view видано за playable restore, feedback V1 тихо приклеєно до latest V2. Кілька аналітичних ролей одного receipt пораховано незалежними спостереженнями.
- **Артефакт:** product feedback evidence contract і blinded comparison template. **Фаза/пріоритет:** C5/P1.
- **Підстави:** RSI-SURVEY:R07, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:experience-improvement, CONTRACT:creator-evolution

### AF-RSI-027 — Пропонувати research portfolio та перегляд product goal

- **Залежності:** 003, 007, 025, 026. **Reuse:** AF-009 intake, AF-013 Blueprint, AF-022 ADR, AF-AMM backlog revisions.
- **Результат:** альтернативні product/research directions із value-of-information, cost, uncertainty, decisive experiment, opportunity cost і stop/abandon criterion.
- **Приймання:** агент може довести, що поточний напрям не підтверджується; scope/objective/value function change оформлено як versioned proposal до власника; попередні критерії не переписуються, щоб «успішно» завершити стару мету. Окремий контрприклад має зростання локального task-success і недостатнє наближення до потреби власника; допустимий висновок — abandon/change proposal із ціною переходу й decisive experiment.
- **Негативні перевірки:** власна benchmark-слабкість перетворюється на вилучення user need, adoption росте через приховування costs, goal drift без decision, нескінченне дослідження без decisive experiment. Успішне виконання багатьох дрібних задач оголошене доказом правильного продуктового напряму без перевірки потреби.
- **Артефакт:** portfolio decision memo, comparison of alternatives і owner-decision boundary. **Фаза/пріоритет:** C5/P0.
- **Підстави:** RSI-SURVEY:R07, RSI-SURVEY:R10, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:experience-improvement

### AF-RSI-028 — Перевіряти нові інструменти й топології як пояснювані експерименти

- **Залежності:** 013, 020, 023, 027. **Reuse:** AF-010 roles, AF-012 workforce, AF-018 tool gateway, AF-023 coordination, AF-024 packs.
- **Результат:** дослідницький профіль для synthesized tools, new skill libraries, agent-role topology та context/retrieval strategy з одним variable per minimal comparison або явним factorial design.
- **Приймання:** результат перевіряється на нових task families; tool permissions/register/lifecycle лишаються чинними; ablation відділяє gain інструмента від додаткових агентів/tokens.
- **Негативні перевірки:** generated tool має hidden network/write effect, debate створює correlated reviewers, search-space expansion оминає cap, зміна багатьох факторів не має attribution.
- **Артефакт:** experiment portfolio і qualified reusable capability candidate. **Фаза/пріоритет:** C5/P1.
- **Підстави:** RSI-SURVEY:R02, RSI-SURVEY:R08, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture

## C6 — довести тривале накопичення користі й зупинити деградацію

### AF-RSI-029 — Випробувати довгу еволюцію на poisoning, drift і відновлення

- **Залежності:** 012, 016, 017, 022, 024. **Reuse:** AF-021 security, AF-028 chaos/recovery, AF-033 soak.
- **Результат:** versioned long-run schedule зі staged bad skill, evaluator bias, stale memory, corrupted candidate, interrupted migration, provider outage та exhausted budget.
- **Приймання:** за preregistered run length і workload profile неприйнята зміна не поширюється; revoked evidence/skill відстежується до consumers; сумісний state і дозволене previous accepted generation відновлюються, а за відсутності придатного fallback зберігаються історія й recovery disposition у paused/degraded режимі; не приховано ресурсне зростання. Майбутня реалізація проходить застосовні до прийнятих Core profiles RC01–14/16 із recovery-contract.md на neutral fixtures, включаючи final-commit races, bounded unknown effects і supervisor handoff. Доменний RC15 перевіряється тільки при окремій кваліфікації C7; not-applicable/unsupported не рахується pass і не створює world prerequisite для standalone Core.
- **Негативні перевірки:** помилка переживає rollback у shared cache, кілька слабких accepted changes дають сукупну деградацію, orphan optimizer далі витрачає ресурси, evaluator drift вимикає sentinel. Письмова таблиця RC не вважається виконаним chaos report; stale fence не дає права робити remote effect, який не підтримує fence.
- **Артефакт:** soak/chaos report з усіма interventions і failure lineage. **Фаза/пріоритет:** C6/P0.
- **Підстави:** RSI-SURVEY:R03, RSI-SURVEY:R06, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery

### AF-RSI-030 — Прийняти самовдосконалення Lokvetia Core як окремий продукт

- **Залежності:** 019, 024, 026, 027, 028, 029. **Reuse:** AF-034 acceptance mission, AF-032 qualification, AF-035 GA handover evidence.
- **Результат:** окремий Core RSI acceptance dossier; немає залежності від playable Lokiravia чи прийняття ігрового світу.
- **Приймання:** за зафіксованим протоколом кілька послідовних поколінь охоплюють власні source/harness і optimizer; показано benefit на щонайменше двох незалежних non-game task families, product-signal evidence, failed candidate, evaluator challenge і rollback. Реальна кількість поколінь/вибірка/порогові значення зафіксовані до запуску. Якщо дані не підтверджують приріст, gate не пройдено.
- **Негативні перевірки:** успіх тільки на cached training tasks; жодної зміни optimizer; змінений evaluator — єдине джерело gain; Core не працює без Cloud/game pack; підтримку оголошено поза qualified OS/model envelope.
- **Артефакт:** independent release review, supported scope, measured limits, source/export/restore bundle і список наступних відкритих research questions. **Фаза/пріоритет:** C6/P0.
- **Підстави:** RSI-SURVEY:R08, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture

## Чому це не дублює існуючий беклог

Нові tasks не переписують sandbox, typed memory, role routing, worktrees, coding delivery чи pack lifecycle. Вони додають відсутні **суб’єкти покоління, protocols/holdout, comparison, promotion lineage, evaluator/optimizer experiments і Core-specific acceptance** поверх існуючих служб. `AF-RSI-009`, `013`, `014`, `016`, `018`, `029` є саме інтеграцією/кваліфікацією existing capabilities для нового recursion scope, а не claim на другу реалізацію тих самих модулів.

Core-on-Core не залежить від commercial non-game offering `AF-CLD-066`: Core вже має бути domain-neutral самостійним продуктом. Аналогічно новий Core RSI gate не дозволяє пропускати game Play/rights/age/commercial gates у Lokiravia. Shared evidence infrastructure має одну implementation authority; product benefit і world quality оцінюються кожним продуктом за власним accepted protocol.

Найперший reviewable зріз: 001–004 і concrete protocol для 015. Паралельно можна уточнювати isolation/evaluator adapters 006/009 та product-signal дослідження 026 на design level. Реальний запуск чекає своїх технічних prerequisites; документаційне дослідження наступних фаз не повинно чекати майбутніх імплементацій.

## C7 — спільні контракти для domain packs, окремо від standalone Core gate

031–034 конкретизують раніше описані gameplay follow-ups. Це optional consumer track: жоден із 001–030 не залежить від нього. Правила світу залишаються в game pack, а Core надає нейтральні validation/runtime/evidence adapters.

### AF-RSI-031 — Типізувати дозволену дію агента у зовнішньому домені

- **Залежності:** 001, 002, 004, 006. **Reuse:** AF-018 tool gateway, AF-021 injection defense, AF-GC-043 admission; domain-action follow-up з існуючого Unreal plan.
- **Результат:** optional domain-action adapter: actor/world/session/revision/request identity, expiry, typed arguments, domain validation hook, allowed scope та receipts.
- **Приймання:** adapter не знає сюжету чи економіки; domain validator має остаточне слово щодо state delta; duplicate/stale/unauthorized proposals не дають effect; provider text не може створити новий action type.
- **Негативні перевірки:** старий save epoch, знищений actor, forged authority, повторний request, інша tenant/world identity, невідомий тип дії.
- **Артефакт:** versioned action contract, compatibility adapter plan і conformance fixtures. **Фаза/пріоритет:** C7/P0.
- **Підстави:** RSI-SURVEY:R03, RSI-SURVEY:R04, REPO-AUDIT, DESIGN:core-architecture

### AF-RSI-032 — Задати нейтральний контракт replay та доменного checkpoint

- **Залежності:** 004, 031. **Reuse:** AF-002 events, AF-003 evidence, AF-016 memory, AF-028 recovery; game-specific application залишається в pack.
- **Результат:** adapter пов’язує accepted event, causation, revision, rule digest, random draws, checkpoint та replay receipt; канон стану належить engine/pack.
- **Приймання:** replay використовує записані inputs, не нову LLM генерацію; атомарний checkpoint зберігає active rule epoch та останню прийняту revision; causal queries розрізняють факт, belief і невідомий зв’язок. Checkpoint має committed revision/watermark, stable accepted jobs, rule/schema digest; migration від stale revision відхиляється. Load видає новий session epoch; final state commit повторно звіряє epoch/fence і атомарно фіксує delta/event/resource/job completion/dedup.
- **Негативні перевірки:** пропущена/подвійна подія, checkpoint до незавершеної транзакції, хибне твердження про глобальний детермінізм, unbounded offscreen catch-up. RC12/13/15: lost accepted event між copy і switch, partial checkpoint, precheck reply до load з apply після load, виданий ресурс без job receipt.
- **Артефакт:** replay/checkpoint contract, injected-gap fixtures і declared determinism envelope. **Фаза/пріоритет:** C7/P0.
- **Підстави:** RSI-SURVEY:R03, RSI-SURVEY:R11, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery

### AF-RSI-033 — Кваліфікувати повільні agent decisions поза ігровим tick

- **Залежності:** 008, 009, 031. **Reuse:** AF-011 routing, AF-027 budgets, AF-044 runtime, AF-GC-041 effective provider evidence.
- **Результат:** bounded asynchronous inference profile із cancellation, per-session costs, request expiry та domain fallback signal.
- **Приймання:** deterministic engine не чекає LLM на кадрі; stale/cancelled reply відкидається; budget рахує retries й provider fallback; qualified envelope містить latency/frame impact, source/target versions і поведінку при outage. Late reply після cancel/load перевіряється також на authoritative apply boundary; відсутність provider stop observer лишає effect reconciliation, а не доказ зупиненого процесу.
- **Негативні перевірки:** timeout на п’ять хвилин, відсутній usage receipt, callback після load, master key у player package, retry storm. Успішний precheck не дозволяє apply після зміни epoch; невідома provider charge не зникає з budget ledger.
- **Артефакт:** runtime-profile contract, failure walkthrough і measurement protocol. **Фаза/пріоритет:** C7/P0.
- **Підстави:** RSI-SURVEY:R08, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery

### AF-RSI-034 — Оцінювати domain-rule candidates без присвоєння художньої влади

- **Залежності:** 007, 016, 017, 031, 032. **Reuse:** AF-020 evaluation, AF-024 packs, AF-051 candidates; domain suite і людський playtest визначає автор продукту.
- **Результат:** `world_rules` subject підтримує old/new rule digest, compatibility/migration, deterministic receipts і окремі human-quality evidence.
- **Приймання:** schema/test pass не вважається доказом гумору; Core comparison не переписує world state і не публікує pack; comparison decision і scoped promotion authorization розділені; старий accepted consumer pin працездатний. Rule migration переключає coherent rule/schema/checkpoint/revision/writer binding; comparison, scoped grant і ActivationReceipt розділені. Qualification stale snapshot не переноситься на нові live writes без перевірки. Domain scenario bundle розрізняє authored expected outcomes, виконані state receipts та human evidence. Consumer planner claim не замінює незалежний non-game Core gate або O0→O1→O2 method proof.
- **Негативні перевірки:** новий evaluator схвалює власне правило без зовнішніх anchors, rule update змінює минулі події, відкат знищує чесні пізні дії, stale canary grant застосовується до інших bytes. RC07/09/12–16: revoke/ABA, міграція r10 після live r11, half checkpoint, mixed rule/state, rewind save повторює зовнішній grant. Готова паперова історія чи новий world-state trace видається за вже поліпшений Core; новий evaluator сам створює легший corpus для своєї оцінки.
- **Артефакт:** domain-evolution integration receipt і versioned migration/recovery specification. **Фаза/пріоритет:** C7/P1.
- **Підстави:** RSI-SURVEY:R03, RSI-SURVEY:R04, RSI-SURVEY:R12, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:recovery, CONTRACT:counterfactual-evaluation

## C8 — довгий дослідницький горизонт

### AF-RSI-035 — Перевірити доцільність training-time self-iteration

- **Залежності:** 005, 007, 021, 027, 029. **Reuse:** AF-024 packs, AF-027 cost accounting, AF-032 qualification; RSI-SURVEY §4 і RSI-AEVOLVE.
- **Результат:** окремий feasibility/experiment design перевіряє, чи дозволений adapter/model training дає додаткову користь конкретному Core workflow проти frozen-weight harness-only альтернативи.
- **Приймання:** design відділяє feasibility, scoped pilot admission та post-run adoption/reject/inconclusive, виміряний gain не вимагається до першого пілоту; доступ до weights/data rights/license, ресурсний profile і достатність протоколу обґрунтовані до admission, саме додавання design не дозволяє training; research/controller model+harness, target/base/tokenizer, trainer/data/recipe, job і produced checkpoint мають окремі exact identities, future output hash фіксується після створення; standing recipe не підміняє reference, прихована спадковість checkpoint/optimizer state виключена; визначені checkpoint-selection/repeats/noise, actual data manifests, dev/adaptive feedback/final confirmation та contamination/collapse controls; внутрішній selection strategy може бути treatment за спільного external criterion, зміна authoritative acceptance потребує окремого protocol, retrospective threshold rescue заборонений; receiver profile задає submit/cancel/result reconciliation, exact resume відрізнено від нового warm-start plan/input/admission, job/campaign caps і unresolved costs збережені; повний cost ledger включає synthesis, failures/retries, evaluation, I/O/storage/export, reference preparation та serving, зміна policy не збільшує authority; майбутній adoption вимагає incremental product/regression/cost evidence проти harness-only control і qualification exact model+adapter/base+tokenizer+harness serving bundle, no-go/inconclusive лишаються повноцінними результатами.
- **Негативні перевірки:** приватні player traces без consent; synthetic labels видані за external grounding; repeated leaderboard queries приховані від final-set exposure; reference/alias непомітно став winning checkpoint; training loss або зовнішня target model названа поліпшенням дослідника чи Core без integration evidence; post-hoc threshold прийняв власного winner; duplicate submit, partial checkpoint або weights-only warm start названо успішним resume; новий mission ID/Stop request скинув charges; відсутній дешевший harness baseline; 30B/120B/550B чи illustrative ratios зі статті стали мінімальною конфігурацією/кошторисом Core.
- **Артефакт:** feasibility memo, scoped admission specification, TrainingPlan/Run/ModelCandidate identity contracts, budgeted comparison/recovery/serving protocol та Q04-T01–08; рішення про реальний training окреме. **Фаза/пріоритет:** C8/P2.
- **Підстави:** RSI-SURVEY:R09, RSI-SURVEY:R10, RSI-AEVOLVE:AE-01, RSI-AEVOLVE:AE-02, RSI-AEVOLVE:AE-03, RSI-AEVOLVE:AE-04, RSI-AEVOLVE:AE-05, REPO-AUDIT, DESIGN:core-architecture, CONTRACT:training-research

C7 — паралельний consumer track для спільних E3/E4 доказів. C8 — необов’язковий research горизонт E5. Ці додатки не збільшують scope standalone Core acceptance AF-RSI-030.
