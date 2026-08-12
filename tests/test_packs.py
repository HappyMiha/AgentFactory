import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from agent_factory.packs import (
    PackDependency,
    PackManager,
    PackManifest,
    SignatureMetadata,
)
from agent_factory.storage import SQLiteStorage


class PackManagerTests(unittest.TestCase):
    secret = b"test-only-pack-signing-root"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        self.manager = PackManager(self.storage, core_version="0.1.0")
        self.manager.approve_trust_root(
            key_id="release-root", secret=self.secret, actor="Admin",
            actor_role="human_administrator",
        )

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    @staticmethod
    def manifest(version="1.0.0", **changes):
        value = PackManifest(
            pack_key="example_pack", version=version, pack_type="capability",
            core_min_version="0.1.0", core_max_version="0.2.0",
            permissions=("read_project",), dependencies=(),
            migrations=("001-create-index",), evaluations=("contract-test",),
            signature=SignatureMetadata("release-root"),
        )
        return replace(value, **changes)

    def signed(self, manifest=None, payload=None):
        manifest = manifest or self.manifest()
        payload = payload or {
            "requested_permissions": ["read_project"], "components": {"handler": "v1"}
        }
        return self.manager.sign(manifest, payload, self.secret), payload

    def install(self, manifest=None, payload=None, **kwargs):
        signed, payload = self.signed(manifest, payload)
        return self.manager.install(
            signed, payload, qualification_results={"contract-test": True},
            actor=kwargs.get("actor", "Operator"),
            actor_role=kwargs.get("actor_role", "operator"), reason="qualified install",
        )

    def test_manifest_persists_complete_signed_extension_contract(self):
        version_id = self.install()
        row = self.storage.db.execute(
            "SELECT * FROM pack_versions WHERE id=?", (version_id,)
        ).fetchone()
        manifest = json.loads(row["manifest_json"])
        self.assertEqual(manifest["pack_key"], "example_pack")
        self.assertEqual(manifest["version"], "1.0.0")
        self.assertEqual(manifest["core_min_version"], "0.1.0")
        self.assertEqual(manifest["permissions"], ["read_project"])
        self.assertEqual(manifest["dependencies"], [])
        self.assertEqual(manifest["migrations"], ["001-create-index"])
        self.assertEqual(manifest["evaluations"], ["contract-test"])
        self.assertEqual(manifest["signature"]["algorithm"], "hmac-sha256")
        self.assertEqual(len(manifest["signature"]["value"]), 64)
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE pack_versions SET payload_json='{}' WHERE id=?", (version_id,)
            )

    def test_install_rejects_signature_compatibility_permissions_and_qualification(self):
        signed, payload = self.signed()
        with self.assertRaisesRegex(PermissionError, "signature is invalid"):
            self.manager.install(
                replace(signed, signature=replace(signed.signature, value="0" * 64)),
                payload, qualification_results={"contract-test": True}, actor="Operator",
            )
        incompatible, payload = self.signed(self.manifest(core_min_version="9.0.0"))
        with self.assertRaisesRegex(PermissionError, "incompatible"):
            self.manager.install(
                incompatible, payload, qualification_results={"contract-test": True},
                actor="Operator",
            )
        undeclared_payload = {
            "requested_permissions": ["read_project", "network"], "components": {},
        }
        undeclared, undeclared_payload = self.signed(payload=undeclared_payload)
        with self.assertRaisesRegex(PermissionError, "undeclared"):
            self.manager.install(
                undeclared, undeclared_payload,
                qualification_results={"contract-test": True}, actor="Operator",
            )
        with self.assertRaisesRegex(PermissionError, "qualification"):
            self.manager.install(
                signed, payload, qualification_results={"contract-test": False},
                actor="Operator",
            )

    def test_privileged_connector_requires_human_administrator(self):
        manifest = self.manifest(
            pack_type="connector", permissions=("read_project", "mutate_external")
        )
        payload = {
            "requested_permissions": ["read_project", "mutate_external"],
            "components": {"connector": "bounded"},
        }
        signed, payload = self.signed(manifest, payload)
        with self.assertRaisesRegex(PermissionError, "human administrator"):
            self.manager.install(
                signed, payload, qualification_results={"contract-test": True},
                actor="Worker", actor_role="operator",
            )
        version_id = self.manager.install(
            signed, payload, qualification_results={"contract-test": True},
            actor="Admin", actor_role="human_administrator", reason="Connector reviewed",
        )
        self.assertGreater(version_id, 0)

    def test_upgrade_disable_and_rollback_restore_previous_without_history_loss(self):
        first_id = self.install()
        second_manifest = self.manifest(version="1.1.0")
        second_payload = {
            "requested_permissions": ["read_project"], "components": {"handler": "v2"}
        }
        second_id = self.install(second_manifest, second_payload)
        self.manager.disable("example_pack", actor="Admin", reason="Investigate regression")
        disabled = self.storage.db.execute(
            "SELECT * FROM pack_installations WHERE pack_key='example_pack'"
        ).fetchone()
        self.assertEqual((disabled["state"], disabled["active_version_id"]), (
            "disabled", second_id,
        ))
        restored = self.manager.rollback(
            "example_pack", actor="Admin", reason="Restore last working version"
        )
        self.assertEqual(restored, first_id)
        active = self.storage.db.execute(
            "SELECT * FROM pack_installations WHERE pack_key='example_pack'"
        ).fetchone()
        self.assertEqual((active["state"], active["active_version_id"]), (
            "active", first_id,
        ))
        self.assertEqual(
            self.storage.db.execute(
                "SELECT COUNT(*) FROM pack_versions WHERE pack_key='example_pack'"
            ).fetchone()[0],
            2,
        )
        self.assertEqual([
            row["event_type"] for row in self.storage.db.execute(
                "SELECT event_type FROM pack_lifecycle_events ORDER BY id"
            )
        ], ["installed", "upgraded", "disabled", "rolled_back"])


if __name__ == "__main__":
    unittest.main()
