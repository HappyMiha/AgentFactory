from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_DIR = PACKAGE_DIR / "defaults"
WORKSPACE = Path(os.environ.get("AGENT_FACTORY_WORKSPACE", Path.cwd())).expanduser().resolve()
ROOT = WORKSPACE  # Backwards-compatible alias for integrations using the original API.
STATE_DIR = WORKSPACE / ".agent-factory"
STATE_CONFIG_DIR = STATE_DIR / "config"


def _explicit_config_dir() -> Path | None:
    raw = os.environ.get("AGENT_FACTORY_CONFIG_DIR")
    return Path(raw).expanduser().resolve() if raw else None


def _names(name: str | Path) -> tuple[str, ...]:
    path = Path(name)
    stem = path.stem if path.suffix.lower() in {".json", ".yaml", ".yml"} else path.name
    requested = path.name if path.suffix else f"{stem}.json"
    return tuple(dict.fromkeys((requested, f"{stem}.json", f"{stem}.yaml", f"{stem}.yml")))


def config_path(name: str | Path) -> Path:
    """Resolve a configuration file from overrides, workspace state, or package defaults.

    ``AGENT_FACTORY_CONFIG_DIR`` has highest priority. A per-workspace state
    override created by the CLI is next, followed by a checked-in ``config``
    directory and the immutable defaults shipped with the package. JSON and
    JSON-compatible YAML filenames are accepted without adding a YAML parser.
    """

    directories = [
        _explicit_config_dir(),
        STATE_CONFIG_DIR,
        WORKSPACE / "config",
        DEFAULT_CONFIG_DIR,
    ]
    for directory in directories:
        if directory is None:
            continue
        for filename in _names(name):
            candidate = directory / filename
            if candidate.is_file():
                return candidate
    searched = ", ".join(str(path) for path in directories if path is not None)
    raise RuntimeError(f"Configuration {name!s} is unavailable in: {searched}")


def writable_config_path(name: str | Path) -> Path:
    """Return a writable override, materializing the effective default once."""

    stem = Path(name).stem if Path(name).suffix else Path(name).name
    directory = _explicit_config_dir() or STATE_CONFIG_DIR
    target = directory / f"{stem}.json"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        save_yaml(target, load_yaml(config_path(name)))
    return target


def load_yaml(path: Path | str) -> Any:
    """Load JSON or JSON-compatible YAML without a third-party dependency."""

    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save_yaml(path: Path | str, value: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


CONFIG_DIR = _explicit_config_dir() or (
    STATE_CONFIG_DIR if STATE_CONFIG_DIR.is_dir() else WORKSPACE / "config"
)
if not CONFIG_DIR.is_dir():
    CONFIG_DIR = DEFAULT_CONFIG_DIR
