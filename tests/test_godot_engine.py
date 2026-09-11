"""Godot adapter: real engine execution, bounded logs, and honest evidence."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_factory.godot_engine import (
    PLAYED_GAME_EVIDENCE,
    REQUIRED_FLAGS,
    BuildArtifact,
    GodotAdapter,
    engine_series,
)
from agent_factory.godot_pack import GodotPack


FAKE_ENGINE = '''
import json, os, sys, time

config = json.loads(open(sys.argv[1], encoding="utf-8").read())
arguments = sys.argv[2:]


def finish(behaviour, *, default_code=0):
    time.sleep(float(behaviour.get("sleep", 0)))
    sys.stdout.write(behaviour.get("stdout", ""))
    sys.stderr.write(behaviour.get("stderr", ""))
    sys.exit(int(behaviour.get("exit", default_code)))


if "--version" in arguments:
    sys.stdout.write(config.get("version", "4.3.stable.official") + "\\n")
    sys.exit(int(config.get("version_exit", 0)))

if "--help" in arguments:
    flags = config.get("flags")
    if flags is None:
        flags = %(required)s
    sys.stdout.write("Usage: godot [options]\\n" + "\\n".join(flags) + "\\n")
    sys.exit(int(config.get("help_exit", 0)))

if "--import" in arguments:
    finish(config.get("import", {}))

if "--check-only" in arguments:
    finish(config.get("script_check", {}))

if "--quit-after" in arguments:
    finish(config.get("headless_smoke", {}))

if "--export-release" in arguments:
    behaviour = config.get("export", {})
    destination = arguments[-1]
    if behaviour.get("write", True) and int(behaviour.get("exit", 0)) == 0:
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        with open(destination, "wb") as handle:
            handle.write(behaviour.get("payload", "binary").encode("utf-8"))
    finish(behaviour)

sys.stderr.write("unexpected invocation: " + " ".join(arguments) + "\\n")
sys.exit(3)
''' % {"required": json.dumps(list(REQUIRED_FLAGS))}


class GodotAdapterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.engine = self.root / "fake_godot.py"
        self.engine.write_text(FAKE_ENGINE, encoding="utf-8")
        self.config = self.root / "engine.json"
        self.pack = GodotPack()
        self.project = self.root / "project"
        self.pack.apply(self.pack.plan(self.project, "collector-2d"))
        self.scripts = ("scripts/main.gd", "scripts/player.gd")

    def adapter(self, behaviour: dict | None = None, **kwargs) -> GodotAdapter:
        self.config.write_text(json.dumps(behaviour or {}), encoding="utf-8")
        return GodotAdapter(
            executable_candidates=(sys.executable,),
            executable_args=(str(self.engine), str(self.config)),
            **kwargs,
        )


class GodotHealthTest(GodotAdapterTestCase):
    def test_missing_executable_is_unavailable(self) -> None:
        adapter = GodotAdapter(executable_candidates=("godot-that-is-not-installed",))
        health = adapter.health()
        self.assertFalse(health.healthy)
        self.assertIsNone(health.executable)
        self.assertEqual(health.missing_flags, REQUIRED_FLAGS)

    def test_qualified_engine_is_healthy(self) -> None:
        health = self.adapter().health()
        self.assertTrue(health.healthy, health.reason)
        self.assertEqual(health.version, "4.3.stable.official")
        self.assertTrue(health.interface_qualified)
        self.assertEqual(health.missing_flags, ())

    def test_unsupported_engine_series_is_refused(self) -> None:
        health = self.adapter({"version": "3.5.3.stable.official"}).health()
        self.assertFalse(health.healthy)
        self.assertFalse(health.version_supported)
        self.assertIn("outside the supported range", health.reason)

    def test_missing_flags_fail_interface_qualification(self) -> None:
        health = self.adapter({"flags": ["--headless", "--path"]}).health()
        self.assertFalse(health.healthy)
        self.assertFalse(health.interface_qualified)
        self.assertIn("--export-release", health.missing_flags)

    def test_unreadable_version_output_fails(self) -> None:
        health = self.adapter({"version": "not-a-version"}).health()
        self.assertFalse(health.healthy)
        self.assertIn("version could not be identified", health.reason)

    def test_engine_series(self) -> None:
        self.assertEqual(engine_series("4.3.stable.official"), "4.3")
        self.assertEqual(engine_series("4"), "4")


class GodotOperationTest(GodotAdapterTestCase):
    def test_import_success_and_failure(self) -> None:
        run = self.adapter().import_project(self.project)
        self.assertTrue(run.succeeded)
        self.assertEqual(run.exit_code, 0)
        self.assertEqual(run.evidence_kind, "engine_import")

        failed = self.adapter({"import": {"exit": 1, "stderr": "cannot open"}})
        run = failed.import_project(self.project)
        self.assertEqual(run.status, "failed")
        self.assertIn("exited with code 1", run.detail)

    def test_missing_project_is_refused_before_launch(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.adapter().import_project(self.root / "nothing")

    def test_script_error_fails_even_with_exit_code_zero(self) -> None:
        adapter = self.adapter({
            "script_check": {"exit": 0, "stderr": "SCRIPT ERROR: Parse Error: Unexpected token"},
        })
        runs = adapter.check_scripts(self.project, self.scripts)
        self.assertEqual(runs[0].status, "failed")
        self.assertIn("SCRIPT ERROR", runs[0].detail)

    def test_script_check_is_labelled_static_evidence(self) -> None:
        runs = self.adapter().check_scripts(self.project, ("scripts/main.gd",))
        self.assertEqual(runs[0].evidence_kind, "static_script_check")
        self.assertIn("res://scripts/main.gd", runs[0].command)

    def test_script_check_requires_scripts(self) -> None:
        with self.assertRaises(ValueError):
            self.adapter().check_scripts(self.project, ())

    def test_crash_is_reported_as_failure(self) -> None:
        adapter = self.adapter({
            "headless_smoke": {"exit": 0, "stderr": "Program crashed with signal 11"},
        })
        run = adapter.headless_smoke(self.project, frames=30)
        self.assertEqual(run.status, "failed")
        self.assertIn("crashed", run.detail)

    def test_timeout_is_recorded_without_an_exit_code(self) -> None:
        adapter = self.adapter({"headless_smoke": {"sleep": 5}}, max_seconds=1)
        run = adapter.headless_smoke(self.project, frames=30)
        self.assertEqual(run.status, "timeout")
        self.assertIsNone(run.exit_code)
        self.assertIn("exceeded 1s", run.detail)

    def test_output_is_bounded(self) -> None:
        adapter = self.adapter(
            {"headless_smoke": {"stdout": "x" * 5000}}, max_output_chars=200,
        )
        run = adapter.headless_smoke(self.project, frames=30)
        self.assertLess(len(run.stdout), 400)
        self.assertIn("truncated", run.stdout)

    def test_undeclared_preset_never_launches_the_engine(self) -> None:
        run = self.adapter().export(
            self.project, preset="playstation", output=self.root / "out.bin",
        )
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.command, ())
        self.assertIn("not declared", run.detail)

    def test_missing_export_templates_fail(self) -> None:
        adapter = self.adapter({
            "export": {
                "exit": 0, "write": False,
                "stderr": "No export template found at the expected path",
            },
        })
        run = adapter.export(
            self.project, preset="linux-x86_64", output=self.root / "build/game.x86_64",
        )
        self.assertEqual(run.status, "failed")
        self.assertIn("No export template", run.detail)

    def test_frames_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            self.adapter().headless_smoke(self.project, frames=0)


class GodotBuildTest(GodotAdapterTestCase):
    def build(self, behaviour: dict | None = None, **kwargs) -> BuildArtifact:
        adapter = self.adapter(behaviour, **kwargs)
        return adapter.build(
            self.project,
            preset="linux-x86_64",
            output=self.root / "build/game.x86_64",
            template_id="collector-2d",
            template_version="1.0.0",
            project_digest=self.pack.project_digest(self.project, "collector-2d"),
            scripts=self.scripts,
            source_commit="abc1234",
            frames=30,
        )

    def test_successful_build_records_a_checksummed_artifact(self) -> None:
        artifact = self.build()
        self.assertTrue(artifact.succeeded, artifact.failure)
        self.assertEqual(artifact.engine_version, "4.3.stable.official")
        self.assertEqual(artifact.source_commit, "abc1234")
        self.assertEqual(artifact.preset, "linux-x86_64")
        self.assertEqual(len(artifact.artifact_checksum or ""), 64)
        self.assertGreater(artifact.artifact_bytes or 0, 0)
        operations = [run.operation for run in artifact.runs]
        self.assertEqual(
            operations,
            ["import", "script_check", "script_check", "headless_smoke", "export"],
        )
        self.assertEqual(len(artifact.digest), 64)

    def test_headless_success_never_claims_a_played_game(self) -> None:
        artifact = self.build()
        self.assertFalse(artifact.graphical_playtest)
        self.assertIn(PLAYED_GAME_EVIDENCE, artifact.evidence_gap)
        self.assertIn(PLAYED_GAME_EVIDENCE, artifact.manifest["evidence_gap"])

    def test_build_stops_at_the_first_failure(self) -> None:
        artifact = self.build({"import": {"exit": 1, "stderr": "broken"}})
        self.assertFalse(artifact.succeeded)
        self.assertEqual([run.operation for run in artifact.runs], ["import"])
        self.assertIsNone(artifact.artifact_checksum)
        self.assertEqual((artifact.failure or artifact.runs[0]).operation, "import")

    def test_script_failure_skips_runtime_and_export(self) -> None:
        artifact = self.build({"script_check": {"exit": 0, "stderr": "SCRIPT ERROR: bad"}})
        self.assertEqual(
            [run.operation for run in artifact.runs], ["import", "script_check"],
        )
        self.assertIn("headless_runtime", artifact.evidence_gap)

    def test_unhealthy_engine_never_starts_a_build(self) -> None:
        artifact = self.build({"version": "3.5.stable.official"})
        self.assertFalse(artifact.succeeded)
        self.assertEqual([run.operation for run in artifact.runs], ["version_probe"])
        self.assertIn("outside the supported range", artifact.runs[0].detail)

    def test_export_success_without_an_artifact_file_is_a_failure(self) -> None:
        artifact = self.build({"export": {"exit": 0, "write": False}})
        self.assertFalse(artifact.succeeded)
        self.assertIsNone(artifact.artifact_checksum)
        self.assertIn("no artifact file", (artifact.failure or artifact.runs[-1]).detail)

    def test_manifest_is_serialisable_evidence(self) -> None:
        manifest = self.build().manifest
        payload = json.loads(json.dumps(manifest))
        self.assertEqual(payload["template_id"], "collector-2d")
        self.assertEqual(payload["source_commit"], "abc1234")
        self.assertEqual(len(payload["runs"]), 5)
        self.assertFalse(payload["graphical_playtest"])


if __name__ == "__main__":
    unittest.main()
