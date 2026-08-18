import os
import unittest
from unittest.mock import patch

from agent_factory.orchestration.temporal.client import workflow_id_for_job
from agent_factory.orchestration.temporal.models import ActivityResult, DemoWorkflowInput
from agent_factory.orchestration.temporal.policies import (
    classify_error,
    coding_policy,
    fast_transient_policy,
    llm_policy,
)
from agent_factory.orchestration.temporal.settings import TemporalSettings


class TemporalConfigurationTests(unittest.TestCase):
    def test_documented_defaults_and_workflow_id(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = TemporalSettings.from_env()
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.address, "localhost:7233")
        self.assertEqual(settings.namespace, "agentfactory")
        self.assertEqual(settings.task_queue, "agentfactory-main")
        self.assertEqual(workflow_id_for_job("run-17"), "agentfactory-job-run-17")

    def test_invalid_boolean_and_heartbeat_window_fail_closed(self):
        with patch.dict(os.environ, {"TEMPORAL_ENABLED": "sometimes"}, clear=True):
            with self.assertRaisesRegex(ValueError, "true or false"):
                TemporalSettings.from_env()
        with patch.dict(
            os.environ,
            {
                "TEMPORAL_HEARTBEAT_INTERVAL_SECONDS": "60",
                "TEMPORAL_HEARTBEAT_TIMEOUT_SECONDS": "60",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "must be less"):
                TemporalSettings.from_env()

    def test_retry_policies_are_category_specific(self):
        fast = fast_transient_policy()
        llm = llm_policy()
        coding = coding_policy()
        self.assertEqual(fast.maximum_attempts, 5)
        self.assertEqual(llm.maximum_attempts, 4)
        self.assertEqual(coding.maximum_attempts, 2)
        self.assertIn("CONFIGURATION", coding.non_retryable_error_types)

    def test_failure_classification_separates_configuration_and_transient(self):
        self.assertEqual(
            classify_error("operator approval required", {"blocked": True}),
            ("CONFIGURATION", False),
        )
        self.assertEqual(
            classify_error("HTTP 429 rate limit", {}), ("TRANSIENT", True)
        )
        self.assertEqual(
            classify_error("provider timed out", {"timed_out": True}),
            ("TIMEOUT", True),
        )

    def test_activity_result_round_trip(self):
        result = ActivityResult(
            True,
            passed=False,
            exit_code=1,
            summary="tests failed",
            artifacts=["artifact:9"],
            failure_class="TEST_FAILURE",
        )
        self.assertEqual(ActivityResult.from_dict(result.to_dict()), result)

    def test_demo_input_wait_gate_is_backward_compatible(self):
        request = DemoWorkflowInput(workspace="C:\\work", marker="demo", command=[])
        self.assertFalse(request.wait_before_command)


if __name__ == "__main__":
    unittest.main()
