import json
import tempfile
import unittest
from pathlib import Path

from agent_factory.adapters import HEALTH_DIMENSIONS
from agent_factory.context_packages import ContextPackageBuilder
from agent_factory.hermes_qualification import HermesQualificationService
from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_runtime import FallbackForbiddenError


class HermesFallbackQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.storage = SQLiteStorage(self.root / "state.db")
        self.project_id = self.storage.create_project("Hermes qualification", "AF-047")

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def source(self, *, mutable=False):
        task_id = self.storage.create_task(WorkItem(
            "Fallback source", "Exercise controlled runtime replacement", self.project_id,
            permissions=["read_project", *(["worktree_write"] if mutable else [])],
        ))
        run_id = self.storage.start_durable_run(
            project_id=self.project_id, task_id=task_id,
            workflow_id=f"fallback-{task_id}", workflow_version="1",
            definition={"id": f"fallback-{task_id}"},
            stages=[{"id": "runtime", "depends_on": []}],
        )
        self.storage.transition_durable_stage(run_id, "runtime", "running", {"reason": "dispatch"})
        claim = self.storage.claim_runnable_task(
            task_id, "hermes-source", "hermes-acp", conflict_domains=[f"task:{task_id}"]
        )
        package = ContextPackageBuilder(self.storage, self.root).build(
            task_id=task_id, run_id=run_id, assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token, base_sha="a" * 40,
        )
        binding = {
            "run_id": run_id, "stage_id": "runtime", "attempt_id": 1,
            "worktree_id": 1, "allowed_tools": ["read_file"],
        } if mutable else None
        request = {
            "assignment_id": claim.assignment_id, "fencing_token": claim.fencing_token,
            "task_id": task_id, "project_id": self.project_id,
            "worker_id": "hermes-source", "role": "Implementation Worker",
            "permissions": ["read_project"], "mutable": mutable,
            "permission_bridge_id": "bridge" if mutable else None,
            "context_sha256": package.digest, "context_package_digest": package.digest,
            "binding": binding,
        }
        session_id = self.storage.create_runtime_session(
            assignment_id=claim.assignment_id, runtime="hermes-acp", request=request,
            context_digest=package.digest, fencing_token=claim.fencing_token,
        )
        self.storage.start_runtime_session(session_id, f"failed-hermes-{session_id}")
        self.storage.finalize_runtime_session(session_id, status="failed", result={"status": "failed"})
        return task_id, run_id, claim, session_id

    def qualify_target(self, worker_id="codex-readonly"):
        dimensions = {
            name: {"status": "pass", "evidence": "AF-047 fallback fixture"}
            for name in HEALTH_DIMENSIONS
        }
        return self.storage.record_worker_qualification(
            worker_id=worker_id, provider_id="codex", role="Implementation Worker",
            capabilities=["read_project"], dimensions=dimensions,
            evidence={"profile": "read-only"}, status="qualified", ttl_seconds=3600,
        )

    def test_failed_hermes_is_quarantined_and_readonly_fallback_is_exact(self):
        _, _, _, session_id = self.source()
        self.storage.set_worker_lifecycle("hermes-source", "active", reason="qualification passed")
        service = HermesQualificationService(self.storage)
        service.quarantine_failed_runtime(session_id, reason="ACP lifecycle failure")
        self.assertEqual(
            self.storage.db.execute(
                "SELECT state FROM worker_lifecycle WHERE worker_id='hermes-source'"
            ).fetchone()[0],
            "quarantined",
        )
        qualification_id = self.qualify_target()
        authorization_id = service.authorize_readonly_fallback(
            session_id, target_worker_id="codex-readonly", target_runtime="codex-cli",
            required_capabilities={"read_project"},
        )
        row = self.storage.db.execute(
            "SELECT * FROM runtime_fallback_authorizations WHERE id=?", (authorization_id,)
        ).fetchone()
        self.assertEqual(row["target_qualification_id"], qualification_id)
        self.assertEqual(json.loads(row["required_capabilities_json"]), ["read_project"])

    def test_fallback_denies_mutability_and_transfer_requires_checkpoint_and_new_lease(self):
        task_id, run_id, claim, session_id = self.source(mutable=True)
        self.qualify_target()
        service = HermesQualificationService(self.storage)
        with self.assertRaises(FallbackForbiddenError):
            service.authorize_readonly_fallback(
                session_id, target_worker_id="codex-readonly", target_runtime="codex-cli",
                required_capabilities={"read_project"},
            )
        checkpoint_id = int(self.storage.db.execute(
            "SELECT id FROM stage_checkpoints WHERE run_id=? ORDER BY sequence DESC LIMIT 1",
            (run_id,),
        ).fetchone()[0])
        with self.assertRaisesRegex(PermissionError, "newer active lease"):
            service.authorize_mutable_transfer(
                session_id, checkpoint_id=checkpoint_id,
                target_assignment_id=claim.assignment_id,
                target_fencing_token=claim.fencing_token, target_runtime="codex-cli",
            )
        self.storage.release_task_lease(claim.assignment_id, claim.fencing_token, outcome="failed")
        replacement = self.storage.claim_runnable_task(
            task_id, "codex-replacement", "codex-cli", conflict_domains=[f"task:{task_id}"]
        )
        transfer_id = service.authorize_mutable_transfer(
            session_id, checkpoint_id=checkpoint_id,
            target_assignment_id=replacement.assignment_id,
            target_fencing_token=replacement.fencing_token, target_runtime="codex-cli",
        )
        transfer = self.storage.db.execute(
            "SELECT * FROM runtime_transfer_authorizations WHERE id=?", (transfer_id,)
        ).fetchone()
        self.assertGreater(transfer["target_fencing_token"], claim.fencing_token)


if __name__ == "__main__":
    unittest.main()
