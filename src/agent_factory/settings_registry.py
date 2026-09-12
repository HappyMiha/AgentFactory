"""Every configurable value declared once, with where its default comes from.

Two bugs in this repository had the same shape: a fact written down in two
places that quietly drifted apart. So settings are declared here and nowhere
else, each one saying what it is, what it does, what it defaults to, where that
default comes from, and what changing it costs. A value that is derived from
something else - the engine series the installation catalogue installs, the
Hub minimum - is declared read-only rather than copied into a second home.

Nothing here reads or writes state; it is the vocabulary the settings store and
the interface both use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import asset_provenance, export_bundle, godot_pack, support_bundle, unity_setup

KINDS = ("integer", "decimal", "boolean", "text", "choice", "list")
RISKS = ("safe", "sensitive")
BOOLEAN_TRUE = ("true", "yes", "on", "1")
BOOLEAN_FALSE = ("false", "no", "off", "0")
MAX_TEXT = 500
MAX_LIST_ITEMS = 40


class SettingError(ValueError):
    """Raised when a proposed value is not acceptable for its setting."""


@dataclass(frozen=True)
class Section:
    section_id: str
    title: str
    summary: str
    order: int


@dataclass(frozen=True)
class Setting:
    key: str
    section: str
    label: str
    help: str
    kind: str
    default: str
    source: str
    risk: str = "safe"
    consequence: str = ""
    unit: str = ""
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    reconfigurable: bool = True

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"Unknown setting kind: {self.kind!r}")
        if self.risk not in RISKS:
            raise ValueError(f"Unknown setting risk: {self.risk!r}")
        if self.kind == "choice" and not self.choices:
            raise ValueError(f"{self.key} is a choice with no options")
        if self.risk == "sensitive" and not self.consequence:
            raise ValueError(f"{self.key} is sensitive and must state its consequence")
        if not self.source:
            raise ValueError(f"{self.key} must say where its default comes from")
        # A default that its own rules reject would be a trap for the reader.
        self.parse(self.default)

    def parse(self, raw: Any) -> Any:
        text = self.format(raw) if not isinstance(raw, str) else raw.strip()
        if self.kind == "boolean":
            lowered = text.casefold()
            if lowered in BOOLEAN_TRUE:
                return True
            if lowered in BOOLEAN_FALSE:
                return False
            raise SettingError(f"{self.label}: expected yes or no, got {text!r}")
        if self.kind in {"integer", "decimal"}:
            try:
                value = int(text) if self.kind == "integer" else float(text)
            except ValueError:
                raise SettingError(
                    f"{self.label}: expected a number, got {text!r}"
                ) from None
            if self.minimum is not None and value < self.minimum:
                raise SettingError(
                    f"{self.label}: {value} is below the minimum {self.minimum:g}"
                )
            if self.maximum is not None and value > self.maximum:
                raise SettingError(
                    f"{self.label}: {value} is above the maximum {self.maximum:g}"
                )
            return value
        if self.kind == "choice":
            if text not in self.choices:
                raise SettingError(
                    f"{self.label}: {text!r} is not one of "
                    + ", ".join(self.choices)
                )
            return text
        if self.kind == "list":
            items = tuple(part.strip() for part in text.split(",") if part.strip())
            if len(items) > MAX_LIST_ITEMS:
                raise SettingError(f"{self.label}: at most {MAX_LIST_ITEMS} entries")
            if self.choices:
                unknown = [item for item in items if item not in self.choices]
                if unknown:
                    raise SettingError(
                        f"{self.label}: unknown entries " + ", ".join(sorted(unknown))
                    )
            if len(items) != len(set(items)):
                raise SettingError(f"{self.label}: entries must be unique")
            return items
        if len(text) > MAX_TEXT:
            raise SettingError(f"{self.label}: at most {MAX_TEXT} characters")
        if "\x00" in text:
            raise SettingError(f"{self.label}: control characters are not allowed")
        return text

    @staticmethod
    def format(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (tuple, list)):
            return ", ".join(str(item) for item in value)
        return str(value)

    def describe(self, *, value: str, origin: str) -> dict[str, Any]:
        return {
            "key": self.key,
            "section": self.section,
            "label": self.label,
            "help": self.help,
            "kind": self.kind,
            "unit": self.unit,
            "choices": list(self.choices),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "risk": self.risk,
            "consequence": self.consequence,
            "reconfigurable": self.reconfigurable,
            "default": self.default,
            "default_source": self.source,
            "value": value,
            "origin": origin,
            "changed": value != self.default,
        }


def _sections() -> tuple[Section, ...]:
    return (
        Section(
            "engine-godot", "Рушій Godot",
            "Яку серію редактора приймає пакет, і в яких межах працює адаптер.", 10,
        ),
        Section(
            "engine-unity", "Рушій Unity",
            "Закріплений редактор, ціль збірки та межі пакетного запуску.", 20,
        ),
        Section(
            "assets", "Ассети й права",
            "Бюджети цільової машини та ліцензія, з якою імпортується ассет.", 30,
        ),
        Section(
            "export", "Експорт і поширення",
            "Ціль за замовчуванням, що не потрапляє в пакет, і видимість публікації.",
            40,
        ),
        Section(
            "support", "Діагностика",
            "Що входить у бандл підтримки, поки ви не вибрали інше.", 50,
        ),
        Section(
            "updates", "Оновлення й видалення",
            "Довірений корінь оновлень і захист закріплених версій.", 60,
        ),
        Section(
            "playable", "Ігрові версії",
            "Скільки історії показувати та як звертатися до артефактів.", 70,
        ),
        Section(
            "runtime", "Ліміти виконання",
            "Час, обсяг виводу та межі, у яких взагалі щось запускається.", 80,
        ),
    )


def _definitions() -> tuple[Setting, ...]:
    budget = asset_provenance.BUDGETS["baseline-pc"]
    return (
        # ---------------------------------------------------------- Godot
        Setting(
            "godot.baseline_series", "engine-godot", "Базова серія редактора",
            "Серія, під яку створюються нові проєкти. Береться з каталогу "
            "встановлення, щоб пакет не розійшовся з тим, що фабрика ставить.",
            "text", godot_pack.BASELINE_ENGINE_VERSION,
            "defaults/installation-catalog.json", reconfigurable=False,
        ),
        Setting(
            "godot.additional_series", "engine-godot", "Додатково прийнятні серії",
            "Серії вже встановленого редактора, які адаптер теж вважає придатними.",
            "list", ", ".join(godot_pack.ADDITIONAL_ENGINE_VERSIONS),
            "godot_pack.ADDITIONAL_ENGINE_VERSIONS", risk="sensitive",
            consequence="Додана серія почне проходити health-гейт без жодного "
                        "запуску, який це підтвердив.",
        ),
        Setting(
            "godot.renderer", "engine-godot", "Рендерер шаблонів",
            "Рендерер, який шаблони прописують у project.godot.",
            "text", godot_pack.BASELINE_RENDERER, "godot_pack.BASELINE_RENDERER",
            reconfigurable=False,
        ),
        Setting(
            "godot.max_seconds", "engine-godot", "Ліміт часу на операцію",
            "Скільки секунд може тривати імпорт, перевірка, прогін або експорт.",
            "integer", "120", "godot_engine.GodotAdapter", unit="с",
            minimum=10, maximum=3600,
        ),
        Setting(
            "godot.max_output_chars", "engine-godot", "Ліміт журналу",
            "Скільки символів виводу редактора зберігається як доказ.",
            "integer", "100000", "godot_engine.GodotAdapter", unit="символів",
            minimum=1000, maximum=2000000,
        ),
        Setting(
            "godot.smoke_frames", "engine-godot", "Кадрів headless-прогону",
            "Скільки кадрів проганяється в headless-перевірці перед виходом.",
            "integer", "180", "godot_engine.GodotAdapter", unit="кадрів",
            minimum=1, maximum=100000,
        ),
        # ---------------------------------------------------------- Unity
        Setting(
            "unity.editor", "engine-unity", "Закріплений редактор",
            "Версія Unity Editor, під яку налаштовується робота.",
            "choice", unity_setup.DEFAULT_EDITOR, "unity_setup.SUPPORTED_EDITORS",
            choices=tuple(sorted(unity_setup.SUPPORTED_EDITORS)), risk="sensitive",
            consequence="Проєкти на іншій серії доведеться оновлювати, а оновлення "
                        "проєкту незворотне на місці.",
        ),
        Setting(
            "unity.hub_minimum", "engine-unity", "Мінімальна версія Hub",
            "Версія Unity Hub, з якої підтримується встановлення.",
            "text", unity_setup.UNITY_HUB_MINIMUM, "unity_setup.UNITY_HUB_MINIMUM",
            reconfigurable=False,
        ),
        Setting(
            "unity.default_target", "engine-unity", "Ціль збірки за замовчуванням",
            "Платформа, яку пропонує адаптер, якщо не вказано іншу.",
            "choice", "StandaloneWindows64", "unity_setup.TARGET_MODULES",
            choices=tuple(sorted(unity_setup.TARGET_MODULES)),
        ),
        Setting(
            "unity.max_seconds", "engine-unity", "Ліміт часу на операцію",
            "Скільки секунд може тривати пакетний запуск редактора.",
            "integer", "1800", "unity_engine.UnityAdapter", unit="с",
            minimum=60, maximum=21600,
        ),
        Setting(
            "unity.minimum_disk_bytes", "engine-unity", "Мінімум вільного місця",
            "Скільки місця має бути під редактор і модулі, щоб установлення "
            "вважалося можливим.",
            "integer", str(25 * 1024 * 1024 * 1024), "unity_setup.UnitySetup",
            unit="байтів", minimum=1024 * 1024 * 1024,
        ),
        # --------------------------------------------------------- Assets
        Setting(
            "assets.budget_profile", "assets", "Профіль цільової машини",
            "Набір бюджетів, за якими перевіряється кожен імпортований ассет.",
            "choice", "baseline-pc", "asset_provenance.BUDGETS",
            choices=tuple(sorted(asset_provenance.BUDGETS)),
        ),
        Setting(
            "assets.max_asset_bytes", "assets", "Максимум на один ассет",
            "Перевизначає межу профілю для окремого файлу.",
            "integer", str(budget.max_asset_bytes), "asset_provenance.BUDGETS",
            unit="байтів", minimum=1024, risk="sensitive",
            consequence="Підняття межі пропустить у проєкт файли, які цільова "
                        "машина може не потягнути.",
        ),
        Setting(
            "assets.max_total_bytes", "assets", "Максимум на проєкт",
            "Перевизначає сумарну межу профілю.",
            "integer", str(budget.max_total_bytes), "asset_provenance.BUDGETS",
            unit="байтів", minimum=1024 * 1024, risk="sensitive",
            consequence="Підняття межі дозволить проєкту вирости понад те, що "
                        "перевірялося.",
        ),
        Setting(
            "assets.max_image_pixels", "assets", "Максимум пікселів зображення",
            "Перевизначає межу профілю для площі зображення.",
            "integer", str(budget.max_image_pixels), "asset_provenance.BUDGETS",
            unit="пікселів", minimum=1024, risk="sensitive",
            consequence="Великі текстури проходитимуть перевірку без заміру "
                        "продуктивності.",
        ),
        Setting(
            "assets.default_licence", "assets", "Ліцензія за замовчуванням",
            "Яка ліцензія проставляється, якщо під час імпорту не вказано іншу. "
            "«unknown» — чесний стан: він не блокує локальну роботу, але блокує "
            "поширення.",
            "choice", asset_provenance.UNKNOWN, "asset_provenance.LICENCES",
            choices=tuple(sorted(asset_provenance.LICENCES)), risk="sensitive",
            consequence="Ліцензія за замовчуванням, відмінна від «unknown», "
                        "проставить права, яких ніхто не перевіряв.",
        ),
        # --------------------------------------------------------- Export
        Setting(
            "export.default_target", "export", "Ціль експорту за замовчуванням",
            "Платформа, яку пропонує пакувальник.",
            "choice", "linux-x86_64", "export_bundle.TARGETS",
            choices=tuple(
                target.target_id for target in export_bundle.TARGETS.values()
                if target.supported
            ),
        ),
        Setting(
            "export.extra_excludes", "export", "Додатково не пакувати",
            "Шаблони імен, які не потрапляють у пакет понад типовий список.",
            "list", "", "export_bundle.DEFAULT_EXCLUDES",
        ),
        Setting(
            "export.default_visibility", "export", "Видимість за замовчуванням",
            "Яка видимість підставляється у превʼю публікації. Саму публікацію це "
            "не виконує.",
            "choice", "private-link", "export_bundle.VISIBILITIES",
            choices=export_bundle.VISIBILITIES, risk="sensitive",
            consequence="Публічна видимість за замовчуванням робить необережне "
                        "підтвердження помітнішим для сторонніх.",
        ),
        # -------------------------------------------------------- Support
        Setting(
            "support.default_categories", "support", "Що збирати без окремого вибору",
            "Категорії, попередньо позначені у превʼю бандла. Версії збираються "
            "завжди; решта — лише те, що тут перелічено.",
            "list", "", "support_bundle.OPT_IN_CATEGORIES",
            choices=support_bundle.OPT_IN_CATEGORIES, risk="sensitive",
            consequence="Кожна додана категорія потрапить у бандл за замовчуванням, "
                        "а бандл ви віддаєте іншій людині.",
        ),
        Setting(
            "support.audit_limit", "support", "Скільки подій брати",
            "Верхня межа кількості записів журналу подій у бандлі.",
            "integer", "200", "support_bundle.SupportBundler", unit="записів",
            minimum=1, maximum=5000,
        ),
        # -------------------------------------------------------- Updates
        Setting(
            "updates.trust_key_id", "updates", "Довірений корінь оновлень",
            "Ідентифікатор ключа, підписом якого має бути підписане оновлення.",
            "text", "release", "application_update.ApplicationUpdater",
            risk="sensitive",
            consequence="Зміна кореня довіри змінює те, чиї оновлення взагалі "
                        "приймаються.",
        ),
        Setting(
            "updates.protect_pins", "updates", "Захищати закріплені версії",
            "Чи вимагати окремий затверджений план, коли оновлення зрушило б "
            "закріплений рушій або модель.",
            "boolean", "true", "application_update.UpdatePlan", risk="sensitive",
            consequence="Вимкнення дозволить оновленню зрушити закріплений рушій "
                        "проєкту без окремого рішення.",
        ),
        Setting(
            "updates.preserve_projects", "updates", "Зберігати ігри при видаленні",
            "Чи лишати проєкти на місці, коли видаляється застосунок.",
            "boolean", "true", "application_update.uninstall_plan", risk="sensitive",
            consequence="Вимкнення робить видалення ігор типовим варіантом; воно "
                        "все одно потребує окремого підтвердження.",
        ),
        # ------------------------------------------------------- Playable
        Setting(
            "playable.history_limit", "playable", "Глибина історії версій",
            "Скільки записів історії показувати за замовчуванням.",
            "integer", "50", "playable_versions.PlayableVersions", unit="записів",
            minimum=1, maximum=500,
        ),
        Setting(
            "playable.verify_before_play", "playable", "Звіряти артефакт перед грою",
            "Чи перераховувати контрольну суму файлу перед тим, як пропонувати "
            "запуск.",
            "boolean", "true", "playable_versions.PlayableVersions",
        ),
        # -------------------------------------------------------- Runtime
        Setting(
            "runtime.max_timeout", "runtime", "Загальний ліміт часу",
            "Верхня межа часу для запусків, які не мають власного ліміту.",
            "integer", "300", "application.SettingsView", unit="с",
            minimum=10, maximum=86400,
        ),
        Setting(
            "runtime.max_output_chars", "runtime", "Загальний ліміт виводу",
            "Верхня межа збереженого виводу для запусків без власного ліміту.",
            "integer", "200000", "application.SettingsView", unit="символів",
            minimum=1000, maximum=2000000,
        ),
        Setting(
            "runtime.live_provider_approval_required", "runtime",
            "Живий провайдер лише з підтвердженням",
            "Чи вимагати людське підтвердження перед зверненням до реального "
            "провайдера.",
            "boolean", "true", "application.SettingsView", risk="sensitive",
            consequence="Вимкнення прибирає людину з рішення про платний зовнішній "
                        "виклик.",
        ),
        Setting(
            "runtime.automatic_fallback_in_simulation", "runtime",
            "Автопідміна в симуляції",
            "Чи дозволяти автоматичну підміну провайдера в режимі симуляції.",
            "boolean", "false", "application.SettingsView", risk="sensitive",
            consequence="Увімкнення дозволить симуляції мовчки взяти інший "
                        "провайдер, ніж обраний.",
        ),
    )


SECTIONS: tuple[Section, ...] = _sections()
DEFINITIONS: tuple[Setting, ...] = _definitions()
BY_KEY: Mapping[str, Setting] = {setting.key: setting for setting in DEFINITIONS}
BY_SECTION: Mapping[str, tuple[Setting, ...]] = {
    section.section_id: tuple(
        setting for setting in DEFINITIONS if setting.section == section.section_id
    )
    for section in SECTIONS
}


def setting(key: str) -> Setting:
    try:
        return BY_KEY[str(key)]
    except KeyError:
        raise KeyError(f"Unknown setting: {key}") from None


def section(section_id: str) -> Section:
    for item in SECTIONS:
        if item.section_id == str(section_id):
            return item
    raise KeyError(f"Unknown settings section: {section_id}")


@dataclass(frozen=True)
class Finding:
    level: str  # "ok" | "attention" | "problem"
    summary: str
    detail: str = ""

    @property
    def record(self) -> dict[str, str]:
        return {"level": self.level, "summary": self.summary, "detail": self.detail}


Checker = Callable[[Mapping[str, Any]], Sequence[Finding]]


def _check_godot(values: Mapping[str, Any]) -> list[Finding]:
    baseline = str(values["godot.baseline_series"])
    extra = tuple(values["godot.additional_series"])
    findings = [Finding(
        "ok", f"Нові проєкти створюються під серію {baseline}.",
        "Значення взяте з каталогу встановлення, тож пакет не може розійтися "
        "з тим, який редактор ставить фабрика.",
    )]
    unverified = [item for item in extra if item != baseline]
    if unverified:
        findings.append(Finding(
            "attention",
            "Прийнятні серії без підтвердженого запуску: " + ", ".join(unverified),
            "Жоден із цих редакторів не проходив реального прогону в цьому "
            "проєкті. Health-гейт їх пропустить.",
        ))
    if int(values["godot.max_seconds"]) < 60:
        findings.append(Finding(
            "attention", "Ліміт часу менший за хвилину.",
            "Імпорт великого проєкту може не встигнути й буде записаний як timeout.",
        ))
    return findings


def _check_unity(values: Mapping[str, Any]) -> list[Finding]:
    editor = str(values["unity.editor"])
    release = unity_setup.SUPPORTED_EDITORS[editor]
    target = str(values["unity.default_target"])
    module = unity_setup.TARGET_MODULES[target]
    findings = [Finding(
        "ok", f"Закріплено {editor} ({release.series}).", release.notes,
    )]
    findings.append(Finding(
        "attention" if module.reason else "ok",
        f"Ціль {target} потребує модуль {module.module}.",
        module.reason or "Модуль додається через Unity Hub.",
    ))
    findings.append(Finding(
        "attention", "Стан ліцензії тут не читається.",
        "Ліцензію активує людина у власному потоці Unity; цей застосунок не має "
        "де зберігати облікові дані й не має що активувати.",
    ))
    return findings


def _check_assets(values: Mapping[str, Any]) -> list[Finding]:
    profile = str(values["assets.budget_profile"])
    declared = asset_provenance.BUDGETS[profile]
    per_asset = int(values["assets.max_asset_bytes"])
    total = int(values["assets.max_total_bytes"])
    findings: list[Finding] = []
    if per_asset > total:
        findings.append(Finding(
            "problem", "Межа на один ассет більша за межу проєкту.",
            "Жоден файл такого розміру не пройде: сумарна межа відхилить його "
            "раніше.",
        ))
    for label, current, baseline in (
        ("на один ассет", per_asset, declared.max_asset_bytes),
        ("на проєкт", total, declared.max_total_bytes),
        ("пікселів", int(values["assets.max_image_pixels"]), declared.max_image_pixels),
    ):
        if current > baseline:
            findings.append(Finding(
                "attention", f"Межа {label} піднята понад профіль {profile}.",
                f"{current} проти {baseline} у профілі. Профіль описує машину, "
                "яку вимірювали; підняте значення — ні.",
            ))
    if str(values["assets.default_licence"]) != asset_provenance.UNKNOWN:
        findings.append(Finding(
            "attention", "Ліцензія за замовчуванням не «unknown».",
            "Імпорт проставлятиме права, яких ніхто не звіряв із джерелом.",
        ))
    if not findings:
        findings.append(Finding("ok", f"Бюджети відповідають профілю {profile}.", ""))
    return findings


def _check_export(values: Mapping[str, Any]) -> list[Finding]:
    target = export_bundle.TARGETS[str(values["export.default_target"])]
    findings = [Finding(
        "ok" if target.supported else "problem",
        f"Ціль за замовчуванням: {target.target_id}.",
        target.launch if target.supported else target.reason,
    )]
    if str(values["export.default_visibility"]) == "public":
        findings.append(Finding(
            "attention", "Видимість за замовчуванням — публічна.",
            "Публікація все одно потребує окремого підтвердження й іменного "
            "затверджувача, але помилкове схвалення буде помітнішим.",
        ))
    return findings


def _check_support(values: Mapping[str, Any]) -> list[Finding]:
    categories = tuple(values["support.default_categories"])
    findings = [Finding(
        "ok", "Облікові дані не збираються за жодних налаштувань.",
        "Для них немає колектора: " + ", ".join(support_bundle.NEVER_COLLECTED),
    )]
    if categories:
        findings.append(Finding(
            "attention",
            "У бандл за замовчуванням увійде: " + ", ".join(categories),
            "Це дані вашого проєкту й машини. Превʼю все одно можна прочитати "
            "повністю перед відправкою.",
        ))
    return findings


def _check_updates(values: Mapping[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if not values["updates.protect_pins"]:
        findings.append(Finding(
            "problem", "Захист закріплених версій вимкнено.",
            "Оновлення зможе зрушити рушій або модель проєкту без окремого "
            "затвердженого плану.",
        ))
    if not values["updates.preserve_projects"]:
        findings.append(Finding(
            "problem", "Видалення застосунку типово забирає ігри.",
            "Друге підтвердження лишається, але типовий шлях став руйнівним.",
        ))
    if not findings:
        findings.append(Finding(
            "ok", "Оновлення захищене підписом і закріпленнями.",
            f"Довірений корінь: {values['updates.trust_key_id']}.",
        ))
    return findings


def _check_playable(values: Mapping[str, Any]) -> list[Finding]:
    if not values["playable.verify_before_play"]:
        return [Finding(
            "attention", "Артефакт не звіряється перед запуском.",
            "Підмінений або обрізаний файл виявиться вже після того, як гравця "
            "на нього відправили.",
        )]
    return [Finding("ok", "Контрольна сума артефакта звіряється перед запуском.", "")]


def _check_runtime(values: Mapping[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if not values["runtime.live_provider_approval_required"]:
        findings.append(Finding(
            "problem", "Живий провайдер працює без підтвердження людини.",
            "Платний зовнішній виклик відбуватиметься без окремого рішення.",
        ))
    if values["runtime.automatic_fallback_in_simulation"]:
        findings.append(Finding(
            "attention", "У симуляції дозволена автопідміна провайдера.",
            "Результат може прийти не від того провайдера, який обраний.",
        ))
    if not findings:
        findings.append(Finding("ok", "Межі виконання й підтвердження на місці.", ""))
    return findings


CHECKS: Mapping[str, Checker] = {
    "engine-godot": _check_godot,
    "engine-unity": _check_unity,
    "assets": _check_assets,
    "export": _check_export,
    "support": _check_support,
    "updates": _check_updates,
    "playable": _check_playable,
    "runtime": _check_runtime,
}


def verify(section_id: str, values: Mapping[str, Any]) -> tuple[Finding, ...]:
    """Judge a section's effective values. Reads nothing and changes nothing."""
    section(section_id)
    checker = CHECKS.get(str(section_id))
    if checker is None:
        return (Finding("ok", "Для цього розділу перевірок не оголошено.", ""),)
    return tuple(checker(values))
