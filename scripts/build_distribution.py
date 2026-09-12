#!/usr/bin/env python3
"""Build the files a person downloads, and describe exactly what they are.

The output is a directory holding the wheel, the source archive, and a
`distribution.json` that states each file's size and SHA-256, the Python the
release needs, and the operating systems it was actually tried on.

A platform is listed as tried only when this script was run there and the
installed command answered. Passing --tried-on for a system you did not test on
is the one way to make this file lie, so the flag exists but the default is
nothing.

The checksums prove a download did not change on the way. They prove nothing
about who published it: signing belongs to `agent_factory.application_update`,
which needs a trust root this script does not invent.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_factory.distribution import (  # noqa: E402
    build_release,
    tried_platforms,
    write_manifest,
)
from agent_factory.localisation import Message  # noqa: E402


def run(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, check=False, timeout=1800,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command)} failed with {result.returncode}\n{result.stderr}"
        )
    return result.stdout.strip()


def current_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def build(destination: Path) -> list[Path]:
    """Build the wheel and the source archive into a clean directory."""
    destination.mkdir(parents=True, exist_ok=True)
    for existing in destination.glob("*"):
        if existing.is_file():
            existing.unlink()
    run([sys.executable, "-m", "build", "--outdir", str(destination)], cwd=ROOT)
    return sorted(destination.glob("*"))


def prove_it_installs(wheel: Path) -> str:
    """Install the wheel into a clean environment and ask it its version.

    A release nobody installed is not a release. This is what lets the manifest
    say the current system was tried, and it is the only thing that does.
    """
    with tempfile.TemporaryDirectory() as folder:
        environment = Path(folder) / "venv"
        run([sys.executable, "-m", "venv", str(environment)])
        binaries = environment / ("Scripts" if sys.platform.startswith("win") else "bin")
        python = binaries / ("python.exe" if sys.platform.startswith("win") else "python")
        run([str(python), "-m", "pip", "install", "--quiet", str(wheel)])
        return run([str(binaries / "lokvetia"), "--version"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--version", default="",
        help="Release version; defaults to what the built wheel reports.",
    )
    parser.add_argument(
        "--tried-on", action="append", default=[],
        choices=("windows", "macos", "linux"),
        help="A system this release was actually tried on. The build machine is "
             "added automatically when the installed command answers.",
    )
    parser.add_argument(
        "--skip-install-check", action="store_true",
        help="Build without installing the wheel. The build machine is then NOT "
             "listed as tried.",
    )
    parser.add_argument("--notes-uk", default="")
    parser.add_argument("--notes-en", default="")
    arguments = parser.parse_args(argv)

    if shutil.which("git") and (ROOT / ".git").exists():
        revision = run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT)
    else:
        revision = "unknown"

    files = build(arguments.out)
    wheels = [path for path in files if path.suffix == ".whl"]
    if not wheels:
        raise SystemExit("The build produced no wheel")

    reported = ""
    if not arguments.skip_install_check:
        reported = prove_it_installs(wheels[0])
    tried = tried_platforms(
        arguments.tried_on,
        install_checked=bool(reported),
        here=current_platform(),
    )

    version = arguments.version or wheels[0].name.split("-")[1]
    notes = None
    if arguments.notes_uk and arguments.notes_en:
        notes = Message(arguments.notes_uk, arguments.notes_en)

    release = build_release(
        version, files, tried_on=tried, notes=notes,
    )
    manifest = write_manifest(release, arguments.out / "distribution.json")
    print(json.dumps({
        "version": release.version,
        "revision": revision,
        "manifest": str(manifest),
        "files": [item.record() for item in release.artifacts],
        "tried_on": list(release.tried_on),
        "installed_command_reported": reported,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
