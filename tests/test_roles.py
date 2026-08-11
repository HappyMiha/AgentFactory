import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.roles import ContractField, RoleDefinition, RoleRegistry
from agent_factory.storage import SQLiteStorage


def role(role_id, *, incompatible=()):
    return RoleDefinition(
        id=role_id, version="1.0.0", purpose=f"Perform {role_id}",
        responsibilities=("Produce bounded evidence",),
        inputs=(ContractField("task", "object"),),
        outputs=(ContractField("result", "object"),),
        tools=("read_file",), permissions=("read_project",),
        limits=(("max_seconds", 60),),
        evidence=(ContractField("artifact_digest", "string"),),
        incompatible_duties=tuple(incompatible),
    )


class RoleDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        self.registry = RoleRegistry(self.storage)

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def test_typed_contract_validates_input_output_evidence_and_is_immutable(self):
        role_id = self.registry.register(role("implementer"))
        self.registry.validate_input("implementer", "1.0.0", {"task": {"id": 1}})
        self.registry.validate_output("implementer", "1.0.0", {"result": {"ok": True}})
        self.registry.validate_evidence("implementer", "1.0.0", {"artifact_digest": "a" * 64})
        with self.assertRaisesRegex(ValueError, "missing"):
            self.registry.validate_input("implementer", "1.0.0", {})
        with self.assertRaisesRegex(TypeError, "must be object"):
            self.registry.validate_output("implementer", "1.0.0", {"result": "wrong"})
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE role_definitions SET contract_json='{}' WHERE id=?", (role_id,)
            )

    def test_role_versions_resolve_without_agent_definition(self):
        self.registry.register(role("architect"))
        resolved = self.registry.resolve("architect", "1.0.0")
        self.assertEqual((resolved.id, resolved.version), ("architect", "1.0.0"))
        contract = self.storage.db.execute(
            "SELECT contract_json FROM role_definitions WHERE role_id='architect'"
        ).fetchone()[0]
        self.assertNotIn("agent_id", contract)
        self.assertNotIn("provider", contract)

    def test_workflow_stage_references_role_requirement_not_agent(self):
        self.registry.register(role("test_runner"))
        requirement_id = self.registry.require_role(
            workflow_id="software-delivery", workflow_version="1.0.0",
            stage_key="validate", role_id="test_runner", role_version="1.0.0",
        )
        row = self.storage.db.execute(
            "SELECT * FROM workflow_role_requirements WHERE id=?", (requirement_id,)
        ).fetchone()
        self.assertEqual((row["role_id"], row["role_version"]), ("test_runner", "1.0.0"))
        self.assertNotIn("agent", row["requirement_json"])

    def test_incompatible_implementer_and_final_reviewer_same_decision_is_rejected(self):
        self.registry.register(role("implementer", incompatible=("final_reviewer",)))
        self.registry.register(role("final_reviewer", incompatible=("implementer",)))
        self.registry.assign_decision_role(
            decision_key="candidate:1", agent_id="agent-a",
            role_id="implementer", role_version="1.0.0",
        )
        with self.assertRaisesRegex(PermissionError, "incompatible roles"):
            self.registry.assign_decision_role(
                decision_key="candidate:1", agent_id="agent-a",
                role_id="final_reviewer", role_version="1.0.0",
            )
        self.registry.assign_decision_role(
            decision_key="candidate:1", agent_id="agent-b",
            role_id="final_reviewer", role_version="1.0.0",
        )


if __name__ == "__main__":
    unittest.main()
