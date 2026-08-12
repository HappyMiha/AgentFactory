import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_factory.storage import SQLiteStorage
from agent_factory.tenant_storage import PostgresStorageContract, TenantStorageService

class TenantStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = SQLiteStorage(Path(self.tmp.name) / "state.db")
        self.svc = TenantStorageService(self.db, Path(self.tmp.name) / "objects")
        self.svc.configure_tenant("a", retention_seconds=0, quota_bytes=5)
        self.svc.configure_tenant("b", retention_seconds=100)
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def test_scope_quota_export_and_delete_evidence(self):
        obj = self.svc.put("a", "report.txt", b"1234")
        self.assertEqual(self.svc.get("a", "report.txt"), b"1234")
        with self.assertRaises(FileNotFoundError): self.svc.get("b", "report.txt")
        self.assertTrue(self.svc.export("a")["verified"])
        self.assertEqual(self.svc.delete("a", "report.txt")["status"], "deleted")
        self.assertFalse((Path(self.tmp.name) / "objects" / "a" / obj["digest"]).exists())
    def test_retention_and_legal_hold_block_deletion_without_leak(self):
        self.svc.put("b", "secret", b"x")
        result = self.svc.delete("b", "secret")
        self.assertEqual(result["status"], "blocked"); self.assertEqual(result["reason"], "retention")
        self.svc.configure_tenant("b", retention_seconds=0, legal_hold=True)
        self.assertEqual(self.svc.delete("b", "secret")["reason"], "legal_hold")
    def test_postgres_contract_requires_explicit_scope(self):
        self.assertEqual(PostgresStorageContract.validate(dsn="postgresql://db", tenant_id="a")["scope"], "required")
        with self.assertRaises(ValueError): PostgresStorageContract.validate(dsn="postgresql://db", tenant_id="")

if __name__ == "__main__": unittest.main()
