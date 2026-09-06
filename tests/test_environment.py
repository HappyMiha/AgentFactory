import sys
import unittest
from unittest.mock import patch

from agent_factory.environment import as_json, checks


class EnvironmentTests(unittest.TestCase):
    def test_python_uses_running_interpreter(self):
        results = {item.component: item for item in checks()}
        self.assertEqual(results["Python"].status, "installed")
        self.assertEqual(results["Python"].detail, sys.executable)
        self.assertEqual(results["Python"].requirement, "required")

    @patch("agent_factory.environment._resolve", return_value=None)
    def test_missing_optional_tool_is_reported_without_path_claim(self, _resolve):
        results = {item.component: item for item in checks()}
        self.assertEqual(results["Docker"].status, "missing")
        self.assertEqual(results["Docker"].detail, "not found")
        self.assertEqual(results["Docker"].requirement, "optional")
        self.assertEqual(results["Git"].requirement, "required")

    def test_serialized_checks_have_stable_generic_fields(self):
        rows = as_json()
        self.assertTrue(rows)
        self.assertEqual(
            set(rows[0]), {"component", "status", "detail", "requirement"}
        )

    def test_antigravity_is_an_optional_discoverable_component(self):
        results = {item.component: item for item in checks()}
        self.assertIn("Antigravity CLI", results)
        self.assertEqual(results["Antigravity CLI"].requirement, "optional")


if __name__ == "__main__":
    unittest.main()
