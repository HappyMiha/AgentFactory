"""An update never moves a pinned engine on its own, and never loses a game."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_factory.application_update import (
    ApplicationUpdater,
    PinnedRequirement,
    ProjectPin,
    UpdateManifest,
    UpdateRefused,
    uninstall,
    uninstall_plan,
)

SECRET = b"trust-root-material"
OTHER_SECRET = b"a different key"


def manifest(
    *,
    version: str = "0.2.0",
    minimum: str = "0.1.0",
    schema: int = 80,
    engines=(),
    models=(),
    key_id: str = "release",
) -> UpdateManifest:
    return UpdateManifest.create(
        version=version, minimum_current_version=minimum, schema_target=schema,
        key_id=key_id, engines=engines, models=models,
        migrations=("079_add_table", "080_backfill"), notes="routine update",
    )


class UpdaterFixture(unittest.TestCase):
    """Shared helpers; no test methods are inherited by the suites below."""

    def setUp(self) -> None:
        self.updater = ApplicationUpdater(
            current_version="0.1.0", current_schema=78,
            trust_material={"release": SECRET},
        )
        self.signed = ApplicationUpdater.sign(manifest(), SECRET)
        self.backups: list[str] = []
        self.restored: list[str] = []

    def backup(self) -> str:
        self.backups.append("backup-1")
        return "backup-1"

    def restore(self, path: str) -> None:
        self.restored.append(path)


class SignatureTest(UpdaterFixture):
    def test_a_signed_update_verifies(self) -> None:
        self.assertTrue(self.updater.verify(self.signed))
        self.assertTrue(self.updater.plan(self.signed).signature_verified)

    def test_an_unsigned_update_is_blocked(self) -> None:
        plan = self.updater.plan(manifest())
        self.assertFalse(plan.signature_verified)
        self.assertFalse(plan.allowed)
        self.assertIn("not signed by an approved trust root", plan.blocking[0])

    def test_a_foreign_key_does_not_verify(self) -> None:
        forged = ApplicationUpdater.sign(manifest(), OTHER_SECRET)
        self.assertFalse(self.updater.verify(forged))

    def test_an_unknown_trust_root_does_not_verify(self) -> None:
        stranger = ApplicationUpdater.sign(manifest(key_id="someone-else"), SECRET)
        self.assertFalse(self.updater.verify(stranger))

    def test_tampering_with_the_manifest_breaks_the_signature(self) -> None:
        from dataclasses import replace

        tampered = replace(self.signed, notes="now with extra behaviour")
        self.assertFalse(self.updater.verify(tampered))

    def test_manifest_input_is_validated(self) -> None:
        with self.assertRaises(ValueError):
            UpdateManifest.create(
                version="two", minimum_current_version="0.1.0",
                schema_target=80, key_id="release",
            )
        with self.assertRaises(ValueError):
            UpdateManifest.create(
                version="0.2.0", minimum_current_version="0.1.0",
                schema_target=0, key_id="release",
            )
        with self.assertRaises(ValueError):
            UpdateManifest.create(
                version="0.2.0", minimum_current_version="0.1.0",
                schema_target=80, key_id="  ",
            )
        with self.assertRaises(ValueError):
            UpdateManifest.create(
                version="0.2.0", minimum_current_version="0.1.0", schema_target=80,
                key_id="release",
                engines=(PinnedRequirement("godot", "4.3"), PinnedRequirement("godot", "4.4")),
            )


class CompatibilityTest(UpdaterFixture):
    def test_an_older_or_equal_update_is_refused(self) -> None:
        for version in ("0.1.0", "0.0.9"):
            with self.subTest(version=version):
                plan = self.updater.plan(
                    ApplicationUpdater.sign(manifest(version=version), SECRET)
                )
                self.assertFalse(plan.allowed)
                self.assertIn("not newer", plan.blocking[0])

    def test_an_update_that_needs_a_newer_base_is_refused(self) -> None:
        plan = self.updater.plan(
            ApplicationUpdater.sign(manifest(minimum="0.5.0"), SECRET)
        )
        self.assertFalse(plan.allowed)
        self.assertIn("requires 0.5.0 or newer", plan.blocking[0])

    def test_a_backwards_schema_target_is_refused(self) -> None:
        plan = self.updater.plan(
            ApplicationUpdater.sign(manifest(schema=70), SECRET)
        )
        self.assertFalse(plan.allowed)
        self.assertIn("schema 78 is already applied", plan.blocking[0])

    def test_a_clean_update_is_allowed(self) -> None:
        plan = self.updater.plan(self.signed, projects=[
            ProjectPin("my-game", engine="godot", engine_version="4.3"),
        ])
        self.assertTrue(plan.allowed, plan.blocking)
        self.assertEqual(plan.preview()["to_version"], "0.2.0")
        self.assertEqual(plan.preview()["migrations"], ["079_add_table", "080_backfill"])


class PinnedChangeTest(UpdaterFixture):
    def signed_with_engine(self, version: str = "4.4"):
        return ApplicationUpdater.sign(
            manifest(engines=(PinnedRequirement("godot", version),)), SECRET,
        )

    def test_moving_a_pinned_engine_needs_its_own_plan(self) -> None:
        plan = self.updater.plan(
            self.signed_with_engine(),
            projects=[ProjectPin("my-game", engine="godot", engine_version="4.3")],
        )
        self.assertTrue(plan.requires_separate_plan)
        self.assertFalse(plan.allowed)
        self.assertEqual(plan.pinned_changes[0].current, "4.3")
        self.assertEqual(plan.pinned_changes[0].proposed, "4.4")

    def test_a_declared_separate_plan_unblocks_the_pin_change(self) -> None:
        plan = self.updater.plan(
            self.signed_with_engine(),
            projects=[ProjectPin("my-game", engine="godot", engine_version="4.3")],
            separate_plan="engine-migration-2026-09",
        )
        self.assertFalse(plan.requires_separate_plan)
        self.assertTrue(plan.allowed, plan.blocking)

    def test_a_matching_pin_is_not_a_change(self) -> None:
        plan = self.updater.plan(
            self.signed_with_engine("4.3"),
            projects=[ProjectPin("my-game", engine="godot", engine_version="4.3")],
        )
        self.assertEqual(plan.pinned_changes, ())
        self.assertTrue(plan.allowed, plan.blocking)

    def test_a_model_pin_is_treated_like_an_engine_pin(self) -> None:
        signed = ApplicationUpdater.sign(
            manifest(models=(PinnedRequirement("local-7b", "2.0"),)), SECRET,
        )
        plan = self.updater.plan(
            signed,
            projects=[ProjectPin("my-game", model="local-7b", model_version="1.4")],
        )
        self.assertEqual(plan.pinned_changes[0].kind, "model_pin")
        self.assertFalse(plan.allowed)

    def test_projects_that_do_not_use_the_pin_are_unaffected(self) -> None:
        plan = self.updater.plan(
            self.signed_with_engine(),
            projects=[ProjectPin("other", engine="unity", engine_version="2022")],
        )
        self.assertEqual(plan.pinned_changes, ())
        self.assertTrue(plan.allowed, plan.blocking)

    def test_one_pin_change_is_reported_once_across_projects(self) -> None:
        plan = self.updater.plan(
            self.signed_with_engine(),
            projects=[
                ProjectPin("a", engine="godot", engine_version="4.3"),
                ProjectPin("b", engine="godot", engine_version="4.3"),
            ],
        )
        self.assertEqual(len(plan.pinned_changes), 1)
        self.assertEqual(len(plan.issues), 2)


class ApplyTest(UpdaterFixture):
    def test_a_successful_update_records_its_steps(self) -> None:
        done: list[str] = []
        receipt = self.updater.apply(
            self.updater.plan(self.signed), actor="miha",
            backup=self.backup, restore=self.restore,
            steps=[
                ("migrate", lambda: done.append("migrate")),
                ("install", lambda: done.append("install")),
            ],
        )
        self.assertEqual(receipt.outcome, "applied")
        self.assertEqual(receipt.version_after, "0.2.0")
        self.assertEqual(receipt.completed_steps, ("migrate", "install"))
        self.assertEqual(done, ["migrate", "install"])
        self.assertEqual(self.restored, [])

    def test_a_failing_step_rolls_the_whole_update_back(self) -> None:
        def broken() -> None:
            raise RuntimeError("migration hit a constraint")

        receipt = self.updater.apply(
            self.updater.plan(self.signed), actor="miha",
            backup=self.backup, restore=self.restore,
            steps=[("migrate", broken), ("install", lambda: None)],
        )
        self.assertEqual(receipt.outcome, "rolled_back")
        self.assertEqual(receipt.failed_step, "migrate")
        self.assertEqual(receipt.version_after, "0.1.0")
        self.assertIn("migration hit a constraint", receipt.reason)
        self.assertEqual(self.restored, ["backup-1"])

    def test_an_interrupted_later_step_still_rolls_everything_back(self) -> None:
        receipt = self.updater.apply(
            self.updater.plan(self.signed), actor="miha",
            backup=self.backup, restore=self.restore,
            steps=[
                ("migrate", lambda: None),
                ("install", lambda: (_ for _ in ()).throw(OSError("disk full"))),
            ],
        )
        self.assertEqual(receipt.outcome, "rolled_back")
        self.assertEqual(receipt.completed_steps, ("migrate",))
        self.assertEqual(self.restored, ["backup-1"])

    def test_a_blocked_plan_never_runs_a_step_or_a_backup(self) -> None:
        ran: list[str] = []
        receipt = self.updater.apply(
            self.updater.plan(manifest()), actor="miha",
            backup=self.backup, restore=self.restore,
            steps=[("migrate", lambda: ran.append("migrate"))],
        )
        self.assertEqual(receipt.outcome, "refused")
        self.assertEqual(ran, [])
        self.assertEqual(self.backups, [])

    def test_an_update_requires_an_approver_and_steps(self) -> None:
        plan = self.updater.plan(self.signed)
        with self.assertRaises(ValueError):
            self.updater.apply(
                plan, actor="  ", backup=self.backup, restore=self.restore,
                steps=[("migrate", lambda: None)],
            )
        with self.assertRaises(ValueError):
            self.updater.apply(
                plan, actor="miha", backup=self.backup, restore=self.restore, steps=[],
            )

    def test_an_update_never_runs_without_a_backup(self) -> None:
        with self.assertRaises(UpdateRefused):
            self.updater.apply(
                self.updater.plan(self.signed), actor="miha",
                backup=lambda: "", restore=self.restore,
                steps=[("migrate", lambda: None)],
            )


class UninstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name)
        (self.workspace / ".agent-factory").mkdir()
        self.game = self.workspace / "games" / "collector"
        self.game.mkdir(parents=True)
        self.removed: list[str] = []

    def remove(self, path: str) -> None:
        self.removed.append(path)

    def test_games_are_preserved_by_default(self) -> None:
        plan = uninstall_plan(self.workspace, project_paths=[self.game])
        self.assertFalse(plan.removes_projects)
        self.assertEqual(plan.preserved, (str(self.game),))
        self.assertIn("Your games are kept", plan.preview()["note"])

        result = uninstall(plan, actor="miha", remove=self.remove)
        self.assertEqual(self.removed, [str(self.workspace / ".agent-factory")])
        self.assertEqual(result["preserved"], [str(self.game)])

    def test_removing_games_needs_a_second_confirmation(self) -> None:
        plan = uninstall_plan(
            self.workspace, project_paths=[self.game], remove_projects=True,
        )
        with self.assertRaises(UpdateRefused):
            uninstall(plan, actor="miha", remove=self.remove)
        self.assertEqual(self.removed, [])

        uninstall(
            plan, actor="miha", confirm_project_removal=True, remove=self.remove,
        )
        self.assertIn(str(self.game), self.removed)

    def test_an_uninstall_records_who_asked(self) -> None:
        plan = uninstall_plan(self.workspace, project_paths=[self.game])
        with self.assertRaises(ValueError):
            uninstall(plan, actor=" ", remove=self.remove)
        self.assertEqual(self.removed, [])

    def test_a_project_inside_application_state_is_refused(self) -> None:
        nested = self.workspace / ".agent-factory" / "games"
        nested.mkdir()
        with self.assertRaises(UpdateRefused):
            uninstall_plan(self.workspace, project_paths=[nested])

    def test_the_preview_separates_application_state_from_games(self) -> None:
        preview = uninstall_plan(
            self.workspace, project_paths=[self.game],
        ).preview()
        self.assertEqual(preview["removes"], [str(self.workspace / ".agent-factory")])
        self.assertEqual(preview["preserves"], [str(self.game)])
        self.assertEqual(len(preview["plan_digest"]), 64)


if __name__ == "__main__":
    unittest.main()
