"""Qualified, shell-free Godot engine adapter that produces bounded evidence.

A textual verdict from a model is not evidence that a game project works. This
adapter runs the real engine with fixed argument vectors, a hard timeout and a
bounded log, and it records each operation separately so a static script check
is never reported as a played game.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .godot_pack import SUPPORTED_ENGINE_VERSIONS, export_presets


REQUIRED_FLAGS = (
    "--headless", "--path", "--import", "--check-only", "--script",
    "--export-release", "--quit-after",
)
VERSION_PATTERN = re.compile(
    r"\b\d+\.\d+(?:\.\d+)?\.(?:stable|beta\d*|rc\d*|dev)(?:\.[A-Za-z0-9_\-]+)*"
)
ERROR_MARKERS = (
    "SCRIPT ERROR",
    "Parse Error",
    "Compile Error",
    "No export template found",
    "export templates",
    "Cannot open file",
    "Resource file not found",
    "Failed to load",
    "Condition \"err != OK\" is true",
)
CRASH_MARKERS = ("Program crashed", "handle_crash", "Segmentation fault")
OPERATIONS = (
    "version_probe", "interface_probe", "import", "script_check",
    "headless_smoke", "export",
)
EVIDENCE_KINDS = {
    "version_probe": "engine_identity",
    "interface_probe": "engine_interface",
    "import": "engine_import",
    "script_check": "static_script_check",
    "headless_smoke": "headless_runtime",
    "export": "engine_export",
}
PLAYED_GAME_EVIDENCE = "graphical_playtest"


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _bounded(text: str, limit: int) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n[truncated after {limit} characters]"


def engine_series(version: str) -> str:
    parts = str(version).strip().split(".")
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else str(version).strip()


@dataclass(frozen=True)
class EngineHealth:
    healthy: bool
    executable: str | None
    version: str | None
    interface_qualified: bool
    version_supported: bool
    missing_flags: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class EngineRun:
    operation: str
    status: str
    exit_code: int | None
    duration_ms: int
    command: tuple[str, ...]
    command_digest: str
    evidence_kind: str
    stdout: str
    stderr: str
    detail: str

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    @property
    def summary(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "command_digest": self.command_digest,
            "evidence_kind": self.evidence_kind,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class BuildArtifact:
    project_digest: str
    source_commit: str
    engine_version: str
    template_id: str
    template_version: str
    preset: str
    artifact_path: str | None
    artifact_checksum: str | None
    artifact_bytes: int | None
    runs: tuple[EngineRun, ...]
    recorded_at: str
    graphical_playtest: bool = False

    @property
    def succeeded(self) -> bool:
        return bool(self.artifact_checksum) and all(run.succeeded for run in self.runs)

    @property
    def failure(self) -> EngineRun | None:
        return next((run for run in self.runs if not run.succeeded), None)

    @property
    def evidence_gap(self) -> tuple[str, ...]:
        """Evidence this build does not provide, stated instead of implied."""
        gaps: list[str] = []
        if not self.graphical_playtest:
            gaps.append(PLAYED_GAME_EVIDENCE)
        if not any(run.operation == "headless_smoke" and run.succeeded for run in self.runs):
            gaps.append("headless_runtime")
        return tuple(gaps)

    @property
    def manifest(self) -> dict[str, object]:
        return {
            "project_digest": self.project_digest,
            "source_commit": self.source_commit,
            "engine_version": self.engine_version,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "preset": self.preset,
            "artifact_path": self.artifact_path,
            "artifact_checksum": self.artifact_checksum,
            "artifact_bytes": self.artifact_bytes,
            "succeeded": self.succeeded,
            "graphical_playtest": self.graphical_playtest,
            "evidence_gap": list(self.evidence_gap),
            "recorded_at": self.recorded_at,
            "runs": [run.summary for run in self.runs],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.manifest).encode("utf-8")).hexdigest()


class GodotAdapter:
    """Runs a fixed set of Godot operations with no shell and no widenable flags."""

    def __init__(
        self,
        *,
        executable_candidates: Iterable[str] = ("godot", "godot4", "Godot"),
        executable_args: Iterable[str] = (),
        max_seconds: int = 120,
        max_output_chars: int = 100_000,
        probe_seconds: int = 15,
    ):
        self.executable_candidates = tuple(executable_candidates)
        self.executable_args = tuple(executable_args)
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
        environment.update({
            "NO_COLOR": "1", "TERM": "dumb", "GODOT_SILENCE_ROOT_WARNING": "1",
        })
        return environment

    def _execute(
        self, operation: str, arguments: Sequence[str], *, timeout: int,
    ) -> EngineRun:
        if operation not in OPERATIONS:
            raise ValueError(f"Unknown engine operation: {operation}")
        evidence = EVIDENCE_KINDS[operation]
        executable = self.executable()
        if executable is None:
            return EngineRun(
                operation, "unavailable", None, 0, (), "", evidence, "", "",
                "godot executable is not available",
            )
        command = (executable, *self.executable_args, *(str(value) for value in arguments))
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
            return EngineRun(
                operation, "timeout", None, elapsed, command, digest, evidence,
                _bounded(_text(exc.stdout), self.max_output_chars),
                _bounded(_text(exc.stderr), self.max_output_chars),
                f"engine exceeded {timeout}s",
            )
        except OSError as exc:
            elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return EngineRun(
                operation, "unavailable", None, elapsed, command, digest, evidence,
                "", "", f"{type(exc).__name__}: engine could not be started",
            )
        elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        stdout = _bounded(completed.stdout or "", self.max_output_chars)
        stderr = _bounded(completed.stderr or "", self.max_output_chars)
        status, detail = _classify(completed.returncode, stdout, stderr)
        return EngineRun(
            operation, status, completed.returncode, elapsed, command, digest,
            evidence, stdout, stderr, detail,
        )

    def health(self) -> EngineHealth:
        executable = self.executable()
        if executable is None:
            return EngineHealth(
                False, None, None, False, False, REQUIRED_FLAGS,
                "godot executable is not available",
            )
        version_run = self._execute("version_probe", ("--version",), timeout=self.probe_seconds)
        match = VERSION_PATTERN.search(f"{version_run.stdout}\n{version_run.stderr}")
        version = match.group(0) if version_run.exit_code == 0 and match else None
        help_run = self._execute("interface_probe", ("--help",), timeout=self.probe_seconds)
        help_text = f"{help_run.stdout}\n{help_run.stderr}"
        missing = tuple(flag for flag in REQUIRED_FLAGS if flag not in help_text)
        qualified = help_run.exit_code == 0 and not missing
        supported = bool(version) and engine_series(version) in SUPPORTED_ENGINE_VERSIONS
        healthy = bool(version) and qualified and supported
        if healthy:
            reason = "qualified"
        elif not version:
            reason = "engine version could not be identified"
        elif not qualified:
            reason = "engine interface is missing required flags"
        else:
            reason = f"engine {version} is outside the supported range"
        return EngineHealth(
            healthy, executable, version, qualified, supported, missing, reason,
        )

    @staticmethod
    def _project(project: Path) -> Path:
        root = Path(project).resolve()
        if not (root / "project.godot").is_file():
            raise FileNotFoundError(f"No Godot project at {root}")
        return root

    def import_project(self, project: Path, *, timeout: int | None = None) -> EngineRun:
        root = self._project(project)
        return self._execute(
            "import", ("--headless", "--path", str(root), "--import"),
            timeout=timeout or self.max_seconds,
        )

    def check_scripts(
        self, project: Path, scripts: Sequence[str], *, timeout: int | None = None,
    ) -> tuple[EngineRun, ...]:
        """Static parse check only. This never demonstrates that the game plays."""
        root = self._project(project)
        if not scripts:
            raise ValueError("A script check requires at least one script path")
        runs: list[EngineRun] = []
        for script in scripts:
            resource = script if str(script).startswith("res://") else f"res://{script}"
            runs.append(self._execute(
                "script_check",
                ("--headless", "--path", str(root), "--check-only", "--script", resource),
                timeout=timeout or self.max_seconds,
            ))
        return tuple(runs)

    def headless_smoke(
        self, project: Path, *, frames: int = 180, timeout: int | None = None,
    ) -> EngineRun:
        root = self._project(project)
        if frames <= 0:
            raise ValueError("A runtime smoke run requires a positive frame budget")
        return self._execute(
            "headless_smoke",
            ("--headless", "--path", str(root), "--quit-after", str(int(frames))),
            timeout=timeout or self.max_seconds,
        )

    def export(
        self, project: Path, *, preset: str, output: Path, timeout: int | None = None,
    ) -> EngineRun:
        root = self._project(project)
        declared = export_presets(root)
        if preset not in declared:
            return EngineRun(
                "export", "failed", None, 0, (), "", EVIDENCE_KINDS["export"], "", "",
                f"preset {preset!r} is not declared by the project; declared: "
                + (", ".join(declared) if declared else "none"),
            )
        destination = Path(output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        return self._execute(
            "export",
            (
                "--headless", "--path", str(root), "--export-release",
                preset, str(destination),
            ),
            timeout=timeout or self.max_seconds,
        )

    def build(
        self,
        project: Path,
        *,
        preset: str,
        output: Path,
        template_id: str,
        template_version: str,
        project_digest: str,
        scripts: Sequence[str],
        source_commit: str = "unknown",
        frames: int = 180,
    ) -> BuildArtifact:
        """Import, parse, run headless and export, stopping at the first failure."""
        root = self._project(project)
        health = self.health()
        runs: list[EngineRun] = []
        if not health.healthy:
            runs.append(EngineRun(
                "version_probe", "failed", None, 0, (), "",
                EVIDENCE_KINDS["version_probe"], "", "", health.reason,
            ))
            return _artifact(
                project_digest, source_commit, health.version or "unknown",
                template_id, template_version, preset, None, runs,
            )
        runs.append(self.import_project(root))
        if runs[-1].succeeded:
            for run in self.check_scripts(root, scripts):
                runs.append(run)
                if not run.succeeded:
                    break
        if all(run.succeeded for run in runs):
            runs.append(self.headless_smoke(root, frames=frames))
        if all(run.succeeded for run in runs):
            runs.append(self.export(root, preset=preset, output=output))
        artifact_path = Path(output).resolve()
        if all(run.succeeded for run in runs) and artifact_path.is_file():
            payload = artifact_path.read_bytes()
            return _artifact(
                project_digest, source_commit, health.version or "unknown",
                template_id, template_version, preset,
                (str(artifact_path), hashlib.sha256(payload).hexdigest(), len(payload)),
                runs,
            )
        if all(run.succeeded for run in runs):
            runs.append(EngineRun(
                "export", "failed", None, 0, (), "", EVIDENCE_KINDS["export"], "", "",
                "the engine reported success but produced no artifact file",
            ))
        return _artifact(
            project_digest, source_commit, health.version or "unknown",
            template_id, template_version, preset, None, runs,
        )


def _artifact(
    project_digest: str,
    source_commit: str,
    engine_version: str,
    template_id: str,
    template_version: str,
    preset: str,
    payload: tuple[str, str, int] | None,
    runs: Sequence[EngineRun],
) -> BuildArtifact:
    path, checksum, size = payload if payload else (None, None, None)
    return BuildArtifact(
        project_digest, source_commit, engine_version, template_id,
        template_version, preset, path, checksum, size, tuple(runs), _stamp(),
    )


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _classify(returncode: int | None, stdout: str, stderr: str) -> tuple[str, str]:
    combined = f"{stdout}\n{stderr}"
    crash = next((marker for marker in CRASH_MARKERS if marker in combined), None)
    if crash:
        return "failed", f"engine crashed: {crash}"
    if returncode != 0:
        return "failed", f"engine exited with code {returncode}"
    marker = next(
        (value for value in ERROR_MARKERS if value.casefold() in combined.casefold()),
        None,
    )
    if marker:
        return "failed", f"engine reported an error: {marker}"
    return "succeeded", "completed"
