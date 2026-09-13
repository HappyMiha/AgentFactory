"""A report says whose machine it describes, or it is worth nothing."""

import unittest
from pathlib import Path
from unittest.mock import patch

from agent_factory import machine_identity
from agent_factory.localisation import LANGUAGES
from agent_factory.machine_identity import (
    ThisMachine,
    WrongMachine,
    builds_here,
    describe_this_machine,
    require_a_build_machine,
    sign,
)


class DecisionTests(unittest.TestCase):
    def decide(self, *, declared=None, name="", markers=False, cgroup=""):
        environment = {}
        if declared:
            environment["LOKVETIA_MACHINE_KIND"] = declared
        if name:
            environment["LOKVETIA_MACHINE_NAME"] = name
        with patch.dict("os.environ", environment, clear=True), \
                patch.object(Path, "exists", lambda self: markers), \
                patch.object(Path, "read_text", lambda self, encoding=None: cgroup):
            return describe_this_machine()

    def test_a_deployment_that_declares_itself_is_believed(self):
        machine = self.decide(declared="web_container", name="test.lokvetia.com")
        self.assertEqual(machine.kind, "web_container")
        self.assertIn("Declared", machine.basis.text("en"))
        self.assertIn("test.lokvetia.com", machine.label("en"))

    def test_a_declaration_that_is_not_a_kind_is_ignored(self):
        self.assertEqual(self.decide(declared="the-best-machine").kind, "this_pc")

    def test_a_container_marker_means_a_container_of_some_kind(self):
        machine = self.decide(markers=True)
        self.assertEqual(machine.kind, "container")
        self.assertIn("nobody declared which container", machine.basis.text("en"))

    def test_a_container_cgroup_means_a_container_of_some_kind(self):
        self.assertEqual(self.decide(cgroup="12:pids:/docker/abc123").kind, "container")

    def test_with_no_marker_it_is_the_computer_core_is_installed_on(self):
        machine = self.decide()
        self.assertTrue(machine.is_the_users_computer)
        self.assertIn("No container marker", machine.basis.text("en"))

    def test_a_declaration_outranks_the_markers(self):
        self.assertEqual(
            self.decide(declared="cloud_worker", markers=True).kind, "cloud_worker")


class CaveatTests(unittest.TestCase):
    def test_a_container_report_says_it_is_not_your_pc(self):
        machine = ThisMachine("web_container", "", machine_identity.BASIS_CONTAINER)
        self.assertIn("not of your PC", machine.caveat("en"))

    def test_a_local_report_says_it_is_this_computer(self):
        machine = ThisMachine("this_pc", "", machine_identity.BASIS_LOCAL)
        self.assertIn("the computer Core is running on", machine.caveat("en"))

    def test_a_cloud_worker_is_not_your_pc_either(self):
        machine = ThisMachine("cloud_worker", "build-3", machine_identity.BASIS_DECLARED)
        self.assertIn("not of your PC", machine.caveat("en"))
        self.assertIn("build-3", machine.label("en"))

    def test_the_caveat_reads_in_both_languages(self):
        machine = ThisMachine("web_container", "", machine_identity.BASIS_CONTAINER)
        for language in LANGUAGES:
            self.assertTrue(machine.caveat(language).strip())
        self.assertNotEqual(machine.caveat("uk"), machine.caveat("en"))

    def test_the_label_never_contains_a_host_name(self):
        # A hardware report omits host names on purpose; the signature must not
        # smuggle one back in. Only a declared name is ever shown.
        with patch.dict("os.environ", {}, clear=True), \
                patch.object(Path, "exists", lambda self: False), \
                patch.object(Path, "read_text", lambda self, encoding=None: ""):
            self.assertEqual(describe_this_machine().name, "")


class SigningTests(unittest.TestCase):
    def test_a_signed_report_keeps_its_own_content(self):
        with patch.dict("os.environ", {"LOKVETIA_MACHINE_KIND": "web_container"}, clear=True):
            signed = sign({"cpu": {"name": "shared"}}, language="en")
        self.assertEqual(signed["cpu"], {"name": "shared"})
        self.assertEqual(signed["machine"]["kind"], "web_container")
        self.assertIn("not of your PC", signed["machine"]["caveat"])

    def test_a_signature_says_how_it_was_decided(self):
        with patch.dict("os.environ", {}, clear=True), \
                patch.object(Path, "exists", lambda self: False), \
                patch.object(Path, "read_text", lambda self, encoding=None: ""):
            signed = sign({}, language="en")
        self.assertTrue(signed["machine"]["basis"])


class BuildMachineTests(unittest.TestCase):
    """Only a declared web container is refused: cloud workers are containers too."""

    def with_kind(self, kind):
        environment = {"LOKVETIA_MACHINE_KIND": kind} if kind else {}
        return patch.dict("os.environ", environment, clear=True)

    def test_the_declared_web_container_may_not_build(self):
        with self.with_kind("web_container"):
            self.assertFalse(builds_here())
            with self.assertRaises(WrongMachine) as caught:
                require_a_build_machine("A Godot build")
        self.assertIn("A Godot build", caught.exception.text("en"))
        self.assertIn("A worker does this", caught.exception.text("en"))

    def test_a_cloud_worker_builds(self):
        with self.with_kind("cloud_worker"):
            self.assertTrue(builds_here())
            self.assertEqual(require_a_build_machine("A build").kind, "cloud_worker")

    def test_an_undeclared_container_is_not_refused(self):
        # Cloud build workers run in containers. Guessing "web container" from a
        # marker would refuse the very machines that are supposed to build.
        with patch.dict("os.environ", {}, clear=True), \
                patch.object(Path, "exists", lambda self: True):
            self.assertTrue(builds_here())

    def test_the_refusal_reads_in_both_languages(self):
        with self.with_kind("web_container"):
            try:
                require_a_build_machine("A Godot build")
            except WrongMachine as refused:
                for language in LANGUAGES:
                    self.assertTrue(refused.text(language).strip())
                self.assertNotEqual(refused.text("uk"), refused.text("en"))


class EngineGuardTests(unittest.TestCase):
    """Every engine command asks which machine it is on before it runs."""

    def in_the_web_container(self):
        return patch.dict(
            "os.environ", {"LOKVETIA_MACHINE_KIND": "web_container"}, clear=True)

    def test_a_godot_command_in_the_web_container_is_refused(self):
        from agent_factory.godot_engine import GodotAdapter

        with self.in_the_web_container():
            with self.assertRaises(WrongMachine) as caught:
                GodotAdapter().health()
        self.assertIn("A Godot command", caught.exception.text("en"))

    def test_a_unity_command_in_the_web_container_is_refused(self):
        from agent_factory.unity_engine import UnityAdapter

        with self.in_the_web_container():
            with self.assertRaises(WrongMachine) as caught:
                UnityAdapter().health()
        self.assertIn("A Unity command", caught.exception.text("en"))

    def test_the_same_command_is_allowed_on_a_worker(self):
        from agent_factory.godot_engine import GodotAdapter

        with patch.dict("os.environ", {"LOKVETIA_MACHINE_KIND": "cloud_worker"}, clear=True):
            # No engine is installed here, so the honest answer is "unavailable"
            # rather than a refusal about the machine.
            self.assertFalse(GodotAdapter(executable_candidates=("nothing-here",)).health().healthy)


if __name__ == "__main__":
    unittest.main()
