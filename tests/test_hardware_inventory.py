"""Synthetic hardware fixtures and real bounded child-process checks.

These fixtures do not certify physical integrated/discrete hardware or model
readiness. The task's actual host report is separate evidence.
"""
from collections import namedtuple
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_factory import hardware_inventory as inventory


_MODULE = "agent_factory.hardware_inventory."
_GIB = 1024 ** 3
_Disk = namedtuple("Disk", "total used free")


class HardwareInventoryTests(unittest.TestCase):
    def fixture(self, *, system="Windows", gpu_output=None, names=None, free_disk=8 * _GIB):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name, value in (
            ("platform.system", system), ("platform.release", "fixture-release"),
            ("platform.machine", "AMD64"), ("os.cpu_count", 8),
            ("_windows_cpu", "Fixture CPU"), ("_windows_memory", (16 * _GIB, 8 * _GIB)),
            ("shutil.disk_usage", _Disk(100 * _GIB, 92 * _GIB, free_disk)),
            ("_find_local_software", False), ("_known_software_paths", []),
            ("_system_file", "/fixed/nvidia-smi" if gpu_output is not None else None),
            ("_gpu_names", (names or [], None)),
        ):
            stack.enter_context(patch(_MODULE + name, return_value=value))
        probe = stack.enter_context(patch(_MODULE + "_run_probe", return_value=(gpu_output, None)))
        return probe

    def test_cpu_only_fixture_keeps_gpu_absence_unknown_and_never_claims_readiness(self):
        probe = self.fixture()
        report = inventory.collect_inventory(Path("private-workspace"))
        probe.assert_not_called()
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["source"], "local_read_only")
        self.assertEqual(report["gpu_status"], "unknown")
        self.assertEqual(report["gpus"], [])
        self.assertEqual(report["cpu"], {"name": "Fixture CPU", "logical_cores": 8})
        self.assertEqual(report["memory"], {"total_bytes": 16 * _GIB, "available_bytes": 8 * _GIB})
        self.assertIn({"field": "gpus", "reason": "not_detected_in_search_scope"}, report["unknowns"])
        self.assertNotIn("ready", report)
        self.assertNotIn("private-workspace", json.dumps(report))
        self.assertTrue(report["observed_at"].endswith("+00:00"))

    def test_integrated_fixture_does_not_invent_shared_memory_or_kind_from_intel_name(self):
        self.fixture(names=[inventory._gpu("Intel(R) UHD Graphics")])
        report = inventory.collect_inventory(Path("."))
        self.assertEqual(report["gpu_status"], "detected")
        gpu = report["gpus"][0]
        self.assertEqual(gpu["kind"], "unknown")
        self.assertIsNone(gpu["shared_total_bytes"])
        self.assertIsNone(gpu["dedicated_total_bytes"])
        self.assertIn({"field": "gpus[0].shared_total_bytes", "reason": "not_reported"}, report["unknowns"])

    def test_discrete_and_hybrid_fixture_preserves_8gb_memory_and_both_adapters(self):
        probe = self.fixture(gpu_output="NVIDIA GeForce GTX 1070, 8192, 7442\n", names=[
            inventory._gpu("NVIDIA GeForce GTX 1070"), inventory._gpu("Intel(R) UHD Graphics"),
        ])
        report = inventory.collect_inventory(Path("."))
        self.assertEqual(len(report["gpus"]), 2)
        gpu = report["gpus"][0]
        self.assertEqual(gpu["dedicated_total_bytes"], 8 * _GIB)
        self.assertEqual(gpu["dedicated_free_bytes"], 7442 * 1024 ** 2)
        self.assertEqual(gpu["kind"], "unknown")
        probe.assert_called_once_with([
            "/fixed/nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits",
        ])

    def test_full_disk_fixture_preserves_observed_zero_but_permission_failure_is_null(self):
        self.fixture(free_disk=0)
        report = inventory.collect_inventory(Path("."))
        self.assertEqual(report["disk"]["free_bytes"], 0)
        self.assertNotIn({"field": "disk.free_bytes", "reason": "not_reported"}, report["unknowns"])
        with patch(_MODULE + "shutil.disk_usage", side_effect=PermissionError("SECRET /home/person/key")):
            failed = inventory.collect_inventory(Path("."))
        self.assertIsNone(failed["disk"]["free_bytes"])
        self.assertIsNone(failed["disk"]["total_bytes"])
        self.assertIn({"field": "disk.free_bytes", "reason": "permission_denied"}, failed["unknowns"])
        self.assertNotIn("SECRET", json.dumps(failed))

    def test_windows_memory_failure_is_unknown_not_zero(self):
        self.fixture()
        with patch(_MODULE + "_windows_memory", side_effect=PermissionError("PRIVATE native failure")):
            report = inventory.collect_inventory(Path("."))
        self.assertEqual(report["memory"], {"total_bytes": None, "available_bytes": None})
        self.assertIn({"field": "memory.total_bytes", "reason": "permission_denied"}, report["unknowns"])
        self.assertNotIn("PRIVATE", json.dumps(report))

    def test_linux_memavailable_is_not_replaced_with_memfree(self):
        self.fixture(system="Linux")
        def kernel(path, **kwargs):
            return "model name : Linux Fixture CPU\n" if path.name == "cpuinfo" else "MemTotal: 16384 kB\nMemFree: 2048 kB\n"
        with patch(_MODULE + "_read_kernel", side_effect=kernel):
            report = inventory.collect_inventory(Path("."))
        self.assertEqual(report["memory"]["total_bytes"], 16384 * 1024)
        self.assertIsNone(report["memory"]["available_bytes"])
        self.assertEqual(report["cpu"]["name"], "Linux Fixture CPU")

    def test_linux_reports_available_ram_and_rejects_invalid_over_total_value(self):
        self.fixture(system="Linux")
        for available, expected in ((8192, 8192 * 1024), (20000, None)):
            with self.subTest(available=available), patch(_MODULE + "_read_kernel", return_value=f"MemTotal: 16384 kB\nMemAvailable: {available} kB\n"):
                report = inventory.collect_inventory(Path("."))
            self.assertEqual(report["memory"]["available_bytes"], expected)

    def test_unsupported_platform_does_not_run_windows_memory_or_create_fake_values(self):
        self.fixture(system="Darwin")
        with patch(_MODULE + "_windows_memory") as windows:
            report = inventory.collect_inventory(Path("."))
        windows.assert_not_called()
        self.assertEqual(report["memory"], {"total_bytes": None, "available_bytes": None})
        self.assertIn({"field": "memory.available_bytes", "reason": "unsupported_platform"}, report["unknowns"])

    def test_gpu_timeout_returns_other_hardware_and_no_invented_cloud_denial(self):
        self.fixture(gpu_output="ignored")
        with patch(_MODULE + "_run_probe", return_value=(None, "probe_timeout")):
            report = inventory.collect_inventory(Path("."))
        self.assertEqual(report["memory"]["total_bytes"], 16 * _GIB)
        self.assertEqual(report["gpu_status"], "unknown")
        self.assertIn({"field": "gpu_probe", "reason": "probe_timeout"}, report["unknowns"])
        self.assertNotIn("cloud", json.dumps(report))

    def test_hardware_lookup_permission_failure_cannot_abort_or_leak_the_report(self):
        gpu_names = inventory._gpu_names
        self.fixture()
        with patch(_MODULE + "_system_file", side_effect=PermissionError("SECRET driver folder")):
            report = inventory.collect_inventory(Path("."))
        self.assertEqual(report["memory"]["total_bytes"], 16 * _GIB)
        self.assertEqual(report["gpu_status"], "unknown")
        self.assertIn({"field": "gpu_probe", "reason": "permission_denied"}, report["unknowns"])
        self.assertNotIn("SECRET", json.dumps(report))
        with patch(_MODULE + "_system_file", side_effect=PermissionError("SECRET driver folder")):
            self.assertEqual(gpu_names("Windows"), ([], "permission_denied"))

    def test_bad_gpu_csv_cannot_leak_raw_output(self):
        for output in ("C:\\private\\SECRET, nope, 5", "<script>SECRET</script>, 8, 5", "NVIDIA, SECRET, 2", "a,b,c,d"):
            with self.subTest(output=output):
                self.fixture(gpu_output=output)
                report = inventory.collect_inventory(Path("."))
                self.assertEqual(report["gpu_status"], "unknown")
                self.assertNotIn("SECRET", json.dumps(report))
                self.assertIn({"field": "gpu_probe", "reason": "invalid_probe_output"}, report["unknowns"])

    def test_nvidia_unknown_and_zero_memory_are_different(self):
        gpu = inventory._parse_nvidia("NVIDIA, [N/A], 0\n")[0]
        self.assertIsNone(gpu["dedicated_total_bytes"])
        self.assertEqual(gpu["dedicated_free_bytes"], 0)
        self.assertIsNone(inventory._parse_nvidia("NVIDIA, 0, 0\n")[0]["dedicated_total_bytes"])
        self.assertIsNone(inventory._parse_nvidia("NVIDIA, 100, 101\n")[0]["dedicated_free_bytes"])
        self.assertEqual(inventory._parse_nvidia('"NVIDIA, Fixture", 100, 50\n')[0]["name"], "NVIDIA, Fixture")

    def test_software_presence_does_not_execute_cli_or_expose_paths(self):
        self.fixture()
        with patch(_MODULE + "_find_local_software", return_value=True), patch(_MODULE + "_run_probe") as probe:
            report = inventory.collect_inventory(Path("PRIVATE_WORKSPACE"))
        probe.assert_not_called()
        self.assertTrue(all(row["status"] == "detected" for row in report["software"]))
        self.assertTrue(all(row["version"] is None for row in report["software"] if row["id"] != "python"))
        self.assertNotIn("PRIVATE", json.dumps(report))
        self.assertNotIn("processes", report)
        self.assertNotIn("hostname", report)

    def test_cim_queries_names_only_and_rejects_non_names(self):
        for value, count in (('["Intel Graphics", "AMD Radeon"]', 2), ('"Intel Graphics"', 1), ('{"SerialNumber":"SECRET"}', 0)):
            with self.subTest(value=value), patch(_MODULE + "_system_file", return_value="fixed-powershell"), patch(_MODULE + "_run_probe", return_value=(value, None)) as probe:
                gpus, reason = inventory._gpu_names("Windows")
            self.assertEqual(len(gpus), count)
            command = probe.call_args.args[0][-1]
            self.assertIn("-Property Name", command)
            self.assertNotIn("AdapterRAM", command)
            self.assertNotIn("SerialNumber", command)
            self.assertNotIn("SECRET", json.dumps(gpus))
            if not count:
                self.assertEqual(reason, "invalid_probe_output")

    def test_hardware_executable_lookup_never_uses_path(self):
        with patch(_MODULE + "shutil.which") as which, patch(_MODULE + "_local_entry", return_value=False):
            self.assertIsNone(inventory._system_file("Windows", "nvidia-smi"))
            self.assertIsNone(inventory._system_file("Linux", "nvidia-smi"))
        which.assert_not_called()

    def test_kernel_reads_are_bounded_and_cpu_prefix_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture"
            path.write_bytes(b"a" * (inventory._MAX_PROBE_BYTES + 100))
            with self.assertRaises(ValueError):
                inventory._read_kernel(path)
            self.assertEqual(len(inventory._read_kernel(path, prefix=True)), inventory._MAX_PROBE_BYTES)


class HardwareLocalDiscoveryTests(unittest.TestCase):
    def test_unc_device_relative_and_mapped_path_entries_never_reach_file_lookup(self):
        entries = [r"\\server\share\bin", r"\\?\C:\bin", r"\\.\C:\bin", r"relative\bin", ".", "", r"Z:\network"]
        with patch.dict(os.environ, {"PATH": ";".join(entries)}), patch(_MODULE + "_windows_drive_type", return_value=4), patch(_MODULE + "os.lstat") as lstat, patch(_MODULE + "shutil.which") as which:
            self.assertFalse(inventory._find_local_software("Windows", ("node",)))
        lstat.assert_not_called()
        which.assert_not_called()

    def test_absolute_fixed_local_executable_is_detected_without_execution(self):
        system = "Windows" if os.name == "nt" else "Linux"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / ("fixture.exe" if system == "Windows" else "fixture")).write_text("presence only")
            with patch.dict(os.environ, {"PATH": directory}), patch(_MODULE + "_windows_drive_type", return_value=3), patch(_MODULE + "_linux_local_mount", return_value=True), patch(_MODULE + "subprocess.Popen") as popen:
                self.assertTrue(inventory._find_local_software(system, ("fixture",)))
            popen.assert_not_called()

    def test_more_than_32_path_entries_are_not_scanned(self):
        with patch.dict(os.environ, {"PATH": ";".join(["relative"] * 32 + [r"C:\last"])}), patch(_MODULE + "_windows_drive_type") as drive, patch(_MODULE + "os.lstat") as lstat:
            self.assertFalse(inventory._find_local_software("Windows", ("node",)))
        drive.assert_not_called()
        lstat.assert_not_called()

    def test_unc_environment_roots_never_scan_gpu_or_engine_locations(self):
        with patch.dict(os.environ, {"SystemRoot": r"\\secret\windows", "ProgramFiles": r"\\secret\programs", "LOCALAPPDATA": r"\\secret\local", "PATH": ""}), patch(_MODULE + "os.lstat") as lstat, patch(_MODULE + "os.scandir") as scandir:
            self.assertIsNone(inventory._system_file("Windows", "nvidia-smi"))
            self.assertIsNone(inventory._system_file("Windows", "powershell"))
            self.assertEqual(inventory._known_software_paths("Windows", "unreal"), [])
            self.assertEqual(inventory._known_software_paths("Windows", "unity"), [])
            report = inventory._software("Windows", [])
        lstat.assert_not_called()
        scandir.assert_not_called()
        self.assertTrue(all(row["status"] == "not_detected" for row in report if row["id"] != "python"))

    def test_reparse_ancestor_is_rejected_before_children_are_inspected(self):
        observed = []
        def attributes(path):
            observed.append(str(path))
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400 if path.name == "junction" else 0)
        with patch(_MODULE + "_local_path", return_value=True), patch(_MODULE + "os.lstat", side_effect=attributes):
            self.assertFalse(inventory._local_entry(Path("/local/junction/private/node.exe"), "Windows"))
        self.assertTrue(observed[-1].endswith("junction"))
        self.assertFalse(any("private" in name for name in observed))

    def test_linux_network_or_unknown_mount_rejected_before_candidate_lookup(self):
        with patch(_MODULE + "_linux_local_mount", return_value=False), patch(_MODULE + "os.lstat") as lstat:
            self.assertFalse(inventory._local_entry(Path("/network/bin/node"), "Linux"))
        lstat.assert_not_called()


class HardwareProbeProcessTests(unittest.TestCase):
    def test_real_child_success_has_no_stderr_and_uses_no_shell_or_window(self):
        with patch(_MODULE + "subprocess.Popen", wraps=subprocess.Popen) as popen:
            output, reason = inventory._run_probe([sys.executable, "-c", "import sys; print('result'); print('SECRET', file=sys.stderr)"])
        self.assertEqual(output.strip(), "result")
        self.assertIsNone(reason)
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

    def test_real_child_output_limit_is_enforced_without_returning_partial_data(self):
        output, reason = inventory._run_probe([sys.executable, "-c", "print('SECRET' * 100000)"])
        self.assertIsNone(output)
        self.assertEqual(reason, "probe_output_limit")

    def test_real_child_timeout_kills_process_without_returning_partial_data(self):
        started = time.monotonic()
        output, reason = inventory._run_probe([sys.executable, "-c", "import time; print('SECRET', flush=True); time.sleep(20)"], timeout=0.2)
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNone(output)
        self.assertEqual(reason, "probe_timeout")

    def test_probe_creation_failure_returns_only_fixed_reason(self):
        with patch(_MODULE + "subprocess.Popen", side_effect=PermissionError("SECRET token file")):
            self.assertEqual(inventory._run_probe(["fixed-command"]), (None, "permission_denied"))

    def test_real_nonzero_or_invalid_utf8_output_is_not_public(self):
        for script, expected in (("print('SECRET'); raise SystemExit(2)", "probe_failed"),
                                 ("import sys; sys.stdout.buffer.write(bytes([255, 254]))", "invalid_probe_output")):
            with self.subTest(expected=expected):
                output, reason = inventory._run_probe([sys.executable, "-c", script])
                self.assertIsNone(output)
                self.assertEqual(reason, expected)

    def test_inherited_pipe_does_not_leave_a_reader_or_wait_for_descendant(self):
        script = ("import subprocess, sys; "
                  "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1)']); "
                  "print('parent-result', flush=True)")
        before = {thread.ident for thread in threading.enumerate()}
        started = time.monotonic()
        output, reason = inventory._run_probe([sys.executable, "-c", script], timeout=0.6)
        elapsed = time.monotonic() - started
        self.assertEqual(output.strip(), "parent-result")
        self.assertIsNone(reason)
        self.assertLess(elapsed, 0.8)
        self.assertEqual({thread.ident for thread in threading.enumerate()}, before)
        # The fixture child finishes naturally; production code never kills peers.
        time.sleep(max(0, 1.1 - elapsed))


if __name__ == "__main__":
    unittest.main()
