"""Capability probe for the Windows AppContainer sandbox backend.

Exercises the OS boundary that `agent_factory.windows_sandbox` applies and reports
what Windows actually enforced on this host: which writes land, which reads and
network attempts are refused, and whether the process tree dies on job close,
timeout and a force-killed controlling process.

A passing report is an input to qualification, never the qualification itself.
Run: python scripts/windows_appcontainer_probe.py [--report PATH]
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_factory.windows_sandbox import (  # noqa: E402
    WAIT_TIMEOUT,
    apply_ace,
    container_name,
    container_sid,
    kernel32,
    sid_string,
    spawn_contained,
)

SYSTEM32 = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32"
SHELL = str(SYSTEM32 / "cmd.exe")
CURL = str(SYSTEM32 / "curl.exe")


def _discard(path: Path) -> None:
    """A just-terminated child can still hold its inherited output handle."""
    for _ in range(20):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.1)


def launch(command, *, timeout: float, hold_open: bool = False, **kwargs):
    """Run one command in the container and collect its bounded output."""
    out_file = tempfile.NamedTemporaryFile(suffix=".out", delete=False)
    err_file = tempfile.NamedTemporaryFile(suffix=".err", delete=False)
    out_path, err_path = Path(out_file.name), Path(err_file.name)
    job, information = spawn_contained(
        command, streams=(out_file, err_file), **kwargs)

    if hold_open:
        out_file.close(); err_file.close()
        return job, information, out_path, err_path

    waited = kernel32.WaitForSingleObject(information.hProcess, int(timeout * 1000))
    timed_out = waited == WAIT_TIMEOUT
    code = wintypes.DWORD()
    if not timed_out:
        kernel32.GetExitCodeProcess(information.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(job)  # kill-on-close terminates the whole tree
    kernel32.CloseHandle(information.hProcess)
    out_file.close(); err_file.close()
    stdout = out_path.read_text(encoding="utf-8", errors="replace")
    stderr = err_path.read_text(encoding="utf-8", errors="replace")
    _discard(out_path); _discard(err_path)
    return (None if timed_out else code.value), stdout, stderr, timed_out


def run_probe(name: str, target: str, **kwargs) -> dict:
    """Probe through System32 tools, which AppContainers may read by default.

    Using the shell rather than a staged tool separates what the OS boundary
    enforces from the unrelated question of tool reachability.
    """
    shell = {"write": f'echo probe>"{target}"',
             "read": f'type "{target}" >nul',
             "listdir": f'dir /b "{target}" >nul'}.get(name)
    if shell is not None:
        command, line = [SHELL], f'"{SHELL}" /c {shell}'
    elif name == "network":
        command, line = [CURL, "--silent", "--max-time", "6", "--output", "NUL", target], None
    else:
        raise ValueError(f"Unknown probe {name}")
    code, stdout, stderr, timed_out = launch(command, command_line=line, **kwargs)
    outcome = "timed-out" if timed_out else ("allowed" if code == 0 else "denied")
    return {"probe": name, "returncode": code, "outcome": outcome,
            "timed_out": timed_out, "detail": (stdout + stderr).strip()[-160:]}


def hold_child(container: str, cwd: Path) -> int:
    """Start one contained child, report its PID, then block until killed."""
    sid, _ = container_sid(container)
    _, information, _, _ = launch(
        [SHELL], command_line=f'"{SHELL}" /c for /l %i in (0,0,1) do @rem',
        sid=sid, cwd=cwd, timeout=600.0, hold_open=True,
        env={"SystemRoot": os.environ["SystemRoot"], "windir": os.environ["windir"],
             "LOCALAPPDATA": os.environ["LOCALAPPDATA"], "PATHEXT": ".COM;.EXE"})
    print(information.dwProcessId, flush=True)
    time.sleep(600)
    return 0


def alive(pid: int) -> bool:
    listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True)
    return str(pid) in listing.stdout


def redact(path: Path) -> str:
    """Report a stable, machine-independent reference instead of a real path."""
    return "sha256:" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--hold-child", metavar="CONTAINER",
                        help="internal: start a contained child and block, for the crash check")
    parser.add_argument("--cwd", type=Path, help="internal: worktree for --hold-child")
    arguments = parser.parse_args()

    if arguments.hold_child:
        return hold_child(arguments.hold_child, arguments.cwd)

    name = container_name()
    sid, _ = container_sid(name)
    text_sid = sid_string(sid)
    interpreter = str(Path(sys.base_prefix) / "python.exe")
    checks: list[dict] = []
    started = time.time()

    with tempfile.TemporaryDirectory(prefix="af-appcontainer-probe-") as raw:
        workspace = Path(raw).resolve()
        worktree, declared_temp, outside, staged = (
            workspace / part for part in ("worktree", "sandbox-temp", "outside", "tools"))
        for folder in (worktree, declared_temp, outside, staged):
            folder.mkdir()
        private = outside / "private.txt"
        private.write_text("private baseline content", encoding="utf-8")
        shutil.copy2(SYSTEM32 / "where.exe", staged / "where.exe")

        apply_ace(worktree, text_sid, "(M)")
        apply_ace(declared_temp, text_sid, "(M)")
        apply_ace(staged, text_sid, "(RX)")

        environment = {
            "SystemRoot": os.environ["SystemRoot"], "windir": os.environ["windir"],
            # AppContainer profile redirection resolves through LOCALAPPDATA; without
            # it CreateProcessW fails with ERROR_ENVVAR_NOT_FOUND before launch.
            "LOCALAPPDATA": os.environ["LOCALAPPDATA"],
            "TMP": str(declared_temp), "TEMP": str(declared_temp),
            "PATHEXT": ".COM;.EXE;.BAT;.CMD", "NO_COLOR": "1", "TERM": "dumb",
            "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
        }
        common = {"sid": sid, "cwd": worktree, "env": environment, "timeout": 45.0}

        checks.append({"id": "C1-write-worktree", "expected": "allowed",
                       **run_probe("write", str(worktree / "allowed.txt"), **common)})
        checks.append({"id": "C2-write-outside-worktree", "expected": "denied",
                       **run_probe("write", str(outside / "escape.txt"), **common)})
        checks.append({"id": "C3-write-declared-temp", "expected": "allowed",
                       **run_probe("write", str(declared_temp / "scratch.txt"), **common)})
        checks.append({"id": "C4-read-private-file", "expected": "denied",
                       **run_probe("read", str(private), **common)})
        checks.append({"id": "C5-read-user-profile", "expected": "denied",
                       **run_probe("listdir", str(Path.home()), **common)})
        checks.append({"id": "C6-network-outbound", "expected": "denied",
                       **run_probe("network", "https://1.1.1.1/", **common)})

        junction = worktree / "escape-link"
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                              capture_output=True, text=True)
        checks.append({"id": "C7-junction-escape", "expected": "denied",
                       "junction_created": made.returncode == 0,
                       **(run_probe("write", str(junction / "through-link.txt"), **common)
                          if made.returncode == 0 else {"outcome": "not-tested"})})

        profile_temp = Path(os.environ["LOCALAPPDATA"]) / "Packages" / name / "AC" / "Temp"
        checks.append({"id": "C8-appcontainer-own-temp", "expected": "allowed-by-design",
                       **run_probe("write", str(profile_temp / "own.txt"), **common)})

        code, *_ = launch([str(staged / "where.exe"), "/?"], **common)
        checks.append({"id": "C11-staged-tool-launch", "expected": "allowed",
                       "returncode": code, "outcome": "allowed" if code == 0 else "denied",
                       "note": "tool copied into a sandbox-owned directory, then ACL granted"})
        code, *_ = launch([interpreter, "-c", "pass"], **common)
        checks.append({"id": "C12-tool-in-user-profile", "expected": "denied-without-grant",
                       "returncode": code, "outcome": "allowed" if code == 0 else "denied",
                       "note": "interpreter under the user profile with no container ACE"})

        # A busy loop needs no console, signal namespace or network to stay alive.
        spin = "for /l %i in (0,0,1) do @rem"
        job, information, out_path, err_path = launch(
            [SHELL], command_line=f'"{SHELL}" /c start /b "" "{SHELL}" /c {spin} & {spin}',
            hold_open=True, **common)
        time.sleep(4.0)
        before = alive(information.dwProcessId)
        kernel32.CloseHandle(job)
        kernel32.CloseHandle(information.hProcess)
        time.sleep(2.0)
        _discard(out_path); _discard(err_path)
        checks.append({"id": "C9-job-close-kills-tree", "expected": "tree-terminated",
                       "alive_before_close": before,
                       "alive_after_close": alive(information.dwProcessId),
                       "outcome": "tree-terminated"
                                  if before and not alive(information.dwProcessId)
                                  else "not-terminated"})

        code, _, _, timed_out = launch(
            [SHELL], command_line=f'"{SHELL}" /c {spin}',
            sid=sid, cwd=worktree, env=environment, timeout=5.0)
        checks.append({"id": "C10-timeout-terminates", "expected": "tree-terminated",
                       "timed_out": timed_out, "returncode": code,
                       "outcome": "tree-terminated" if timed_out else "not-terminated"})

        holder = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--hold-child", name,
             "--cwd", str(worktree)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        contained = int(holder.stdout.readline().strip())
        before = alive(contained)
        subprocess.run(["taskkill", "/F", "/PID", str(holder.pid)],
                       capture_output=True, text=True)
        holder.wait(timeout=30)
        time.sleep(2.0)
        checks.append({"id": "C13-supervisor-crash-kills-child",
                       "expected": "tree-terminated",
                       "alive_before_kill": before, "alive_after_kill": alive(contained),
                       "outcome": "tree-terminated" if before and not alive(contained)
                                  else "not-terminated",
                       "note": "controlling process force-killed; no graceful teardown ran"})

        for folder in (worktree, declared_temp, staged):
            apply_ace(folder, text_sid, "", remove=True)

    report = {
        "schema_version": 1,
        "artifact_kind": "unqualified-capability-probe",
        "task_refs": ["AF-017", "AF-044", "AF-052"],
        "release": "C-PILOT",
        "qualification": "not-qualified",
        "host": {
            "platform": sys.platform,
            "windows_build": sys.getwindowsversion().build,
            "python": sys.version.split()[0],
            "elevated": bool(ctypes.windll.shell32.IsUserAnAdmin()),
            "interpreter_ref": redact(Path(interpreter)),
        },
        "mechanism": {
            "isolation": "AppContainer (SECURITY_CAPABILITIES, zero capabilities)",
            "process_tree": "Job object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
            "write_grants": "inheritable (OI)(CI)(M) ACE for the container SID",
            "read_grants": "inheritable (OI)(CI)(RX) ACE on the staged tool tree only",
        },
        "elapsed_seconds": round(time.time() - started, 2),
        "checks": checks,
    }
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)

    expected_denied = {"C2-write-outside-worktree", "C4-read-private-file",
                       "C5-read-user-profile", "C6-network-outbound",
                       "C7-junction-escape", "C12-tool-in-user-profile"}
    expected_allowed = {"C1-write-worktree", "C3-write-declared-temp",
                        "C11-staged-tool-launch"}
    terminated = {"C9-job-close-kills-tree", "C10-timeout-terminates",
                  "C13-supervisor-crash-kills-child"}
    failures = [
        check["id"] for check in checks
        if (check["id"] in expected_denied and check.get("outcome") != "denied")
        or (check["id"] in expected_allowed and check.get("outcome") != "allowed")
        or (check["id"] in terminated and check.get("outcome") != "tree-terminated")
    ]
    if failures:
        print("UNMET: " + ", ".join(failures), file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
