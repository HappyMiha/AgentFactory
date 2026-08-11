import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage


class EvidenceLedgerTests(unittest.TestCase):
    def fixture(self, root: Path):
        storage = SQLiteStorage(root / "state.db")
        project_id = storage.create_project("Example", "Evidence checks")
        task_id = storage.create_task(
            WorkItem(
                "Implement feature",
                "Produce independently verifiable evidence.",
                project_id,
                acceptance_criteria=["The deterministic test passes"],
            )
        )
        run_id = storage.start_run(project_id, task_id, "delivery")
        return storage, task_id, run_id

    def test_artifact_has_digest_producer_verifier_inputs_and_toolchain(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, _, run_id = self.fixture(Path(tmp))
            content = "1 passed in 0.04s"
            artifact_id = storage.add_artifact(
                run_id,
                "validate",
                "deterministic-test-runner",
                "local",
                content,
                producer={"role": "Deterministic Test Runner", "worker": "test-1"},
                verifier={"status": "pending", "required_role": "reviewer"},
                inputs={"candidate_digest": "a" * 64, "command": ["python", "-m", "unittest"]},
                toolchain={"python": "3.12", "runner": "unittest"},
                evidence_kind="test_result",
            )
            row = storage.db.execute(
                "SELECT * FROM artifacts WHERE id=?", (artifact_id,)
            ).fetchone()
            self.assertEqual(
                row["digest"], hashlib.sha256(content.encode("utf-8")).hexdigest()
            )
            self.assertEqual(json.loads(row["producer_json"])["role"], "Deterministic Test Runner")
            self.assertEqual(json.loads(row["verifier_json"])["status"], "pending")
            self.assertEqual(json.loads(row["inputs_json"])["candidate_digest"], "a" * 64)
            self.assertEqual(json.loads(row["toolchain_json"])["python"], "3.12")
            self.assertTrue(storage.verify_evidence_ledger()["ok"])
            storage.close()

    def test_summary_alone_cannot_close_criterion_but_primary_evidence_can(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, task_id, run_id = self.fixture(Path(tmp))
            summary_id = storage.add_artifact(
                run_id,
                "review",
                "llm-reviewer",
                "model",
                "The implementation looks correct.",
                evidence_kind="summary",
            )
            summary_evidence = storage.link_criterion_evidence(
                task_id=task_id,
                criterion_index=0,
                artifact_id=summary_id,
                evidence_type="summary",
            )
            storage.decide_criterion_evidence(
                summary_evidence, "accepted", verifier="independent-reviewer"
            )
            status = storage.criterion_evidence_status(task_id)
            self.assertFalse(status["closed"])
            self.assertFalse(status["evidence"][0]["primary"])

            storage.transition_task(task_id, "running")
            storage.transition_task(task_id, "completed")
            with self.assertRaisesRegex(ValueError, "accepted primary evidence"):
                storage.transition_task(task_id, "approved")

            result_id = storage.add_artifact(
                run_id,
                "validate",
                "deterministic-test-runner",
                "local",
                "PASS test_feature",
                evidence_kind="test_result",
            )
            primary_evidence = storage.link_criterion_evidence(
                task_id=task_id,
                criterion_index=0,
                artifact_id=result_id,
                evidence_type="test_result",
            )
            storage.decide_criterion_evidence(
                primary_evidence,
                "accepted",
                verifier="independent-code-reviewer",
                note="Command output and candidate match.",
            )
            self.assertTrue(storage.criterion_evidence_status(task_id)["closed"])
            storage.transition_task(task_id, "approved")
            self.assertEqual(storage.get_task(task_id).status.value, "approved")
            storage.close()

    def test_accepted_evidence_and_artifact_are_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, task_id, run_id = self.fixture(Path(tmp))
            artifact_id = storage.add_artifact(
                run_id,
                "implementation",
                "coding-worker",
                "codex",
                "diff --git a/a.py b/a.py",
                evidence_kind="diff",
            )
            evidence_id = storage.link_criterion_evidence(
                task_id=task_id,
                criterion_index=0,
                artifact_id=artifact_id,
                evidence_type="diff",
            )
            storage.decide_criterion_evidence(
                evidence_id, "accepted", verifier="founder"
            )
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute(
                    "UPDATE artifacts SET content='changed' WHERE id=?", (artifact_id,)
                )
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute(
                    "UPDATE criterion_evidence SET verifier_json='{}' WHERE id=?",
                    (evidence_id,),
                )
            with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
                storage.db.execute(
                    "DELETE FROM criterion_evidence WHERE id=?", (evidence_id,)
                )
            storage.close()

    def test_digest_drift_blocks_acceptance_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, task_id, run_id = self.fixture(Path(tmp))
            artifact_id = storage.add_artifact(
                run_id,
                "validate",
                "test-runner",
                "local",
                "PASS",
                evidence_kind="test_result",
            )
            evidence_id = storage.link_criterion_evidence(
                task_id=task_id,
                criterion_index=0,
                artifact_id=artifact_id,
                evidence_type="test_result",
            )
            storage.db.execute(
                "UPDATE artifacts SET content='FAIL' WHERE id=?", (artifact_id,)
            )
            storage.db.commit()
            with self.assertRaisesRegex(ValueError, "digest changed"):
                storage.decide_criterion_evidence(
                    evidence_id, "accepted", verifier="reviewer"
                )
            self.assertFalse(storage.integrity_check()["ok"])
            storage.close()

    def test_evidence_cannot_be_relabelled_or_cross_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage, task_id, run_id = self.fixture(Path(tmp))
            artifact_id = storage.add_artifact(
                run_id,
                "validate",
                "test-runner",
                "local",
                "PASS",
                evidence_kind="test_result",
            )
            with self.assertRaisesRegex(ValueError, "typed test_result"):
                storage.link_criterion_evidence(
                    task_id=task_id,
                    criterion_index=0,
                    artifact_id=artifact_id,
                    evidence_type="review",
                )
            second_task = storage.create_task(
                WorkItem(
                    "Other task",
                    "Separate authority",
                    storage.get_task(task_id).project_id,
                    acceptance_criteria=["Other criterion"],
                )
            )
            with self.assertRaisesRegex(ValueError, "different work item"):
                storage.link_criterion_evidence(
                    task_id=second_task,
                    criterion_index=0,
                    artifact_id=artifact_id,
                    evidence_type="test_result",
                )
            storage.close()


if __name__ == "__main__":
    unittest.main()
