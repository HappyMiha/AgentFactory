"""The playable pointer moves only for a fully verified, reproducible build."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_factory.playable_versions import (
    CandidateBuild,
    PlayableVersions,
)
from agent_factory.storage import SQLiteStorage


def build(
    *,
    commit: str = "aaaa111",
    checksum: str | None = None,
    succeeded: bool = True,
    runs: tuple[dict, ...] | None = None,
    project_digest: str = "project-digest-1",
    preset: str = "linux-x86_64",
    path: str = "/builds/game.x86_64",
    size: int = 2048,
    failure_reason: str = "",
) -> CandidateBuild:
    payload = checksum or hashlib.sha256(commit.encode()).hexdigest()
    return CandidateBuild(
        engine="godot",
        engine_version="4.3.stable.official",
        source_commit=commit,
        project_digest=project_digest,
        template_id="collector-2d",
        template_version="1.0.0",
        preset=preset,
        artifact_path=path,
        artifact_checksum=payload,
        artifact_bytes=size,
        succeeded=succeeded,
        verification=runs if runs is not None else (
            {"operation": "import", "status": "succeeded"},
            {"operation": "headless_smoke", "status": "succeeded"},
            {"operation": "export", "status": "succeeded"},
        ),
        evidence_gap=("graphical_playtest",),
        failure_reason=failure_reason,
    )


class PlayableVersionsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.storage = SQLiteStorage(self.root / "playable.db")
        self.addCleanup(self.storage.close)
        self.versions = PlayableVersions(self.storage)
        self.project = "collector-demo"

    def promote(self, candidate: CandidateBuild, command: str):
        return self.versions.promote(
            self.project, candidate, command_id=command, actor="miha",
        )


class PromotionTest(PlayableVersionsTestCase):
    def test_verified_build_becomes_the_playable_version(self) -> None:
        result = self.promote(build(), "cmd-1")
        self.assertEqual(result.outcome, "promoted")
        self.assertTrue(result.accepted)
        self.assertTrue(result.pointer_moved)
        current = self.versions.current(self.project)
        self.assertIsNotNone(current)
        self.assertEqual(current.source_commit, "aaaa111")
        checkpoint = current.checkpoint
        self.assertEqual(checkpoint["engine_version"], "4.3.stable.official")
        self.assertEqual(checkpoint["template_id"], "collector-2d")
        self.assertEqual(len(checkpoint["verification"]), 3)
        self.assertEqual(checkpoint["evidence_gap"], ["graphical_playtest"])
        self.assertEqual(self.versions.sequence(self.project), 1)

    def test_no_pointer_exists_before_the_first_verified_build(self) -> None:
        self.assertIsNone(self.versions.current(self.project))
        self.assertEqual(self.versions.sequence(self.project), 0)

    def test_failed_build_is_rejected_and_keeps_the_previous_version(self) -> None:
        self.promote(build(commit="good-1"), "cmd-1")
        first = self.versions.current(self.project)

        result = self.promote(
            build(commit="bad-1", succeeded=False, failure_reason="export failed"),
            "cmd-2",
        )
        self.assertEqual(result.outcome, "rejected")
        self.assertFalse(result.accepted)
        self.assertFalse(result.pointer_moved)
        self.assertEqual(result.reason, "export failed")
        self.assertEqual(self.versions.current(self.project).id, first.id)
        self.assertEqual(self.versions.sequence(self.project), 1)
        self.assertEqual(len(self.versions.history(self.project)), 1)

    def test_failed_verification_run_rejects_a_build_that_claims_success(self) -> None:
        candidate = build(
            commit="mixed-1",
            runs=(
                {"operation": "import", "status": "succeeded"},
                {"operation": "script_check", "status": "failed"},
            ),
        )
        result = self.promote(candidate, "cmd-1")
        self.assertEqual(result.outcome, "rejected")
        self.assertIn("script_check", result.reason)
        self.assertIsNone(self.versions.current(self.project))

    def test_build_without_artifact_evidence_is_rejected(self) -> None:
        for candidate, expected in (
            (build(checksum="short"), "checksum"),
            (build(size=0), "artifact file"),
            (build(runs=()), "verification runs"),
        ):
            with self.subTest(expected=expected):
                result = self.versions.promote(
                    self.project, candidate,
                    command_id=f"cmd-{expected}", actor="miha",
                )
                self.assertEqual(result.outcome, "rejected")
                self.assertIn(expected, result.reason)

    def test_second_verified_build_moves_the_pointer_forward(self) -> None:
        self.promote(build(commit="v1"), "cmd-1")
        result = self.promote(build(commit="v2"), "cmd-2")
        self.assertEqual(result.outcome, "promoted")
        self.assertEqual(result.previous.source_commit, "v1")
        self.assertEqual(self.versions.current(self.project).source_commit, "v2")
        self.assertEqual(self.versions.sequence(self.project), 2)
        self.assertEqual(len(self.versions.history(self.project)), 2)


class ReplayTest(PlayableVersionsTestCase):
    def test_repeated_command_returns_the_recorded_outcome_once(self) -> None:
        first = self.promote(build(), "cmd-1")
        again = self.promote(build(), "cmd-1")
        self.assertTrue(again.replayed)
        self.assertEqual(again.outcome, first.outcome)
        self.assertEqual(again.version.id, first.version.id)
        self.assertEqual(len(self.versions.history(self.project)), 1)
        self.assertEqual(self.versions.sequence(self.project), 1)

    def test_reusing_a_command_for_another_build_is_refused(self) -> None:
        self.promote(build(commit="v1"), "cmd-1")
        with self.assertRaises(PermissionError):
            self.promote(build(commit="v2"), "cmd-1")
        self.assertEqual(self.versions.current(self.project).source_commit, "v1")

    def test_replaying_a_rejection_does_not_promote_later(self) -> None:
        candidate = build(commit="bad", succeeded=False, failure_reason="broken")
        self.promote(candidate, "cmd-1")
        again = self.promote(candidate, "cmd-1")
        self.assertEqual(again.outcome, "rejected")
        self.assertTrue(again.replayed)
        self.assertIsNone(self.versions.current(self.project))

    def test_promoting_the_same_digest_again_is_unchanged(self) -> None:
        self.promote(build(), "cmd-1")
        result = self.promote(build(), "cmd-2")
        self.assertEqual(result.outcome, "unchanged")
        self.assertFalse(result.pointer_moved)
        self.assertEqual(len(self.versions.history(self.project)), 1)
        self.assertEqual(self.versions.sequence(self.project), 1)

    def test_an_earlier_build_can_be_pointed_at_again_without_duplication(self) -> None:
        self.promote(build(commit="v1"), "cmd-1")
        self.promote(build(commit="v2"), "cmd-2")
        result = self.promote(build(commit="v1"), "cmd-3")
        self.assertEqual(result.outcome, "promoted")
        self.assertTrue(result.pointer_moved)
        self.assertEqual(len(self.versions.history(self.project)), 2)
        self.assertEqual(self.versions.current(self.project).source_commit, "v1")

    def test_interrupted_promotion_leaves_no_partial_version(self) -> None:
        self.promote(build(commit="v1"), "cmd-1")
        stable = self.versions.current(self.project)
        with patch.object(
            PlayableVersions, "_record", side_effect=RuntimeError("interrupted")
        ):
            with self.assertRaises(RuntimeError):
                self.promote(build(commit="v2"), "cmd-2")
        self.assertEqual(self.versions.current(self.project).id, stable.id)
        self.assertEqual(len(self.versions.history(self.project)), 1)
        recorded = self.versions.promotions(self.project)
        self.assertEqual([entry["command_id"] for entry in recorded], ["cmd-1"])


class ReproducibilityTest(PlayableVersionsTestCase):
    def test_same_source_identity_with_a_new_checksum_is_flagged(self) -> None:
        self.promote(build(commit="v1", checksum="a" * 64), "cmd-1")
        result = self.promote(build(commit="v1", checksum="b" * 64), "cmd-2")
        self.assertEqual(result.outcome, "promoted")
        self.assertFalse(result.reproducible)
        self.assertIn("different artifact checksum", result.reason)

    def test_a_different_commit_is_not_a_reproducibility_problem(self) -> None:
        self.promote(build(commit="v1"), "cmd-1")
        result = self.promote(build(commit="v2"), "cmd-2")
        self.assertTrue(result.reproducible)


class RestoreTest(PlayableVersionsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.promote(build(commit="v1"), "cmd-1")
        self.first = self.versions.current(self.project)
        self.promote(build(commit="v2"), "cmd-2")

    def test_preview_describes_the_restore_without_changing_anything(self) -> None:
        preview = self.versions.restore_preview(
            self.project, self.first.version_digest, branch="restore/v1",
        )
        self.assertTrue(preview.changes_pointer)
        self.assertEqual(preview.preserved_versions, 2)
        self.assertFalse(preview.summary["history_rewritten"])
        self.assertEqual(self.versions.current(self.project).source_commit, "v2")

    def test_restore_creates_a_new_version_and_preserves_the_original(self) -> None:
        preview = self.versions.restore_preview(
            self.project, self.first.version_digest, branch="restore/v1",
        )
        result = self.versions.restore(
            self.project, self.first.version_digest, branch="restore/v1",
            command_id="cmd-3", actor="miha", preview=preview,
        )
        self.assertEqual(result.outcome, "restored")
        self.assertTrue(result.accepted)
        restored = self.versions.current(self.project)
        self.assertEqual(restored.source_commit, "v1")
        self.assertEqual(restored.restored_from_id, self.first.id)
        self.assertEqual(restored.restore_branch, "restore/v1")
        self.assertNotEqual(restored.id, self.first.id)
        self.assertEqual(len(self.versions.history(self.project)), 3)
        self.assertEqual(
            self.versions.version(self.project, self.first.version_digest).id,
            self.first.id,
        )

    def test_restore_is_replay_safe(self) -> None:
        first = self.versions.restore(
            self.project, self.first.version_digest, branch="restore/v1",
            command_id="cmd-3", actor="miha",
        )
        again = self.versions.restore(
            self.project, self.first.version_digest, branch="restore/v1",
            command_id="cmd-3", actor="miha",
        )
        self.assertTrue(again.replayed)
        self.assertEqual(again.version.id, first.version.id)
        self.assertEqual(len(self.versions.history(self.project)), 3)

    def test_restore_refuses_a_preview_from_another_target(self) -> None:
        preview = self.versions.restore_preview(
            self.project, self.first.version_digest, branch="restore/v1",
        )
        with self.assertRaises(ValueError):
            self.versions.restore(
                self.project, self.first.version_digest, branch="other-branch",
                command_id="cmd-3", actor="miha", preview=preview,
            )

    def test_restoring_a_restore_points_at_the_original_source(self) -> None:
        self.versions.restore(
            self.project, self.first.version_digest, branch="restore/v1",
            command_id="cmd-3", actor="miha",
        )
        restored = self.versions.current(self.project)
        self.versions.restore(
            self.project, restored.version_digest, branch="restore/v2",
            command_id="cmd-4", actor="miha",
        )
        self.assertEqual(
            self.versions.current(self.project).restored_from_id, self.first.id,
        )

    def test_unknown_version_cannot_be_restored(self) -> None:
        with self.assertRaises(KeyError):
            self.versions.restore(
                self.project, "f" * 64, branch="restore/x",
                command_id="cmd-3", actor="miha",
            )


class ArtifactVerificationTest(PlayableVersionsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.artifact = self.root / "game.x86_64"
        self.payload = b"playable-bytes"
        self.artifact.write_bytes(self.payload)
        self.promote(
            build(
                path=str(self.artifact),
                checksum=hashlib.sha256(self.payload).hexdigest(),
                size=len(self.payload),
            ),
            "cmd-1",
        )
        self.version = self.versions.current(self.project)

    def test_intact_artifact_verifies(self) -> None:
        ok, reason = self.versions.verify_artifact(self.version)
        self.assertTrue(ok, reason)

    def test_missing_artifact_fails_verification(self) -> None:
        self.artifact.unlink()
        ok, reason = self.versions.verify_artifact(self.version)
        self.assertFalse(ok)
        self.assertIn("missing", reason)

    def test_replaced_artifact_of_the_same_size_fails_verification(self) -> None:
        self.artifact.write_bytes(b"x" * len(self.payload))
        ok, reason = self.versions.verify_artifact(self.version)
        self.assertFalse(ok)
        self.assertIn("checksum", reason)

    def test_truncated_artifact_fails_verification(self) -> None:
        self.artifact.write_bytes(self.payload[:-1])
        ok, reason = self.versions.verify_artifact(self.version)
        self.assertFalse(ok)
        self.assertIn("size", reason)


class DurabilityTest(PlayableVersionsTestCase):
    def test_recorded_versions_and_promotions_cannot_be_rewritten(self) -> None:
        self.promote(build(), "cmd-1")
        for statement in (
            "UPDATE playable_versions SET source_commit='x'",
            "DELETE FROM playable_versions",
            "UPDATE playable_promotions SET outcome='rejected'",
            "DELETE FROM playable_promotions",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.IntegrityError):
                    with self.storage.db:
                        self.storage.db.execute(statement)

    def test_promotion_history_is_readable(self) -> None:
        self.promote(build(commit="v1"), "cmd-1")
        self.promote(build(commit="bad", succeeded=False), "cmd-2")
        history = self.versions.promotions(self.project)
        self.assertEqual([entry["outcome"] for entry in history], ["rejected", "promoted"])
        self.assertEqual(history[0]["actor"], "miha")


class InputTest(PlayableVersionsTestCase):
    def test_identifiers_are_validated(self) -> None:
        for key in ("", " ", "a/b", "x" * 200):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    self.versions.promote(
                        key, build(), command_id="cmd-1", actor="miha",
                    )
        with self.assertRaises(ValueError):
            self.versions.promote(self.project, build(), command_id="", actor="miha")
        with self.assertRaises(ValueError):
            self.versions.promote(self.project, build(), command_id="cmd-1", actor="")

    def test_history_limit_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            self.versions.history(self.project, limit=0)
        with self.assertRaises(ValueError):
            self.versions.history(self.project, limit=1000)


class EngineAdapterTest(PlayableVersionsTestCase):
    def test_a_godot_build_record_promotes_without_engine_coupling(self) -> None:
        from agent_factory.godot_engine import BuildArtifact, EngineRun

        smoke = EngineRun(
            "headless_smoke", "succeeded", 0, 30, ("godot",), "f" * 64,
            "headless_runtime", "", "", "completed",
        )
        run = EngineRun(
            "export", "succeeded", 0, 12, ("godot",), "d" * 64, "engine_export",
            "", "", "completed",
        )
        artifact = BuildArtifact(
            project_digest="pack-digest", source_commit="abc1234",
            engine_version="4.3.stable.official", template_id="collector-2d",
            template_version="1.0.0", preset="linux-x86_64",
            artifact_path="/builds/collector.x86_64",
            artifact_checksum="c" * 64, artifact_bytes=4096, runs=(smoke, run),
            recorded_at="2026-09-11T00:00:00+00:00",
        )
        candidate = CandidateBuild.from_artifact(artifact, engine="godot")
        self.assertTrue(candidate.succeeded)
        self.assertEqual(candidate.evidence_gap, ("graphical_playtest",))

        result = self.promote(candidate, "cmd-1")
        self.assertEqual(result.outcome, "promoted")
        self.assertEqual(
            self.versions.current(self.project).evidence_gap, ("graphical_playtest",),
        )

    def test_a_failed_godot_build_never_reaches_the_pointer(self) -> None:
        from agent_factory.godot_engine import BuildArtifact, EngineRun

        run = EngineRun(
            "import", "failed", 1, 9, ("godot",), "e" * 64, "engine_import",
            "", "", "engine exited with code 1",
        )
        artifact = BuildArtifact(
            project_digest="pack-digest", source_commit="abc1234",
            engine_version="4.3.stable.official", template_id="collector-2d",
            template_version="1.0.0", preset="linux-x86_64",
            artifact_path=None, artifact_checksum=None, artifact_bytes=None,
            runs=(run,), recorded_at="2026-09-11T00:00:00+00:00",
        )
        candidate = CandidateBuild.from_artifact(artifact, engine="godot")
        result = self.promote(candidate, "cmd-1")
        self.assertEqual(result.outcome, "rejected")
        self.assertIn("exited with code 1", result.reason)
        self.assertIsNone(self.versions.current(self.project))


if __name__ == "__main__":
    unittest.main()
