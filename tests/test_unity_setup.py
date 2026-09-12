"""Unity setup describes the work; the licence step stays with the person."""

from __future__ import annotations

import dataclasses
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_factory import unity_setup
from agent_factory.unity_setup import (
    DEFAULT_EDITOR,
    LICENCE_HANDOFF,
    NEVER_HANDLED,
    SUPPORTED_EDITORS,
    UNITY_HUB_MINIMUM,
    Installation,
    SetupBlocked,
    UnitySetup,
    detect,
    editor_series,
    read_project_requirement,
)

HEALTHY = Installation(
    hub_version="3.9.1",
    editors={DEFAULT_EDITOR: ("windows-il2cpp", "mac-mono")},
    licence_state="active",
    free_disk_bytes=200 * 1024 * 1024 * 1024,
    host_platform="Windows",
)


class CatalogueTest(unittest.TestCase):
    def test_the_catalogue_pins_editors_modules_and_the_handoff(self) -> None:
        catalogue = UnitySetup().catalogue()
        self.assertEqual(catalogue["default_editor"], DEFAULT_EDITOR)
        self.assertEqual(catalogue["hub_minimum"], UNITY_HUB_MINIMUM)
        self.assertTrue(all(item["long_term_support"] for item in catalogue["editors"]))
        targets = {item["target"] for item in catalogue["targets"]}
        self.assertIn("StandaloneWindows64", targets)
        self.assertEqual(catalogue["licence_handoff"], list(LICENCE_HANDOFF))
        self.assertEqual(catalogue["never_handled_here"], list(NEVER_HANDLED))

    def test_an_unpinned_editor_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            UnitySetup(editor_version="2019.4.1f1")
        self.assertIn(DEFAULT_EDITOR, SUPPORTED_EDITORS)

    def test_editor_series(self) -> None:
        self.assertEqual(editor_series("6000.0.23f1"), "6000.0")
        self.assertEqual(editor_series("2022.3.45f1"), "2022.3")
        self.assertEqual(editor_series("nonsense"), "nonsense")

    def test_nothing_here_holds_a_unity_credential(self) -> None:
        forbidden = ("account", "password", "token", "serial", "credential", "licence_key")
        for name in dir(unity_setup):
            value = getattr(unity_setup, name)
            if dataclasses.is_dataclass(value) and isinstance(value, type):
                for field in dataclasses.fields(value):
                    for marker in forbidden:
                        self.assertNotIn(
                            marker, field.name.casefold(),
                            f"{value.__name__}.{field.name} looks like a credential",
                        )
        self.assertFalse(hasattr(UnitySetup, "activate"))


class StatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self.setup = UnitySetup()

    def test_a_complete_installation_is_ready(self) -> None:
        status = self.setup.status(HEALTHY)
        self.assertTrue(status.ready)
        self.assertEqual(status.actions, ())
        self.assertEqual(status.record["licence_state"], "active")
        self.setup.require_ready(status)

    def test_every_gap_produces_its_own_action_for_a_person(self) -> None:
        status = self.setup.status(Installation(
            hub_version="3.1.0", editors={"2022.3.45f1": ("windows-il2cpp",)},
            licence_state="expired", free_disk_bytes=1024,
        ))
        codes = [action.code for action in status.actions]
        self.assertEqual(
            codes, ["upgrade_hub", "install_editor", "licence", "disk_space"],
        )
        self.assertEqual({a.performed_by for a in status.actions}, {"person"})
        self.assertEqual(status.state, "action_required")
        self.assertEqual(len(status.waiting_on_person), 4)

    def test_a_missing_hub_is_named_before_the_editor(self) -> None:
        status = self.setup.status(Installation(licence_state="unknown"))
        self.assertEqual(status.actions[0].code, "install_hub")

    def test_a_missing_platform_module_is_its_own_action(self) -> None:
        status = self.setup.status(Installation(
            hub_version="3.9.1", editors={DEFAULT_EDITOR: ("mac-mono",)},
            licence_state="active", free_disk_bytes=10**12,
        ))
        codes = [action.code for action in status.actions]
        self.assertEqual(codes, ["add_module"])
        self.assertIn("windows-il2cpp", status.actions[0].detail)

    def test_other_editors_are_reported_but_never_removed(self) -> None:
        status = self.setup.status(Installation(
            hub_version="3.9.1", editors={"2022.3.45f1": ("windows-il2cpp",)},
            licence_state="active", free_disk_bytes=10**12,
        ))
        action = next(a for a in status.actions if a.code == "install_editor")
        self.assertIn("2022.3.45f1", action.detail)
        self.assertIn("nothing has to be removed", action.detail)

    def test_a_target_this_machine_cannot_build_is_blocked(self) -> None:
        status = self.setup.status(HEALTHY, target="iOS")
        self.assertEqual(status.state, "blocked")
        self.assertEqual(status.actions[0].code, "host_platform")
        self.assertIn("Apple developer account", status.actions[0].detail)
        with self.assertRaises(SetupBlocked):
            self.setup.require_ready(status)

    def test_an_unknown_target_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            self.setup.status(HEALTHY, target="Dreamcast")

    def test_the_licence_action_carries_unitys_own_flow(self) -> None:
        status = self.setup.status(
            Installation(
                hub_version="3.9.1", editors={DEFAULT_EDITOR: ("windows-il2cpp",)},
                licence_state="inactive", free_disk_bytes=10**12,
            )
        )
        action = next(a for a in status.actions if a.code == "licence")
        self.assertEqual(action.performed_by, "person")
        self.assertIn("sign in with your own Unity account", action.detail)
        self.assertIn("not something this tool can accept for you", action.detail)


class ProjectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.project = Path(self.directory.name) / "game"
        (self.project / "ProjectSettings").mkdir(parents=True)
        (self.project / "Packages").mkdir()
        self.setup = UnitySetup()

    def write_version(self, version: str) -> None:
        (self.project / "ProjectSettings/ProjectVersion.txt").write_text(
            f"m_EditorVersion: {version}\nm_EditorVersionWithRevision: {version} (abc)\n",
            encoding="utf-8",
        )

    def test_the_project_version_and_lock_digest_are_read(self) -> None:
        self.write_version(DEFAULT_EDITOR)
        lock = b'{"dependencies": {}}'
        (self.project / "Packages/packages-lock.json").write_bytes(lock)
        requirement = read_project_requirement(self.project)
        self.assertTrue(requirement.found)
        self.assertEqual(requirement.editor_version, DEFAULT_EDITOR)
        self.assertEqual(
            requirement.packages_lock_digest, hashlib.sha256(lock).hexdigest(),
        )

    def test_a_matching_project_keeps_the_setup_ready(self) -> None:
        self.write_version(DEFAULT_EDITOR)
        status = self.setup.status(HEALTHY, project=self.project)
        self.assertTrue(status.ready)

    def test_a_same_series_mismatch_says_the_hub_can_open_it(self) -> None:
        self.write_version("6000.0.11f1")
        status = self.setup.status(HEALTHY, project=self.project)
        action = next(a for a in status.actions if a.code == "project_editor_mismatch")
        self.assertIn("Same series", action.detail)

    def test_a_cross_series_mismatch_warns_that_it_is_not_reversible(self) -> None:
        self.write_version("2022.3.45f1")
        status = self.setup.status(HEALTHY, project=self.project)
        action = next(a for a in status.actions if a.code == "project_editor_mismatch")
        self.assertIn("not reversible in place", action.detail)
        self.assertIn("Copy it first", action.detail)

    def test_a_missing_project_version_file_is_reported(self) -> None:
        status = self.setup.status(HEALTHY, project=self.project)
        self.assertEqual(status.actions[0].code, "project_unreadable")
        self.assertIn("ProjectVersion.txt", status.actions[0].detail)

    def test_an_empty_project_version_file_is_not_treated_as_a_version(self) -> None:
        (self.project / "ProjectSettings/ProjectVersion.txt").write_text(
            "m_EditorVersionWithRevision: something\n", encoding="utf-8",
        )
        requirement = read_project_requirement(self.project)
        self.assertFalse(requirement.found)
        self.assertIn("no m_EditorVersion", requirement.detail)


class ResumeTest(unittest.TestCase):
    def test_setup_resumes_after_the_person_activated_the_licence(self) -> None:
        setup = UnitySetup()
        states = iter(["inactive", "active"])

        def probe() -> Installation:
            return Installation(
                hub_version="3.9.1", editors={DEFAULT_EDITOR: ("windows-il2cpp",)},
                licence_state=next(states), free_disk_bytes=10**12,
            )

        first = setup.resume(probe)
        self.assertEqual([a.code for a in first.actions], ["licence"])
        second = setup.resume(probe)
        self.assertTrue(second.ready)

    def test_detect_builds_an_installation_from_probes(self) -> None:
        installation = detect(
            hub_probe=lambda: "3.9.1",
            editor_probe=lambda: {DEFAULT_EDITOR: ["windows-il2cpp"]},
            licence_probe=lambda: "active",
            disk_probe=lambda: 10**12,
        )
        self.assertEqual(installation.hub_version, "3.9.1")
        self.assertEqual(installation.editors[DEFAULT_EDITOR], ("windows-il2cpp",))
        self.assertTrue(UnitySetup().status(installation).ready)

    def test_an_unknown_licence_state_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Installation(licence_state="probably fine")


if __name__ == "__main__":
    unittest.main()
