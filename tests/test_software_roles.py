import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.roles import RoleRegistry
from agent_factory.software_roles import SOFTWARE_ROLE_IDS, SoftwareEngineeringRolePack
from agent_factory.storage import SQLiteStorage


class SoftwareEngineeringRolePackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        self.pack_service = SoftwareEngineeringRolePack(self.storage)

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def test_pack_defines_exact_eight_typed_roles_and_is_immutable(self):
        pack = self.pack_service.install()
        self.assertEqual(pack.role_ids, SOFTWARE_ROLE_IDS)
        self.assertEqual(len(pack.role_ids), 8)
        registry = RoleRegistry(self.storage)
        for role_id in pack.role_ids:
            role = registry.resolve(role_id, "1.0.0")
            self.assertTrue(role.inputs)
            self.assertTrue(role.outputs)
            self.assertTrue(role.evidence)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE software_role_packs SET manifest_json='{}' WHERE id=?", (pack.id,)
            )

    def test_validator_reviewer_and_implementer_acceptance_duties_are_separate(self):
        self.pack_service.install()
        registry = RoleRegistry(self.storage)
        registry.assign_decision_role(
            decision_key="candidate:1", agent_id="worker",
            role_id="implementation_worker", role_version="1.0.0",
        )
        for role_id in ("deterministic_test_runner", "independent_code_reviewer"):
            with self.subTest(role=role_id), self.assertRaisesRegex(PermissionError, "incompatible"):
                registry.assign_decision_role(
                    decision_key="candidate:1", agent_id="worker",
                    role_id=role_id, role_version="1.0.0",
                )
        registry.assign_decision_role(
            decision_key="candidate:1", agent_id="reviewer",
            role_id="independent_code_reviewer", role_version="1.0.0",
        )

    def test_release_rejects_unknown_or_unapproved_candidate(self):
        with self.assertRaises(KeyError):
            self.pack_service.authorize_release(999, release_agent_id="release-agent")


if __name__ == "__main__":
    unittest.main()
