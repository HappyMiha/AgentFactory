import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_factory.credentials import CredentialBroker, REDACTED
from agent_factory.storage import SQLiteStorage


class CredentialBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.temporary.name) / "state.db")
        self.broker = CredentialBroker(self.storage)
        self.now = datetime(2026, 8, 12, tzinfo=timezone.utc)
        self.secret = "super-secret-value-123456789"

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def issue(self, **overrides):
        values = {
            "tenant_id": "tenant-a", "mission_id": "mission-a",
            "tool_key": "github.issue", "operations": ("read",),
            "preapproved_operations": {"read"}, "environment_key": "GITHUB_API_TOKEN",
            "secret_value": self.secret, "ttl_seconds": 60, "actor": "Credential Broker",
            "now": self.now,
        }
        values.update(overrides)
        return self.broker.issue(**values)

    def test_issuance_is_exactly_scoped_short_lived_and_expansion_needs_human(self):
        handle = self.issue()
        row = self.storage.db.execute(
            "SELECT * FROM credential_issuances WHERE handle=?", (handle,)
        ).fetchone()
        self.assertEqual((row["tenant_id"], row["mission_id"], row["tool_key"]), (
            "tenant-a", "mission-a", "github.issue",
        ))
        self.assertEqual(json.loads(row["operations_json"]), ["read"])
        self.assertEqual(
            datetime.fromisoformat(row["expires_at"]), self.now + timedelta(seconds=60)
        )
        with self.assertRaisesRegex(PermissionError, "system-owner approval"):
            self.issue(
                operations=("read", "write"), preapproved_operations={"read"},
                secret_value="another-secret-value-1234",
            )
        expanded = self.issue(
            operations=("read", "write"), preapproved_operations={"read"},
            secret_value="another-secret-value-5678", human_approved_by="System Owner",
        )
        self.assertTrue(expanded)

    def test_secret_is_injected_only_to_executor_and_redacted_from_all_surfaces(self):
        handle = self.issue()
        seen = {}

        def execute(environment, arguments):
            seen["environment"] = environment.copy()
            return {
                "message": f"used {environment['GITHUB_API_TOKEN']}",
                "nested": [handle, {"echo": environment["GITHUB_API_TOKEN"]}],
            }

        result = self.broker.use(
            handle, tenant_id="tenant-a", mission_id="mission-a",
            tool_key="github.issue", operation="read", prompt="Read issue metadata",
            arguments={"number": 1}, executor=execute, actor="Tool Gateway", now=self.now,
        )
        self.assertEqual(seen["environment"], {"GITHUB_API_TOKEN": self.secret})
        self.assertEqual(result["message"], f"used {REDACTED}")
        self.assertEqual(result["nested"][0], REDACTED)
        replay = self.broker.use(
            handle, tenant_id="tenant-a", mission_id="mission-a",
            tool_key="github.issue", operation="read", prompt="Read issue metadata",
            arguments={"number": 1}, executor=execute, actor="Tool Gateway", now=self.now,
        )
        self.assertEqual(replay, result)
        self.assertEqual(self.storage.db.execute(
            "SELECT COUNT(*) FROM credential_use_evidence"
        ).fetchone()[0], 2)
        persisted = "\n".join(
            str(value)
            for table in (
                "credential_issuances", "credential_lifecycle_events",
                "credential_use_evidence", "events", "outbox_messages",
            )
            for row in self.storage.db.execute(f"SELECT * FROM {table}")
            for value in tuple(row)
        )
        self.assertNotIn(self.secret, persisted)
        self.assertNotIn(handle, json.dumps(result))
        with self.assertRaisesRegex(PermissionError, "cannot enter prompts"):
            self.broker.use(
                handle, tenant_id="tenant-a", mission_id="mission-a",
                tool_key="github.issue", operation="read", prompt=f"use {self.secret}",
                arguments={}, executor=execute, actor="Tool Gateway", now=self.now,
            )

    def test_exception_is_sanitized_and_scope_mismatch_never_calls_executor(self):
        handle = self.issue()
        calls = []

        def fail(environment, arguments):
            calls.append(1)
            raise RuntimeError(f"provider rejected {environment['GITHUB_API_TOKEN']}")

        with self.assertRaisesRegex(RuntimeError, REDACTED):
            self.broker.use(
                handle, tenant_id="tenant-a", mission_id="mission-a",
                tool_key="github.issue", operation="read", prompt="read", arguments={},
                executor=fail, actor="Tool Gateway", now=self.now,
            )
        evidence = self.storage.db.execute(
            "SELECT sanitized_result_json FROM credential_use_evidence"
        ).fetchone()[0]
        self.assertNotIn(self.secret, evidence)
        self.assertIn(REDACTED, evidence)
        with self.assertRaisesRegex(PermissionError, "scope"):
            self.broker.use(
                handle, tenant_id="tenant-b", mission_id="mission-a",
                tool_key="github.issue", operation="read", prompt="read", arguments={},
                executor=fail, actor="Tool Gateway", now=self.now,
            )
        self.assertEqual(len(calls), 1)

    def test_revocation_prevents_use_and_audits_without_secret(self):
        handle = self.issue()
        self.broker.revoke(handle, actor="System Owner", reason="mission cancelled")
        with self.assertRaisesRegex(PermissionError, "revoked"):
            self.broker.use(
                handle, tenant_id="tenant-a", mission_id="mission-a",
                tool_key="github.issue", operation="read", prompt="read", arguments={},
                executor=lambda env, args: {"ok": True}, actor="Tool Gateway", now=self.now,
            )
        row = self.storage.db.execute(
            "SELECT status FROM credential_issuances WHERE handle=?", (handle,)
        ).fetchone()
        self.assertEqual(row["status"], "revoked")
        events = [item["event_type"] for item in self.storage.db.execute(
            "SELECT event_type FROM credential_lifecycle_events WHERE credential_id=(SELECT id FROM credential_issuances WHERE handle=?) ORDER BY id",
            (handle,),
        )]
        self.assertEqual(events, ["issued", "revoked", "denied"])
        serialized = "\n".join(
            str(value) for item in self.storage.db.execute(
                "SELECT * FROM credential_lifecycle_events"
            ) for value in tuple(item)
        )
        self.assertNotIn(self.secret, serialized)


if __name__ == "__main__":
    unittest.main()
