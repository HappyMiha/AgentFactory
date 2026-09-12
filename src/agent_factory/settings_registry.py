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
from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message

KINDS = ("integer", "decimal", "boolean", "text", "choice", "list")
RISKS = ("safe", "sensitive")
BOOLEAN_TRUE = ("true", "yes", "on", "1")
BOOLEAN_FALSE = ("false", "no", "off", "0")
MAX_TEXT = 500
MAX_LIST_ITEMS = 40


class SettingError(LocalisedError):
    """Raised when a proposed value is not acceptable, in both languages."""


@dataclass(frozen=True)
class Section:
    section_id: str
    title: Message
    summary: Message
    order: int

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "section": self.section_id,
            "title": self.title.text(language),
            "summary": self.summary.text(language),
            "order": self.order,
        }


@dataclass(frozen=True)
class Setting:
    key: str
    section: str
    label: Message
    help: Message
    kind: str
    default: str
    source: str
    risk: str = "safe"
    consequence: Message | None = None
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
        if self.risk == "sensitive" and self.consequence is None:
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
            raise SettingError(Message(
                f"{self.label.uk}: очікується «так» або «ні», а не {text!r}.",
                f"{self.label.en}: expected yes or no, not {text!r}.",
            ))
        if self.kind in {"integer", "decimal"}:
            try:
                value = int(text) if self.kind == "integer" else float(text)
            except ValueError:
                raise SettingError(Message(
                    f"{self.label.uk}: очікується число, а не {text!r}.",
                    f"{self.label.en}: expected a number, not {text!r}.",
                )) from None
            if self.minimum is not None and value < self.minimum:
                raise SettingError(Message(
                    f"{self.label.uk}: {value} менше за мінімум {self.minimum:g}. "
                    "Виберіть значення в межах.",
                    f"{self.label.en}: {value} is below the minimum "
                    f"{self.minimum:g}. Choose a value in range.",
                ))
            if self.maximum is not None and value > self.maximum:
                raise SettingError(Message(
                    f"{self.label.uk}: {value} більше за максимум {self.maximum:g}. "
                    "Виберіть значення в межах.",
                    f"{self.label.en}: {value} is above the maximum "
                    f"{self.maximum:g}. Choose a value in range.",
                ))
            return value
        if self.kind == "choice":
            if text not in self.choices:
                raise SettingError(Message(
                    f"{self.label.uk}: {text!r} не входить до переліку "
                    + ", ".join(self.choices) + ".",
                    f"{self.label.en}: {text!r} is not one of "
                    + ", ".join(self.choices) + ".",
                ))
            return text
        if self.kind == "list":
            items = tuple(part.strip() for part in text.split(",") if part.strip())
            if len(items) > MAX_LIST_ITEMS:
                raise SettingError(Message(
                    f"{self.label.uk}: щонайбільше {MAX_LIST_ITEMS} записів.",
                    f"{self.label.en}: at most {MAX_LIST_ITEMS} entries.",
                ))
            if self.choices:
                unknown = [item for item in items if item not in self.choices]
                if unknown:
                    raise SettingError(Message(
                        f"{self.label.uk}: невідомі записи "
                        + ", ".join(sorted(unknown)) + ".",
                        f"{self.label.en}: unknown entries "
                        + ", ".join(sorted(unknown)) + ".",
                    ))
            if len(items) != len(set(items)):
                raise SettingError(Message(
                    f"{self.label.uk}: записи не можуть повторюватися.",
                    f"{self.label.en}: entries must be unique.",
                ))
            return items
        if len(text) > MAX_TEXT:
            raise SettingError(Message(
                f"{self.label.uk}: щонайбільше {MAX_TEXT} символів.",
                f"{self.label.en}: at most {MAX_TEXT} characters.",
            ))
        if "\x00" in text:
            raise SettingError(Message(
                f"{self.label.uk}: керівні символи не дозволені.",
                f"{self.label.en}: control characters are not allowed.",
            ))
        return text

    @staticmethod
    def format(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (tuple, list)):
            return ", ".join(str(item) for item in value)
        return str(value)

    def describe(
        self, *, value: str, origin: str, language: str = DEFAULT_LANGUAGE
    ) -> dict[str, Any]:
        return {
            "key": self.key,
            "section": self.section,
            "label": self.label.text(language),
            "help": self.help.text(language),
            "kind": self.kind,
            "unit": self.unit,
            "choices": list(self.choices),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "risk": self.risk,
            "consequence": self.consequence.text(language) if self.consequence else "",
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
            "engine-godot",
            Message("Рушій Godot", "Godot engine"),
            Message(
                "Яку серію редактора приймає пакет, і в яких межах працює адаптер.",
                "Which editor series the pack accepts, and the limits the adapter "
                "works within.",
            ),
            10,
        ),
        Section(
            "engine-unity",
            Message("Рушій Unity", "Unity engine"),
            Message(
                "Закріплений редактор, ціль збірки та межі пакетного запуску.",
                "The pinned editor, the build target, and the limits of a batch run.",
            ),
            20,
        ),
        Section(
            "assets",
            Message("Ассети й права", "Assets and rights"),
            Message(
                "Бюджети цільової машини та ліцензія, з якою імпортується ассет.",
                "The target machine's budgets, and the licence an asset arrives with.",
            ),
            30,
        ),
        Section(
            "export",
            Message("Експорт і поширення", "Export and sharing"),
            Message(
                "Ціль за замовчуванням, що не потрапляє в пакет, і видимість "
                "публікації.",
                "The default target, what never goes into a package, and the "
                "visibility a publication starts from.",
            ),
            40,
        ),
        Section(
            "support",
            Message("Діагностика", "Diagnostics"),
            Message(
                "Що входить у бандл підтримки, поки ви не вибрали інше.",
                "What a support bundle contains until you choose otherwise.",
            ),
            50,
        ),
        Section(
            "updates",
            Message("Оновлення й видалення", "Updates and uninstall"),
            Message(
                "Довірений корінь оновлень і захист закріплених версій.",
                "The update trust root, and the protection around pinned versions.",
            ),
            60,
        ),
        Section(
            "playable",
            Message("Ігрові версії", "Playable versions"),
            Message(
                "Скільки історії показувати та як звертатися до артефактів.",
                "How much history to show, and how artifacts are treated.",
            ),
            70,
        ),
        Section(
            "runtime",
            Message("Ліміти виконання", "Execution limits"),
            Message(
                "Час, обсяг виводу та межі, у яких взагалі щось запускається.",
                "Time, output size, and the limits anything runs within at all.",
            ),
            80,
        ),
    )


def _definitions() -> tuple[Setting, ...]:
    budget = asset_provenance.BUDGETS["baseline-pc"]
    return (
        # ---------------------------------------------------------- Godot
        Setting(
            "godot.baseline_series", "engine-godot",
            Message("Базова серія редактора", "Baseline editor series"),
            Message(
                "Серія, під яку створюються нові проєкти. Береться з каталогу "
                "встановлення, щоб пакет не розійшовся з тим, що фабрика ставить.",
                "The series new projects are created for. Taken from the "
                "installation catalogue so the pack cannot drift from the editor "
                "the factory installs.",
            ),
            "text", godot_pack.BASELINE_ENGINE_VERSION,
            "defaults/installation-catalog.json", reconfigurable=False,
        ),
        Setting(
            "godot.additional_series", "engine-godot",
            Message("Додатково прийнятні серії", "Additionally accepted series"),
            Message(
                "Серії вже встановленого редактора, які адаптер теж вважає "
                "придатними.",
                "Series of an already installed editor that the adapter also "
                "accepts.",
            ),
            "list", ", ".join(godot_pack.ADDITIONAL_ENGINE_VERSIONS),
            "godot_pack.ADDITIONAL_ENGINE_VERSIONS", risk="sensitive",
            consequence=Message(
                "Додана серія почне проходити health-гейт без жодного запуску, "
                "який це підтвердив.",
                "An added series starts passing the health gate without any run "
                "having confirmed it.",
            ),
        ),
        Setting(
            "godot.renderer", "engine-godot",
            Message("Рендерер шаблонів", "Template renderer"),
            Message(
                "Рендерер, який шаблони прописують у project.godot.",
                "The renderer the templates write into project.godot.",
            ),
            "text", godot_pack.BASELINE_RENDERER, "godot_pack.BASELINE_RENDERER",
            reconfigurable=False,
        ),
        Setting(
            "godot.max_seconds", "engine-godot",
            Message("Ліміт часу на операцію", "Time limit per operation"),
            Message(
                "Скільки секунд може тривати імпорт, перевірка, прогін або експорт.",
                "How long an import, check, run or export may take.",
            ),
            "integer", "120", "godot_engine.GodotAdapter", unit="с",
            minimum=10, maximum=3600,
        ),
        Setting(
            "godot.max_output_chars", "engine-godot",
            Message("Ліміт журналу", "Log limit"),
            Message(
                "Скільки символів виводу редактора зберігається як доказ.",
                "How many characters of editor output are kept as evidence.",
            ),
            "integer", "100000", "godot_engine.GodotAdapter", unit="символів",
            minimum=1000, maximum=2000000,
        ),
        Setting(
            "godot.smoke_frames", "engine-godot",
            Message("Кадрів headless-прогону", "Headless run frames"),
            Message(
                "Скільки кадрів проганяється в headless-перевірці перед виходом.",
                "How many frames the headless check runs before quitting.",
            ),
            "integer", "180", "godot_engine.GodotAdapter", unit="кадрів",
            minimum=1, maximum=100000,
        ),
        # ---------------------------------------------------------- Unity
        Setting(
            "unity.editor", "engine-unity",
            Message("Закріплений редактор", "Pinned editor"),
            Message(
                "Версія Unity Editor, під яку налаштовується робота.",
                "The Unity Editor version the work is set up for.",
            ),
            "choice", unity_setup.DEFAULT_EDITOR, "unity_setup.SUPPORTED_EDITORS",
            choices=tuple(sorted(unity_setup.SUPPORTED_EDITORS)), risk="sensitive",
            consequence=Message(
                "Проєкти на іншій серії доведеться оновлювати, а оновлення проєкту "
                "незворотне на місці.",
                "Projects on another series will have to be upgraded, and a project "
                "upgrade is not reversible in place.",
            ),
        ),
        Setting(
            "unity.hub_minimum", "engine-unity",
            Message("Мінімальна версія Hub", "Minimum Hub version"),
            Message(
                "Версія Unity Hub, з якої підтримується встановлення.",
                "The Unity Hub version from which installation is supported.",
            ),
            "text", unity_setup.UNITY_HUB_MINIMUM, "unity_setup.UNITY_HUB_MINIMUM",
            reconfigurable=False,
        ),
        Setting(
            "unity.default_target", "engine-unity",
            Message("Ціль збірки за замовчуванням", "Default build target"),
            Message(
                "Платформа, яку пропонує адаптер, якщо не вказано іншу.",
                "The platform the adapter uses when no other is given.",
            ),
            "choice", "StandaloneWindows64", "unity_setup.TARGET_MODULES",
            choices=tuple(sorted(unity_setup.TARGET_MODULES)),
        ),
        Setting(
            "unity.max_seconds", "engine-unity",
            Message("Ліміт часу на операцію", "Time limit per operation"),
            Message(
                "Скільки секунд може тривати пакетний запуск редактора.",
                "How long a batch run of the editor may take.",
            ),
            "integer", "1800", "unity_engine.UnityAdapter", unit="с",
            minimum=60, maximum=21600,
        ),
        Setting(
            "unity.minimum_disk_bytes", "engine-unity",
            Message("Мінімум вільного місця", "Minimum free disk space"),
            Message(
                "Скільки місця має бути під редактор і модулі, щоб установлення "
                "вважалося можливим.",
                "How much space the editor and its modules need before an install "
                "is considered possible.",
            ),
            "integer", str(25 * 1024 * 1024 * 1024), "unity_setup.UnitySetup",
            unit="байтів", minimum=1024 * 1024 * 1024,
        ),
        # --------------------------------------------------------- Assets
        Setting(
            "assets.budget_profile", "assets",
            Message("Профіль цільової машини", "Target machine profile"),
            Message(
                "Набір бюджетів, за якими перевіряється кожен імпортований ассет.",
                "The set of budgets every imported asset is measured against.",
            ),
            "choice", "baseline-pc", "asset_provenance.BUDGETS",
            choices=tuple(sorted(asset_provenance.BUDGETS)),
        ),
        Setting(
            "assets.max_asset_bytes", "assets",
            Message("Максимум на один ассет", "Maximum per asset"),
            Message(
                "Перевизначає межу профілю для окремого файлу.",
                "Overrides the profile's limit for a single file.",
            ),
            "integer", str(budget.max_asset_bytes), "asset_provenance.BUDGETS",
            unit="байтів", minimum=1024, risk="sensitive",
            consequence=Message(
                "Підняття межі пропустить у проєкт файли, які цільова машина може "
                "не потягнути.",
                "Raising the limit lets files into the project that the target "
                "machine may not handle.",
            ),
        ),
        Setting(
            "assets.max_total_bytes", "assets",
            Message("Максимум на проєкт", "Maximum per project"),
            Message(
                "Перевизначає сумарну межу профілю.",
                "Overrides the profile's total limit.",
            ),
            "integer", str(budget.max_total_bytes), "asset_provenance.BUDGETS",
            unit="байтів", minimum=1024 * 1024, risk="sensitive",
            consequence=Message(
                "Підняття межі дозволить проєкту вирости понад те, що перевірялося.",
                "Raising the limit lets the project grow beyond what was measured.",
            ),
        ),
        Setting(
            "assets.max_image_pixels", "assets",
            Message("Максимум пікселів зображення", "Maximum image pixels"),
            Message(
                "Перевизначає межу профілю для площі зображення.",
                "Overrides the profile's limit on image area.",
            ),
            "integer", str(budget.max_image_pixels), "asset_provenance.BUDGETS",
            unit="пікселів", minimum=1024, risk="sensitive",
            consequence=Message(
                "Великі текстури проходитимуть перевірку без заміру продуктивності.",
                "Large textures will pass the check with no performance measured.",
            ),
        ),
        Setting(
            "assets.default_licence", "assets",
            Message("Ліцензія за замовчуванням", "Default licence"),
            Message(
                "Яка ліцензія проставляється, якщо під час імпорту не вказано іншу. "
                "«unknown» — чесний стан: він не блокує локальну роботу, але блокує "
                "поширення.",
                "The licence recorded when an import does not name one. "
                "\"unknown\" is the honest state: it never blocks local work, and "
                "always blocks distribution.",
            ),
            "choice", asset_provenance.UNKNOWN, "asset_provenance.LICENCES",
            choices=tuple(sorted(asset_provenance.LICENCES)), risk="sensitive",
            consequence=Message(
                "Ліцензія за замовчуванням, відмінна від «unknown», проставить "
                "права, яких ніхто не перевіряв.",
                "A default other than \"unknown\" records rights that nobody "
                "verified.",
            ),
        ),
        # --------------------------------------------------------- Export
        Setting(
            "export.default_target", "export",
            Message("Ціль експорту за замовчуванням", "Default export target"),
            Message(
                "Платформа, яку пропонує пакувальник.",
                "The platform the packager offers.",
            ),
            "choice", "linux-x86_64", "export_bundle.TARGETS",
            choices=tuple(
                target.target_id for target in export_bundle.TARGETS.values()
                if target.supported
            ),
        ),
        Setting(
            "export.extra_excludes", "export",
            Message("Додатково не пакувати", "Additionally never packaged"),
            Message(
                "Шаблони імен, які не потрапляють у пакет понад типовий список.",
                "Name patterns kept out of a package on top of the default list.",
            ),
            "list", "", "export_bundle.DEFAULT_EXCLUDES",
        ),
        Setting(
            "export.default_visibility", "export",
            Message("Видимість за замовчуванням", "Default visibility"),
            Message(
                "Яка видимість підставляється у превʼю публікації. Саму публікацію "
                "це не виконує.",
                "The visibility a publication preview starts from. This never "
                "publishes anything by itself.",
            ),
            "choice", "private-link", "export_bundle.VISIBILITIES",
            choices=export_bundle.VISIBILITIES, risk="sensitive",
            consequence=Message(
                "Публічна видимість за замовчуванням робить необережне "
                "підтвердження помітнішим для сторонніх.",
                "A public default makes a careless confirmation visible to "
                "strangers.",
            ),
        ),
        # -------------------------------------------------------- Support
        Setting(
            "support.default_categories", "support",
            Message("Що збирати без окремого вибору", "Collected without asking"),
            Message(
                "Категорії, попередньо позначені у превʼю бандла. Версії "
                "збираються завжди; решта — лише те, що тут перелічено.",
                "Categories pre-selected in a bundle preview. Versions are always "
                "collected; everything else only if listed here.",
            ),
            "list", "", "support_bundle.OPT_IN_CATEGORIES",
            choices=support_bundle.OPT_IN_CATEGORIES, risk="sensitive",
            consequence=Message(
                "Кожна додана категорія потрапить у бандл за замовчуванням, а бандл "
                "ви віддаєте іншій людині.",
                "Each added category goes into the bundle by default, and the "
                "bundle is something you hand to another person.",
            ),
        ),
        Setting(
            "support.audit_limit", "support",
            Message("Скільки подій брати", "How many events to take"),
            Message(
                "Верхня межа кількості записів журналу подій у бандлі.",
                "The upper bound on event-log entries in a bundle.",
            ),
            "integer", "200", "support_bundle.SupportBundler", unit="записів",
            minimum=1, maximum=5000,
        ),
        # -------------------------------------------------------- Updates
        Setting(
            "updates.trust_key_id", "updates",
            Message("Довірений корінь оновлень", "Update trust root"),
            Message(
                "Ідентифікатор ключа, підписом якого має бути підписане оновлення.",
                "The key identifier an update must be signed by.",
            ),
            "text", "release", "application_update.ApplicationUpdater",
            risk="sensitive",
            consequence=Message(
                "Зміна кореня довіри змінює те, чиї оновлення взагалі приймаються.",
                "Changing the trust root changes whose updates are accepted at all.",
            ),
        ),
        Setting(
            "updates.protect_pins", "updates",
            Message("Захищати закріплені версії", "Protect pinned versions"),
            Message(
                "Чи вимагати окремий затверджений план, коли оновлення зрушило б "
                "закріплений рушій або модель.",
                "Whether moving a pinned engine or model needs its own approved "
                "plan.",
            ),
            "boolean", "true", "application_update.UpdatePlan", risk="sensitive",
            consequence=Message(
                "Вимкнення дозволить оновленню зрушити закріплений рушій проєкту "
                "без окремого рішення.",
                "Turning this off lets an update move a project's pinned engine "
                "with no separate decision.",
            ),
        ),
        Setting(
            "updates.preserve_projects", "updates",
            Message("Зберігати ігри при видаленні", "Keep games on uninstall"),
            Message(
                "Чи лишати проєкти на місці, коли видаляється застосунок.",
                "Whether projects stay in place when the application is removed.",
            ),
            "boolean", "true", "application_update.uninstall_plan", risk="sensitive",
            consequence=Message(
                "Вимкнення робить видалення ігор типовим варіантом; воно все одно "
                "потребує окремого підтвердження.",
                "Turning this off makes removing games the default path; it still "
                "needs a separate confirmation.",
            ),
        ),
        # ------------------------------------------------------- Playable
        Setting(
            "playable.history_limit", "playable",
            Message("Глибина історії версій", "Version history depth"),
            Message(
                "Скільки записів історії показувати за замовчуванням.",
                "How many history entries to show by default.",
            ),
            "integer", "50", "playable_versions.PlayableVersions", unit="записів",
            minimum=1, maximum=500,
        ),
        Setting(
            "playable.verify_before_play", "playable",
            Message("Звіряти артефакт перед грою", "Verify the artifact before play"),
            Message(
                "Чи перераховувати контрольну суму файлу перед тим, як пропонувати "
                "запуск.",
                "Whether to recompute the file's checksum before offering to launch "
                "it.",
            ),
            "boolean", "true", "playable_versions.PlayableVersions",
        ),
        # -------------------------------------------------------- Runtime
        Setting(
            "runtime.max_timeout", "runtime",
            Message("Загальний ліміт часу", "General time limit"),
            Message(
                "Верхня межа часу для запусків, які не мають власного ліміту.",
                "The upper bound for runs with no limit of their own.",
            ),
            "integer", "300", "application.SettingsView", unit="с",
            minimum=10, maximum=86400,
        ),
        Setting(
            "runtime.max_output_chars", "runtime",
            Message("Загальний ліміт виводу", "General output limit"),
            Message(
                "Верхня межа збереженого виводу для запусків без власного ліміту.",
                "The upper bound on stored output for runs with no limit of their "
                "own.",
            ),
            "integer", "200000", "application.SettingsView", unit="символів",
            minimum=1000, maximum=2000000,
        ),
        Setting(
            "runtime.live_provider_approval_required", "runtime",
            Message(
                "Живий провайдер лише з підтвердженням",
                "A live provider only with approval",
            ),
            Message(
                "Чи вимагати людське підтвердження перед зверненням до реального "
                "провайдера.",
                "Whether a human confirmation is required before calling a real "
                "provider.",
            ),
            "boolean", "true", "application.SettingsView", risk="sensitive",
            consequence=Message(
                "Вимкнення прибирає людину з рішення про платний зовнішній виклик.",
                "Turning this off removes the person from the decision to make a "
                "paid external call.",
            ),
        ),
        Setting(
            "runtime.automatic_fallback_in_simulation", "runtime",
            Message("Автопідміна в симуляції", "Automatic fallback in simulation"),
            Message(
                "Чи дозволяти автоматичну підміну провайдера в режимі симуляції.",
                "Whether a provider may be substituted automatically in simulation.",
            ),
            "boolean", "false", "application.SettingsView", risk="sensitive",
            consequence=Message(
                "Увімкнення дозволить симуляції мовчки взяти інший провайдер, ніж "
                "обраний.",
                "Turning this on lets simulation quietly use a provider other than "
                "the one chosen.",
            ),
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
    """One judgement about a section, in every language the product claims."""

    level: str  # "ok" | "attention" | "problem"
    summary: Message
    detail: Message | None = None

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, str]:
        return {
            "level": self.level,
            "summary": self.summary.text(language),
            "detail": self.detail.text(language) if self.detail else "",
        }


Checker = Callable[[Mapping[str, Any]], Sequence[Finding]]


def _check_godot(values: Mapping[str, Any]) -> list[Finding]:
    baseline = str(values["godot.baseline_series"])
    extra = tuple(values["godot.additional_series"])
    findings = [Finding(
        "ok",
        Message(
            f"Нові проєкти створюються під серію {baseline}.",
            f"New projects are created for series {baseline}.",
        ),
        Message(
            "Значення взяте з каталогу встановлення, тож пакет не може розійтися "
            "з тим, який редактор ставить фабрика.",
            "The value comes from the installation catalogue, so the pack cannot "
            "drift from the editor the factory installs.",
        ),
    )]
    unverified = [item for item in extra if item != baseline]
    if unverified:
        listed = ", ".join(unverified)
        findings.append(Finding(
            "attention",
            Message(
                f"Прийнятні серії без підтвердженого запуску: {listed}",
                f"Accepted series with no confirmed run: {listed}",
            ),
            Message(
                "Жоден із цих редакторів не проходив реального прогону в цьому "
                "проєкті. Health-гейт їх пропустить.",
                "None of these editors has had a real run in this project. The "
                "health gate will let them through.",
            ),
        ))
    if int(values["godot.max_seconds"]) < 60:
        findings.append(Finding(
            "attention",
            Message("Ліміт часу менший за хвилину.", "The time limit is under a minute."),
            Message(
                "Імпорт великого проєкту може не встигнути й буде записаний як "
                "timeout.",
                "Importing a large project may not finish and will be recorded as "
                "a timeout.",
            ),
        ))
    return findings


def _check_unity(values: Mapping[str, Any]) -> list[Finding]:
    editor = str(values["unity.editor"])
    release = unity_setup.SUPPORTED_EDITORS[editor]
    target = str(values["unity.default_target"])
    module = unity_setup.TARGET_MODULES[target]
    findings = [Finding(
        "ok",
        Message(
            f"Закріплено {editor} ({release.series}).",
            f"Pinned to {editor} ({release.series}).",
        ),
        Message(release.notes, release.notes),
    )]
    findings.append(Finding(
        "attention" if module.reason else "ok",
        Message(
            f"Ціль {target} потребує модуль {module.module}.",
            f"Target {target} needs the {module.module} module.",
        ),
        Message(
            module.reason or "Модуль додається через Unity Hub.",
            module.reason or "The module is added through Unity Hub.",
        ),
    ))
    findings.append(Finding(
        "attention",
        Message(
            "Стан ліцензії тут не читається.",
            "The licence state is not read here.",
        ),
        Message(
            "Ліцензію активує людина у власному потоці Unity; цей застосунок не "
            "має де зберігати облікові дані й не має що активувати.",
            "A person activates the licence in Unity's own flow; this application "
            "has nowhere to store credentials and nothing to activate.",
        ),
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
            "problem",
            Message(
                "Межа на один ассет більша за межу проєкту.",
                "The per-asset limit is larger than the project limit.",
            ),
            Message(
                "Жоден файл такого розміру не пройде: сумарна межа відхилить його "
                "раніше.",
                "No file that size can pass: the total limit refuses it first.",
            ),
        ))
    for label_uk, label_en, current, baseline in (
        ("на один ассет", "per asset", per_asset, declared.max_asset_bytes),
        ("на проєкт", "per project", total, declared.max_total_bytes),
        (
            "пікселів", "on pixels",
            int(values["assets.max_image_pixels"]), declared.max_image_pixels,
        ),
    ):
        if current > baseline:
            findings.append(Finding(
                "attention",
                Message(
                    f"Межа {label_uk} піднята понад профіль {profile}.",
                    f"The limit {label_en} is raised above the {profile} profile.",
                ),
                Message(
                    f"{current} проти {baseline} у профілі. Профіль описує машину, "
                    "яку вимірювали; підняте значення — ні.",
                    f"{current} against {baseline} in the profile. The profile "
                    "describes a machine that was measured; the raised value does "
                    "not.",
                ),
            ))
    if str(values["assets.default_licence"]) != asset_provenance.UNKNOWN:
        findings.append(Finding(
            "attention",
            Message(
                "Ліцензія за замовчуванням не «unknown».",
                'The default licence is not "unknown".',
            ),
            Message(
                "Імпорт проставлятиме права, яких ніхто не звіряв із джерелом.",
                "Imports will record rights nobody checked against the source.",
            ),
        ))
    if not findings:
        findings.append(Finding(
            "ok",
            Message(
                f"Бюджети відповідають профілю {profile}.",
                f"The budgets match the {profile} profile.",
            ),
        ))
    return findings


def _check_export(values: Mapping[str, Any]) -> list[Finding]:
    target = export_bundle.TARGETS[str(values["export.default_target"])]
    findings = [Finding(
        "ok" if target.supported else "problem",
        Message(
            f"Ціль за замовчуванням: {target.target_id}.",
            f"Default target: {target.target_id}.",
        ),
        Message(
            target.launch if target.supported else target.reason,
            target.launch if target.supported else target.reason,
        ),
    )]
    if str(values["export.default_visibility"]) == "public":
        findings.append(Finding(
            "attention",
            Message(
                "Видимість за замовчуванням — публічна.",
                "The default visibility is public.",
            ),
            Message(
                "Публікація все одно потребує окремого підтвердження й іменного "
                "затверджувача, але помилкове схвалення буде помітнішим.",
                "Publishing still needs a separate confirmation and a named "
                "approver, but a mistaken approval will be more visible.",
            ),
        ))
    return findings


def _check_support(values: Mapping[str, Any]) -> list[Finding]:
    categories = tuple(values["support.default_categories"])
    never = ", ".join(support_bundle.NEVER_COLLECTED)
    findings = [Finding(
        "ok",
        Message(
            "Облікові дані не збираються за жодних налаштувань.",
            "Credentials are never collected, whatever the settings say.",
        ),
        Message(
            f"Для них немає колектора: {never}",
            f"They have no collector: {never}",
        ),
    )]
    if categories:
        listed = ", ".join(categories)
        findings.append(Finding(
            "attention",
            Message(
                f"У бандл за замовчуванням увійде: {listed}",
                f"The bundle will include by default: {listed}",
            ),
            Message(
                "Це дані вашого проєкту й машини. Превʼю все одно можна прочитати "
                "повністю перед відправкою.",
                "This is your project's and your machine's data. The preview can "
                "still be read in full before you send it.",
            ),
        ))
    return findings


def _check_updates(values: Mapping[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if not values["updates.protect_pins"]:
        findings.append(Finding(
            "problem",
            Message(
                "Захист закріплених версій вимкнено.",
                "Protection of pinned versions is off.",
            ),
            Message(
                "Оновлення зможе зрушити рушій або модель проєкту без окремого "
                "затвердженого плану.",
                "An update will be able to move a project's engine or model with "
                "no separate approved plan.",
            ),
        ))
    if not values["updates.preserve_projects"]:
        findings.append(Finding(
            "problem",
            Message(
                "Видалення застосунку типово забирає ігри.",
                "Uninstalling the application takes the games by default.",
            ),
            Message(
                "Друге підтвердження лишається, але типовий шлях став руйнівним.",
                "The second confirmation remains, but the default path is now "
                "destructive.",
            ),
        ))
    if not findings:
        key = values["updates.trust_key_id"]
        findings.append(Finding(
            "ok",
            Message(
                "Оновлення захищене підписом і закріпленнями.",
                "Updates are protected by a signature and by the pins.",
            ),
            Message(f"Довірений корінь: {key}.", f"Trust root: {key}."),
        ))
    return findings


def _check_playable(values: Mapping[str, Any]) -> list[Finding]:
    if not values["playable.verify_before_play"]:
        return [Finding(
            "attention",
            Message(
                "Артефакт не звіряється перед запуском.",
                "The artifact is not verified before launch.",
            ),
            Message(
                "Підмінений або обрізаний файл виявиться вже після того, як гравця "
                "на нього відправили.",
                "A replaced or truncated file will be found only after a player "
                "was sent to it.",
            ),
        )]
    return [Finding(
        "ok",
        Message(
            "Контрольна сума артефакта звіряється перед запуском.",
            "The artifact's checksum is verified before launch.",
        ),
    )]


def _check_runtime(values: Mapping[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    if not values["runtime.live_provider_approval_required"]:
        findings.append(Finding(
            "problem",
            Message(
                "Живий провайдер працює без підтвердження людини.",
                "A live provider runs with no human confirmation.",
            ),
            Message(
                "Платний зовнішній виклик відбуватиметься без окремого рішення.",
                "A paid external call will happen with no separate decision.",
            ),
        ))
    if values["runtime.automatic_fallback_in_simulation"]:
        findings.append(Finding(
            "attention",
            Message(
                "У симуляції дозволена автопідміна провайдера.",
                "Automatic provider substitution is allowed in simulation.",
            ),
            Message(
                "Результат може прийти не від того провайдера, який обраний.",
                "A result may come from a provider other than the one chosen.",
            ),
        ))
    if not findings:
        findings.append(Finding(
            "ok",
            Message(
                "Межі виконання й підтвердження на місці.",
                "The execution limits and confirmations are in place.",
            ),
        ))
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
        return (Finding(
            "ok",
            Message(
                "Для цього розділу перевірок не оголошено.",
                "No checks are declared for this section.",
            ),
        ),)
    return tuple(checker(values))
