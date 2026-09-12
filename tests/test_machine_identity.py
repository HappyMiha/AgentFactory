"""A report says whose machine it describes, or it is worth nothing."""

import unittest
from pathlib import Path
from unittest.mock import patch

from agent_factory import machine_identity
from agent_factory.localisation import LANGUAGES
from agent_factory.machine_identity import ThisMachine, describe_this_machine, sign


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

    def test_a_container_marker_means_a_container(self):
        machine = self.decide(markers=True)
        self.assertEqual(machine.kind, "web_container")
        self.assertIn("Container markers", machine.basis.text("en"))

    def test_a_container_cgroup_means_a_container(self):
        machine = self.decide(cgroup="12:pids:/docker/abc123")
        self.assertEqual(machine.kind, "web_container")

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


if __name__ == "__main__":
    unittest.main()
