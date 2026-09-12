"""Which machine is this process actually running on.

A hardware report is only worth reading if you know whose hardware it describes.
The demo that showed a container's CPU as the user's PC was not lying on
purpose: nothing in the report said which machine it came from, so the reader
supplied the wrong answer.

This decides, in one place and by one rule:

* **A declaration wins.** Whoever deploys says what this is, in
  ``LOKVETIA_MACHINE_KIND`` (and optionally ``LOKVETIA_MACHINE_NAME``). A
  deployment knows; guessing is for when nobody said.
* **Container markers mean a container.** ``/.dockerenv``, ``/run/.containerenv``
  or a container cgroup are enough to say this is not the person's computer.
* **Otherwise it is the computer this is installed on** - which is the truth for
  a local install, and the reason the answer says how it was reached.

The name is deliberately not a hostname. A hardware report already omits host
names and paths on purpose, and undoing that here to make a label prettier
would leak exactly what that decision protects.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .localisation import DEFAULT_LANGUAGE, Message, normalise

KINDS = ("this_pc", "web_container", "cloud_worker")
DECLARED_KIND = "LOKVETIA_MACHINE_KIND"
DECLARED_NAME = "LOKVETIA_MACHINE_NAME"
CONTAINER_MARKERS = ("/.dockerenv", "/run/.containerenv")
CGROUP = Path("/proc/self/cgroup")
CONTAINER_CGROUP = re.compile(r"docker|kubepods|containerd|lxc|podman")

KIND_LABELS = {
    "this_pc": Message("цей комп'ютер", "this computer"),
    "web_container": Message("вебконтейнер сайту", "the site's web container"),
    "cloud_worker": Message("хмарний воркер", "a cloud worker"),
}
BASIS_DECLARED = Message(
    "Так оголошено при розгортанні.", "Declared this way by the deployment.",
)
BASIS_CONTAINER = Message(
    "Знайдено ознаки контейнера, тож це не комп'ютер користувача.",
    "Container markers were found, so this is not the user's own computer.",
)
BASIS_LOCAL = Message(
    "Ознак контейнера немає, тож це комп'ютер, на якому встановлено Core.",
    "No container marker was found, so this is the computer Core is installed on.",
)
NOT_YOUR_PC = Message(
    "Це показники {machine}, а не вашого ПК.",
    "These are the numbers of {machine}, not of your PC.",
)
YOUR_PC = Message(
    "Це показники комп'ютера, на якому працює Core.",
    "These are the numbers of the computer Core is running on.",
)


def _declared() -> tuple[str, str] | None:
    kind = str(os.environ.get(DECLARED_KIND, "")).strip()
    if kind not in KINDS:
        return None
    return kind, str(os.environ.get(DECLARED_NAME, "")).strip()


def _in_container() -> bool:
    for marker in CONTAINER_MARKERS:
        if Path(marker).exists():
            return True
    try:
        return bool(CONTAINER_CGROUP.search(CGROUP.read_text(encoding="utf-8")))
    except OSError:
        return False


@dataclass(frozen=True)
class ThisMachine:
    """What this process may honestly say about the machine under it."""

    kind: str
    name: str
    basis: Message

    @property
    def is_the_users_computer(self) -> bool:
        return self.kind == "this_pc"

    def label(self, language: str = DEFAULT_LANGUAGE) -> str:
        chosen = normalise(language)
        title = KIND_LABELS[self.kind].text(chosen)
        return f"{title}: {self.name}" if self.name else title

    def caveat(self, language: str = DEFAULT_LANGUAGE) -> str:
        """The sentence a report carries so nobody reads it as their own PC."""
        chosen = normalise(language)
        if self.is_the_users_computer:
            return YOUR_PC.text(chosen)
        return NOT_YOUR_PC.text(chosen, machine=KIND_LABELS[self.kind].text(chosen))

    def record(self, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
        chosen = normalise(language)
        return {
            "kind": self.kind,
            "name": self.name,
            "label": self.label(chosen),
            "basis": self.basis.text(chosen),
            "is_the_users_computer": self.is_the_users_computer,
            "caveat": self.caveat(chosen),
        }


def describe_this_machine() -> ThisMachine:
    """Decide once, by declaration first and evidence second."""
    declared = _declared()
    if declared is not None:
        kind, name = declared
        return ThisMachine(kind, name, BASIS_DECLARED)
    if _in_container():
        return ThisMachine("web_container", "", BASIS_CONTAINER)
    return ThisMachine("this_pc", "", BASIS_LOCAL)


def sign(report: dict[str, Any], *, language: str = DEFAULT_LANGUAGE) -> dict[str, Any]:
    """Attach the machine to a report, so it can never be read as another's."""
    machine = describe_this_machine()
    return {**report, "machine": machine.record(language)}
