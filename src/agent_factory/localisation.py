"""Two languages, one catalogue, and a test that fails when one is missing.

The product claims Ukrainian and English. A half-translated interface is worse
than an untranslated one, because it hides which half is missing, so every
message here carries both languages and a completeness test refuses a catalogue
where one is blank. Nothing falls back silently.

Language is negotiated from the request, never guessed from the machine: an
explicit choice wins, then a stored preference, then what the browser asked for,
then Ukrainian.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

LANGUAGES = ("uk", "en")
DEFAULT_LANGUAGE = "uk"
LANGUAGE_COOKIE = "lokvetia_language"
ACCEPT_LANGUAGE = re.compile(r"([A-Za-z]{2,3})(?:-[A-Za-z0-9]+)?\s*(?:;\s*q=([0-9.]+))?")


class LocalisedError(ValueError):
    """An error that carries its text in every supported language.

    A message a person has to act on must reach them in their language, so the
    error travels as a Message and the boundary that knows the request renders
    it. str() gives Ukrainian so a log line still reads.
    """

    def __init__(self, message: "Message"):
        self.message = message
        super().__init__(message.text(DEFAULT_LANGUAGE))

    def text(self, language: str = DEFAULT_LANGUAGE) -> str:
        return self.message.text(language)


class MissingTranslation(ValueError):
    """Raised when a message does not carry every supported language."""


@dataclass(frozen=True)
class Message:
    """One piece of text in every language the product claims to support."""

    uk: str
    en: str

    def __post_init__(self) -> None:
        for language in LANGUAGES:
            if not str(getattr(self, language)).strip():
                raise MissingTranslation(
                    f"Message is missing its {language} text: {self!r}"
                )

    def text(self, language: str = DEFAULT_LANGUAGE, **parameters: Any) -> str:
        value = getattr(self, normalise(language))
        return value.format(**parameters) if parameters else value

    def record(self) -> dict[str, str]:
        return {"uk": self.uk, "en": self.en}


def normalise(language: str | None) -> str:
    """Reduce a tag to a supported language, or to the default."""
    candidate = str(language or "").strip().casefold().replace("_", "-").split("-")[0]
    return candidate if candidate in LANGUAGES else DEFAULT_LANGUAGE


def negotiate(
    *,
    explicit: str | None = None,
    stored: str | None = None,
    accept_language: str | None = None,
) -> str:
    """An explicit choice wins, then a stored one, then the browser's preference."""
    for candidate in (explicit, stored):
        if candidate and normalise(candidate) == str(candidate).strip().casefold()[:2]:
            return normalise(candidate)
    ranked: list[tuple[float, int, str]] = []
    for index, match in enumerate(ACCEPT_LANGUAGE.finditer(accept_language or "")):
        tag = match.group(1).casefold()
        if tag not in LANGUAGES:
            continue
        try:
            quality = float(match.group(2)) if match.group(2) else 1.0
        except ValueError:
            quality = 1.0
        ranked.append((-quality, index, tag))
    if ranked:
        return sorted(ranked)[0][2]
    return DEFAULT_LANGUAGE


CATALOGUE: Mapping[str, Message] = {
    # Shared chrome
    "app.name": Message("Lokvetia Core", "Lokvetia Core"),
    "app.workspace": Message("Локальний робочий простір", "Local workspace"),
    "nav.games": Message("Мої ігри", "My games"),
    "nav.hardware": Message("Перевірити ПК", "Check this PC"),
    "nav.credentials": Message("Доступ до AI", "AI access"),
    "nav.operations": Message("Панель оператора", "Operator console"),
    "nav.settings": Message("Налаштування", "Settings"),
    "nav.progress": Message("Хід роботи", "Work in progress"),
    "nav.login": Message("Доступ і вихід", "Sign in and out"),
    "nav.skip": Message("До вмісту", "Skip to content"),
    "nav.aria": Message("Навігація", "Navigation"),
    "language.label": Message("Мова", "Language"),
    "language.uk": Message("Українська", "Ukrainian"),
    "language.en": Message("Англійська", "English"),
    "common.unknown": Message("Невідомо", "Unknown"),
    "common.loading": Message("Завантаження…", "Loading…"),
    "common.refresh": Message("Оновити", "Refresh"),
    "common.cancel": Message("Скасувати", "Cancel"),
    "common.apply": Message("Застосувати", "Apply"),

    # Settings page
    "settings.title": Message("Налаштування", "Settings"),
    "settings.eyebrow": Message("Робочий простір", "Workspace"),
    "settings.lead": Message(
        "Усе, що впливає на роботу, зібране тут: чинне значення, звідки воно "
        "взялося, і що зміниться, якщо його змінити. Файли редагувати не потрібно.",
        "Everything that affects how this works is here: the current value, where "
        "it came from, and what changes if you change it. No file editing needed.",
    ),
    "settings.who.label": Message("Хто змінює", "Who is changing this"),
    "settings.who.placeholder": Message("Ваше імʼя", "Your name"),
    "settings.who.help": Message(
        "Кожна зміна записується на конкретну людину й лишається в незмінній "
        "історії внизу сторінки. Без імені зміна не зберігається.",
        "Every change is recorded against a named person and stays in the "
        "unchangeable history below. Without a name, nothing is saved.",
    ),
    "settings.save": Message("Зберегти", "Save"),
    "settings.reset": Message("Повернути типове", "Restore the default"),
    "settings.verify": Message("Перевірити розділ", "Check this section"),
    "settings.reason.placeholder": Message(
        "Причина (необовʼязково)", "Reason (optional)"
    ),
    "settings.reason.label": Message("Причина зміни: {label}", "Reason for: {label}"),
    "settings.save.label": Message("Зберегти: {label}", "Save: {label}"),
    "settings.reset.label": Message(
        "Повернути типове: {label}", "Restore the default: {label}"
    ),
    "settings.verify.label": Message(
        "Перевірити розділ: {title}", "Check this section: {title}"
    ),
    "settings.badge.default": Message("типове", "default"),
    "settings.badge.changed": Message("змінено", "changed"),
    "settings.badge.sensitive": Message("важливе", "important"),
    "settings.badge.locked": Message("лише перегляд", "view only"),
    "settings.origin.default": Message("Типове: {value}", "Default: {value}"),
    "settings.origin.source": Message(
        "Джерело типового: {source}", "Where the default comes from: {source}"
    ),
    "settings.origin.unit": Message("Одиниці: {unit}", "Unit: {unit}"),
    "settings.origin.changed_by": Message(
        "Змінив(ла) {actor}", "Changed by {actor}"
    ),
    "settings.origin.reason": Message("Причина: {reason}", "Reason: {reason}"),
    "settings.consequence": Message(
        "Якщо змінити: {consequence}", "If you change it: {consequence}"
    ),
    "settings.current": Message("Чинне значення: {value}", "Current value: {value}"),
    "settings.changed_count": Message(
        "Змінено від типового: {count}", "Changed from the default: {count}"
    ),
    "settings.summary.changed": Message(
        "Значень, змінених від типового: {count}.",
        "Values changed from their default: {count}.",
    ),
    "settings.summary.clean": Message(
        "Усі значення типові — нічого не перевизначено.",
        "Every value is the default — nothing is overridden.",
    ),
    "settings.saved": Message("Збережено: {label}.", "Saved: {label}."),
    "settings.restored": Message(
        "Повернуто типове: {label}.", "Restored the default: {label}."
    ),
    "settings.applied": Message(
        "Зміну застосовано з підтвердженням наслідку.",
        "The change was applied with its consequence acknowledged.",
    ),
    "settings.not_applied": Message(
        "Зміну не застосовано: наслідок не підтверджено.",
        "Not applied: the consequence was not acknowledged.",
    ),
    "settings.need_actor": Message(
        "Спершу вкажіть, хто змінює.", "First say who is making the change."
    ),
    "settings.read_failed": Message(
        "Не вдалося прочитати налаштування ({status}).",
        "Could not read the settings ({status}).",
    ),
    "settings.history.title": Message("Історія змін", "Change history"),
    "settings.history.note": Message(
        "Записи не редагуються й не видаляються — цього не дозволяє сама база.",
        "Entries are never edited or deleted — the database itself refuses.",
    ),
    "settings.history.empty": Message(
        "Змін ще не було: усі значення типові.",
        "No changes yet: every value is the default.",
    ),
    "settings.history.when": Message("Коли", "When"),
    "settings.history.setting": Message("Налаштування", "Setting"),
    "settings.history.change": Message("Було → стало", "Before → after"),
    "settings.history.who": Message("Хто", "Who"),
    "settings.history.why": Message("Причина", "Reason"),
    "settings.history.region": Message(
        "Історія змін налаштувань", "Settings change history"
    ),
    "settings.confirm.title": Message("Підтвердьте наслідок", "Acknowledge the cost"),
    "settings.confirm.reason": Message("Причина зміни", "Reason for the change"),
    "settings.confirm.ack": Message(
        "Розумію наслідок і беру його на себе",
        "I understand the consequence and accept it",
    ),

    # Settings errors, phrased as cause and action
    "error.actor_required": Message(
        "Зміна налаштування записується на конкретну людину. Вкажіть імʼя.",
        "A setting is recorded against a named person. Enter a name.",
    ),
    "error.not_reconfigurable": Message(
        "{label} походить із {source} і змінюється там, а не тут.",
        "{label} comes from {source} and is changed there, not here.",
    ),
    "error.confirmation_required": Message(
        "{label}: {consequence} Підтвердьте наслідок, щоб застосувати зміну.",
        "{label}: {consequence} Acknowledge the consequence to apply the change.",
    ),
    "error.unknown_setting": Message(
        "Такого налаштування немає: {key}.", "No such setting: {key}."
    ),
    "error.out_of_range": Message(
        "{label}: {value} поза межами {minimum}–{maximum}. Виберіть значення в межах.",
        "{label}: {value} is outside {minimum}–{maximum}. Choose a value in range.",
    ),
}


def translate(key: str, language: str = DEFAULT_LANGUAGE, **parameters: Any) -> str:
    try:
        message = CATALOGUE[key]
    except KeyError:
        raise KeyError(f"Unknown message key: {key}") from None
    return message.text(language, **parameters)


def bundle(language: str = DEFAULT_LANGUAGE, *, prefix: str = "") -> dict[str, str]:
    """Every message a static page needs, in one language."""
    chosen = normalise(language)
    return {
        key: message.text(chosen)
        for key, message in CATALOGUE.items()
        if not prefix or key.startswith(prefix)
    }


def missing_translations(messages: Iterable[Any]) -> tuple[str, ...]:
    """Names of messages that do not carry every supported language."""
    gaps: list[str] = []
    for index, message in enumerate(messages):
        for language in LANGUAGES:
            value = getattr(message, language, "")
            if not str(value).strip():
                gaps.append(f"{index}:{language}")
    return tuple(gaps)
