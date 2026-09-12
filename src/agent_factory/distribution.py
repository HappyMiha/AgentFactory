"""What you downloaded, and whether it is what we published.

A person who installs Core from a website is trusting a file. The only way to
make that trust checkable is to publish, next to the file, exactly what it
should be: its name, its size, its SHA-256, the Python it needs, and which
operating systems the release was actually tried on.

The rules this module enforces:

* **A file is verified against the manifest, not the other way round.** A
  digest that does not match refuses installation and names both digests; a
  size that does not match refuses before a byte is read into a hash.
* **A platform is listed only where the release was actually tried.** Anything
  else says "not tried on this system yet" instead of implying it works.
* **A manifest is not a signature.** Checksums prove that a download matches
  what the manifest says; they prove nothing about who wrote the manifest. This
  module says that plainly rather than letting "verified" mean more than it
  does. Signed updates are :mod:`agent_factory.application_update`, which needs
  a trust root this module deliberately does not invent.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .localisation import DEFAULT_LANGUAGE, LocalisedError, Message, normalise

SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PLATFORMS = ("windows", "macos", "linux")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
READ_CHUNK = 1024 * 1024


class DistributionRefused(LocalisedError):
    """Raised when installing this would mean trusting an unchecked file."""


BAD_VERSION = Message(
    "Версія «{version}» не схожа на версію вигляду 1.2.3.",
    "The version '{version}' does not look like 1.2.3.",
)
BAD_DIGEST = Message(
    "Контрольна сума має бути 64 шістнадцятковими символами, а не «{digest}».",
    "A checksum must be 64 hexadecimal characters, not '{digest}'.",
)
UNKNOWN_PLATFORM = Message(
    "Невідома система: {platform}.", "Unknown operating system: {platform}.",
)
NO_ARTIFACTS = Message(
    "Реліз без жодного файлу нема що встановлювати.",
    "A release with no file has nothing to install.",
)
MISSING_FILE = Message(
    "Файла немає: {name}.", "The file is missing: {name}.",
)
WRONG_SIZE = Message(
    "Розмір файлу {name} — {actual} байт, а має бути {expected}. Це не той файл.",
    "The file {name} is {actual} bytes and should be {expected}. This is not "
    "that file.",
)
WRONG_DIGEST = Message(
    "Контрольна сума файлу {name} не збігається. Очікували {expected}, "
    "отримали {actual}. Не встановлюйте його.",
    "The checksum of {name} does not match. Expected {expected}, got {actual}. "
    "Do not install it.",
)
UNTRIED_PLATFORM = Message(
    "Цей реліз ще не пробували на {platform}. Він може працювати, але ми цього "
    "не перевіряли.",
    "This release has not been tried on {platform} yet. It may work; we have "
    "not checked.",
)
TRIED_PLATFORM = Message(
    "Реліз перевіряли на {platform}.", "The release was tried on {platform}.",
)
NOT_A_SIGNATURE = Message(
    "Контрольна сума доводить, що файл не змінився дорогою. Вона не доводить, "
    "хто його опублікував.",
    "A checksum proves the file did not change on the way. It does not prove "
    "who published it.",
)
PYTHON_REQUIRED = Message(
    "Потрібен Python {version} або новіший.", "Python {version} or newer is required.",
)


def _digest_of(path: Path) -> str:
    reader = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(READ_CHUNK)
            if not chunk:
                break
            reader.update(chunk)
    return reader.hexdigest()


@dataclass(frozen=True)
class Artifact:
    """One published file, and what it must be."""

    name: str
    size_bytes: int
    sha256: str
    kind: str = "wheel"

    def __post_init__(self) -> None:
        if not DIGEST.fullmatch(str(self.sha256)):
            raise DistributionRefused(BAD_DIGEST, digest=self.sha256)
        if int(self.size_bytes) <= 0:
            raise ValueError("A published file has a size")

    def record(self) -> dict[str, Any]:
        return {
            "name": self.name, "size_bytes": self.size_bytes,
            "sha256": self.sha256, "kind": self.kind,
        }


@dataclass(frozen=True)
class Release:
    """A published release: the files, the Python it needs, where it was tried."""

    version: str
    artifacts: tuple[Artifact, ...]
    python_requires: str = "3.11"
    tried_on: tuple[str, ...] = ()
    notes: Message | None = None

    def __post_init__(self) -> None:
        if not SEMVER.fullmatch(str(self.version)):
            raise DistributionRefused(BAD_VERSION, version=self.version)
        if not self.artifacts:
            raise DistributionRefused(NO_ARTIFACTS)
        for platform in self.tried_on:
            if platform not in PLATFORMS:
                raise DistributionRefused(UNKNOWN_PLATFORM, platform=platform)

    def artifact(self, name: str) -> Artifact:
        for item in self.artifacts:
            if item.name == name:
                return item
        raise KeyError(f"Unknown artifact {name}")

    def platform_note(self, platform: str) -> Message:
        """What we can honestly say about this release on that system."""
        if platform not in PLATFORMS:
            raise DistributionRefused(UNKNOWN_PLATFORM, platform=platform)
        template = TRIED_PLATFORM if platform in self.tried_on else UNTRIED_PLATFORM
        return Message(
            template.uk.format(platform=platform),
            template.en.format(platform=platform),
        )

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        chosen = normalise(language)
        return {
            "version": self.version,
            "python_requires": self.python_requires,
            "artifacts": [item.record() for item in self.artifacts],
            "tried_on": list(self.tried_on),
            "platforms": {
                platform: self.platform_note(platform).text(chosen)
                for platform in PLATFORMS
            },
            "python": PYTHON_REQUIRED.text(chosen, version=self.python_requires),
            "notes": self.notes.text(chosen) if self.notes else "",
            "checksums_are_not_a_signature": NOT_A_SIGNATURE.text(chosen),
        }

    def manifest(self) -> dict[str, Any]:
        """The machine-readable file published next to the release."""
        return {
            "schema_version": 1,
            "version": self.version,
            "python_requires": self.python_requires,
            "tried_on": list(self.tried_on),
            "artifacts": [item.record() for item in self.artifacts],
            "notes": self.notes.record() if self.notes else None,
        }


def load_release(payload: Mapping[str, Any]) -> Release:
    """Read a published manifest, refusing anything it cannot vouch for."""
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("Unsupported distribution manifest schema")
    notes = payload.get("notes")
    return Release(
        version=str(payload.get("version", "")),
        artifacts=tuple(
            Artifact(
                str(item["name"]), int(item["size_bytes"]), str(item["sha256"]),
                str(item.get("kind", "wheel")),
            )
            for item in payload.get("artifacts", [])
        ),
        python_requires=str(payload.get("python_requires", "3.11")),
        tried_on=tuple(str(item) for item in payload.get("tried_on", ())),
        notes=Message(notes["uk"], notes["en"]) if notes else None,
    )


@dataclass(frozen=True)
class Verification:
    """Whether the file on this disk is the file that was published."""

    name: str
    matches: bool
    expected: str
    actual: str
    summary: Message

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        return {
            "name": self.name, "matches": self.matches,
            "expected": self.expected, "actual": self.actual,
            "summary": self.summary.text(language),
        }


MATCHES = Message(
    "Файл {name} збігається з опублікованим.",
    "The file {name} matches what was published.",
)


def verify(release: Release, directory: Path, name: str) -> Verification:
    """Check one downloaded file against the manifest. Refuse anything else."""
    artifact = release.artifact(name)
    path = Path(directory) / name
    if not path.is_file():
        raise DistributionRefused(MISSING_FILE, name=name)
    size = path.stat().st_size
    if size != artifact.size_bytes:
        raise DistributionRefused(
            WRONG_SIZE, name=name, actual=size, expected=artifact.size_bytes,
        )
    actual = _digest_of(path)
    if actual != artifact.sha256:
        raise DistributionRefused(
            WRONG_DIGEST, name=name, expected=artifact.sha256[:12],
            actual=actual[:12],
        )
    return Verification(
        name, True, artifact.sha256, actual,
        Message(MATCHES.uk.format(name=name), MATCHES.en.format(name=name)),
    )


def verify_all(release: Release, directory: Path) -> tuple[Verification, ...]:
    """Every published file, in order. The first bad one stops the install."""
    return tuple(verify(release, directory, item.name) for item in release.artifacts)


def describe(
    release: Release, *, platform: str = "", language: str = DEFAULT_LANGUAGE
) -> dict[str, Any]:
    """What a download page can honestly say about this release."""
    chosen = normalise(language)
    described = release.record(chosen)
    if platform:
        described["platform_note"] = release.platform_note(platform).text(chosen)
        described["tried_here"] = platform in release.tried_on
    return described


def build_release(
    version: str,
    files: Iterable[Path],
    *,
    python_requires: str = "3.11",
    tried_on: Sequence[str] = (),
    notes: Message | None = None,
) -> Release:
    """Describe files that exist, by reading them - never by being told."""
    artifacts = []
    for path in files:
        path = Path(path)
        if not path.is_file():
            raise DistributionRefused(MISSING_FILE, name=path.name)
        artifacts.append(Artifact(
            path.name, path.stat().st_size, _digest_of(path),
            "wheel" if path.suffix == ".whl" else "archive",
        ))
    return Release(
        version=str(version), artifacts=tuple(artifacts),
        python_requires=str(python_requires),
        tried_on=tuple(str(item) for item in tried_on), notes=notes,
    )


def tried_platforms(
    requested: Sequence[str], *, install_checked: bool, here: str,
) -> tuple[str, ...]:
    """Which systems a release may claim, given what was actually done.

    The machine that built the release counts only when the built wheel was
    installed there and the installed command answered. Building without that
    check proves the files exist, not that they work, so the build machine is
    left off the list.
    """
    listed = list(dict.fromkeys(str(item) for item in requested))
    for platform in listed:
        if platform not in PLATFORMS:
            raise DistributionRefused(UNKNOWN_PLATFORM, platform=platform)
    if install_checked and here in PLATFORMS and here not in listed:
        listed.append(here)
    return tuple(listed)


def write_manifest(release: Release, path: Path) -> Path:
    """Write the manifest that is published next to the files."""
    path = Path(path)
    path.write_text(
        json.dumps(release.manifest(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
