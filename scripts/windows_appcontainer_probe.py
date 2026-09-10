"""Unqualified AppContainer/Job-object probe for the C-PILOT Windows decision.

This is a spike, not a SandboxBackend. It launches probe commands inside a
per-run AppContainer under a kill-on-close job object and reports what the OS
actually enforced. Nothing here grants writable execution to Core; a passing
report is an input to qualification, never the qualification itself.

Run: python scripts/windows_appcontainer_probe.py [--report PATH] [--keep]
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
import uuid
from ctypes import wintypes
from pathlib import Path

if sys.platform != "win32":  # pragma: no cover - probe is Windows-only by design
    raise SystemExit("This probe only runs on Windows")

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
userenv = ctypes.WinDLL("userenv", use_last_error=True)

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NEW_PROCESS_GROUP = 0x00000200
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
WAIT_TIMEOUT = 0x00000102
ERROR_ALREADY_EXISTS = 0xB7


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.c_void_p),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_void_p),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _declare() -> None:
    """Explicit signatures; default ctypes marshalling truncates pointer arguments."""
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
        wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
    userenv.DeleteAppContainerProfile.restype = ctypes.c_long


_declare()


def _check(result, name):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error(), f"{name} failed")
    return result


def container_sid(name: str) -> tuple[ctypes.c_void_p, bool]:
    """Return the AppContainer SID, creating the per-user profile when absent."""
    sid = ctypes.c_void_p()
    status = userenv.CreateAppContainerProfile(
        ctypes.c_wchar_p(name), ctypes.c_wchar_p(name),
        ctypes.c_wchar_p("Lokvetia Core sandbox probe"), None, 0, ctypes.byref(sid))
    if status == 0:
        return sid, True
    if status & 0xFFFF != ERROR_ALREADY_EXISTS:
        raise OSError(f"CreateAppContainerProfile failed: 0x{status & 0xFFFFFFFF:08x}")
    status = userenv.DeriveAppContainerSidFromAppContainerName(
        ctypes.c_wchar_p(name), ctypes.byref(sid))
    if status != 0:
        raise OSError(f"DeriveAppContainerSid failed: 0x{status & 0xFFFFFFFF:08x}")
    return sid, False


def sid_string(sid: ctypes.c_void_p) -> str:
    text = wintypes.LPWSTR()
    _check(advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)), "ConvertSidToStringSidW")
    try:
        return str(text.value)
    finally:
        kernel32.LocalFree(text)


def icacls(path: Path, sid: str, rights: str, *, remove: bool = False) -> None:
    """Grant or remove one inheritable ACE for the container SID."""
    arguments = ["icacls", str(path), "/Q", "/C"]
    arguments += ["/remove:g", f"*{sid}"] if remove else ["/grant", f"*{sid}:(OI)(CI){rights}"]
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode != 0 and not remove:
        raise OSError(f"icacls failed for {path.name}: {result.stdout.strip()} {result.stderr.strip()}")


def _discard(path: Path) -> None:
    """A just-terminated child can still hold its inherited output handle."""
    for _ in range(20):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.1)


def environment_block(values: dict[str, str]) -> ctypes.Array:
    joined = "".join(f"{key}={value}\0" for key, value in sorted(values.items())) + "\0"
    return ctypes.create_unicode_buffer(joined)


def launch(
    command: list[str],
    *,
    sid: ctypes.c_void_p,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    hold_open: bool = False,
    command_line: str | None = None,
):
    """Run one command inside the AppContainer within a kill-on-close job object.

    Returns (returncode, stdout, stderr, timed_out). With hold_open the caller
    receives the live job/process handles instead, to test teardown behaviour.
    """
    job = _check(kernel32.CreateJobObjectW(None, None), "CreateJobObjectW")
    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    _check(
        kernel32.SetInformationJobObject(
            job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits), ctypes.sizeof(limits)),
        "SetInformationJobObject")

    out_file = tempfile.NamedTemporaryFile(suffix=".out", delete=False)
    err_file = tempfile.NamedTemporaryFile(suffix=".err", delete=False)
    out_path, err_path = Path(out_file.name), Path(err_file.name)
    import msvcrt
    for handle_source in (out_file, err_file):
        handle = msvcrt.get_osfhandle(handle_source.fileno())
        _check(kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT),
               "SetHandleInformation")

    size = ctypes.c_size_t()
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attributes = ctypes.create_string_buffer(size.value)
    _check(
        kernel32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)),
        "InitializeProcThreadAttributeList")
    capabilities = SECURITY_CAPABILITIES(AppContainerSid=sid, Capabilities=None,
                                         CapabilityCount=0, Reserved=0)
    _check(
        kernel32.UpdateProcThreadAttribute(
            attributes, 0, ctypes.c_size_t(PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES),
            ctypes.byref(capabilities), ctypes.sizeof(capabilities), None, None),
        "UpdateProcThreadAttribute")

    startup = STARTUPINFOEXW()
    startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    startup.StartupInfo.hStdInput = None
    startup.StartupInfo.hStdOutput = msvcrt.get_osfhandle(out_file.fileno())
    startup.StartupInfo.hStdError = msvcrt.get_osfhandle(err_file.fileno())
    startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)

    information = PROCESS_INFORMATION()
    # cmd.exe parses its own quoting; list2cmdline escaping breaks redirection.
    line = command_line if command_line is not None else subprocess.list2cmdline(command)
    created = kernel32.CreateProcessW(
        command[0], ctypes.create_unicode_buffer(line), None, None, True,
        EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT
        | CREATE_NEW_PROCESS_GROUP,
        ctypes.cast(environment_block(env), ctypes.c_void_p), str(cwd),
        ctypes.byref(startup.StartupInfo), ctypes.byref(information))
    if not created:
        error = ctypes.WinError(ctypes.get_last_error(), "CreateProcessW failed")
        kernel32.DeleteProcThreadAttributeList(attributes)
        kernel32.CloseHandle(job)
        out_file.close(); err_file.close()
        raise error

    _check(kernel32.AssignProcessToJobObject(job, information.hProcess),
           "AssignProcessToJobObject")
    kernel32.ResumeThread(information.hThread)
    kernel32.CloseHandle(information.hThread)
    kernel32.DeleteProcThreadAttributeList(attributes)

    if hold_open:
        out_file.close(); err_file.close()
        return job, information, out_path, err_path

    waited = kernel32.WaitForSingleObject(information.hProcess, int(timeout * 1000))
    timed_out = waited == WAIT_TIMEOUT
    code = wintypes.DWORD()
    if timed_out:
        kernel32.CloseHandle(job)  # kill-on-close terminates the whole tree
        job = None
    else:
        kernel32.GetExitCodeProcess(information.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(information.hProcess)
    if job:
        kernel32.CloseHandle(job)
    out_file.close(); err_file.close()
    stdout = out_path.read_text(encoding="utf-8", errors="replace")
    stderr = err_path.read_text(encoding="utf-8", errors="replace")
    _discard(out_path); _discard(err_path)
    return (None if timed_out else code.value), stdout, stderr, timed_out


SHELL = str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "cmd.exe")
CURL = str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32" / "curl.exe")


def run_probe(name: str, target: str, **kwargs) -> dict:
    """Probe through System32 tools, which AppContainers may read by default.

    Using the shell rather than the project interpreter separates what the OS
    boundary enforces from the unrelated question of tool reachability.
    """
    shell = {"write": f'echo probe>"{target}"',
             "read": f'type "{target}" >nul',
             "listdir": f'dir /b "{target}" >nul'}.get(name)
    if shell is not None:
        argv, line = [SHELL], f'"{SHELL}" /c {shell}'
    elif name == "network":
        argv = [CURL, "--silent", "--max-time", "6", "--output", "NUL", target]
        line = None
    else:
        raise ValueError(f"Unknown probe {name}")
    code, stdout, stderr, timed_out = launch(argv, command_line=line, **kwargs)
    combined = (stdout + stderr).strip()
    outcome = "allowed" if code == 0 else "denied"
    if timed_out:
        outcome = "timed-out"
    return {"probe": name, "returncode": code, "outcome": outcome,
            "timed_out": timed_out, "detail": combined[-160:]}


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
    parser.add_argument("--keep", action="store_true", help="keep the AppContainer profile")
    parser.add_argument("--hold-child", metavar="CONTAINER",
                        help="internal: start a contained child and block, for the crash check")
    parser.add_argument("--cwd", type=Path, help="internal: worktree for --hold-child")
    arguments = parser.parse_args()

    if arguments.hold_child:
        return hold_child(arguments.hold_child, arguments.cwd)

    name = "LokvetiaCoreProbe" + uuid.uuid4().hex[:16]
    sid, created = container_sid(name)
    text_sid = sid_string(sid)
    interpreter = str(Path(sys.base_prefix) / "python.exe")
    checks: list[dict] = []
    started = time.time()

    with tempfile.TemporaryDirectory(prefix="af-appcontainer-probe-") as raw:
        workspace = Path(raw).resolve()
        worktree = workspace / "worktree"
        declared_temp = workspace / "sandbox-temp"
        outside = workspace / "outside"
        for folder in (worktree, declared_temp, outside):
            folder.mkdir()
        private = outside / "private.txt"
        private.write_text("private baseline content", encoding="utf-8")

        staged_tool = workspace / "tools"
        staged_tool.mkdir()
        shutil.copy2(Path(os.environ["SystemRoot"]) / "System32" / "where.exe",
                     staged_tool / "where.exe")

        icacls(worktree, text_sid, "(M)")
        icacls(declared_temp, text_sid, "(M)")
        icacls(staged_tool, text_sid, "(RX)")

        environment = {
            "SystemRoot": os.environ.get("SystemRoot", "C:\\Windows"),
            "windir": os.environ.get("windir", "C:\\Windows"),
            # AppContainer profile redirection resolves through LOCALAPPDATA; without
            # it CreateProcessW fails with ERROR_ENVVAR_NOT_FOUND before launch.
            "LOCALAPPDATA": os.environ["LOCALAPPDATA"],
            "TMP": str(declared_temp), "TEMP": str(declared_temp),
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "NO_COLOR": "1", "TERM": "dumb", "PYTHONIOENCODING": "utf-8",
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

        code, stdout, _, _ = launch([str(staged_tool / "where.exe"), "/?"], **common)
        checks.append({"id": "C11-staged-tool-launch", "expected": "allowed",
                       "returncode": code, "outcome": "allowed" if code == 0 else "denied",
                       "note": "tool copied into a sandbox-owned directory, then ACL granted"})
        code, _, _, _ = launch([interpreter, "-c", "pass"], **common)
        checks.append({"id": "C12-tool-in-user-profile", "expected": "denied-without-grant",
                       "returncode": code,
                       "outcome": "allowed" if code == 0 else "denied",
                       "note": "interpreter under %USERPROFILE% with no container ACE"})

        # A busy loop needs no console, signal namespace or network to stay alive.
        spin = "for /l %i in (0,0,1) do @rem"
        job, information, out_path, err_path = launch(
            [SHELL], command_line=f'"{SHELL}" /c start /b "" "{SHELL}" /c {spin} & {spin}',
            hold_open=True, **common)
        time.sleep(4.0)
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {information.dwProcessId}", "/NH"],
            capture_output=True, text=True)
        alive_before = str(information.dwProcessId) in listing.stdout
        kernel32.CloseHandle(job)
        kernel32.CloseHandle(information.hProcess)
        time.sleep(2.0)
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {information.dwProcessId}", "/NH"],
            capture_output=True, text=True)
        alive_after = str(information.dwProcessId) in listing.stdout
        _discard(out_path); _discard(err_path)
        checks.append({"id": "C9-job-close-kills-tree", "expected": "tree-terminated",
                       "alive_before_close": alive_before, "alive_after_close": alive_after,
                       "outcome": "tree-terminated" if alive_before and not alive_after
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

        for folder in (worktree, declared_temp, staged_tool):
            icacls(folder, text_sid, "", remove=True)

    if created and not arguments.keep:
        userenv.DeleteAppContainerProfile(ctypes.c_wchar_p(name))

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
            "read_grants": "inheritable (OI)(CI)(RX) ACE on the interpreter tree only",
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
                       "C5-read-user-profile", "C6-network-outbound", "C7-junction-escape",
                       "C12-tool-in-user-profile"}
    expected_allowed = {"C1-write-worktree", "C3-write-declared-temp",
                        "C11-staged-tool-launch"}
    failures = [
        check["id"] for check in checks
        if (check["id"] in expected_denied and check.get("outcome") != "denied")
        or (check["id"] in expected_allowed and check.get("outcome") != "allowed")
        or (check["id"] in {"C9-job-close-kills-tree", "C10-timeout-terminates",
                            "C13-supervisor-crash-kills-child"}
            and check.get("outcome") != "tree-terminated")
    ]
    if failures:
        print("UNMET: " + ", ".join(failures), file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
