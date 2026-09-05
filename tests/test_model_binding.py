"""Offline execution evidence for AF-GC-006; no paid provider calls."""

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from agent_factory.application import AgentFactoryService
from agent_factory.models import Agent, ExecutionApproval, WorkItem
from agent_factory.providers import CLIProvider
from agent_factory.registry import AgentRegistry
from agent_factory.reviewers import ReviewerRouter, ReviewSubject
from agent_factory.runtime import AgentRuntime, ExecutionMode
from agent_factory.storage import SQLiteStorage


class ModelBindingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.agent = Agent("worker", "Worker", "Implementation Worker", True,
                           "test", "Return evidence", model="fixture:model-a")
        self.item = WorkItem("Task", "Return evidence", 1, id=7)
        self.approval = ExecutionApproval(1, "test", "worker", 7)

    def provider(self, **overrides):
        options = dict(model_namespace="fixture", model_ids=["model-a", "model-b"],
                       allow_execution=True, workspace=self.root)
        options.update(overrides)
        return CLIProvider("test", sys.executable,
                           ["-c", "import json,sys; print(json.dumps(sys.argv[1:]))", "{model}"],
                           **options)

    def test_two_selected_models_reach_the_real_process_and_metadata(self):
        provider = self.provider()
        for model in ("model-a", "model-b"):
            with self.subTest(model=model):
                agent = replace(self.agent, model=f"fixture:{model}")
                result = provider.execute(agent, self.item, {}, self.approval)
                self.assertTrue(result.ok, result.error)
                self.assertEqual(json.loads(result.content), [model])
                self.assertEqual(result.metadata["requested_model"], agent.model)
                self.assertEqual(result.metadata["effective_model"], agent.model)
                self.assertEqual(result.metadata["args"][-1], model)

    def test_unknown_missing_and_shell_text_are_rejected_before_spawn(self):
        supervisor = Mock()
        provider = self.provider(supervisor=supervisor)
        for value in ("", "fixture:missing", "model-a", "fixture:model-a --evil",
                      "fixture:model-a; echo SECRET", "fixture:model-a\nSECRET"):
            with self.subTest(value=value):
                result = provider.execute(replace(self.agent, model=value), self.item, {}, self.approval)
                self.assertFalse(result.ok)
                self.assertTrue(result.metadata["model_binding_error"])
                self.assertNotIn("SECRET", json.dumps(result.__dict__))
        supervisor.spawn.assert_not_called()

    def test_invalid_binding_configuration_is_rejected(self):
        for namespace, ids, args in (
            ("fixture", ["--model-a"], ["{model}"]),
            ("fixture", ["model-a;echo"], ["{model}"]),
            ("bad namespace", ["model-a"], ["{model}"]),
            ("fixture", ["model-a"], ["{model}", "{model}"]),
            ("fixture", ["model-a"], ["fixed-model"]),
        ):
            provider = CLIProvider("test", sys.executable, args,
                                   model_namespace=namespace, model_ids=ids)
            with self.assertRaises(ValueError):
                provider.model_request(self.agent.model)

    def test_unbound_legacy_tool_cannot_claim_selected_model(self):
        provider = CLIProvider("test", sys.executable, ["-c", "print('ok')"])
        self.assertEqual(provider.model_request(""), (list(provider.args), None))
        with self.assertRaises(ValueError):
            provider.model_request(self.agent.model)
        runtime = AgentRuntime({"test": provider}, workspace=self.root)
        with self.assertRaises(ValueError):
            runtime.effective_model(replace(self.agent, model=""))

    def test_live_runtime_preserves_binding_failure(self):
        runtime = AgentRuntime({"test": self.provider()}, workspace=self.root)
        result = runtime.run(replace(self.agent, model="unknown"), self.item, {},
                             self.approval, mode=ExecutionMode.LIVE)
        self.assertFalse(result.ok)
        self.assertTrue(result.metadata["model_binding_error"])

    def test_shipped_bindings_replace_the_native_model_argument(self):
        runtime = AgentRuntime(workspace=self.root)
        for provider, prefix, first, second in (
            ("codex", "openai", "gpt-5.6-sol", "gpt-6-astra"),
            ("ollama", "local", "qwen2.5-coder:7b", "qwen2.5-coder:14b"),
        ):
            adapter = runtime.providers[provider]
            a, identity_a = adapter.model_request(f"{prefix}:{first}")
            b, identity_b = adapter.model_request(f"{prefix}:{second}")
            self.assertIn(first, a)
            self.assertIn(second, b)
            self.assertNotIn(first, b)
            self.assertNotEqual(identity_a, identity_b)
            self.assertNotIn("{model}", a)

    def test_ui_rejects_unknown_model_without_changing_saved_agent(self):
        with closing(SQLiteStorage(self.root / "state.db")) as storage:
            service = AgentFactoryService(storage, workspace=self.root)
            before = service.registry.get("coding-worker-codex")
            with self.assertRaisesRegex(ValueError, "unknown or unsupported"):
                service.replace_agent_provider(before.id, "codex", "unconfigured-model")
            self.assertEqual(service.registry.get(before.id), before)
            changed = service.replace_agent_provider(before.id, "codex", "openai:gpt-6-astra")
            self.assertEqual(changed.model, "openai:gpt-6-astra")

    def test_model_change_invalidates_the_approved_snapshot_before_execution(self):
        with closing(SQLiteStorage(self.root / "state.db")) as storage:
            service = AgentFactoryService(storage, workspace=self.root)
            project = storage.create_project("Example", "Model snapshot")
            task = storage.create_task(WorkItem("Task", "Evidence", project))
            agent = service.registry.get("coding-worker-codex")
            gate = service.request_provider_execution(agent.provider, agent.id, task)
            storage.decide_provider_execution(gate, "approved", "Fixture approval")
            service.replace_agent_provider(agent.id, "codex", "openai:gpt-6-astra")
            with patch("agent_factory.providers.ProcessSupervisor.spawn") as spawn:
                with self.assertRaisesRegex(PermissionError, "request a new gate"):
                    service.invoke_provider(gate)
                spawn.assert_not_called()

    def test_review_uses_stored_effective_model_after_author_settings_change(self):
        with closing(SQLiteStorage(self.root / "state.db")) as storage:
            author = replace(self.agent, model="fixture:model-b")
            same = replace(self.agent, id="same", role="Proxy Reviewer")
            other = replace(same, id="other", model="fixture:model-b")
            path = self.root / "agents.json"
            path.write_text(json.dumps({"agents": [a.__dict__ for a in (author, same, other)]}))
            registry = AgentRegistry(path)
            runtime = AgentRuntime({"test": self.provider()}, workspace=self.root)
            project = storage.create_project("Example", "Review")
            task = storage.create_task(WorkItem("Task", "Review", project))
            run = storage.start_run(project, task, "fixture")
            artifact = storage.add_artifact(run, "implementation", author.id, "test", "Evidence",
                producer={"agent_id": author.id, "effective_model": "fixture:model-a",
                          "model_identity_source": "qualified_request"})
            selected = ReviewerRouter(storage, registry).select(
                run_id=run, stage="validation", candidate_ids=["same", "other"],
                subjects=[ReviewSubject("implementation", artifact, author)],
                required_role="Proxy Reviewer", model_resolver=runtime.effective_model)
            self.assertEqual(selected.id, "other")
            unknown = storage.add_artifact(run, "legacy", author.id, "test", "No identity")
            with self.assertRaisesRegex(RuntimeError, "no effective model identity"):
                ReviewerRouter(storage, registry).select(
                    run_id=run, stage="validation", candidate_ids=["other"],
                    subjects=[ReviewSubject("legacy", unknown, author)],
                    required_role="Proxy Reviewer", model_resolver=runtime.effective_model)


if __name__ == "__main__":
    unittest.main()
