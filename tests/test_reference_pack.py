import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.packs import PackManager
from agent_factory.reference_pack import (
    RELEASE_AUTHORITY_ROLE,
    ReferencePackService,
    ReleaseTrace,
)
from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage


class ReferencePackServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        project_id = self.storage.create_project("Reference", "AF-025")
        self.task_id = self.storage.create_task(
            WorkItem(
                "Ship reference capability", "Package proven contracts", project_id,
                acceptance_criteria=["Manifest is reproducible"],
            )
        )
        self.manager = PackManager(self.storage, core_version="0.1.0")
        self.service = ReferencePackService(self.storage, self.manager)
        self.trace = ReleaseTrace(
            requirements=("R-REFERENCE-001",), tasks=(self.task_id,),
            blueprint_decisions=("verification_decision",),
            adrs=("ADR-REFERENCE-001",),
            test_evidence=("test_reference_pack.py", "full-suite:247"),
            review_verdicts=("accepted-review:AF-020:reference-pack",),
        )
        self.secret = b"reference-pack-release-secret"

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def test_manifest_consumes_existing_core_contracts_and_traceability(self):
        manifest, payload = self.service.build_manifest(trace=self.trace)
        self.assertEqual(manifest.pack_key, "software-engineering-reference")
        self.assertEqual(manifest.dependencies[0].pack_key, "software-engineering")
        self.assertEqual(
            set(payload["core_contracts"]),
            {
                "managed_worktrees", "worker_runtime", "candidate_artifacts",
                "deterministic_validators", "independent_evaluation", "coding_delivery",
            },
        )
        self.assertEqual(payload["traceability"]["tasks"], [self.task_id])
        self.assertTrue(payload["rollback"]["verified"])

    def test_publish_requires_human_release_authority_and_persists_reproducible_evidence(self):
        with self.assertRaisesRegex(PermissionError, "release authority"):
            self.service.publish(
                trace=self.trace, signing_secret=self.secret,
                administrator="Admin", release_authority="Worker",
                release_authority_role="operator",
            )
        release = self.service.publish(
            trace=self.trace, signing_secret=self.secret,
            administrator="Admin", release_authority="ReleaseLead",
            release_authority_role=RELEASE_AUTHORITY_ROLE,
        )
        row = self.storage.db.execute(
            "SELECT * FROM reference_pack_releases WHERE id=?", (release.id,)
        ).fetchone()
        self.assertEqual(row["status"], "candidate")
        manifest = json.loads(row["release_manifest_json"])
        self.assertEqual(manifest["pack_version_id"], release.pack_version_id)
        self.assertEqual(json.loads(row["traceability_json"])["review_verdicts"], [
            "accepted-review:AF-020:reference-pack"
        ])
        self.assertTrue(json.loads(row["rollback_evidence_json"])["verified"])
        self.assertEqual(
            self.storage.db.execute(
                "SELECT state FROM pack_installations WHERE pack_key='software-engineering-reference'"
            ).fetchone()[0],
            "active",
        )
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE reference_pack_releases SET release_manifest_json='{}' WHERE id=?",
                (release.id,),
            )

    def test_release_lifecycle_and_rollback_procedure_are_attributed(self):
        release = self.service.publish(
            trace=self.trace, signing_secret=self.secret,
            administrator="Admin", release_authority="ReleaseLead",
            release_authority_role=RELEASE_AUTHORITY_ROLE,
        )
        with self.assertRaisesRegex(PermissionError, "configured release authority"):
            self.service.approve(release.id, authority="Other", reason="approve")
        self.service.approve(release.id, authority="ReleaseLead", reason="Evidence reviewed")
        self.service.publish_approved(
            release.id, authority="ReleaseLead", reason="Publish protected release"
        )
        self.assertEqual(
            self.storage.db.execute(
                "SELECT status FROM reference_pack_releases WHERE id=?", (release.id,)
            ).fetchone()[0],
            "published",
        )
        with self.assertRaisesRegex(ValueError, "previous"):
            self.service.rollback(release.id, authority="ReleaseLead", reason="Rollback")
        events = self.storage.db.execute(
            "SELECT event_type,actor FROM reference_pack_release_events WHERE release_id=? ORDER BY id",
            (release.id,),
        ).fetchall()
        self.assertEqual([(row["event_type"], row["actor"]) for row in events], [
            ("approved", "ReleaseLead"), ("published", "ReleaseLead"),
        ])


if __name__ == "__main__":
    unittest.main()
