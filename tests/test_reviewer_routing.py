import json
import tempfile
import unittest
from pathlib import Path

from agent_factory.models import Agent, WorkItem
from agent_factory.registry import AgentRegistry
from agent_factory.reviewers import ReviewerRouter, ReviewSubject
from agent_factory.storage import SQLiteStorage


class ReviewerRoutingTests(unittest.TestCase):
    @staticmethod
    def registry(path: Path) -> AgentRegistry:
        agents = [
            Agent("author", "Author", "Implementation Worker", True, "codex", "", model="model-a"),
            Agent("same-model", "Same", "Proxy Reviewer", True, "other", "", model="model-a"),
            Agent("reviewer-b", "B", "Proxy Reviewer", True, "claude", "", model="model-b"),
            Agent("reviewer-c", "C", "Proxy Reviewer", True, "ollama", "", model="model-c"),
        ]
        path.write_text(
            json.dumps({"agents": [agent.__dict__ for agent in agents]}),
            encoding="utf-8",
        )
        return AgentRegistry(path)

    def test_rotation_excludes_producer_model_and_avoids_consecutive_reviewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = SQLiteStorage(root / "state.db")
            registry = self.registry(root / "agents.json")
            router = ReviewerRouter(storage, registry)
            project_id = storage.create_project("Example", "Rotation")
            selected = []
            for index in range(3):
                task_id = storage.create_task(
                    WorkItem(
                        title=f"Task {index}",
                        description="Review independently",
                        project_id=project_id,
                        acceptance_criteria=["Evidence exists"],
                    )
                )
                run_id = storage.start_run(project_id, task_id, "rotation-test")
                artifact_id = storage.add_artifact(
                    run_id, "implementation", "author", "codex", "candidate"
                )
                reviewer = router.select(
                    run_id=run_id,
                    stage="validation",
                    candidate_ids=["same-model", "reviewer-b", "reviewer-c"],
                    subjects=[ReviewSubject("implementation", artifact_id, registry.get("author"))],
                    required_role="Proxy Reviewer",
                )
                selected.append(reviewer.id)
                storage.finish_run(run_id, "failed")

            self.assertEqual(selected, ["reviewer-b", "reviewer-c", "reviewer-b"])
            assignments = storage.reviewer_assignments()
            self.assertTrue(all(row["reviewer_model"] != "model-a" for row in assignments))
            self.assertEqual(
                storage.db.execute(
                    "SELECT count(*) FROM events WHERE event_type='reviewer.assigned'"
                ).fetchone()[0],
                3,
            )
            storage.close()

    def test_fails_closed_when_only_the_producer_model_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = SQLiteStorage(root / "state.db")
            registry = self.registry(root / "agents.json")
            project_id = storage.create_project("Example", "Independence")
            task_id = storage.create_task(
                WorkItem("Task", "Review", project_id, acceptance_criteria=["Evidence"])
            )
            run_id = storage.start_run(project_id, task_id, "rotation-test")
            artifact_id = storage.add_artifact(
                run_id, "implementation", "author", "codex", "candidate"
            )
            with self.assertRaisesRegex(RuntimeError, "No independent reviewer"):
                ReviewerRouter(storage, registry).select(
                    run_id=run_id,
                    stage="validation",
                    candidate_ids=["same-model"],
                    subjects=[ReviewSubject("implementation", artifact_id, registry.get("author"))],
                    required_role="Proxy Reviewer",
                )
            storage.finish_run(run_id, "failed")
            storage.close()


if __name__ == "__main__":
    unittest.main()
