import tempfile
import unittest
from pathlib import Path

from agent_factory.api_contract import ConflictError, ControlPlaneAPIContract, SDKClient
from agent_factory.storage import SQLiteStorage

class APIContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = SQLiteStorage(Path(self.tmp.name) / "state.db"); self.api = ControlPlaneAPIContract(self.db, token="secret", webhook_secret=b"hook")
    def tearDown(self): self.db.close(); self.tmp.cleanup()
    def test_auth_etag_and_idempotency(self):
        self.assertEqual(self.api.authenticate("Bearer secret"), "authenticated")
        with self.assertRaises(PermissionError): self.api.authenticate(None)
        result = self.api.idempotent("tenant-a", "k1", {"x": 1}, lambda: {"id": 7}); self.assertEqual(result, self.api.idempotent("tenant-a", "k1", {"x": 1}, lambda: {"id": 8}))
        with self.assertRaises(ValueError): self.api.idempotent("tenant-a", "k1", {"x": 2}, lambda: {})
        tag = self.api.etag({"version": 1}); self.api.require_if_match({"version": 1}, tag)
        with self.assertRaises(ConflictError): self.api.require_if_match({"version": 1}, '"old"')
    def test_signed_webhook_retries_idempotently_and_sdk_headers(self):
        calls = []; sender = lambda event, signature: calls.append((event, signature)) or len(calls) == 2
        first = self.api.signed_webhook("tenant-a", "d1", {"type": "ready"}, sender=sender); replay = self.api.signed_webhook("tenant-a", "d1", {"type": "ready"}, sender=sender)
        self.assertEqual(first["status"], "delivered"); self.assertEqual(replay["attempts"], 2); self.assertEqual(len(calls), 2)
        captured = []; SDKClient(lambda *args, **kwargs: captured.append((args, kwargs)) or {}, "secret").mutate("/v1/runs", {"x": 1}, idempotency_key="k", etag='"e"'); self.assertEqual(captured[0][1]["headers"]["Idempotency-Key"], "k")

if __name__ == "__main__": unittest.main()
