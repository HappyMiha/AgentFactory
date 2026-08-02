import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.github import GitHubClient
from agent_factory.storage import SQLiteStorage

REPOSITORY = "example-org/example-repository"


def operation(key="example:test:1", action="create_issue"):
    return {
        "action": action,
        "idempotency_key": key,
        "title": "[Task] Example",
        "body": "Reviewable proposal",
        "labels": ["type:task"],
    }


class GitHubTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = SQLiteStorage(Path(self.tmp.name) / "state.db")

    def tearDown(self):
        self.storage.close()
        self.tmp.cleanup()

    @staticmethod
    def verified_runner(mutations=None, permission="WRITE"):
        mutations = mutations if mutations is not None else []

        def run(command):
            if command[1:3] == ["api", "user"]:
                return {"ok": True, "data": {"login": "contributor"}}
            if command[1:3] == ["repo", "view"]:
                return {
                    "ok": True,
                    "data": {
                        "nameWithOwner": REPOSITORY,
                        "viewerPermission": permission,
                    },
                }
            mutations.append(command)
            return {"ok": True, "data": {"url": "https://example.invalid/1"}}

        return run

    def test_repository_is_required_and_mutations_are_dry_run_by_default(self):
        with self.assertRaises(ValueError):
            GitHubClient().apply([operation()])
        result = GitHubClient(repo=REPOSITORY).apply([operation()])
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["results"][0]["executed"])

    def test_plan_is_immutable_hash_deterministic_and_gate_is_one_use(self):
        first = self.storage.create_github_plan(REPOSITORY, [operation()])
        second = self.storage.create_github_plan(REPOSITORY, [operation()])
        self.assertEqual(first, second)
        with self.assertRaises(sqlite3.DatabaseError):
            self.storage.db.execute(
                "UPDATE github_mutation_plans SET repo='changed/value' WHERE id=?", (first[0],)
            )
        gate = self.storage.request_github_gate(first[0])
        self.storage.decide_github_gate(gate, "approved", "bounded plan")
        self.storage.claim_github_gate(gate, first[0], REPOSITORY, first[1])
        with self.assertRaises(PermissionError):
            self.storage.claim_github_gate(gate, first[0], REPOSITORY, first[1])

    def test_organization_collaborator_with_write_permission_is_accepted(self):
        mutations = []
        client = GitHubClient(
            repo=REPOSITORY,
            dry_run=False,
            runner=self.verified_runner(mutations),
        )
        result = client.apply([operation()])
        self.assertTrue(result["ok"])
        self.assertEqual(result["verification"]["login"], "contributor")
        self.assertEqual(len(mutations), 1)

    def test_wrong_repository_or_insufficient_permission_blocks_mutations(self):
        calls = []

        def wrong_target(command):
            if command[1:3] == ["api", "user"]:
                return {"ok": True, "data": {"login": "contributor"}}
            if command[1:3] == ["repo", "view"]:
                return {
                    "ok": True,
                    "data": {
                        "nameWithOwner": "other/repository",
                        "viewerPermission": "ADMIN",
                    },
                }
            calls.append(command)
            return {"ok": True}

        result = GitHubClient(REPOSITORY, False, wrong_target).apply([operation()])
        self.assertFalse(result["ok"])
        self.assertEqual(calls, [])
        denied = GitHubClient(
            REPOSITORY, False, self.verified_runner(permission="READ")
        ).apply([operation()])
        self.assertFalse(denied["ok"])

    def test_allowlist_rejects_unknown_actions_fields_and_duplicate_keys(self):
        with self.assertRaises(ValueError):
            GitHubClient(REPOSITORY).apply([operation(action="delete_issue")])
        unsafe = operation()
        unsafe["state"] = "closed"
        with self.assertRaises(ValueError):
            GitHubClient(REPOSITORY).apply([unsafe])
        with self.assertRaises(ValueError):
            GitHubClient(REPOSITORY).apply([operation(), operation()])

    def test_partial_failure_is_reported_and_success_is_idempotent(self):
        count = 0

        def runner(command):
            nonlocal count
            if command[1:3] == ["api", "user"]:
                return {"ok": True, "data": {"login": "contributor"}}
            if command[1:3] == ["repo", "view"]:
                return {
                    "ok": True,
                    "data": {
                        "nameWithOwner": REPOSITORY,
                        "viewerPermission": "ADMIN",
                    },
                }
            count += 1
            return {"ok": count == 1, "error": None if count == 1 else "failure"}

        operations = [operation("one"), operation("two")]
        plan_id, plan_hash = self.storage.create_github_plan(REPOSITORY, operations)
        gate = self.storage.request_github_gate(plan_id)
        self.storage.decide_github_gate(gate, "approved", "reviewed")
        self.storage.claim_github_gate(gate, plan_id, REPOSITORY, plan_hash)
        report = GitHubClient(REPOSITORY, False, runner).apply(operations)
        self.assertFalse(report["ok"])
        self.storage.finish_github_apply(gate, plan_id, report)
        self.assertEqual(self.storage.github_completed_keys(REPOSITORY), {"one"})


if __name__ == "__main__":
    unittest.main()
