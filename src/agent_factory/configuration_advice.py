"""Read-only planning advice. Client observations never grant runtime admission."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

POLICY = "configuration-advice-2026-09-06"
GIB = 1024 ** 3
CATALOG = {
    "reviewed_on": "2026-09-06", "review_due": "2026-10-06",
    "sources": [
        {"id": "godot", "url": "https://docs.godotengine.org/en/stable/about/system_requirements.html",
         "finding": "Godot desktop editor: minimum 4 GB RAM; editor and installed export templates about 1.5 GB. Project caches add space. Compatibility needs supported graphics APIs."},
        {"id": "ollama", "url": "https://ollama.com/library/qwen2.5-coder:7b",
         "finding": "qwen2.5-coder:7b download is approximately 4.7 GB; model weights are not total inference memory."},
    ],
    "planning_policy": {"editor_total_gib": 8, "editor_available_gib": 4, "editor_free_disk_gib": 10,
                        "local_total_gib": 16, "local_available_gib": 8, "local_free_disk_gib": 15},
    "technical_requirements": "Godot Compatibility renderer: verify graphics API/driver and export templates for the target. Local candidate qwen2.5-coder:7b requires effective-model canary and runtime memory measurement. A cloud option requires qualified worker/provider admission. Independent coding/review requires distinct qualified identities.",
    "policy_basis": "Conservative Lokvetia Core planning reserves for a small 2D project, not upstream minimum requirements or measured performance.",
}


def _number(value):
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 2 ** 60:
        raise ValueError("invalid observation")
    return value


def _part(report, key):
    value = report.get(key, {})
    if not isinstance(value, dict):
        raise ValueError("invalid observation")
    return value


def advise(fields, report, *, now=None):
    from .game_planning import validate_fields
    validate_fields(fields)
    if not isinstance(report, dict):
        raise ValueError("invalid observation")
    now = now or datetime.now(timezone.utc)
    raw = report.get("observed_at")
    try:
        observed = datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        observed = None
    fresh = bool(observed and observed.tzinfo and timedelta(0) <= now - observed <= timedelta(minutes=15))
    catalog_current = now.date().isoformat() < CATALOG["review_due"] and now.date().isoformat() >= CATALOG["reviewed_on"]
    memory, disk, system = (_part(report, key) for key in ("memory", "disk", "os"))
    total = _number(memory.get("total_bytes")); available = _number(memory.get("available_bytes"))
    free = _number(disk.get("free_bytes"))
    if total is not None and available is not None and available > total:
        raise ValueError("invalid observation")
    gpus = report.get("gpus", [])
    if not isinstance(gpus, list) or len(gpus) > 16 or not all(isinstance(g, dict) for g in gpus):
        raise ValueError("invalid observation")
    vrams = [_number(g.get("dedicated_total_bytes")) for g in gpus]
    vram = max((v for v in vrams if v is not None), default=None)
    os_name = system.get("name")
    # Inventory release is a Windows version or a kernel version, not a Linux distribution qualification.
    release = system.get("release")
    known_os = os_name in ("Windows", "Linux", "Darwin")
    old_windows = os_name == "Windows" and release in ("7", "8", "8.1")
    reasons = []
    if not fresh: reasons.append("Звіт відсутній або старший за 15 хвилин. Повторіть перевірку ПК.")
    if not catalog_current: reasons.append("Каталог вимог потребує нового огляду. Числову рекомендацію призупинено.")
    if not known_os: reasons.append("Підтримка цієї ОС невідома.")
    if old_windows: reasons.append("Поточний Godot потребує Windows 10 або новішої; цей звіт показує старішу систему.")
    for value, label in ((total,"Обсяг RAM"),(available,"Доступна RAM"),(free,"Вільний диск")):
        if value is None: reasons.append(label + " невідомий; запас ресурсів не підтверджений.")
    if vram is None: reasons.append("Пам’ять відеокарти невідома. Локальний AI може працювати повільно; його швидкість потрібно перевірити.")
    reasons.append("Потрібно перевірити, чи цей ПК правильно показує гру та запускає готовий файл.")
    reasons.append("Обрана версія програми для створення гри має працювати з вашою системою та відеокартою.")
    resource_ok = fresh and catalog_current and known_os and not old_windows
    def capacity(prefix):
        p = CATALOG["planning_policy"]
        return resource_ok and all(value is not None and value >= p[prefix + key] * GIB for value,key in
                                  ((total,"_total_gib"),(available,"_available_gib"),(free,"_free_disk_gib")))
    editor = capacity("editor"); local = capacity("local")
    if not editor: reasons.append("Для локальної розробки поки не підтверджено плановий запас 8 ГіБ RAM, 4 ГіБ доступної RAM і 10 ГіБ диска.")
    target = "Windows: потрібно додати засоби створення готового файлу та перевірити гру на Windows без редактора." if fields["platform"] == "windows" else "Web: потрібно створити браузерну версію й перевірити її у браузері. Успішний запуск звичайного файлу цього не підтверджує."
    def option(key, title, engine, mode, selectable, explanation):
        note = f"Плановий варіант: {title}. {explanation} Каталог {CATALOG['reviewed_on']}; встановлення, запуск і витрати потребують окремого погодження та перевірки."
        return {"id": key, "title": title, "engine": engine, "ai_mode": mode,
                "selectable": bool(selectable), "reason": explanation, "selection_note": note}
    options = [
        option("manual", "Зберегти поточний задум і готувати план вручну", fields["engine"], "manual", True,
               "Не потребує модельного завантаження або витрат на AI. Поточний рушій залишається у плані."),
        option("godot-cloud", "Godot + хмарний AI", "godot", "cloud", catalog_current,
               "AI працює через інтернет і не займає пам’ять цього ПК. Редактор гри все одно потребує ресурсів. Якщо їх мало, редактор має працювати на іншому перевіреному комп’ютері. Потрібні доступний вам сервіс, перевірка його роботи й погоджений бюджет."),
        option("godot-local", "Godot + локальний AI", "godot", "local", local,
               "Для цього варіанта плануємо 16 ГіБ пам’яті, з них 8 ГіБ вільних, і 15 ГіБ диска. AI виконує одну роботу за раз; швидкість і якість потрібно перевірити. Один локальний AI не може незалежно перевірити власну роботу."),
        option("unity-later", "Unity — наступний етап", "unity", "unqualified", False,
               "Підтримка Unity ще потребує перевірки: чи можна створити гру, виправити помилки та запустити готовий результат. Самого встановленого редактора недостатньо."),
        option("unreal-later", "Unreal — наступний етап", "unreal", "unqualified", False,
               "Підтримка Unreal ще потребує перевірки створення гри, готового файлу та гри всередині нього. Цей варіант поки не пропонуємо для першої версії."),
    ]
    recommended = "godot-local" if local and vram is not None and vram >= 8 * GIB else "godot-cloud" if editor else "manual"
    if fields["engine"] != "godot": recommended = "manual"
    return {"policy": POLICY, "advisory_only": True, "execution_ready": False,
            "input_digest": hashlib.sha256(json.dumps({"fields":fields,"report":report},sort_keys=True,separators=(",", ":"),ensure_ascii=False).encode()).hexdigest(),
            "catalog": deepcopy(CATALOG), "catalog_current": catalog_current, "observation_fresh": fresh,
            "observation_trust": "client_reported_planning_only", "recommended": recommended,
            "renderer": "Compatibility (needs actual API/driver test)", "target": target,
            "reasons": reasons, "options": options,
            "estimates": [
                {"item":"Godot і засоби створення готової гри", "range":"Близько 1.5 GB після встановлення; проєкт і кеш — додатково, верхня межа невідома.", "source":"godot"},
                {"item":"qwen2.5-coder:7b", "range":"Близько 4.7 GB завантаження; пам’ять під час роботи залежить від обсягу задачі, верхня межа тут невідома.", "source":"ollama"},
                {"item":"Час і вартість", "range":"Діапазон невідомий до вимірювання мережі, моделі, задачі й тарифу. Хмарний сервіс може бути платним; локальний AI витрачає час і електроенергію.", "source":"planning_policy"}],
            "scope_note":"Пропозиція першої версії: один завершений ігровий цикл у малому рівні. Жанр, правила й відкладений задум не змінюються автоматично."}
