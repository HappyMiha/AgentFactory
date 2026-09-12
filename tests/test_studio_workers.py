"""Which machine did this, and which machine may do the next thing."""

import tempfile
import unittest
from pathlib import Path

from agent_factory.localisation import LANGUAGES
from agent_factory.storage import SQLiteStorage
from agent_factory.studio_workers import StudioMachines, WorkerRefused


class Fixture(unittest.TestCase):
    """Shared machines only: the subclasses below carry the tests."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = SQLiteStorage(Path(self.folder.name) / "machines.db")
        self.addCleanup(self.storage.db.close)
        self.machines = StudioMachines(self.storage)
        self.machines.register("web", name="lokvetia-core-web", kind="web_container")
        self.machines.register(
            "cloud", name="build-worker-3", kind="cloud_worker",
            capabilities=["godot", "linux"])
        self.machines.register(
            "pc", name="desktop-tefqhlo", kind="this_pc",
            capabilities=["godot", "unity", "gpu"], video_memory_gb=8.0)


class MachineTests(Fixture):
    def test_the_web_container_never_builds_or_scans_hardware(self):
        for work in ("build", "hardware_scan", "engine_command", "local_inference"):
            with self.assertRaises(WorkerRefused) as caught:
                self.machines.admit("web", work)
            self.assertIn("web container", caught.exception.text("en"))

    def test_a_real_worker_may_build(self):
        self.assertEqual(self.machines.admit("cloud", "build").name, "build-worker-3")

    def test_a_machine_only_gets_work_it_can_do(self):
        with self.assertRaises(WorkerRefused) as caught:
            self.machines.admit("cloud", "build", needs=["unity"])
        self.assertIn("unity", caught.exception.text("en"))

    def test_your_own_pc_can_take_the_work_it_is_equipped_for(self):
        self.assertEqual(self.machines.admit("pc", "build", needs=["unity"]).kind, "this_pc")

    def test_an_unregistered_machine_is_refused(self):
        with self.assertRaises(WorkerRefused) as caught:
            self.machines.admit("somebody-elses-laptop", "build")
        self.assertIn("somebody-elses-laptop", caught.exception.text("en"))

    def test_an_invented_kind_of_work_is_refused(self):
        with self.assertRaises(WorkerRefused):
            self.machines.admit("cloud", "mine_bitcoin")

    def test_an_invented_kind_of_machine_is_refused(self):
        with self.assertRaises(WorkerRefused):
            self.machines.register("odd", name="odd", kind="toaster")

    def test_a_machine_record_has_nowhere_to_put_a_key(self):
        columns = {
            row[1] for row in self.storage.db.execute("PRAGMA table_info(studio_machines)")
        }
        for forbidden in ("api_key", "token", "password", "secret", "credential"):
            self.assertFalse([name for name in columns if forbidden in name.casefold()])


class ReportTests(Fixture):
    def test_every_report_names_the_machine_it_came_from(self):
        report = self.machines.report(
            "pc", kind="hardware_scan", body={"cpu": "Ryzen"}, language="en")
        self.assertEqual(report["machine_kind"], "this_pc")
        self.assertIn("your PC", report["signature"])
        self.assertIn("desktop-tefqhlo", report["signature"])

    def test_a_cloud_worker_says_it_is_a_cloud_worker(self):
        report = self.machines.report(
            "cloud", kind="hardware_scan", body={"cpu": "EPYC"}, language="en")
        self.assertIn("cloud worker", report["signature"])

    def test_the_container_cannot_produce_a_hardware_report_at_all(self):
        with self.assertRaises(WorkerRefused):
            self.machines.report("web", kind="hardware_scan", body={"cpu": "shared"})

    def test_the_signature_reads_in_both_languages(self):
        machine = self.machines.machine("pc")
        self.assertNotEqual(machine.signature("uk"), machine.signature("en"))

    def test_a_report_cannot_be_rewritten_or_deleted(self):
        self.machines.report("pc", kind="hardware_scan", body={"cpu": "Ryzen"})
        for statement in (
            "UPDATE studio_machine_reports SET machine_key='web' WHERE id=1",
            "DELETE FROM studio_machine_reports WHERE id=1",
        ):
            with self.assertRaises(Exception):
                with self.storage.db:
                    self.storage.db.execute(statement)

    def test_the_overview_lists_the_machines_and_what_the_container_may_not_do(self):
        overview = self.machines.overview(language="en")
        self.assertEqual(len(overview["machines"]), 3)
        self.assertIn("build", overview["never_on_the_web_container"])


class LocalModelTests(Fixture):
    def test_a_model_that_does_not_fit_is_refused_plainly(self):
        verdict = self.machines.local_model_fits("pc", needed_gb=24)
        self.assertFalse(verdict.fits)
        self.assertIn("will not run locally", verdict.reason.text("en"))

    def test_a_model_that_fits_says_so_with_the_numbers(self):
        verdict = self.machines.local_model_fits("pc", needed_gb=6)
        self.assertTrue(verdict.fits)
        self.assertIn("6", verdict.record("en")["reason"])

    def test_a_machine_with_no_video_card_is_told_so(self):
        verdict = self.machines.local_model_fits("cloud", needed_gb=6)
        self.assertFalse(verdict.fits)
        self.assertIn("no video card", verdict.reason.text("en"))

    def test_the_verdict_reads_in_both_languages(self):
        verdict = self.machines.local_model_fits("pc", needed_gb=24)
        for language in LANGUAGES:
            self.assertTrue(verdict.record(language)["reason"])
        self.assertNotEqual(
            verdict.record("uk")["reason"], verdict.record("en")["reason"])


if __name__ == "__main__":
    unittest.main()
