from __future__ import annotations

import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Check:
    component: str
    status: str
    detail: str
    requirement: str


REQUIRED = {"Git", "Python"}
COMMANDS: dict[str, tuple[str, ...]] = {
    "Git": ("git",),
    "GitHub CLI": ("gh",),
    "uv": ("uv",),
    "Node.js": ("node",),
    "npm": ("npm.cmd", "npm"),
    "Docker": ("docker",),
    "WSL": ("wsl.exe", "wsl"),
    "Codex CLI": (
        "%USERPROFILE%\\.codex\\plugins\\.plugin-appserver\\codex.exe",
        "%USERPROFILE%\\.codex\\.sandbox-bin\\codex.exe",
        "codex.exe",
        "codex",
    ),
    "Claude Code": (
        "%USERPROFILE%\\.local\\bin\\claude.exe",
        "%APPDATA%\\npm\\claude.cmd",
        "claude.exe",
        "claude",
    ),
    "Gemini CLI": ("%APPDATA%\\npm\\gemini.cmd", "gemini.cmd", "gemini"),
    "Antigravity CLI": (
        "%LOCALAPPDATA%\\agy\\bin\\agy.exe",
        "%LOCALAPPDATA%\\antigravity\\staging\\agy.exe",
        "~/.local/bin/agy",
        "agy.exe",
        "agy",
    ),
    "Ollama": (
        "%LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe",
        "ollama.exe",
        "ollama",
    ),
    "OpenClaw": ("%APPDATA%\\npm\\openclaw.cmd", "openclaw.cmd", "openclaw"),
}


def _resolve(candidates: tuple[str, ...]) -> str | None:
    for raw in candidates:
        expanded = os.path.expandvars(os.path.expanduser(raw))
        candidate = Path(expanded)
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
        if candidate.parent == Path("."):
            resolved = shutil.which(expanded)
            if resolved:
                return resolved
    return None


def checks() -> list[Check]:
    discovered = {name: _resolve(candidates) for name, candidates in COMMANDS.items()}
    discovered["Python"] = sys.executable
    try:
        import pip  # noqa: F401

        discovered["pip"] = f"{sys.executable} -m pip"
    except ImportError:
        discovered["pip"] = None
    return [
        Check(
            name,
            "ready" if path else "missing",
            path or "not found",
            "required" if name in REQUIRED else "optional",
        )
        for name, path in discovered.items()
    ]


def as_json() -> list[dict]:
    return [asdict(item) for item in checks()]
