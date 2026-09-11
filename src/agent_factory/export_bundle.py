"""Portable export packaging, with sharing as a separate, explicit decision.

Exporting a build and publishing it are two different acts. This module packages
a verified version for a supported target - with attribution, checksums and
launch instructions, and without secrets or local paths - and stops there.
Publication needs its own preview, its own named approver and its own call; a
development authorisation never grants it, and a cancelled share performs no
external action at all.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

BUNDLE_MANIFEST = "lokvetia-bundle.json"
LAUNCH_FILE = "LAUNCH.md"
ATTRIBUTION_FILE = "ATTRIBUTIONS.md"
MAX_SCAN_BYTES = 4 * 1024 * 1024
VISIBILITIES = ("private-link", "unlisted", "public")
SHARE_OUTCOMES = ("published", "cancelled", "refused")

DEFAULT_EXCLUDES = (
    ".git/*", ".git", ".lokvetia/*", ".venv/*", "__pycache__/*", "*.pyc",
    "*.db", "*.sqlite", "*.sqlite3", ".env", "*.env", "*.key", "*.pem", "*.pfx",
    "id_rsa*", "*.log", "export_presets.cfg", ".DS_Store", "Thumbs.db",
    "*.lokvetia-tmp",
)


class ExportRefused(PermissionError):
    """Raised when a package must not be built or shared."""


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class ExportTarget:
    target_id: str
    platform: str
    supported: bool
    launch: str
    reason: str = ""


TARGETS: Mapping[str, ExportTarget] = {
    target.target_id: target
    for target in (
        ExportTarget(
            "linux-x86_64", "Linux", True,
            "Make the game file executable (`chmod +x`) and run it from a terminal "
            "or your file manager.",
        ),
        ExportTarget(
            "windows-x86_64", "Windows", True,
            "Unzip the whole folder, then double-click the game's .exe file. Keep "
            "the files together.",
        ),
        ExportTarget(
            "portable-zip", "Any desktop", True,
            "Unzip the folder and run the game file for your operating system.",
        ),
        ExportTarget(
            "ios", "iOS", False, "",
            "iOS distribution needs an Apple developer account and a signed build "
            "that this project cannot produce; it is not offered.",
        ),
        ExportTarget(
            "console", "Console", False, "",
            "Console targets require a platform partner agreement and a qualified "
            "toolchain; they stay unavailable until that is recorded.",
        ),
        ExportTarget(
            "web", "Browser", False, "",
            "A browser export needs its own engine template and qualification run; "
            "it is not qualified yet.",
        ),
    )
}


# ------------------------------------------------------------ secret scanning

@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    sample: str


_SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}")),
    (
        "credential assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|password|passwd|token|client[_-]?secret)\b"
            r"\s*[:=]\s*[\"']?[A-Za-z0-9/+=_\-]{8,}"
        ),
    ),
)
_PATH_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("local home path", re.compile(r"(?i)[/\\](?:home|users)[/\\][A-Za-z0-9._\-]{2,}[/\\]")),
)


def scan_payload(path: str, payload: bytes) -> tuple[Finding, ...]:
    """Look for secrets and local paths in one file, bounded and non-executing."""
    window = payload[:MAX_SCAN_BYTES]
    try:
        text = window.decode("utf-8")
    except UnicodeDecodeError:
        text = window.decode("latin-1", errors="ignore")
    findings: list[Finding] = []
    for rule, pattern in (*_SECRET_RULES, *_PATH_RULES):
        match = pattern.search(text)
        if match:
            sample = match.group(0)
            findings.append(Finding(path, rule, _mask(sample)))
    return tuple(findings)


def _mask(sample: str) -> str:
    trimmed = sample.strip()[:64]
    if len(trimmed) <= 12:
        return trimmed[:4] + "..."
    return trimmed[:8] + "..." + trimmed[-4:]


def excluded(path: str, patterns: Sequence[str]) -> str:
    normalised = path.replace("\\", "/")
    for pattern in patterns:
        if fnmatch.fnmatch(normalised, pattern) or fnmatch.fnmatch(
            Path(normalised).name, pattern
        ):
            return pattern
        if pattern.endswith("/*") and normalised.startswith(pattern[:-1]):
            return pattern
    return ""


# ------------------------------------------------------------------ preflight

@dataclass(frozen=True)
class ExportPreflight:
    target: ExportTarget
    project_root: str
    included: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]
    findings: tuple[Finding, ...]
    refusals: tuple[str, ...]
    attributions: tuple[Mapping[str, str], ...]
    version_digest: str
    source_commit: str

    @property
    def allowed(self) -> bool:
        return not self.refusals and not self.findings

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical({
            "target": self.target.target_id,
            "included": list(self.included),
            "version_digest": self.version_digest,
        }).encode("utf-8")).hexdigest()

    def preview(self) -> dict[str, Any]:
        return {
            "target": self.target.target_id,
            "platform": self.target.platform,
            "supported": self.target.supported,
            "allowed": self.allowed,
            "preflight_digest": self.digest,
            "included": list(self.included),
            "skipped": [{"path": path, "rule": rule} for path, rule in self.skipped],
            "findings": [
                {"path": item.path, "rule": item.rule, "sample": item.sample}
                for item in self.findings
            ],
            "refusals": list(self.refusals),
            "attributions": [dict(item) for item in self.attributions],
        }


@dataclass(frozen=True)
class ExportBundle:
    path: str
    checksum: str
    size_bytes: int
    target_id: str
    version_digest: str
    source_commit: str
    manifest: Mapping[str, Any]
    recorded_at: str


class ExportBundler:
    """Packages one verified version for one supported target, or refuses."""

    def __init__(
        self,
        project_root: Path,
        *,
        excludes: Sequence[str] = DEFAULT_EXCLUDES,
    ):
        self.project_root = Path(project_root)
        self.excludes = tuple(excludes)

    def preflight(
        self,
        *,
        target_id: str,
        version: Any,
        artifact: Path,
        rights: Any = None,
        attributions: Sequence[Mapping[str, str]] = (),
        extra_excludes: Sequence[str] = (),
    ) -> ExportPreflight:
        """Decide before building. An unsupported target is explained, not attempted."""
        target = TARGETS.get(str(target_id))
        refusals: list[str] = []
        if target is None:
            raise KeyError(f"Unknown export target: {target_id}")
        if not target.supported:
            refusals.append(target.reason)
        artifact_path = Path(artifact)
        if not artifact_path.is_file():
            refusals.append("the recorded build artifact is not on disk")
        elif getattr(version, "artifact_checksum", None):
            payload = artifact_path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != version.artifact_checksum:
                refusals.append(
                    "the artifact on disk does not match the verified version"
                )
        if rights is not None and not getattr(rights, "allowed", False):
            for name, reason in getattr(rights, "blocking", ()):
                refusals.append(f"{name}: {reason}")
        patterns = (*self.excludes, *extra_excludes)
        included: list[str] = []
        skipped: list[tuple[str, str]] = []
        findings: list[Finding] = []
        if target.supported and not refusals:
            for path in sorted(self._project_files()):
                rule = excluded(path, patterns)
                if rule:
                    skipped.append((path, rule))
                    continue
                included.append(path)
                findings.extend(
                    scan_payload(path, (self.project_root / path).read_bytes())
                )
            findings.extend(scan_payload(artifact_path.name, artifact_path.read_bytes()))
        return ExportPreflight(
            target, str(self.project_root), tuple(included), tuple(skipped),
            tuple(findings), tuple(refusals), tuple(dict(item) for item in attributions),
            str(getattr(version, "version_digest", "")),
            str(getattr(version, "source_commit", "")),
        )

    def _project_files(self) -> list[str]:
        if not self.project_root.is_dir():
            return []
        return [
            str(item.relative_to(self.project_root)).replace("\\", "/")
            for item in self.project_root.rglob("*")
            if item.is_file() and not item.is_symlink()
        ]

    def build(
        self,
        preflight: ExportPreflight,
        *,
        artifact: Path,
        output: Path,
        version: Any,
        game_name: str = "Game",
    ) -> ExportBundle:
        if not preflight.allowed:
            raise ExportRefused(
                "; ".join(preflight.refusals) or
                "the package contains secrets or local paths: "
                + ", ".join(sorted({item.rule for item in preflight.findings}))
            )
        artifact_path = Path(artifact)
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema": 1,
            "bundle_kind": "playable-export",
            "game_name": str(game_name)[:120],
            "target": preflight.target.target_id,
            "platform": preflight.target.platform,
            "version_digest": preflight.version_digest,
            "source_commit": preflight.source_commit,
            "engine": str(getattr(version, "engine", "")),
            "engine_version": str(getattr(version, "engine_version", "")),
            "artifact_name": artifact_path.name,
            "artifact_checksum": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            "files": list(preflight.included),
            "attributions": [dict(item) for item in preflight.attributions],
            "built_at": _stamp(),
            "published": False,
        }
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(
                BUNDLE_MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            )
            bundle.writestr(LAUNCH_FILE, _launch_text(manifest, preflight.target))
            bundle.writestr(ATTRIBUTION_FILE, _attribution_text(preflight.attributions))
            bundle.write(artifact_path, f"game/{artifact_path.name}")
            for path in preflight.included:
                bundle.write(self.project_root / path, f"source/{path}")
        payload = destination.read_bytes()
        return ExportBundle(
            str(destination), hashlib.sha256(payload).hexdigest(), len(payload),
            preflight.target.target_id, preflight.version_digest,
            preflight.source_commit, manifest, _stamp(),
        )


def _launch_text(manifest: Mapping[str, Any], target: ExportTarget) -> str:
    return (
        f"# {manifest['game_name']}\n\n"
        f"Built for {target.platform} ({target.target_id}) from commit "
        f"{manifest['source_commit']}.\n\n"
        "## How to play\n\n"
        f"1. {target.launch}\n"
        "2. The game file is in the `game/` folder of this package.\n\n"
        "## What is in this package\n\n"
        "- `game/` - the built game.\n"
        "- `source/` - the project files this build came from.\n"
        f"- `{ATTRIBUTION_FILE}` - credits required by the assets used.\n"
        f"- `{BUNDLE_MANIFEST}` - version, checksums and build details.\n\n"
        "## Verify this package\n\n"
        f"The game file's SHA-256 is `{manifest['artifact_checksum']}`.\n"
    )


def _attribution_text(attributions: Sequence[Mapping[str, str]]) -> str:
    if not attributions:
        return (
            "# Attributions\n\nThis package uses no assets that require "
            "attribution.\n"
        )
    lines = ["# Attributions", ""]
    for item in attributions:
        name = item.get("asset", "asset")
        licence = item.get("licence_id", "")
        credit = item.get("attribution", "")
        source = item.get("source", "")
        lines.append(f"- **{name}** - {credit} ({licence})" + (f", {source}" if source else ""))
    return "\n".join(lines) + "\n"


def attributions_from_library(library: Any) -> tuple[dict[str, str], ...]:
    """Collect the credits an asset library says are required."""
    records: list[dict[str, str]] = []
    for name in sorted(library.assets()):
        provenance = library.provenance(name)
        if provenance.licence.attribution_required and provenance.attribution:
            records.append({
                "asset": name,
                "licence_id": provenance.licence_id,
                "attribution": provenance.attribution,
                "source": provenance.source,
            })
    return tuple(records)


# ---------------------------------------------------------------------- share

@dataclass(frozen=True)
class SharePreview:
    bundle_checksum: str
    destination: str
    visibility: str
    allowed: bool
    reason: str
    requires: tuple[str, ...]

    @property
    def record(self) -> dict[str, Any]:
        return {
            "bundle_checksum": self.bundle_checksum,
            "destination": self.destination,
            "visibility": self.visibility,
            "allowed": self.allowed,
            "reason": self.reason,
            "requires": list(self.requires),
            "performed": False,
        }


@dataclass(frozen=True)
class ShareDecision:
    outcome: str
    bundle_checksum: str
    destination: str
    visibility: str
    external_state_changed: bool
    reason: str
    actor: str
    recorded_at: str

    @property
    def record(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "bundle_checksum": self.bundle_checksum,
            "destination": self.destination,
            "visibility": self.visibility,
            "external_state_changed": self.external_state_changed,
            "reason": self.reason,
            "actor": self.actor,
            "recorded_at": self.recorded_at,
        }


class ShareGate:
    """Publication is its own decision. Development access never implies it."""

    def __init__(self, *, publisher: Callable[[ExportBundle, str, str], str] | None = None):
        self.publisher = publisher

    def prepare(
        self,
        bundle: ExportBundle,
        *,
        destination: str,
        visibility: str,
        rights: Any = None,
    ) -> SharePreview:
        if visibility not in VISIBILITIES:
            raise ValueError(f"Unknown visibility: {visibility!r}")
        target = str(destination).strip()
        requires = ["a named human approver", "an explicit publish decision"]
        if not target:
            return SharePreview(
                bundle.checksum, "", visibility, False,
                "a publication destination is required", tuple(requires),
            )
        if rights is not None and not getattr(rights, "allowed", False):
            blocking = ", ".join(name for name, _ in getattr(rights, "blocking", ()))
            return SharePreview(
                bundle.checksum, target, visibility, False,
                f"assets without export rights block publication: {blocking}",
                tuple(requires),
            )
        if self.publisher is None:
            requires.append("a configured publisher; none is connected")
        return SharePreview(
            bundle.checksum, target, visibility, True,
            "ready for an explicit publish decision", tuple(requires),
        )

    def decide(
        self,
        preview: SharePreview,
        *,
        decision: str,
        actor: str,
        bundle: ExportBundle | None = None,
    ) -> ShareDecision:
        if decision not in {"approve", "cancel"}:
            raise ValueError("A share decision is either 'approve' or 'cancel'")
        if decision == "cancel":
            return ShareDecision(
                "cancelled", preview.bundle_checksum, preview.destination,
                preview.visibility, False,
                "cancelled before any external call was made", str(actor).strip(),
                _stamp(),
            )
        if not str(actor).strip():
            raise ValueError("Publication requires a named human approver")
        if not preview.allowed:
            return ShareDecision(
                "refused", preview.bundle_checksum, preview.destination,
                preview.visibility, False, preview.reason, str(actor).strip(), _stamp(),
            )
        if self.publisher is None or bundle is None:
            return ShareDecision(
                "refused", preview.bundle_checksum, preview.destination,
                preview.visibility, False,
                "no publisher is connected; nothing was published",
                str(actor).strip(), _stamp(),
            )
        if bundle.checksum != preview.bundle_checksum:
            raise ExportRefused("The reviewed package is not the one being published")
        located = self.publisher(bundle, preview.destination, preview.visibility)
        return ShareDecision(
            "published", preview.bundle_checksum, preview.destination,
            preview.visibility, True, f"published to {located}",
            str(actor).strip(), _stamp(),
        )


def load_bundle(path: Path) -> ExportBundle:
    """Read a built package back, so sharing works on the file, not on memory."""
    bundle_path = Path(path)
    if not zipfile.is_zipfile(bundle_path):
        raise ExportRefused(f"{bundle_path} is not a Lokvetia package")
    with zipfile.ZipFile(bundle_path) as archive:
        if BUNDLE_MANIFEST not in archive.namelist():
            raise ExportRefused("the package has no Lokvetia manifest")
        manifest = json.loads(archive.read(BUNDLE_MANIFEST).decode("utf-8"))
    payload = bundle_path.read_bytes()
    return ExportBundle(
        str(bundle_path), hashlib.sha256(payload).hexdigest(), len(payload),
        str(manifest.get("target", "")), str(manifest.get("version_digest", "")),
        str(manifest.get("source_commit", "")), manifest,
        str(manifest.get("built_at", "")),
    )
