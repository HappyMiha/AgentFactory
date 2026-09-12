"""Unity's exit code is not the verdict; the log and the results file are."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_factory.unity_engine import (
    PLAYED_GAME_EVIDENCE,
    UnityAdapter,
    classify,
    read_test_results,
)
from agent_factory.unity_setup import DEFAULT_EDITOR

FAKE_UNITY = '''
import json, os, sys, time

config = json.loads(open(sys.argv[1], encoding="utf-8").read())
arguments = sys.argv[2:]


def value_after(flag):
    return arguments[arguments.index(flag) + 1] if flag in arguments else ""


def finish(behaviour):
    time.sleep(float(behaviour.get("sleep", 0)))
    sys.stdout.write(behaviour.get("log", ""))
    sys.exit(int(behaviour.get("exit", 0)))


if "-version" in arguments:
    sys.stdout.write(config.get("version", "6000.0.23f1") + "\\n")
    sys.exit(int(config.get("version_exit", 0)))

if "-runTests" in arguments:
    platform = value_after("-testPlatform")
    behaviour = config.get("edit_tests" if platform == "EditMode" else "play_tests", {})
    destination = value_after("-testResults")
    counts = behaviour.get("counts")
    if counts is not None and destination:
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        with open(destination, "w", encoding="utf-8") as handle:
            handle.write(
                '<test-run total="%d" passed="%d" failed="%d" skipped="%d" />'
                % (counts["total"], counts["passed"], counts["failed"], counts.get("skipped", 0))
            )
    finish(behaviour)

if "-executeMethod" in arguments:
    behaviour = config.get("build", {})
    destination = value_after("-lokvetiaBuildOutput")
    if behaviour.get("write", True) and destination:
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        with open(destination, "wb") as handle:
            handle.write(behaviour.get("payload", "unity-binary").encode("utf-8"))
    finish(behaviour)

finish(config.get("import", {}))
'''


class UnityFixture(unittest.TestCase):
    """Shared helpers; no test methods are inherited by the suites below."""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.engine = self.root / "fake_unity.py"
        self.engine.write_text(FAKE_UNITY, encoding="utf-8")
        self.config = self.root / "unity.json"
        self.project = self.root / "game"
        (self.project / "ProjectSettings").mkdir(parents=True)
        (self.project / "ProjectSettings/ProjectVersion.txt").write_text(
            f"m_EditorVersion: {DEFAULT_EDITOR}\n", encoding="utf-8",
        )
        (self.project / "Packages").mkdir()
        (self.project / "Packages/packages-lock.json").write_bytes(b"{}")
        self.output = self.root / "build" / "game.exe"

    def adapter(self, behaviour: dict | None = None, *, licence="active", **kwargs):
        self.config.write_text(json.dumps(behaviour or {}), encoding="utf-8")
        return UnityAdapter(
            executable_candidates=(sys.executable,),
            executable_args=(str(self.engine), str(self.config)),
            licence_probe=(lambda: licence) if licence is not None else None,
            **kwargs,
        )

    def passing(self) -> dict:
        return {
            "edit_tests": {"counts": {"total": 4, "passed": 4, "failed": 0}},
            "play_tests": {"counts": {"total": 2, "passed": 2, "failed": 0}},
        }

    def build(self, behaviour=None, *, licence="active", **kwargs):
        merged = self.passing()
        merged.update(behaviour or {})
        adapter = self.adapter(merged, licence=licence, **kwargs)
        return adapter.verify_and_build(
            self.project, build_method="Lokvetia.Build.Run",
            build_target="StandaloneWindows64", output=self.output,
            source_commit="abc1234",
        )


class HealthTest(UnityFixture):
    def test_a_missing_editor_is_unavailable(self) -> None:
        adapter = UnityAdapter(executable_candidates=("unity-not-installed",))
        health = adapter.health()
        self.assertFalse(health.healthy)
        self.assertIsNone(health.executable)

    def test_a_pinned_editor_with_an_active_licence_is_healthy(self) -> None:
        health = self.adapter().health()
        self.assertTrue(health.healthy, health.reason)
        self.assertEqual(health.version, DEFAULT_EDITOR)
        self.assertTrue(health.licence_active)

    def test_an_inactive_licence_blocks_health(self) -> None:
        health = self.adapter(licence="inactive").health()
        self.assertFalse(health.healthy)
        self.assertTrue(health.version_supported)
        self.assertIn("a person has to activate it", health.reason)

    def test_no_licence_probe_means_no_licence(self) -> None:
        health = self.adapter(licence=None).health()
        self.assertFalse(health.healthy)
        self.assertFalse(health.licence_active)

    def test_an_unpinned_editor_is_refused(self) -> None:
        health = self.adapter({"version": "2019.4.40f1"}).health()
        self.assertFalse(health.healthy)
        self.assertFalse(health.version_supported)
        self.assertIn("outside the pinned range", health.reason)

    def test_an_unreadable_version_fails(self) -> None:
        health = self.adapter({"version": "who knows"}).health()
        self.assertFalse(health.healthy)
        self.assertIn("could not be identified", health.reason)


class ClassifyTest(unittest.TestCase):
    def test_a_clean_exit_with_a_compile_error_is_a_failure(self) -> None:
        status, detail = classify(0, "Assets/P.cs(1,1): error CS1002: ; expected")
        self.assertEqual(status, "failed")
        self.assertIn("compile error", detail)

    def test_known_failure_shapes_are_recognised(self) -> None:
        cases = (
            ("Build completed with a result of 'Failed'", "build failed"),
            ("No valid Unity Editor license found", "licence not active"),
            ("Multiple Unity instances cannot open the same project", "editor already running"),
            ("Failed to resolve packages: something", "package resolution failed"),
            ("Aborting batchmode due to failure", "batchmode aborted"),
            ("Compilation failed", "compilation failed"),
        )
        for log, label in cases:
            with self.subTest(label=label):
                status, detail = classify(0, log)
                self.assertEqual(status, "failed")
                self.assertIn(label, detail)

    def test_a_clean_log_and_exit_succeeds(self) -> None:
        self.assertEqual(classify(0, "Exiting batchmode successfully")[0], "succeeded")

    def test_a_non_zero_exit_fails_even_on_a_clean_log(self) -> None:
        self.assertEqual(classify(2, "nothing to see")[0], "failed")


class OperationTest(UnityFixture):
    def test_import_succeeds_and_fails_on_its_log(self) -> None:
        self.assertTrue(self.adapter().import_project(self.project).succeeded)
        run = self.adapter(
            {"import": {"exit": 0, "log": "Assets/A.cs(3,1): error CS0103: missing"}}
        ).import_project(self.project)
        self.assertEqual(run.status, "failed")
        self.assertIn("compile error", run.detail)

    def test_a_missing_project_is_refused_before_launch(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.adapter().import_project(self.root / "nothing")

    def test_tests_are_read_from_the_results_file(self) -> None:
        run = self.adapter(self.passing()).run_tests(self.project, platform="EditMode")
        self.assertTrue(run.succeeded, run.detail)
        self.assertEqual(run.tests.total, 4)
        self.assertTrue(run.tests.parsed)
        self.assertEqual(run.evidence_kind, "edit_mode_tests")

    def test_a_failing_test_fails_the_run_despite_a_clean_log(self) -> None:
        run = self.adapter(
            {"edit_tests": {"counts": {"total": 4, "passed": 3, "failed": 1}}}
        ).run_tests(self.project, platform="EditMode")
        self.assertEqual(run.status, "failed")
        self.assertIn("1 test(s) failed", run.detail)

    def test_a_missing_results_file_is_not_a_pass(self) -> None:
        run = self.adapter({"edit_tests": {}}).run_tests(self.project)
        self.assertEqual(run.status, "failed")
        self.assertIn("no test results file", run.detail)
        self.assertFalse(run.tests.parsed)

    def test_play_mode_is_recorded_as_runtime_evidence(self) -> None:
        run = self.adapter(self.passing()).run_tests(self.project, platform="PlayMode")
        self.assertEqual(run.evidence_kind, "play_mode_runtime")

    def test_an_unknown_test_platform_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.adapter().run_tests(self.project, platform="Whatever")

    def test_a_build_needs_a_qualified_method_name(self) -> None:
        for method in ("", "Build", "   "):
            with self.subTest(method=method):
                with self.assertRaises(ValueError):
                    self.adapter().build(
                        self.project, build_method=method,
                        build_target="StandaloneWindows64", output=self.output,
                    )

    def test_a_timeout_is_recorded_without_an_exit_code(self) -> None:
        run = self.adapter(
            {"import": {"sleep": 5}}, max_seconds=1
        ).import_project(self.project)
        self.assertEqual(run.status, "timeout")
        self.assertIsNone(run.exit_code)

    def test_the_log_is_bounded(self) -> None:
        run = self.adapter(
            {"import": {"log": "x" * 5000}}, max_output_chars=200
        ).import_project(self.project)
        self.assertLess(len(run.log), 400)
        self.assertIn("truncated", run.log)

    def test_results_reader_handles_a_broken_file(self) -> None:
        broken = self.root / "broken.xml"
        broken.write_text("<not-xml", encoding="utf-8")
        self.assertFalse(read_test_results(broken).parsed)
        self.assertFalse(read_test_results(self.root / "absent.xml").parsed)


class VerifyAndBuildTest(UnityFixture):
    def test_a_full_pass_records_a_checksummed_artifact(self) -> None:
        artifact = self.build()
        self.assertTrue(artifact.succeeded, artifact.failure)
        self.assertEqual(
            [run.operation for run in artifact.runs],
            ["import_project", "edit_mode_tests", "play_mode_tests", "build"],
        )
        self.assertEqual(len(artifact.artifact_checksum or ""), 64)
        self.assertEqual(artifact.project_editor_version, DEFAULT_EDITOR)
        self.assertEqual(len(artifact.packages_lock_digest), 64)
        self.assertEqual(artifact.build_target, "StandaloneWindows64")

    def test_a_headless_pass_never_claims_a_played_game(self) -> None:
        artifact = self.build()
        self.assertFalse(artifact.graphical_playtest)
        self.assertIn(PLAYED_GAME_EVIDENCE, artifact.evidence_gap)
        self.assertIn(PLAYED_GAME_EVIDENCE, artifact.manifest["evidence_gap"])

    def test_an_inactive_licence_stops_everything(self) -> None:
        artifact = self.build(licence="inactive")
        self.assertFalse(artifact.succeeded)
        self.assertEqual([run.operation for run in artifact.runs], ["version_probe"])
        self.assertIn("licence is not active", artifact.runs[0].detail)

    def test_a_compile_error_stops_before_the_tests(self) -> None:
        artifact = self.build({"import": {"log": "Assets/A.cs(1,1): error CS0103: x"}})
        self.assertEqual([run.operation for run in artifact.runs], ["import_project"])
        self.assertIsNone(artifact.artifact_checksum)

    def test_a_failing_edit_mode_test_stops_before_play_mode(self) -> None:
        artifact = self.build(
            {"edit_tests": {"counts": {"total": 2, "passed": 1, "failed": 1}}}
        )
        self.assertEqual(
            [run.operation for run in artifact.runs],
            ["import_project", "edit_mode_tests"],
        )
        self.assertIn("play_mode_runtime", artifact.evidence_gap)

    def test_a_build_that_reports_failed_is_not_an_artifact(self) -> None:
        artifact = self.build(
            {"build": {"write": False, "log": "Build completed with a result of 'Failed'"}}
        )
        self.assertFalse(artifact.succeeded)
        self.assertIn("build failed", (artifact.failure or artifact.runs[-1]).detail)

    def test_success_without_an_artifact_file_is_a_failure(self) -> None:
        artifact = self.build({"build": {"write": False}})
        self.assertFalse(artifact.succeeded)
        self.assertIn(
            "no artifact file", (artifact.failure or artifact.runs[-1]).detail,
        )

    def test_the_manifest_is_serialisable_evidence(self) -> None:
        payload = json.loads(json.dumps(self.build().manifest))
        self.assertEqual(payload["engine"], "unity")
        self.assertEqual(payload["source_commit"], "abc1234")
        self.assertEqual(len(payload["runs"]), 4)
        self.assertFalse(payload["graphical_playtest"])


if __name__ == "__main__":
    unittest.main()


class LedgerIntegrationTest(UnityFixture):
    def test_a_unity_build_promotes_through_the_engine_neutral_ledger(self) -> None:
        from agent_factory.playable_versions import CandidateBuild, PlayableVersions
        from agent_factory.storage import SQLiteStorage

        artifact = self.build()
        storage = SQLiteStorage(self.root / "playable.db")
        self.addCleanup(storage.close)
        versions = PlayableVersions(storage)
        candidate = CandidateBuild.from_artifact(artifact.promotable, engine="unity")
        self.assertEqual(candidate.engine_version, DEFAULT_EDITOR)
        self.assertEqual(candidate.preset, "StandaloneWindows64")

        result = versions.promote(
            "unity-demo", candidate, command_id="rel-1", actor="miha",
        )
        self.assertEqual(result.outcome, "promoted")
        current = versions.current("unity-demo")
        self.assertEqual(current.engine, "unity")
        self.assertIn(PLAYED_GAME_EVIDENCE, current.evidence_gap)

    def test_a_failed_unity_build_is_refused_by_the_ledger(self) -> None:
        from agent_factory.playable_versions import CandidateBuild, PlayableVersions
        from agent_factory.storage import SQLiteStorage

        artifact = self.build({"build": {"write": False}})
        storage = SQLiteStorage(self.root / "playable.db")
        self.addCleanup(storage.close)
        versions = PlayableVersions(storage)
        result = versions.promote(
            "unity-demo",
            CandidateBuild.from_artifact(artifact.promotable, engine="unity"),
            command_id="rel-1", actor="miha",
        )
        self.assertEqual(result.outcome, "rejected")
        self.assertIsNone(versions.current("unity-demo"))
