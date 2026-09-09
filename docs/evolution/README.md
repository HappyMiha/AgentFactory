# Lokvetia Core: продукт, який уміє доказово поліпшувати себе

Документаційний портфель · 2026-09-09 · **E0 / proposed**. 35 нових карток Core; спільно з Lokiravia — 65. Реалізацію не розпочато. Чинні alpha-обмеження, backlog і release gates зберігаються.

Core має поліпшувати власний код, harness, інструменти, пам’ять, UX, метод дослідження та наступний optimizer. Кожне прийняте покоління прив’язане до незмінного суб’єкта, незалежних доказів, визначеної до запуску метрики й шляху відновлення. Lokiravia є одним зі споживачів; standalone користь Core доводиться без готової гри.

## Почати тут

| Документ | Навіщо читати |
|---|---|
| [Спільна концепція](vision.uk.md) | Кому потрібні продукти, обіцянка досвіду, три об’єкти еволюції та E0–E5 |
| [Архітектура Core](core-architecture.md) | Чотири контури, reuse, manifest lifecycle, O0→O1→O2, verifier/optimizer evolution, шість ADR |
| [План доказів і поставок](delivery-plan.md) | Порядок роботи, перші вузькі зрізи, інтеграція чинних GC/CLD gates, creator experiment |
| [35 карток беклогу](backlog.md) · [JSON](backlog.json) | Outcomes, acceptance, negative cases, залежності, reusable capabilities і джерела |
| [Контракт Core ↔ світ](platform-world-contract.md) | Хто може змінити стан/правило/платформу; replay, session epochs, migration та receipt profiles |

## Підстави й якість

- [Аудит обох репозиторіїв](repository-audit.md) — exact baseline й фактичні прогалини.
- [RSI: реєстр тверджень](rsi-source-analysis.md) — прочитаний PDF, первинні джерела та межі висновків.
- [Джерела й покриття](source-guide.md) · [10 файлових ідентичностей](sources.json) — що справді прочитано й що ще потребує перевірки.
- [Журнал трьох проходів](iteration-review.md) · [Перевірки](validation.md) — які заперечення змінили дизайн.
- [Черга наступних проходів](continuation.md) — конкретні питання, stop conditions і відкладене людське evidence.

Супутній [портфель Lokiravia](https://github.com/HappyMiha/Lokiravia/blob/docs/living-systems-rsi/docs/evolution/README.md) містить літературні дослідження, оригінальну пригоду та 30 світових задач.

Markdown є джерелом змісту карток; JSON зберігає синхронні структуровані поля й кваліфіковані залежності. Обидва файли редагуються разом. Цей design manifest не імпортують у runtime як чинний backlog. Усі дослідницькі результати тут proposed; майбутній no-go може бути правильним результатом.
