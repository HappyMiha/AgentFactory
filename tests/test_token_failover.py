import json
import tempfile
import unittest
from pathlib import Path

from agent_factory.config import config_path_for_workspace, load_yaml
from agent_factory.models import Agent, ProviderResult, WorkItem
from agent_factory.providers import Provider
from agent_factory.registry import AgentRegistry
from agent_factory.runtime import AgentRuntime, ExecutionMode
from agent_factory.storage import SQLiteStorage
from agent_factory.token_failover import (
    configured_coding_chain,
    exhausted_providers_for_run,
    record_exhausted_providers,
    token_quota_exhausted,
)
from agent_factory.workflow import WorkflowEngine


class ScriptedProvider(Provider):
    def __init__(self, name: str, *results: ProviderResult):
        self.name = name
        self.results = list(results)
        self.calls: list[str] = []

    def health(self):
        return {"provider": self.name, "healthy": True}

    def execute(self, agent, item, context, approval=None):
        self.calls.append(agent.id)
        if not self.results:
            raise AssertionError(f"Unexpected call to {self.name}")
        return self.results.pop(0)


class WorkflowProvider(Provider):
    def __init__(self, name: str, *, exhaust_implementation: bool = False):
        self.name = name
        self.exhaust_implementation = exhaust_implementation
        self.calls: list[str] = []

    def health(self):
        return {"provider": self.name, "healthy": True}

    def execute(self, agent, item, context, approval=None):
        stage_id = str(item.inputs["stage"])
        self.calls.append(f"{stage_id}:{agent.id}")
        if self.exhaust_implementation and stage_id == "implementation":
            return ProviderResult(
                False,
                provider=self.name,
                error="usage limit reached",
            )
        verdict = {
            "policy-precheck": "ALIGNED",
            "implementation": "COMPLETE",
            "validation": "PASS",
            "policy-postcheck": "ALIGNED",
        }[stage_id]
        content = json.dumps(
            {
                "verdict": verdict,
                "criteria_evidence": {
                    criterion: f"{self.name} evidence"
                    for criterion in item.acceptance_criteria
                },
                "summary": f"{self.name} completed {stage_id}",
            }
        )
        return ProviderResult(True, content, self.name)


def worker(agent_id: str, provider: str) -> Agent:
    return Agent(
        agent_id,
        agent_id,
        "Implementation Worker",
        True,
        provider,
        "Implement only the assigned task",
        ["read_project", "create_artifact", "propose_code"],
    )


class TokenFailoverTests(unittest.TestCase):
    def setUp(self):
        self.claude_agent = worker("coding-worker-claude", "claude")
        self.gemini_agent = worker("coding-worker-gemini", "gemini")
        self.codex_agent = worker("coding-worker-codex", "codex")
        self.item = WorkItem("Implement", "Make the approved change", 1, id=7)

    def execute_chain(self, providers):
        return AgentRuntime(providers).run(
            self.gemini_agent,
            self.item,
            {},
            mode=ExecutionMode.LIVE,
            token_exhaustion_fallback_agents=(
                self.claude_agent,
                self.codex_agent,
            ),
        )

    def test_gemini_quota_promotes_only_claude(self):
        gemini = ScriptedProvider(
            "gemini",
            ProviderResult(False, provider="gemini", error="You've hit your usage limit"),
        )
        claude = ScriptedProvider(
            "claude", ProviderResult(True, "implemented", "claude")
        )
        codex = ScriptedProvider(
            "codex", ProviderResult(True, "should not run", "codex")
        )

        result = self.execute_chain(
            {"claude": claude, "gemini": gemini, "codex": codex}
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "claude")
        self.assertEqual(result.metadata["selected_agent_id"], "coding-worker-claude")
        self.assertEqual(
            result.metadata["token_exhausted_providers"],
            [{"provider": "gemini", "agent_id": "coding-worker-gemini"}],
        )
        self.assertEqual(gemini.calls, ["coding-worker-gemini"])
        self.assertEqual(claude.calls, ["coding-worker-claude"])
        self.assertEqual(codex.calls, [])

    def test_both_external_quotas_promote_codex(self):
        gemini = ScriptedProvider(
            "gemini",
            ProviderResult(
                False,
                provider="gemini",
                error="quota exhausted",
                metadata={"quota_exhausted": True},
            ),
        )
        claude = ScriptedProvider(
            "claude",
            ProviderResult(
                False,
                provider="claude",
                error="RESOURCE_EXHAUSTED",
                metadata={"error_code": "RESOURCE_EXHAUSTED"},
            ),
        )
        codex = ScriptedProvider(
            "codex", ProviderResult(True, "codex completed the task", "codex")
        )

        result = self.execute_chain(
            {"claude": claude, "gemini": gemini, "codex": codex}
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "codex")
        self.assertEqual(result.metadata["selected_agent_id"], "coding-worker-codex")
        self.assertEqual(
            [item["provider"] for item in result.metadata["token_exhausted_providers"]],
            ["gemini", "claude"],
        )

    def test_generic_error_and_bare_429_do_not_promote_standby(self):
        for message in ("implementation failed", "HTTP 429 rate limit"):
            with self.subTest(message=message):
                gemini = ScriptedProvider(
                    "gemini", ProviderResult(False, provider="gemini", error=message)
                )
                claude = ScriptedProvider(
                    "claude", ProviderResult(True, "should not run", "claude")
                )
                codex = ScriptedProvider(
                    "codex", ProviderResult(True, "should not run", "codex")
                )

                result = self.execute_chain(
                    {"claude": claude, "gemini": gemini, "codex": codex}
                )

                self.assertFalse(result.ok)
                self.assertEqual(result.error, message)
                self.assertEqual(gemini.calls, ["coding-worker-gemini"])
                self.assertEqual(claude.calls, [])
                self.assertEqual(codex.calls, [])

    def test_runtime_remembers_exhaustion_for_its_session(self):
        gemini = ScriptedProvider(
            "gemini",
            ProviderResult(False, provider="gemini", error="usage limit reached"),
        )
        claude = ScriptedProvider(
            "claude",
            ProviderResult(True, "first", "claude"),
            ProviderResult(True, "second", "claude"),
        )
        codex = ScriptedProvider(
            "codex", ProviderResult(True, "should not run", "codex")
        )
        runtime = AgentRuntime({"claude": claude, "gemini": gemini, "codex": codex})

        first = runtime.run(
            self.gemini_agent,
            self.item,
            {},
            mode=ExecutionMode.LIVE,
            token_exhaustion_fallback_agents=(self.claude_agent, self.codex_agent),
        )
        second = runtime.run(
            self.gemini_agent,
            self.item,
            {},
            mode=ExecutionMode.LIVE,
            token_exhaustion_fallback_agents=(self.claude_agent, self.codex_agent),
        )

        self.assertTrue(first.ok and second.ok)
        self.assertEqual(gemini.calls, ["coding-worker-gemini"])
        self.assertEqual(claude.calls, ["coding-worker-claude"] * 2)

    def test_default_configuration_has_exact_coding_chain_and_claude_standby(self):
        registry = AgentRegistry()
        workflows = load_yaml(config_path_for_workspace("workflows", Path.cwd()))
        delivery = next(item for item in workflows["workflows"] if item["id"] == "delivery")
        implementation = next(
            stage for stage in delivery["stages"] if stage["id"] == "implementation"
        )

        chain = configured_coding_chain(implementation, registry.list())

        self.assertEqual(
            [agent.id for agent in chain],
            [
                "coding-worker-gemini",
                "coding-worker-claude",
                "coding-worker-codex",
            ],
        )
        self.assertEqual(delivery["orchestration"]["provider"], "codex")
        self.assertFalse(delivery["orchestration"]["worker_task_creation"])
        providers = load_yaml(config_path_for_workspace("providers", Path.cwd()))
        claude = next(item for item in providers["providers"] if item["id"] == "claude")
        gemini = next(item for item in providers["providers"] if item["id"] == "gemini")
        self.assertTrue(claude["standby"])
        self.assertFalse(gemini["standby"])
        self.assertEqual(gemini["allowed_roles"], ["Implementation Worker"])
        self.assertEqual(
            gemini["args"][:2], ["--model", "gemini-3.1-pro-preview"]
        )
        self.assertNotIn("flash", " ".join(gemini["args"]).casefold())
        gemini_agent = registry.get("coding-worker-gemini")
        self.assertEqual(gemini_agent.model, "google:gemini-3.1-pro-preview")
        self.assertIn("production-quality", gemini_agent.instructions)

    def test_quota_events_are_run_scoped_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "state.db")
            project_id = storage.create_project("Quota", "routing")
            task_id = storage.create_task(WorkItem("Task", "Do it", project_id))
            run_id = storage.start_run(project_id, task_id, "delivery")
            exhausted = [
                {"provider": "gemini", "agent_id": "coding-worker-gemini"}
            ]

            record_exhausted_providers(
                storage,
                run_id=run_id,
                stage_id="implementation",
                exhausted=exhausted,
            )
            record_exhausted_providers(
                storage,
                run_id=run_id,
                stage_id="implementation",
                exhausted=exhausted,
            )

            self.assertEqual(exhausted_providers_for_run(storage, run_id), {"gemini"})
            count = storage.db.execute(
                """SELECT COUNT(*) FROM events
                     WHERE event_type='workflow.provider.token_quota_exhausted'
                       AND entity_id=?""",
                (str(run_id),),
            ).fetchone()[0]
            self.assertEqual(count, 1)
            storage.close()

    def test_default_workflow_records_gemini_to_claude_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(Path(tmp) / "state.db")
            project_id = storage.create_project("Failover", "workflow")
            task_id = storage.create_task(
                WorkItem(
                    "Implement",
                    "Make the approved change",
                    project_id,
                    acceptance_criteria=["Change is reviewable"],
                )
            )
            providers = {
                "claude": WorkflowProvider("claude"),
                "gemini": WorkflowProvider(
                    "gemini", exhaust_implementation=True
                ),
                "codex": WorkflowProvider("codex"),
                "ollama": WorkflowProvider("ollama"),
            }

            run_id = WorkflowEngine(
                storage, runtime=AgentRuntime(providers)
            ).run(
                "delivery",
                storage.get_task(task_id),
                mode=ExecutionMode.LIVE,
            )

            implementation = next(
                row
                for row in storage.artifacts(run_id)
                if row["stage"] == "implementation"
            )
            self.assertEqual(implementation["agent_id"], "coding-worker-claude")
            self.assertEqual(implementation["provider"], "claude")
            self.assertEqual(exhausted_providers_for_run(storage, run_id), {"gemini"})
            self.assertEqual(storage.latest_run()["status"], "awaiting_approval")
            storage.close()

    def test_classifier_accepts_explicit_metadata_but_not_context_limits(self):
        self.assertTrue(token_quota_exhausted("failed", {"token_exhausted": True}))
        self.assertFalse(token_quota_exhausted("maximum context length exceeded"))


if __name__ == "__main__":
    unittest.main()
