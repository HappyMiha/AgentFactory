"""Small, local, read-only observations; never an engine/model readiness verdict.

No provider CLI is started, and discovered software is not authenticated or
qualified. Hardware probes have fixed arguments, bounded output and a deadline.
Public results intentionally omit executable paths, host names and raw errors.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import platform
import re
import select
import shutil
import stat
import subprocess
import time


_MAX_PROBE_BYTES = 32_768
_PROBE_TIMEOUT = 3.0
_MAX_GPUS = 16
_MIB = 1024 * 1024


def _unknown(items: list[dict], field: str, reason: str = "not_reported") -> None:
    entry = {"field": field, "reason": reason}
    if entry not in items:
        items.append(entry)


def _label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (not value or len(value) > 160 or any(ord(c) < 32 for c in value)
            or any(c in value for c in "\\/<>") or "\x7f" in value):
        return None
    return value


def _number(value: object, *, positive: bool = False) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if (value > 0 if positive else value >= 0) else None


def _failure(exc: BaseException) -> str:
    return "permission_denied" if isinstance(exc, PermissionError) else "probe_failed"


def _read_kernel(path: Path, *, prefix: bool = False) -> str:
    # Only callers' fixed /proc and /sys paths are read; no user-selected files.
    with path.open("rb") as stream:
        data = stream.read(_MAX_PROBE_BYTES + 1)
    if len(data) > _MAX_PROBE_BYTES and not prefix:
        raise ValueError("bounded kernel data exceeded")
    return data[:_MAX_PROBE_BYTES].decode("utf-8", errors="replace")


def _pipe_chunk(stream, count: int) -> bytes | None:
    """Read only bytes already available; None means a still-open empty pipe."""
    descriptor = stream.fileno()
    if os.name == "nt":
        import msvcrt
        available = ctypes.c_uint32()
        peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
        peek.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                         ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        peek.restype = ctypes.c_int
        if not peek(msvcrt.get_osfhandle(descriptor), None, 0, None, ctypes.byref(available), None):
            if ctypes.get_last_error() == 109:  # ERROR_BROKEN_PIPE
                return b""
            raise OSError("pipe observation failed")
        return os.read(descriptor, min(count, available.value)) if available.value else None
    readable, _, _ = select.select([descriptor], [], [], 0)
    return os.read(descriptor, count) if readable else None


def _run_probe(argv: list[str], *, timeout: float = _PROBE_TIMEOUT) -> tuple[str | None, str | None]:
    """Bound output and lifetime without creating reader threads or descendants."""
    try:
        process = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as exc:
        return None, _failure(exc)
    chunks: list[bytes] = []
    outcome = None
    size = 0
    deadline = time.monotonic() + timeout
    try:
        assert process.stdout is not None
        while time.monotonic() < deadline:
            chunk = _pipe_chunk(process.stdout, min(4096, _MAX_PROBE_BYTES + 1 - size))
            if chunk:
                size += len(chunk)
                if size > _MAX_PROBE_BYTES:
                    outcome = "probe_output_limit"
                    break
                chunks.append(chunk)
            elif chunk == b"" or process.poll() is not None:
                break
            else:
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        if not outcome:
            process.wait(timeout=max(0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        outcome = outcome or "probe_timeout"
    except OSError as exc:
        outcome = _failure(exc)
    finally:
        if process.poll() is None:
            try:
                process.kill()  # Only the exact child we started, never its process tree.
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                outcome = outcome or "probe_failed"
        assert process.stdout is not None
        process.stdout.close()  # No reader can retain this pipe after our deadline.
    if outcome:
        return None, outcome
    if process.returncode != 0:
        return None, "probe_failed"
    try:
        return b"".join(chunks).decode("utf-8-sig"), None
    except UnicodeError:
        return None, "invalid_probe_output"


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in (
            "total_physical", "available_physical", "total_page_file",
            "available_page_file", "total_virtual", "available_virtual",
            "available_extended_virtual",
        )
    ]


def _windows_memory() -> tuple[int, int]:
    status = _MemoryStatus()
    status.length = ctypes.sizeof(status)
    function = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
    function.argtypes = [ctypes.POINTER(_MemoryStatus)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(status)):
        raise OSError("memory observation unavailable")
    return status.total_physical, status.available_physical


def _windows_cpu() -> str | None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                        r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
        return _label(winreg.QueryValueEx(key, "ProcessorNameString")[0])


def _cpu_memory(system: str, unknowns: list[dict]) -> tuple[dict, dict]:
    cpu = {"name": None, "logical_cores": _number(os.cpu_count(), positive=True)}
    memory: dict[str, int | None] = {"total_bytes": None, "available_bytes": None}
    reason = "unsupported_platform"
    cpu_reason = "unsupported_platform"
    if system == "Windows":
        try:
            cpu["name"] = _windows_cpu()
            cpu_reason = "not_reported"
        except (OSError, ValueError) as exc:
            cpu_reason = _failure(exc)
        try:
            total, available = _windows_memory()
            memory = {"total_bytes": _number(total, positive=True), "available_bytes": _number(available)}
            reason = "invalid_probe_output"
        except (OSError, ValueError) as exc:
            reason = _failure(exc)
    elif system == "Linux":
        try:
            text = _read_kernel(Path("/proc/cpuinfo"), prefix=True)
            match = re.search(r"^(?:model name|Hardware)\s*:\s*(.+)$", text, re.MULTILINE)
            cpu["name"] = _label(match.group(1)) if match else None
            cpu_reason = "not_reported"
        except (OSError, ValueError) as exc:
            cpu_reason = _failure(exc)
        try:
            text = _read_kernel(Path("/proc/meminfo"))
            for source, target in (("MemTotal", "total_bytes"), ("MemAvailable", "available_bytes")):
                match = re.search(rf"^{source}:\s+(\d+)\s+kB\s*$", text, re.MULTILINE)
                if match:
                    memory[target] = _number(int(match.group(1)) * 1024, positive=target == "total_bytes")
            reason = "not_reported"
        except (OSError, ValueError) as exc:
            reason = _failure(exc)
    if (memory["total_bytes"] is not None and memory["available_bytes"] is not None
            and memory["available_bytes"] > memory["total_bytes"]):
        memory["available_bytes"] = None
        reason = "invalid_probe_output"
    for field, value in cpu.items():
        if value is None:
            _unknown(unknowns, f"cpu.{field}", cpu_reason if field == "name" else "not_reported")
    for field, value in memory.items():
        if value is None:
            _unknown(unknowns, f"memory.{field}", reason)
    return cpu, memory


def _gpu(name: str) -> dict:
    return {"name": name, "kind": "unknown", "dedicated_total_bytes": None,
            "dedicated_free_bytes": None, "shared_total_bytes": None}


def _parse_nvidia(text: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text), strict=True))
    if len(rows) > _MAX_GPUS:
        raise ValueError("too many hardware rows")
    result = []
    for row in rows:
        if len(row) != 3 or not (name := _label(row[0])):
            raise ValueError("invalid hardware row")
        item = _gpu(name)
        for source, target in ((row[1], "dedicated_total_bytes"), (row[2], "dedicated_free_bytes")):
            source = source.strip()
            if re.fullmatch(r"\d{1,9}", source):
                item[target] = _number(int(source) * _MIB, positive=target == "dedicated_total_bytes")
            elif source not in ("[N/A]", "N/A", "[Not Supported]"):
                raise ValueError("invalid memory observation")
        if (item["dedicated_total_bytes"] is not None and item["dedicated_free_bytes"] is not None
                and item["dedicated_free_bytes"] > item["dedicated_total_bytes"]):
            item["dedicated_free_bytes"] = None
        # Vendor and VRAM alone do not establish whether an adapter is discrete.
        result.append(item)
    return result


def _windows_drive_type(root: str) -> int:
    function = ctypes.WinDLL("kernel32", use_last_error=True).GetDriveTypeW
    function.argtypes = [ctypes.c_wchar_p]
    function.restype = ctypes.c_uint32
    return function(root)


def _linux_local_mount(path: str) -> bool:
    try:
        with Path("/proc/self/mountinfo").open("rb") as stream:
            data = stream.read(262_145)
        if len(data) > 262_144:
            return False
        matches = []
        for line in data.decode("utf-8", errors="strict").splitlines():
            before, after = line.split(" - ", 1)
            mount = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), before.split()[4])
            if path == mount or path.startswith(mount.rstrip("/") + "/"):
                matches.append((len(mount), after.split()[0]))
        filesystem = max(matches, default=(0, ""))[1]
        return filesystem in {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "tmpfs", "overlay", "squashfs", "f2fs", "rootfs"}
    except (OSError, ValueError, IndexError, UnicodeError):
        return False


def _local_path(path: Path, system: str) -> bool:
    """Reject network/device/relative locations before any candidate file lookup."""
    raw = str(path)
    if not raw or len(raw) > 4096 or any(ord(char) < 32 for char in raw):
        return False
    if system == "Windows":
        if not re.match(r"^[a-zA-Z]:[\\/]", raw) or ":" in raw[2:]:
            return False
        parts = re.split(r"[\\/]", raw[3:])
        if len(parts) > 64 or any(part in (".", "..") for part in parts):
            return False
        # DRIVE_FIXED / DRIVE_RAMDISK only. In particular reject mapped shares.
        return _windows_drive_type(raw[:2] + "\\") in (3, 6)
    if system == "Linux":
        if not raw.startswith("/") or raw.startswith("//") or len(raw.split("/")) > 64 or ".." in raw.split("/"):
            return False
        return _linux_local_mount(raw)
    # A platform without a local-mount classifier gets no speculative file scan.
    return False


def _local_entry(path: Path, system: str, *, directory: bool = False) -> bool:
    if not _local_path(path, system):
        return False
    try:
        # Validate each ancestor before crossing it, including Windows junctions.
        # A local drive can contain a reparse point leading to a remote share.
        chain = list(reversed(path.parents)) + [path]
        for index, part in enumerate(chain):
            info = os.lstat(part)
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return False
            final = index == len(chain) - 1
            if (not final or directory) and not stat.S_ISDIR(info.st_mode):
                return False
            if final and not directory and not stat.S_ISREG(info.st_mode):
                return False
        return True
    except OSError:
        return False


def _find_local_software(system: str, commands: tuple[str, ...]) -> bool:
    # No shutil.which: it can traverse UNC, mapped drives or relative PATH entries.
    raw_path = os.environ.get("PATH", "")
    if len(raw_path) > 32_768:
        raw_path = raw_path[:32_768].rsplit(";" if system == "Windows" else ":", 1)[0]
    entries = raw_path.split(";" if system == "Windows" else ":", 32)[:32]
    suffixes = (".exe", ".cmd", ".bat") if system == "Windows" else ("",)
    for raw in entries:
        if not raw or not _local_entry(Path(raw), system, directory=True):
            continue
        for command in commands:
            for suffix in suffixes:
                if _local_entry(Path(raw) / (command + suffix), system):
                    return True
    return False


def _system_file(system: str, tool: str) -> str | None:
    if system == "Windows":
        root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        paths = ([root / "System32" / "nvidia-smi.exe",
                  Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"]
                 if tool == "nvidia-smi" else
                 [root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"])
    else:
        paths = [Path("/usr/bin/nvidia-smi"), Path("/bin/nvidia-smi")] if tool == "nvidia-smi" else []
    return next((str(path) for path in paths if _local_entry(path, system)), None)


def _gpu_names(system: str) -> tuple[list[dict], str | None]:
    if system == "Windows":
        try:
            powershell = _system_file(system, "powershell")
        except OSError as exc:
            return [], _failure(exc)
        if not powershell:
            return [], "not_detected_in_search_scope"
        command = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
                   "$ErrorActionPreference = 'Stop'; "
                   "@(Get-CimInstance -ClassName Win32_VideoController -Property Name | "
                   "Select-Object -ExpandProperty Name) | ConvertTo-Json -Compress")
        text, error = _run_probe([powershell, "-NoProfile", "-NonInteractive", "-Command", command])
        if error:
            return [], error
        try:
            names = json.loads(text) if text and text.strip() else []
            names = [names] if isinstance(names, str) else names
            if not isinstance(names, list) or len(names) > _MAX_GPUS or any(_label(name) is None for name in names):
                raise ValueError("invalid adapter names")
            return [_gpu(_label(name)) for name in names], None
        except (ValueError, TypeError):
            return [], "invalid_probe_output"
    if system == "Linux":
        result = []
        try:
            # Fixed card numbers avoid broad filesystem and personal-file scans.
            for index in range(_MAX_GPUS):
                path = Path(f"/sys/class/drm/card{index}/device/vendor")
                if not path.is_file():
                    continue
                vendor = _read_kernel(path).strip().lower()
                label = {"0x8086": "Intel", "0x1002": "AMD", "0x10de": "NVIDIA"}.get(vendor, "Graphics")
                result.append(_gpu(f"{label} adapter {index + 1}"))
            return result, None
        except (OSError, ValueError) as exc:
            return result, _failure(exc)
    return [], "unsupported_platform"


def _gpus(system: str, unknowns: list[dict]) -> list[dict]:
    result: list[dict] = []
    try:
        nvidia = _system_file(system, "nvidia-smi")
    except OSError as exc:
        nvidia = None
        _unknown(unknowns, "gpu_probe", _failure(exc))
    if nvidia:
        text, error = _run_probe([
            nvidia, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits",
        ])
        if not error:
            try:
                result = _parse_nvidia(text or "")
            except (ValueError, csv.Error):
                error = "invalid_probe_output"
        if error:
            _unknown(unknowns, "gpu_probe", error)
    names, error = _gpu_names(system)
    if error:
        _unknown(unknowns, "gpu_names_probe", error)
    # Windows supplies actual names, allowing a hybrid Intel + NVIDIA report.
    # Generic Linux DRM labels cannot be reliably matched to nvidia-smi devices:
    # omit only NVIDIA generic rows when that probe already enumerated NVIDIA.
    known = {item["name"].casefold() for item in result}
    for item in names:
        if item["name"].casefold() not in known and not (
                system == "Linux" and result and item["name"].startswith("NVIDIA adapter ")):
            result.append(item)
            known.add(item["name"].casefold())
    result = result[:_MAX_GPUS]
    if not result:
        _unknown(unknowns, "gpus", "not_detected_in_search_scope")
    for index, item in enumerate(result):
        for field, value in item.items():
            if value is None or (field == "kind" and value == "unknown"):
                _unknown(unknowns, f"gpus[{index}].{field}")
    return result


_SOFTWARE = (
    ("git", "Git", ("git",)), ("node", "Node.js", ("node",)),
    ("docker", "Docker", ("docker",)), ("ollama", "Ollama", ("ollama",)),
    ("godot", "Godot", ("godot", "godot4", "Godot")),
    ("unity_hub", "Unity Hub", ("unityhub",)), ("unity", "Unity Editor", ("Unity", "unity-editor")),
    ("unreal", "Unreal Editor", ("UnrealEditor", "UE4Editor")),
)


def _known_software_paths(system: str, software_id: str) -> list[Path]:
    if system == "Windows":
        programs = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        local = os.environ.get("LOCALAPPDATA")
        paths = {
            "ollama": [Path(local) / "Programs/Ollama/ollama.exe"] if local else [],
            "unity_hub": [programs / "Unity Hub/Unity Hub.exe"],
            "godot": [programs / "Godot/godot.exe"],
            "docker": [programs / "Docker/Docker/resources/bin/docker.exe"],
        }.get(software_id, [])
        base, relative, pattern = {
            "unity": (programs / "Unity/Hub/Editor", Path("Editor/Unity.exe"), r"\d[\w.\-]{0,40}"),
            "unreal": (programs / "Epic Games", Path("Engine/Binaries/Win64/UnrealEditor.exe"), r"UE_[\w.\-]{1,40}"),
        }.get(software_id, (None, None, None))
        if base is not None and _local_entry(base, system, directory=True):
            # At most 32 entries in a standard application directory, no recursion.
            with os.scandir(base) as entries:
                for index, entry in enumerate(entries):
                    if index >= 32:
                        break
                    if re.fullmatch(pattern, entry.name) and entry.is_dir(follow_symlinks=False):
                        paths.append(Path(entry.path) / relative)
        return paths
    if system == "Darwin":
        return {
            "unity_hub": [Path("/Applications/Unity Hub.app/Contents/MacOS/Unity Hub")],
            "godot": [Path("/Applications/Godot.app/Contents/MacOS/Godot")],
            "docker": [Path("/Applications/Docker.app/Contents/Resources/bin/docker")],
        }.get(software_id, [])
    return []


def _software(system: str, unknowns: list[dict]) -> list[dict]:
    rows = [{"id": "python", "label": "Python", "status": "detected", "version": platform.python_version()}]
    for software_id, label, commands in _SOFTWARE:
        detected = False
        reason = "not_detected_in_search_scope"
        try:
            detected = _find_local_software(system, commands)
            if not detected:
                detected = any(_local_entry(path, system) for path in _known_software_paths(system, software_id))
        except OSError as exc:
            reason = _failure(exc)
        rows.append({"id": software_id, "label": label, "status": "detected" if detected else "not_detected", "version": None})
        _unknown(unknowns, f"software[{software_id}].version", "not_reported" if detected else reason)
    return rows


def collect_inventory(workspace: Path) -> dict:
    """Observe the local host. Caller supplies its configured workspace volume.

    Nothing is installed, written, sent, inferred or marked ready. Zero is kept
    only when observed (for example a full disk); unavailable values are null.
    """
    unknowns: list[dict] = []
    system = platform.system()
    operating_system = {"name": _label(system), "release": _label(platform.release()), "architecture": _label(platform.machine())}
    for field, value in operating_system.items():
        if value is None:
            _unknown(unknowns, f"os.{field}")
    cpu, memory = _cpu_memory(system, unknowns)
    disk: dict = {"total_bytes": None, "free_bytes": None, "location": "workspace_volume"}
    try:
        observation = shutil.disk_usage(workspace)
        disk.update(total_bytes=_number(observation.total, positive=True), free_bytes=_number(observation.free))
        if disk["total_bytes"] is not None and disk["free_bytes"] is not None and disk["free_bytes"] > disk["total_bytes"]:
            disk["free_bytes"] = None
        disk_reason = "invalid_probe_output"
    except OSError as exc:
        disk_reason = _failure(exc)
    for field in ("total_bytes", "free_bytes"):
        if disk[field] is None:
            _unknown(unknowns, f"disk.{field}", disk_reason)
    gpus = _gpus(system, unknowns)
    software = _software(system, unknowns)
    return {"schema_version": 1, "observed_at": datetime.now(timezone.utc).isoformat(),
            "source": "local_read_only", "os": operating_system, "cpu": cpu, "memory": memory,
            "gpus": gpus, "gpu_status": "detected" if gpus else "unknown", "disk": disk,
            "software": software, "unknowns": unknowns}


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a local read-only PC inventory; no software is started or installed except fixed OS GPU probes.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Configured workspace whose volume is measured (path is not included in the report)")
    args = parser.parse_args()
    print(json.dumps(collect_inventory(args.workspace), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
