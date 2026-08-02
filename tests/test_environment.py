import sys
import unittest
from unittest.mock import patch

from agent_factory.environment import as_json, checks


class EnvironmentTests(unittest.TestCase):
    def test_python_uses_running_interpreter(self):
        results = {item.component: item for item in checks()}
        self.assertEqual(results["Python"].status, "ready")
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


if __name__ == "__main__":
    unittest.main()
