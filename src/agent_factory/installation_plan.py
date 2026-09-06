"""Pure, bounded installation proposals. No download, consent issuer or execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from importlib.resources import files
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_MAX_BYTES = 2**50


def _text(value: Any, name: str, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"Invalid {name}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"Invalid {name}")
    return value


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid package identifier")
    return value


def _size(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_BYTES:
        raise ValueError(f"Invalid {name}")
    return value


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError("Invalid SHA-256")
    return value


def _url(value: Any) -> str:
    value = _text(value, "source URL", 1000)
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.port
            or "\\" in value or any(char.isspace() for char in value)):
        raise ValueError("Expected a fixed public HTTPS source")
    return value


def _path(value: Any) -> str:
    value = _text(value, "relative target", 200)
    reserved = {"con", "prn", "aux", "nul"} | {f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)}
    if any(not _ID.fullmatch(part) or part in {".", ".."} or part.endswith(".")
           or part.split(".")[0] in reserved
           for part in value.split("/")):
        raise ValueError("Target must be a bounded relative workspace path")
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def validate_catalog(catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Validate structure; publisher trust still comes from reviewed host code."""
    if not isinstance(catalog, Mapping) or set(catalog) != {
        "schema_version", "revision", "reviewed_on", "packages"
    }:
        raise ValueError("Invalid catalogue fields")
    if type(catalog["schema_version"]) is not int or catalog["schema_version"] != 1:
        raise ValueError("Unsupported catalogue schema")
    _text(catalog["revision"], "catalogue revision", 80)
    reviewed_on = _text(catalog["reviewed_on"], "review date", 10)
    if date.fromisoformat(reviewed_on).isoformat() != reviewed_on:
        raise ValueError("Expected ISO review date")
    packages = catalog["packages"]
    if not isinstance(packages, dict) or not 1 <= len(packages) <= 64:
        raise ValueError("Expected 1 to 64 catalogue packages")
    if any(not isinstance(package, dict) for package in packages.values()):
        raise ValueError("Invalid package record")
    required = {"version", "platform", "url", "sha256", "download_bytes",
                "extraction_budget_bytes", "target", "requires_admin", "dependencies",
                "license", "license_url", "license_step", "source_evidence"}
    targets = []
    for key, package in packages.items():
        _identifier(key)
        if not isinstance(package, dict) or set(package) != required:
            raise ValueError("Invalid package fields")
        _identifier(package["version"])
        if not package["version"][0].isdigit():
            raise ValueError("Expected a pinned numeric release version")
        _identifier(package["platform"])
        _url(package["url"])
        _url(package["license_url"])
        _url(package["source_evidence"])
        _sha(package["sha256"])
        _size(package["download_bytes"], "download size")
        _size(package["extraction_budget_bytes"], "extraction budget")
        if not package["download_bytes"] or not package["extraction_budget_bytes"]:
            raise ValueError("Package sizes must be positive")
        target = _path(package["target"])
        if any(target == old or target.startswith(old + "/") or old.startswith(target + "/")
               for old in targets):
            raise ValueError("Package targets overlap")
        targets.append(target)
        if type(package["requires_admin"]) is not bool:
            raise ValueError("Invalid privilege requirement")
        _text(package["license"], "license", 100)
        if package["license_step"] not in {"preserve_notices", "manual_acceptance"}:
            raise ValueError("Invalid licensing step")
        dependencies = package["dependencies"]
        if not isinstance(dependencies, dict) or len(dependencies) > 16:
            raise ValueError("Invalid dependencies")
        for dependency, version in dependencies.items():
            _identifier(dependency)
            _identifier(version)
            if dependency not in packages or packages[dependency].get("version") != version:
                raise ValueError("Missing or conflicting locked dependency")
    # Validate even unused packages: an invalid catalogue must not become trusted.
    _ordered(packages, sorted(packages))
    return json.loads(_canonical(catalog))


def _ordered(packages: Mapping[str, Any], requested: Sequence[str]) -> list[str]:
    visited: set[str] = set()
    visiting: set[str] = set()
    result: list[str] = []

    def visit(key: str) -> None:
        if key in visiting:
            raise ValueError("Dependency cycle")
        if key in visited:
            return
        if key not in packages:
            raise ValueError("Package is not in the reviewed catalogue")
        visiting.add(key)
        for dependency in sorted(packages[key]["dependencies"]):
            visit(dependency)
        visiting.remove(key)
        visited.add(key)
        result.append(key)

    for key in sorted(set(requested)):
        visit(key)
    return result


def load_catalog() -> dict[str, Any]:
    return validate_catalog(json.loads(files("agent_factory").joinpath(
        "defaults/installation-catalog.json").read_text(encoding="utf-8")))


@dataclass(frozen=True)
class InstallationPlan:
    """Immutable proposal snapshot. Its digest proves content, never consent."""

    _json: str

    @property
    def digest(self) -> str:
        return hashlib.sha256(self._json.encode("utf-8")).hexdigest()

    def document(self) -> dict[str, Any]:
        return json.loads(self._json)

    def require_same_reviewed_content(self, reviewed_digest: str) -> None:
        """Use only after independently authenticating/persisting the decision."""
        if _sha(reviewed_digest) != self.digest:
            raise ValueError("Installation plan changed; a new decision is required")


def build_plan(
    requested: Sequence[str], *, context: Mapping[str, str], platform: str,
    inventory: Mapping[str, Mapping[str, Any]] | None = None,
    cached_sha256: Sequence[str] = (), updates: Sequence[str] = (),
    offline: bool = False, admin_available: bool = False,
    free_bytes: int | None = None, catalog: Mapping[str, Any] | None = None,
) -> InstallationPlan:
    """Create a proposal from caller observations; none are execution evidence.

    Inventory hashes describe original archive provenance, not current installed
    file integrity. A future installer must re-probe and enforce all constraints.
    """
    catalog = load_catalog() if catalog is None else validate_catalog(catalog)
    if not isinstance(context, Mapping) or set(context) != {"tenant", "project", "host", "workspace"}:
        raise ValueError("Expected tenant, project, host and workspace context")
    context = {key: _text(value, key, 120) for key, value in context.items()}
    _identifier(platform)
    for collection in (requested, updates, cached_sha256):
        if not isinstance(collection, (list, tuple)) or len(collection) > 64:
            raise ValueError("Expected a bounded list")
    if not requested:
        raise ValueError("Select at least one package")
    for key in (*requested, *updates):
        _identifier(key)
    cache = {_sha(value) for value in cached_sha256}
    if type(offline) is not bool or type(admin_available) is not bool:
        raise ValueError("Invalid environment flags")
    if free_bytes is not None:
        _size(free_bytes, "available disk space")
    inventory = {} if inventory is None else inventory
    if not isinstance(inventory, Mapping) or len(inventory) > 64:
        raise ValueError("Invalid inventory")
    for key, observed in inventory.items():
        _identifier(key)
        if not isinstance(observed, Mapping) or set(observed) != {"version", "sha256", "target", "managed"}:
            raise ValueError("Invalid installed package observation")
        _identifier(observed["version"])
        _sha(observed["sha256"])
        # An opaque location label, never an executable path from the caller.
        _text(observed["target"], "observed location", 200)
        if type(observed["managed"]) is not bool:
            raise ValueError("Invalid installation ownership")
    ordered = _ordered(catalog["packages"], requested)
    if not set(updates) <= set(ordered):
        raise ValueError("Update request is outside the selected dependency closure")
    steps = []
    required_bytes = 0
    download_bytes = 0

    def location(value: str) -> str:
        # Comparison only. These caller labels are never resolved or executed.
        value = value.replace("\\", "/").rstrip("/")
        return value.casefold() if platform.startswith("windows-") else value

    for key in ordered:
        package = catalog["packages"][key]
        old = inventory.get(key)
        exact = bool(old and old["version"] == package["version"] and old["sha256"] == package["sha256"])
        action = "install"
        if exact:
            action = "already_installed" if location(old["target"]) == location(package["target"]) else "reuse"
        elif old and old["managed"] and key in updates:
            action = "update"
        reasons = []
        mutate = action in {"install", "update"}
        cached = package["sha256"] in cache
        if package["platform"] != platform:
            reasons.append("unsupported_platform")
        if mutate:
            target = location(package["target"])
            occupied = [location(observation["target"]) for observation in inventory.values()]
            if any(target == path or target.startswith(path + "/") or path.startswith(target + "/")
                   for path in occupied):
                reasons.append("target_conflict")
            if package["requires_admin"] and not admin_available:
                reasons.append("administrator_unavailable")
            if offline and not cached:
                reasons.append("offline_archive_missing")
            if package["license_step"] == "manual_acceptance":
                reasons.append("license_acceptance_required")
        if any(step["action"] == "manual_action" and step["package"] in package["dependencies"]
               for step in steps):
            reasons.append("dependency_needs_action")
        transfer = package["download_bytes"] if mutate and not cached else 0
        space = (package["extraction_budget_bytes"] + transfer) if mutate else 0
        required_bytes += space
        download_bytes += transfer
        permissions = (["write_workspace"] + (["network"] if transfer else [])
                       + (["administrator"] if package["requires_admin"] else [])) if mutate else []
        steps.append({"package": key, **package, "proposed_action": action,
                      "action": "manual_action" if reasons else action, "reasons": reasons,
                      "permissions": permissions, "archive_reported_cached": cached,
                      "observation": dict(old) if old else None,
                      "download_required_bytes": transfer, "disk_budget_bytes": space,
                      "preserve_existing_installations": True})
    issues = []
    if required_bytes and free_bytes is None:
        issues.append("available_disk_space_unknown")
    elif free_bytes is not None and free_bytes < required_bytes:
        issues.append("insufficient_disk_budget")
    document = {"schema_version": 1, "context": context, "platform": platform,
                "catalog_revision": catalog["revision"], "catalog_reviewed_on": catalog["reviewed_on"],
                "requested": sorted(set(requested)), "updates": sorted(set(updates)),
                "offline": offline, "admin_available": admin_available, "free_bytes": free_bytes,
                "steps": steps, "download_required_bytes": download_bytes,
                "disk_budget_bytes": required_bytes, "disk_budget_is_measured_size": False,
                "issues": issues, "requires_manual_action": bool(issues or any(s["reasons"] for s in steps)),
                "observation_trust": "caller_reported_planning_only", "execution_eligible": False}
    return InstallationPlan(_canonical(document))


def changed_fields(before: InstallationPlan, after: InstallationPlan) -> list[str]:
    """Show exactly which displayed fields invalidate an earlier content review."""
    changes = []

    def compare(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() | right.keys()):
                next_path = f"{path}.{key}" if path else key
                if key not in left or key not in right:
                    changes.append(next_path)
                else:
                    compare(left[key], right[key], next_path)
        elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
            for index, (a, b) in enumerate(zip(left, right)):
                compare(a, b, f"{path}[{index}]")
        elif type(left) is not type(right) or left != right:
            changes.append(path)

    compare(before.document(), after.document(), "")
    return changes
