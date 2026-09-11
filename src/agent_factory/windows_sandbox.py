"""AppContainer launcher for the Windows sandbox backend.

Core spawns this module as an ordinary child process; it places the real command
inside a per-execution AppContainer with zero capabilities, held by a job object
that terminates the whole tree when this launcher goes away. Killing the launcher
is therefore sufficient teardown, which is what the existing process supervisor
already does on timeout, overflow and stop.

Findings behind the design are recorded in docs/windows-sandbox-qualification.md.
"""

from __future__ import annotations

import ctypes
import json
import msvcrt
import os
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Sequence

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
userenv = ctypes.WinDLL("userenv", use_last_error=True)

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
ERROR_ALREADY_EXISTS = 0xB7
WAIT_INFINITE = 0xFFFFFFFF
WAIT_TIMEOUT = 0x00000102


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
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


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
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


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
    """Explicit signatures; default marshalling truncates pointer arguments."""
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
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
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


class AppContainerError(RuntimeError):
    pass


def _check(result, name):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error(), f"{name} failed")
    return result


def container_name() -> str:
    return "LokvetiaSandbox" + uuid.uuid4().hex[:16]


def container_sid(name: str) -> tuple[ctypes.c_void_p, bool]:
    """Return the container SID, creating the per-user profile when it is absent."""
    sid = ctypes.c_void_p()
    status = userenv.CreateAppContainerProfile(
        name, name, "Lokvetia Core sandboxed execution", None, 0, ctypes.byref(sid))
    if status == 0:
        return sid, True
    if status & 0xFFFF != ERROR_ALREADY_EXISTS:
        raise AppContainerError(f"CreateAppContainerProfile failed: 0x{status & 0xFFFFFFFF:08x}")
    return derive_sid(name), False


def derive_sid(name: str) -> ctypes.c_void_p:
    """Compute a container SID from its name without creating the profile."""
    sid = ctypes.c_void_p()
    status = userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
    if status != 0:
        raise AppContainerError(f"DeriveAppContainerSid failed: 0x{status & 0xFFFFFFFF:08x}")
    return sid


def sid_string(sid: ctypes.c_void_p) -> str:
    text = wintypes.LPWSTR()
    _check(advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)), "ConvertSidToStringSidW")
    try:
        return str(text.value)
    finally:
        kernel32.LocalFree(text)


def apply_ace(path: Path, sid: str, rights: str, *, remove: bool = False) -> None:
    """Add or drop one inheritable ACE. Existing children need the recursive form."""
    arguments = ["icacls", str(path), "/Q", "/T"]
    arguments += ["/remove:g", f"*{sid}"] if remove else ["/grant", f"*{sid}:(OI)(CI){rights}"]
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode != 0 and not remove:
        raise AppContainerError(f"Sandbox ACL grant failed for {path.name}")


def environment_block(values: dict[str, str]) -> ctypes.Array:
    joined = "".join(f"{key}={value}\0" for key, value in sorted(values.items())) + "\0"
    return ctypes.create_unicode_buffer(joined)


def contained_environment() -> dict[str, str]:
    """Pass on the scrubbed environment Core already gave this launcher.

    AppContainer profile redirection resolves through LOCALAPPDATA; without it
    CreateProcessW fails with ERROR_ENVVAR_NOT_FOUND before the process exists.
    """
    values = dict(os.environ)
    if not values.get("LOCALAPPDATA"):
        raise AppContainerError("LOCALAPPDATA is required to start an AppContainer")
    return values


def spawn_contained(
    command: Sequence[str],
    *,
    sid,
    cwd: Path,
    env: dict[str, str],
    streams: Sequence = (),
    command_line: str | None = None,
):
    """Start the command inside the container, held by a kill-on-close job object.

    Output goes to this launcher's own stdout/stderr unless `streams` names two open
    files instead, which lets a diagnostic caller capture a run separately.
    """
    job = _check(kernel32.CreateJobObjectW(None, None), "CreateJobObjectW")
    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    _check(kernel32.SetInformationJobObject(
        job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits),
        ctypes.sizeof(limits)), "SetInformationJobObject")

    handles = []
    for stream in (streams or (sys.stdout, sys.stderr)):
        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT)
        handles.append(handle)

    size = ctypes.c_size_t()
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attributes = ctypes.create_string_buffer(size.value)
    _check(kernel32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)),
           "InitializeProcThreadAttributeList")
    capabilities = SECURITY_CAPABILITIES(AppContainerSid=sid, Capabilities=None,
                                         CapabilityCount=0, Reserved=0)
    _check(kernel32.UpdateProcThreadAttribute(
        attributes, 0, ctypes.c_size_t(PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES),
        ctypes.byref(capabilities), ctypes.sizeof(capabilities), None, None),
        "UpdateProcThreadAttribute")

    startup = STARTUPINFOEXW()
    startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    startup.StartupInfo.hStdInput = None
    startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = handles
    startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)

    information = PROCESS_INFORMATION()
    line = command_line if command_line is not None else subprocess.list2cmdline(command)
    created = kernel32.CreateProcessW(
        command[0], ctypes.create_unicode_buffer(line),
        None, None, True,
        EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT,
        ctypes.cast(environment_block(env), ctypes.c_void_p), str(cwd),
        ctypes.byref(startup.StartupInfo), ctypes.byref(information))
    if not created:
        error = ctypes.WinError(ctypes.get_last_error(), "Sandboxed CreateProcessW failed")
        kernel32.DeleteProcThreadAttributeList(attributes)
        kernel32.CloseHandle(job)
        raise error
    # Assignment happens while suspended, so no descendant can start outside the job.
    _check(kernel32.AssignProcessToJobObject(job, information.hProcess),
           "AssignProcessToJobObject")
    kernel32.ResumeThread(information.hThread)
    kernel32.CloseHandle(information.hThread)
    kernel32.DeleteProcThreadAttributeList(attributes)
    return job, information


def release(specification: dict) -> None:
    """Drop the grants and profile for one execution, however it ended.

    Killing the launcher skips its own teardown, so this stays idempotent and
    safe to repeat: a removed ACE and an absent profile are both no-ops.
    """
    text_sid = sid_string(derive_sid(specification["container"]))
    for value in [*specification["write_roots"], *specification["tool_roots"]]:
        root = Path(value)
        if root.exists():
            apply_ace(root, text_sid, "", remove=True)
    userenv.DeleteAppContainerProfile(specification["container"])


def run(specification: dict) -> int:
    write_roots = [Path(value) for value in specification["write_roots"]]
    tool_roots = [Path(value) for value in specification["tool_roots"]]
    name = specification["container"]
    sid, created = container_sid(name)
    text_sid = sid_string(sid)
    granted: list[Path] = []
    job = None
    try:
        for root in write_roots:
            apply_ace(root, text_sid, "(M)")
            granted.append(root)
        for root in tool_roots:
            apply_ace(root, text_sid, "(RX)")
            granted.append(root)
        job, information = spawn_contained(
            specification["command"], sid=sid, cwd=Path(specification["cwd"]),
            env=contained_environment())
        kernel32.WaitForSingleObject(information.hProcess, WAIT_INFINITE)
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(information.hProcess, ctypes.byref(code))
        kernel32.CloseHandle(information.hProcess)
        return int(code.value)
    finally:
        if job:
            kernel32.CloseHandle(job)  # Terminates any descendant still running.
        for root in granted:
            apply_ace(root, text_sid, "", remove=True)
        if created:
            for _ in range(10):
                if userenv.DeleteAppContainerProfile(name) == 0:
                    break
                time.sleep(0.2)  # The profile stays locked briefly after teardown.


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: python -m agent_factory.windows_sandbox <specification.json>",
              file=sys.stderr)
        return 2
    specification = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    try:
        return run(specification)
    except (AppContainerError, OSError) as error:
        # Core captures this stream as execution evidence; a traceback adds nothing.
        print(f"sandbox launch failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

