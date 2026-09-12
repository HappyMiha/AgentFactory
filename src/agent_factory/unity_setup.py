"""Unity setup as a recipe, with the licence step handed to a person.

Unity is not Godot: the Editor is installed through a Hub, modules are added per
platform, and the account, licence and EULA steps belong to Unity's own flow. So
this module describes the setup, detects what is already there, checks whether a
project matches, and reports what a person still has to do - and it never
performs the licence step, never asks for Unity credentials, and has nowhere to
store them if it did.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

UNITY_HUB_MINIMUM = "3.8.0"
EDITOR_VERSION_PATTERN = re.compile(r"^(\d{4})\.(\d+)\.(\d+)([abfp])(\d+)$")
PROJECT_VERSION_FILE = "ProjectSettings/ProjectVersion.txt"
PACKAGES_LOCK_FILE = "Packages/packages-lock.json"
LICENCE_STATES = ("active", "inactive", "expired", "unknown")
SETUP_STATES = ("ready", "action_required", "blocked")
# There is deliberately no field, argument or file anywhere in this module for a
# Unity account, password, token or serial. The licence step is not ours to do.
NEVER_HANDLED = ("unity account", "unity password", "licence serial", "activation token")


class SetupBlocked(PermissionError):
    """Raised when setup cannot continue without a person acting first."""


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def editor_series(version: str) -> str:
    """`6000.0.23f1` -> `6000.0`. An unparsable version keeps its own text."""
    match = EDITOR_VERSION_PATTERN.match(str(version).strip())
    if not match:
        parts = str(version).strip().split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else str(version).strip()
    return f"{match.group(1)}.{match.group(2)}"


@dataclass(frozen=True)
class EditorRelease:
    version: str
    series: str
    long_term_support: bool
    modules: tuple[str, ...]
    notes: str = ""


@dataclass(frozen=True)
class TargetModule:
    target: str
    module: str
    host_platforms: tuple[str, ...]
    reason: str = ""


SUPPORTED_EDITORS: Mapping[str, EditorRelease] = {
    release.version: release
    for release in (
        EditorRelease(
            "6000.0.23f1", "6000.0", True,
            ("windows-il2cpp", "mac-mono", "linux-il2cpp"),
            "Long-term support release; the pinned default for new projects.",
        ),
        EditorRelease(
            "2022.3.45f1", "2022.3", True,
            ("windows-il2cpp", "mac-mono", "linux-il2cpp"),
            "Previous long-term support release; accepted for existing projects.",
        ),
    )
}
DEFAULT_EDITOR = "6000.0.23f1"
TARGET_MODULES: Mapping[str, TargetModule] = {
    module.target: module
    for module in (
        TargetModule("StandaloneWindows64", "windows-il2cpp", ("Windows",)),
        TargetModule("StandaloneLinux64", "linux-il2cpp", ("Linux", "Windows")),
        TargetModule("StandaloneOSX", "mac-mono", ("Darwin",)),
        TargetModule(
            "iOS", "ios", ("Darwin",),
            "iOS builds require macOS and an Apple developer account.",
        ),
        TargetModule(
            "Android", "android", ("Windows", "Darwin", "Linux"),
            "Android also needs the SDK, NDK and JDK modules installed together.",
        ),
    )
}

LICENCE_HANDOFF = (
    "Open Unity Hub and sign in with your own Unity account.",
    "In Preferences, Licenses, choose Add and follow Unity's own activation flow.",
    "Accept Unity's terms in that flow; they are an agreement between you and "
    "Unity, not something this tool can accept for you.",
    "Come back and re-run the readiness check; setup resumes from where it "
    "stopped.",
)


@dataclass(frozen=True)
class Installation:
    hub_version: str = ""
    editors: Mapping[str, tuple[str, ...]] = None  # version -> installed modules
    licence_state: str = "unknown"
    free_disk_bytes: int = 0
    host_platform: str = "Windows"

    def __post_init__(self) -> None:
        if self.editors is None:
            object.__setattr__(self, "editors", {})
        if self.licence_state not in LICENCE_STATES:
            raise ValueError(f"Unknown licence state: {self.licence_state!r}")


@dataclass(frozen=True)
class ProjectRequirement:
    editor_version: str
    packages_lock_digest: str
    found: bool
    detail: str


@dataclass(frozen=True)
class SetupAction:
    code: str
    summary: str
    detail: str
    performed_by: str  # "person" or "factory"

    @property
    def record(self) -> dict[str, Any]:
        return {
            "code": self.code, "summary": self.summary,
            "detail": self.detail, "performed_by": self.performed_by,
        }


@dataclass(frozen=True)
class SetupStatus:
    state: str
    editor_version: str
    target: str
    installation: Installation
    project: ProjectRequirement | None
    actions: tuple[SetupAction, ...]
    recorded_at: str

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    @property
    def waiting_on_person(self) -> tuple[SetupAction, ...]:
        return tuple(item for item in self.actions if item.performed_by == "person")

    @property
    def record(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "ready": self.ready,
            "editor_version": self.editor_version,
            "editor_series": editor_series(self.editor_version),
            "target": self.target,
            "licence_state": self.installation.licence_state,
            "project": {
                "editor_version": self.project.editor_version,
                "packages_lock_digest": self.project.packages_lock_digest,
                "found": self.project.found,
                "detail": self.project.detail,
            } if self.project else None,
            "actions": [action.record for action in self.actions],
            "waiting_on_person": [action.code for action in self.waiting_on_person],
            "never_handled_here": list(NEVER_HANDLED),
            "recorded_at": self.recorded_at,
        }


def read_project_requirement(project: Path) -> ProjectRequirement:
    """What a Unity project on disk says it needs. Text files only, no editor."""
    root = Path(project)
    version_file = root / PROJECT_VERSION_FILE
    if not version_file.is_file():
        return ProjectRequirement(
            "", "", False, f"no {PROJECT_VERSION_FILE} in {root}",
        )
    version = ""
    try:
        for line in version_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("m_EditorVersion:"):
                version = line.split(":", 1)[1].strip()
                break
    except (OSError, UnicodeDecodeError) as exc:
        return ProjectRequirement("", "", False, f"unreadable: {type(exc).__name__}")
    lock = root / PACKAGES_LOCK_FILE
    digest = ""
    if lock.is_file():
        try:
            digest = hashlib.sha256(lock.read_bytes()).hexdigest()
        except OSError:
            digest = ""
    if not version:
        return ProjectRequirement(
            "", digest, False, f"{PROJECT_VERSION_FILE} declares no m_EditorVersion",
        )
    return ProjectRequirement(version, digest, True, "read from the project")


class UnitySetup:
    """Reports what is installed, what a project needs, and who does what next."""

    def __init__(
        self,
        *,
        editor_version: str = DEFAULT_EDITOR,
        minimum_disk_bytes: int = 25 * 1024 * 1024 * 1024,
    ):
        if editor_version not in SUPPORTED_EDITORS:
            raise ValueError(
                f"Unsupported Unity Editor: {editor_version!r}; pinned versions are "
                + ", ".join(sorted(SUPPORTED_EDITORS))
            )
        self.editor_version = editor_version
        self.minimum_disk_bytes = int(minimum_disk_bytes)

    @property
    def release(self) -> EditorRelease:
        return SUPPORTED_EDITORS[self.editor_version]

    def catalogue(self) -> dict[str, Any]:
        return {
            "hub_minimum": UNITY_HUB_MINIMUM,
            "default_editor": DEFAULT_EDITOR,
            "editors": [
                {
                    "version": release.version, "series": release.series,
                    "long_term_support": release.long_term_support,
                    "modules": list(release.modules), "notes": release.notes,
                }
                for release in SUPPORTED_EDITORS.values()
            ],
            "targets": [
                {
                    "target": module.target, "module": module.module,
                    "host_platforms": list(module.host_platforms),
                    "reason": module.reason,
                }
                for module in TARGET_MODULES.values()
            ],
            "licence_handoff": list(LICENCE_HANDOFF),
            "never_handled_here": list(NEVER_HANDLED),
        }

    def status(
        self,
        installation: Installation,
        *,
        target: str = "StandaloneWindows64",
        project: Path | None = None,
    ) -> SetupStatus:
        module = TARGET_MODULES.get(str(target))
        actions: list[SetupAction] = []
        blocked = False
        if module is None:
            raise KeyError(f"Unknown build target: {target}")
        if installation.host_platform not in module.host_platforms:
            blocked = True
            actions.append(SetupAction(
                "host_platform", f"{target} cannot be built on this machine",
                f"{target} needs one of: {', '.join(module.host_platforms)}."
                + (f" {module.reason}" if module.reason else ""),
                "person",
            ))
        if not installation.hub_version:
            actions.append(SetupAction(
                "install_hub", "Unity Hub is not installed",
                f"Install Unity Hub {UNITY_HUB_MINIMUM} or newer from Unity's own "
                "download page.", "person",
            ))
        elif _older(installation.hub_version, UNITY_HUB_MINIMUM):
            actions.append(SetupAction(
                "upgrade_hub", "Unity Hub is older than the supported minimum",
                f"Hub {installation.hub_version} is installed; {UNITY_HUB_MINIMUM} "
                "or newer is required.", "person",
            ))
        installed_modules = tuple(installation.editors.get(self.editor_version, ()))
        if self.editor_version not in installation.editors:
            conflicting = sorted(
                version for version in installation.editors
                if editor_series(version) != self.release.series
            )
            actions.append(SetupAction(
                "install_editor", f"Unity {self.editor_version} is not installed",
                (
                    f"Install Unity {self.editor_version} through the Hub."
                    + (
                        " Other editors are present and stay installed: "
                        + ", ".join(conflicting) + "; Unity supports several side "
                        "by side, so nothing has to be removed."
                        if conflicting else ""
                    )
                ),
                "person",
            ))
        elif module.module not in installed_modules:
            actions.append(SetupAction(
                "add_module", f"The {module.module} module is missing",
                f"Add the {module.module} module to Unity {self.editor_version} "
                f"through the Hub; it is what builds {target}."
                + (f" {module.reason}" if module.reason else ""),
                "person",
            ))
        if installation.licence_state != "active":
            actions.append(SetupAction(
                "licence", f"The Unity licence is {installation.licence_state}",
                " ".join(LICENCE_HANDOFF), "person",
            ))
        if installation.free_disk_bytes < self.minimum_disk_bytes:
            actions.append(SetupAction(
                "disk_space", "Not enough free disk space",
                f"{installation.free_disk_bytes} bytes free; the editor and its "
                f"modules need about {self.minimum_disk_bytes}. Free space or "
                "choose another drive in the Hub.", "person",
            ))
        requirement = read_project_requirement(project) if project is not None else None
        if requirement is not None and requirement.found:
            if requirement.editor_version != self.editor_version:
                same_series = (
                    editor_series(requirement.editor_version) == self.release.series
                )
                actions.append(SetupAction(
                    "project_editor_mismatch",
                    "The project was made with a different editor",
                    f"The project asks for Unity {requirement.editor_version}; "
                    f"{self.editor_version} is selected. "
                    + (
                        "Same series, so the Hub can open it, and the upgrade is "
                        "recorded in the project."
                        if same_series else
                        "Different series: opening it will upgrade the project, "
                        "which is not reversible in place. Copy it first."
                    ),
                    "person",
                ))
        elif requirement is not None:
            actions.append(SetupAction(
                "project_unreadable", "The project's editor version is unknown",
                requirement.detail, "person",
            ))
        if blocked:
            state = "blocked"
        elif actions:
            state = "action_required"
        else:
            state = "ready"
        return SetupStatus(
            state, self.editor_version, str(target), installation, requirement,
            tuple(actions), _stamp(),
        )

    def resume(
        self,
        probe: Callable[[], Installation],
        *,
        target: str = "StandaloneWindows64",
        project: Path | None = None,
    ) -> SetupStatus:
        """Re-check after a person acted. The probe reports; this never activates."""
        return self.status(probe(), target=target, project=project)

    def require_ready(self, status: SetupStatus) -> None:
        if status.ready:
            return
        raise SetupBlocked(
            "Unity setup is not finished: "
            + "; ".join(action.summary for action in status.actions)
        )


def _older(version: str, minimum: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        return tuple(
            int(re.sub(r"\D", "", piece) or 0) for piece in str(value).split(".")[:3]
        )

    return parts(version) < parts(minimum)


def detect(
    *,
    hub_probe: Callable[[], str],
    editor_probe: Callable[[], Mapping[str, Sequence[str]]],
    licence_probe: Callable[[], str],
    disk_probe: Callable[[], int],
    host_platform: str = "Windows",
) -> Installation:
    """Build an Installation from injected probes; no Unity call is made here."""
    return Installation(
        hub_version=str(hub_probe() or ""),
        editors={
            str(version): tuple(str(module) for module in modules)
            for version, modules in dict(editor_probe() or {}).items()
        },
        licence_state=str(licence_probe() or "unknown"),
        free_disk_bytes=int(disk_probe() or 0),
        host_platform=str(host_platform),
    )
