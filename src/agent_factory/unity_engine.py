"""Qualified, shell-free Unity adapter whose verdict is not the exit code.

Unity in batch mode exits 0 in situations that are plainly failures: C# files
that did not compile, a build method that reported Failed, packages that never
resolved. So every run here is judged by its log as well as its code, tests are
read from the results file rather than inferred, and no operation starts at all
while the licence is not active - because a batch run without a licence produces
a confusing log rather than an honest error.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .unity_setup import (
    PACKAGES_LOCK_FILE,
    PROJECT_VERSION_FILE,
    SUPPORTED_EDITORS,
    editor_series,
    read_project_requirement,
)

OPERATIONS = (
    "version_probe", "import_project", "edit_mode_tests", "play_mode_tests", "build",
)
EVIDENCE_KINDS = {
    "version_probe": "engine_identity",
    "import_project": "engine_import",
    "edit_mode_tests": "edit_mode_tests",
    "play_mode_tests": "play_mode_runtime",
    "build": "engine_build",
}
PLAYED_GAME_EVIDENCE = "graphical_playtest"
VERSION_PATTERN = re.compile(r"\b(\d{4}\.\d+\.\d+[abfp]\d+)\b")
FAILURE_MARKERS = (
    ("compile error", re.compile(r"error CS\d{4}")),
    ("compilation failed", re.compile(r"(?i)compilation failed")),
    ("build failed", re.compile(r"Build completed with a result of ['\"]?Failed")),
    ("licence not active", re.compile(r"(?i)(no valid unity editor license|license is not active|failed to activate)")),
    ("editor already running", re.compile(r"(?i)multiple unity instances cannot open the same project")),
    ("package resolution failed", re.compile(r"(?i)(failed to resolve packages|package manager \[?error)")),
    ("batchmode aborted", re.compile(r"(?i)aborting batchmode due to failure")),
    ("missing asset", re.compile(r"(?i)could not (be )?(find|load) (the )?(asset|scene)")),
)
BASE_ARGUMENTS = ("-batchmode", "-nographics", "-logFile", "-")


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _bounded(text: str, limit: int) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n[truncated after {limit} characters]"


@dataclass(frozen=True)
class UnityHealth:
    healthy: bool
    executable: str | None
    version: str | None
    version_supported: bool
    licence_active: bool
    reason: str


@dataclass(frozen=True)
class TestOutcome:
    total: int
    passed: int
    failed: int
    skipped: int
    parsed: bool

    @property
    def record(self) -> dict[str, Any]:
        return {
            "total": self.total, "passed": self.passed, "failed": self.failed,
            "skipped": self.skipped, "parsed": self.parsed,
        }


@dataclass(frozen=True)
class UnityRun:
    operation: str
    status: str
    exit_code: int | None
    duration_ms: int
    command: tuple[str, ...]
    command_digest: str
    evidence_kind: str
    log: str
    detail: str
    tests: TestOutcome | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "operation": self.operation, "status": self.status,
            "exit_code": self.exit_code, "duration_ms": self.duration_ms,
            "command_digest": self.command_digest,
            "evidence_kind": self.evidence_kind, "detail": self.detail,
            "tests": self.tests.record if self.tests else None,
        }


@dataclass(frozen=True)
class UnityArtifact:
    editor_version: str
    project_editor_version: str
    packages_lock_digest: str
    build_target: str
    source_commit: str
    artifact_path: str | None
    artifact_checksum: str | None
    artifact_bytes: int | None
    runs: tuple[UnityRun, ...]
    recorded_at: str
    graphical_playtest: bool = False

    @property
    def succeeded(self) -> bool:
        return bool(self.artifact_checksum) and all(run.succeeded for run in self.runs)

    @property
    def failure(self) -> UnityRun | None:
        return next((run for run in self.runs if not run.succeeded), None)

    @property
    def evidence_gap(self) -> tuple[str, ...]:
        gaps: list[str] = []
        if not self.graphical_playtest:
            gaps.append(PLAYED_GAME_EVIDENCE)
        if not any(
            run.operation == "play_mode_tests" and run.succeeded for run in self.runs
        ):
            gaps.append("play_mode_runtime")
        return tuple(gaps)

    @property
    def promotable(self) -> dict[str, Any]:
        """The same build in the ledger's neutral shape, so it can be promoted.

        The playable ledger is engine-neutral and names fields its own way. Rather
        than bend Unity's manifest into those names, the mapping is stated here
        once: the editor version is the engine version, the packages lock is what
        identifies the project's dependency state, and the build target plays the
        part of an export preset.
        """
        return {
            **self.manifest,
            "engine_version": self.editor_version,
            "project_digest": self.packages_lock_digest or "no-packages-lock",
            "template_id": "unity-project",
            "template_version": self.project_editor_version or "unknown",
            "preset": self.build_target,
        }

    @property
    def manifest(self) -> dict[str, Any]:
        return {
            "engine": "unity",
            "editor_version": self.editor_version,
            "project_editor_version": self.project_editor_version,
            "packages_lock_digest": self.packages_lock_digest,
            "build_target": self.build_target,
            "source_commit": self.source_commit,
            "artifact_path": self.artifact_path,
            "artifact_checksum": self.artifact_checksum,
            "artifact_bytes": self.artifact_bytes,
            "succeeded": self.succeeded,
            "graphical_playtest": self.graphical_playtest,
            "evidence_gap": list(self.evidence_gap),
            "recorded_at": self.recorded_at,
            "runs": [run.summary for run in self.runs],
        }


class UnityAdapter:
    """Runs a fixed set of Unity batch operations and judges them by their logs."""

    def __init__(
        self,
        *,
        executable_candidates: Iterable[str] = ("Unity", "unity"),
        executable_args: Iterable[str] = (),
        editor_version: str = "",
        licence_probe: Any = None,
        max_seconds: int = 1800,
        max_output_chars: int = 200_000,
        probe_seconds: int = 60,
    ):
        self.executable_candidates = tuple(executable_candidates)
        self.executable_args = tuple(executable_args)
        self.editor_version = str(editor_version)
        self.licence_probe = licence_probe
        if max_seconds <= 0 or max_output_chars <= 0 or probe_seconds <= 0:
            raise ValueError("Engine limits must be positive")
        self.max_seconds = int(max_seconds)
        self.max_output_chars = int(max_output_chars)
        self.probe_seconds = int(probe_seconds)

    @staticmethod
    def _resolve(raw: str) -> str | None:
        expanded = os.path.expandvars(os.path.expanduser(raw))
        candidate = Path(expanded)
        if candidate.is_absolute() or candidate.parent != Path("."):
            resolved = candidate.resolve()
            return str(resolved) if resolved.is_file() else None
        located = shutil.which(expanded)
        return str(Path(located).resolve()) if located else None

    def executable(self) -> str | None:
        for raw in self.executable_candidates:
            resolved = self._resolve(raw)
            if resolved:
                return resolved
        return None

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = {
            key: value for key, value in os.environ.items()
            if not any(
                marker in key.upper()
                for marker in ("TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL")
            )
        }
        environment.update({"NO_COLOR": "1", "TERM": "dumb"})
        return environment

    def _execute(
        self, operation: str, arguments: Sequence[str], *, timeout: int,
    ) -> UnityRun:
        if operation not in OPERATIONS:
            raise ValueError(f"Unknown Unity operation: {operation}")
        evidence = EVIDENCE_KINDS[operation]
        executable = self.executable()
        if executable is None:
            return UnityRun(
                operation, "unavailable", None, 0, (), "", evidence, "",
                "the Unity Editor executable is not available",
            )
        command = (executable, *self.executable_args, *(str(v) for v in arguments))
        if any("\x00" in value for value in command):
            raise ValueError("Engine arguments must be a clean fixed vector")
        digest = hashlib.sha256(_canonical(list(command)).encode("utf-8")).hexdigest()
        started = datetime.now(timezone.utc)
        try:
            completed = subprocess.run(
                list(command), shell=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, check=False,
                env=self._environment(),
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return UnityRun(
                operation, "timeout", None, elapsed, command, digest, evidence,
                _bounded(_text(exc.stdout) + _text(exc.stderr), self.max_output_chars),
                f"the editor exceeded {timeout}s",
            )
        except OSError as exc:
            elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return UnityRun(
                operation, "unavailable", None, elapsed, command, digest, evidence,
                "", f"{type(exc).__name__}: the editor could not be started",
            )
        elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        log = _bounded(
            (completed.stdout or "") + (completed.stderr or ""), self.max_output_chars
        )
        status, detail = classify(completed.returncode, log)
        return UnityRun(
            operation, status, completed.returncode, elapsed, command, digest,
            evidence, log, detail,
        )

    def health(self) -> UnityHealth:
        executable = self.executable()
        if executable is None:
            return UnityHealth(
                False, None, None, False, False,
                "the Unity Editor executable is not available",
            )
        run = self._execute("version_probe", ("-version",), timeout=self.probe_seconds)
        match = VERSION_PATTERN.search(run.log)
        version = match.group(1) if match else None
        supported = bool(version) and (
            version in SUPPORTED_EDITORS
            or editor_series(version) in {
                release.series for release in SUPPORTED_EDITORS.values()
            }
        )
        licence = self.licence_active()
        healthy = bool(version) and supported and licence
        if healthy:
            reason = "qualified"
        elif not version:
            reason = "the editor version could not be identified"
        elif not supported:
            reason = f"editor {version} is outside the pinned range"
        else:
            reason = "the Unity licence is not active; a person has to activate it"
        return UnityHealth(healthy, executable, version, supported, licence, reason)

    def licence_active(self) -> bool:
        """Never activates anything. Reports what a caller-supplied probe found."""
        if self.licence_probe is None:
            return False
        return str(self.licence_probe()) == "active"

    @staticmethod
    def _project(project: Path) -> Path:
        root = Path(project).resolve()
        if not (root / PROJECT_VERSION_FILE).is_file():
            raise FileNotFoundError(f"No Unity project at {root}")
        return root

    def import_project(self, project: Path, *, timeout: int | None = None) -> UnityRun:
        root = self._project(project)
        return self._execute(
            "import_project",
            (*BASE_ARGUMENTS, "-quit", "-projectPath", str(root)),
            timeout=timeout or self.max_seconds,
        )

    def run_tests(
        self,
        project: Path,
        *,
        platform: str = "EditMode",
        results: Path | None = None,
        timeout: int | None = None,
    ) -> UnityRun:
        if platform not in {"EditMode", "PlayMode"}:
            raise ValueError("Unity test platforms are EditMode and PlayMode")
        root = self._project(project)
        destination = Path(results) if results else root / f"{platform}-results.xml"
        destination.parent.mkdir(parents=True, exist_ok=True)
        operation = "edit_mode_tests" if platform == "EditMode" else "play_mode_tests"
        # -runTests must not be combined with -quit: the editor exits on its own.
        run = self._execute(
            operation,
            (
                *BASE_ARGUMENTS, "-runTests", "-projectPath", str(root),
                "-testPlatform", platform, "-testResults", str(destination),
            ),
            timeout=timeout or self.max_seconds,
        )
        outcome = read_test_results(destination)
        detail = run.detail
        status = run.status
        if status == "succeeded" and not outcome.parsed:
            status, detail = "failed", "the run produced no test results file"
        elif status == "succeeded" and outcome.failed:
            status, detail = "failed", f"{outcome.failed} test(s) failed"
        return UnityRun(
            run.operation, status, run.exit_code, run.duration_ms, run.command,
            run.command_digest, run.evidence_kind, run.log, detail, outcome,
        )

    def build(
        self,
        project: Path,
        *,
        build_method: str,
        build_target: str,
        output: Path,
        timeout: int | None = None,
    ) -> UnityRun:
        root = self._project(project)
        if not str(build_method).strip() or "." not in str(build_method):
            raise ValueError(
                "A Unity batch build needs a fully qualified static method name"
            )
        destination = Path(output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        return self._execute(
            "build",
            (
                *BASE_ARGUMENTS, "-quit", "-projectPath", str(root),
                "-buildTarget", str(build_target),
                "-executeMethod", str(build_method),
                "-lokvetiaBuildOutput", str(destination),
            ),
            timeout=timeout or self.max_seconds,
        )

    def verify_and_build(
        self,
        project: Path,
        *,
        build_method: str,
        build_target: str,
        output: Path,
        source_commit: str = "unknown",
        play_mode: bool = True,
    ) -> UnityArtifact:
        """Import, compile, test and build, stopping at the first failure."""
        root = self._project(project)
        requirement = read_project_requirement(root)
        health = self.health()
        runs: list[UnityRun] = []
        if not health.healthy:
            runs.append(UnityRun(
                "version_probe", "failed", None, 0, (), "",
                EVIDENCE_KINDS["version_probe"], "", health.reason,
            ))
            return _artifact(
                health.version or "unknown", requirement, build_target,
                source_commit, None, runs,
            )
        runs.append(self.import_project(root))
        if runs[-1].succeeded:
            runs.append(self.run_tests(root, platform="EditMode"))
        if play_mode and all(run.succeeded for run in runs):
            runs.append(self.run_tests(root, platform="PlayMode"))
        if all(run.succeeded for run in runs):
            runs.append(self.build(
                root, build_method=build_method, build_target=build_target,
                output=output,
            ))
        destination = Path(output).resolve()
        if all(run.succeeded for run in runs) and destination.is_file():
            payload = destination.read_bytes()
            return _artifact(
                health.version or "unknown", requirement, build_target, source_commit,
                (str(destination), hashlib.sha256(payload).hexdigest(), len(payload)),
                runs,
            )
        if all(run.succeeded for run in runs):
            runs.append(UnityRun(
                "build", "failed", None, 0, (), "", EVIDENCE_KINDS["build"], "",
                "the editor reported success but produced no artifact file",
            ))
        return _artifact(
            health.version or "unknown", requirement, build_target, source_commit,
            None, runs,
        )


def _artifact(
    editor_version: str,
    requirement: Any,
    build_target: str,
    source_commit: str,
    payload: tuple[str, str, int] | None,
    runs: Sequence[UnityRun],
) -> UnityArtifact:
    path, checksum, size = payload if payload else (None, None, None)
    return UnityArtifact(
        editor_version, getattr(requirement, "editor_version", ""),
        getattr(requirement, "packages_lock_digest", ""), str(build_target),
        str(source_commit), path, checksum, size, tuple(runs), _stamp(),
    )


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def classify(returncode: int | None, log: str) -> tuple[str, str]:
    """An exit code alone never decides: Unity exits 0 on real failures."""
    for label, pattern in FAILURE_MARKERS:
        if pattern.search(log or ""):
            return "failed", f"the editor log reports a {label}"
    if returncode != 0:
        return "failed", f"the editor exited with code {returncode}"
    return "succeeded", "completed"


def read_test_results(path: Path) -> TestOutcome:
    """Read Unity's NUnit results file. An absent file is not a pass."""
    results = Path(path)
    if not results.is_file():
        return TestOutcome(0, 0, 0, 0, False)
    try:
        root = ElementTree.parse(results).getroot()
    except (ElementTree.ParseError, OSError):
        return TestOutcome(0, 0, 0, 0, False)
    def number(name: str) -> int:
        try:
            return int(root.attrib.get(name, 0))
        except (TypeError, ValueError):
            return 0
    return TestOutcome(
        number("total"), number("passed"), number("failed"), number("skipped"), True,
    )
