import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import is_dataclass
from pathlib import Path

from agent_factory.application import (
    AgentFactoryService,
    ApprovalView,
    EventView,
    ProjectView,
    ReviewView,
    RunView,
    SettingsView,
    WorkItemView,
)
from agent_factory.providers import DeterministicProvider
from agent_factory.registry import AgentRegistry
from agent_factory.runtime import AgentRuntime
from agent_factory.storage import SQLiteStorage

ROOT = Path(__file__).resolve().parent.parent


def deterministic_runtime(workspace: Path) -> AgentRuntime:
    providers = {
        name: DeterministicProvider()
        for name in (
            "deterministic",
            "codex",
            "claude",
            "gemini",
            "antigravity",
            "ollama",
        )
    }
    return AgentRuntime(providers, workspace=workspace)


def event_types(storage: SQLiteStorage) -> list[str]:
    return [
        str(row["event_type"])
        for row in storage.db.execute("SELECT event_type FROM events ORDER BY id")
    ]


class ApplicationQueryTests(unittest.TestCase):
    def test_operator_resources_are_typed_and_decode_stored_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            storage = SQLiteStorage(workspace / ".agent-factory" / "state.db")
            service = AgentFactoryService(
                storage,
                runtime=deterministic_runtime(workspace),
                workspace=workspace,
            )
            project = service.create_project("Control Center", "Operator queries")
            task = service.create_work_item(
                project_id=project.project_id,
                title="Build shared services",
                description="Keep operator clients consistent",
                acceptance_criteria=["CLI and web observe the same state"],
            )
            service.claim_work_item(task.id, "coding-worker-codex")
            run = service.run_workflow(task.id)

            self.assertIsInstance(service.projects()[0], ProjectView)
            self.assertIsInstance(service.work_items()[0], WorkItemView)
            self.assertIsInstance(run, RunView)
            self.assertEqual(run.status, "awaiting_approval")
            self.assertEqual(run.artifact_count, 4)
            self.assertTrue(all(is_dataclass(item) for item in service.agents()))
            self.assertTrue(all(is_dataclass(item) for item in service.providers()))

            reviews = service.reviews(run.id)
            self.assertEqual(len(reviews), 2)
            self.assertIsInstance(reviews[0], ReviewView)
            self.assertIsInstance(reviews[0].reviewed_stages, tuple)
            self.assertIsInstance(reviews[0].producer_agents, tuple)
            self.assertIsInstance(reviews[0].excluded_candidates, dict)

            approvals = service.approvals()
            self.assertIsInstance(approvals[0], ApprovalView)
            self.assertEqual(
                [(item.kind, item.status) for item in approvals],
                [("workflow", "pending")],
            )
            events = service.events(limit=10)
            self.assertIsInstance(events[0], EventView)
            self.assertIsInstance(events[0].payload, dict)
            self.assertIsInstance(service.settings(), SettingsView)
            self.assertEqual(service.settings().workspace, str(workspace.resolve()))
            storage.close()

    def test_all_approval_kinds_have_one_typed_query_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            storage = SQLiteStorage(workspace / "state.db")
            service = AgentFactoryService(
                storage,
                runtime=deterministic_runtime(workspace),
                workspace=workspace,
            )
            project = service.create_project("Approvals")
            task = service.create_work_item(
                project_id=project.project_id,
                title="Approval targets",
                description="Create every gate kind",
                acceptance_criteria=["Each gate remains distinct"],
            )
            service.run_workflow(task.id)
            provider_gate = service.request_provider_execution(
                "codex", "coding-worker-codex", task.id
            )
            plan_id, _ = storage.create_github_plan(
                "owner/repo",
                [
                    {
                        "action": "create_issue",
                        "idempotency_key": "issue:first",
                        "title": "First",
                        "body": "Evidence",
                        "labels": [],
                    }
                ],
            )
            github_gate = storage.request_github_gate(plan_id)

            by_kind = {item.kind: item for item in service.approvals()}
            self.assertEqual(set(by_kind), {"workflow", "provider", "github"})
            self.assertEqual(by_kind["provider"].id, provider_gate)
            self.assertEqual(by_kind["github"].id, github_gate)
            self.assertEqual(by_kind["github"].metadata["repo"], "owner/repo")
            storage.close()


class ApplicationCommandContractTests(unittest.TestCase):
    def run_cli(self, workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_factory",
                "--workspace",
                str(workspace),
                *arguments,
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )

    def checked_cli(self, workspace: Path, *arguments: str) -> str:
        result = self.run_cli(workspace, *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_cli_and_service_commands_have_equivalent_state_and_audit(self):
        with tempfile.TemporaryDirectory() as cli_tmp, tempfile.TemporaryDirectory() as service_tmp:
            cli_workspace = Path(cli_tmp)
            service_workspace = Path(service_tmp)

            project_output = self.checked_cli(
                cli_workspace,
                "project",
                "init",
                "--name",
                "Equivalent",
                "--description",
                "Shared path",
            )
            cli_project_id = int(json.loads(project_output)["project_id"])
            item_output = self.checked_cli(
                cli_workspace,
                "work-item",
                "create",
                "--project-id",
                str(cli_project_id),
                "--title",
                "First task",
                "--description",
                "Produce evidence",
                "--acceptance",
                "Evidence is reviewable",
            )
            cli_task_id = int(json.loads(item_output)["task_id"])
            self.checked_cli(
                cli_workspace,
                "task",
                "claim",
                str(cli_task_id),
                "--agent",
                "coding-worker-codex",
            )
            self.checked_cli(
                cli_workspace,
                "workflow",
                "run",
                "--task-id",
                str(cli_task_id),
            )
            approval_output = self.checked_cli(
                cli_workspace, "approvals", "list"
            )
            cli_gate_id = int(json.loads(approval_output)[0]["id"])
            self.checked_cli(
                cli_workspace,
                "approvals",
                "approve",
                str(cli_gate_id),
                "--note",
                "Accepted",
            )

            service_storage = SQLiteStorage(
                service_workspace / ".agent-factory" / "state.db"
            )
            service = AgentFactoryService(
                service_storage,
                runtime=deterministic_runtime(service_workspace),
                workspace=service_workspace,
            )
            change = service.create_project("Equivalent", "Shared path")
            service_task = service.create_work_item(
                project_id=change.project_id,
                title="First task",
                description="Produce evidence",
                acceptance_criteria=["Evidence is reviewable"],
            )
            service.claim_work_item(service_task.id, "coding-worker-codex")
            service_run = service.run_workflow(service_task.id)
            service_gate = next(
                item for item in service.approvals() if item.kind == "workflow"
            )
            service.decide_workflow_approval(
                service_gate.id, "approved", "Accepted"
            )

            cli_storage = SQLiteStorage(
                cli_workspace / ".agent-factory" / "state.db"
            )
            cli_service = AgentFactoryService(
                cli_storage,
                runtime=deterministic_runtime(cli_workspace),
                workspace=cli_workspace,
            )
            self.assertEqual(cli_service.run(1).status, service.run(service_run.id).status)
            self.assertEqual(cli_service.run(1).status, "approved")
            self.assertEqual(event_types(cli_storage), event_types(service_storage))
            self.assertEqual(
                [item.status for item in cli_service.approvals()],
                [item.status for item in service.approvals()],
            )
            cli_storage.close()
            service_storage.close()

    def test_guarded_agent_and_provider_commands_use_audited_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            registry_path = workspace / "agents.json"
            registry_path.write_text(
                json.dumps(
                    {
                        "agents": [
                            {
                                "id": "worker",
                                "name": "Worker",
                                "role": "Implementation Worker",
                                "enabled": True,
                                "provider": "codex",
                                "instructions": "Produce evidence",
                                "permissions": ["read_project", "create_artifact"],
                                "model": "openai:test",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            storage = SQLiteStorage(workspace / "state.db")
            service = AgentFactoryService(
                storage,
                AgentRegistry(registry_path),
                deterministic_runtime(workspace),
                workspace=workspace,
            )
            project = service.create_project("Guarded commands")
            task = service.create_work_item(
                project_id=project.project_id,
                title="Provider task",
                description="Require one-use approval",
                acceptance_criteria=["Invocation is audited"],
            )

            service.set_agent_enabled("worker", False)
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                service.request_provider_execution("codex", "worker", task.id)
            service.set_agent_enabled("worker", True)
            gate_id = service.request_provider_execution("codex", "worker", task.id)
            service.decide_provider_execution(gate_id, "approved", "One attempt")
            result = service.invoke_provider(gate_id)

            self.assertTrue(result.ok)
            self.assertEqual(
                [
                    kind
                    for kind in event_types(storage)
                    if kind.startswith(("agent.", "provider."))
                ],
                [
                    "agent.disabled",
                    "agent.enabled",
                    "provider.execution.requested",
                    "provider.execution.approved",
                    "provider.execution.claimed",
                    "provider.execution.running",
                    "provider.execution.succeeded",
                ],
            )
            with self.assertRaisesRegex(ValueError, "already"):
                service.decide_provider_execution(gate_id, "rejected", "Replay")
            storage.close()


if __name__ == "__main__":
    unittest.main()
