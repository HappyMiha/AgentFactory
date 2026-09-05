"""Coordination tests use real local Git remotes; no GitHub writes or live PRs."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("team_coordination", Path(__file__).resolve().parents[1] / "scripts" / "team.py")
team = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(team)


def task(dependencies=None, **kwargs):
    return {"dependencies": dependencies or [], "status": "planned", "owner": None,
            "branch": None, "scopes": [], "updated_at": None, "note": "", "pr": None, **kwargs}


class TeamCoordinationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentfactory-team-tests-")
        self.root = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {"TEAM_STATE_DIR": str(self.root / "state-checkouts")})
        self.env.start()
        self.remote = self.root / "registry.git"
        team.git("init", "--bare", "--quiet", str(self.remote))
        self.seed = self.root / "registry-seed"
        self.seed.mkdir()
        self.init(self.seed, "team-state")
        self.initial = {"version": 1, "workers": ["alice", {"name": "bob"}, "carol"], "events": [], "tasks": {
            "core:AF-GC-001": task(required_scopes=["core:src/one"]),
            "core:AF-GC-002": task(["core:AF-GC-001"]),
            "core:AF-GC-003": task(),
            "cloud:AF-CLD-001": task(),
        }}
        self.write_state(self.initial)
        team.git("remote", "add", "origin", str(self.remote), cwd=self.seed)
        team.git("push", "--quiet", "origin", "team-state", cwd=self.seed)
        self.registry = team.Registry(str(self.remote))

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def init(self, path, branch="main"):
        team.git("init", "--quiet", "--initial-branch=" + branch, cwd=path)
        team.git("config", "user.name", "Team Tests", cwd=path)
        team.git("config", "user.email", "tests@example.invalid", cwd=path)
        team.git("config", "commit.gpgsign", "false", cwd=path)
        team.git("config", "core.hooksPath", str(path / "no-hooks"), cwd=path)

    def write_state(self, state):
        (self.seed / "team-state.json").write_text(json.dumps(state), encoding="utf-8")
        team.git("add", "team-state.json", cwd=self.seed)
        team.git("commit", "--quiet", "-m", "registry fixture", cwd=self.seed)

    def claim(self, key="core:AF-GC-001", worker="alice", scopes=None, registry=None):
        return team.claim(registry or self.registry, key, worker, scopes or [], team.branch_for(key, worker))

    def token(self, key="core:AF-GC-001"):
        return self.registry.read()["tasks"][key].get("claim_id")

    def transition(self, action, key, worker, note="", pr=None):
        return team.transition(self.registry, action, key, worker, note, pr, claim_id=self.token(key))

    def checkout(self):
        bare = self.root / "project.git"
        team.git("init", "--bare", "--quiet", str(bare))
        path = self.root / "project"
        path.mkdir()
        self.init(path)
        (path / "README.md").write_text("initial\n", encoding="utf-8")
        team.git("add", "README.md", cwd=path)
        team.git("commit", "--quiet", "-m", "initial", cwd=path)
        team.git("remote", "add", "origin", str(bare), cwd=path)
        team.git("push", "--quiet", "--set-upstream", "origin", "main", cwd=path)
        branch = team.branch_for("core:AF-GC-001", "alice")
        team.git("switch", "--quiet", "--create", branch, cwd=path)
        return path, bare, branch

    def commit_file(self, path, name="src/one/change.txt", value="change\n"):
        file = path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(value, encoding="utf-8")
        team.git("add", name, cwd=path)
        team.git("commit", "--quiet", "-m", "change", cwd=path)

    def test_claim_adds_required_scopes_and_appends_event(self):
        state = self.claim(scopes=["core:tests/test_one.py"])
        claimed = state["tasks"]["core:AF-GC-001"]
        self.assertEqual(claimed["scopes"], ["core:src/one", "core:tests/test_one.py"])
        self.assertEqual(claimed["owner"], "alice")
        self.assertEqual(len(self.registry.read()["events"]), 1)

    def test_duplicate_claim_and_no_automatic_expiry(self):
        self.initial["tasks"]["core:AF-GC-001"].update(status="claimed", owner="alice",
            branch="team/alice/core-af-gc-001", scopes=["core:src/one"], updated_at="2000-01-01T00:00:00Z")
        self.write_state(self.initial)
        team.git("push", "--quiet", "origin", "team-state", cwd=self.seed)
        with self.assertRaisesRegex(team.TeamError, "never expire"):
            self.claim(worker="bob")
        with self.assertRaisesRegex(team.TeamError, "current owner"):
            self.transition("release", "core:AF-GC-001", "bob")
        self.assertEqual(self.registry.read()["tasks"]["core:AF-GC-001"]["owner"], "alice")

    def test_dependencies_must_be_done_and_registration_required(self):
        with self.assertRaisesRegex(team.TeamError, "Dependencies"):
            self.claim("core:AF-GC-002", scopes=["core:src/two"])
        with self.assertRaisesRegex(team.TeamError, "registered"):
            self.claim(worker="unknown")

    def test_scope_prefixes_and_cross_repository_locks(self):
        self.claim()
        with self.assertRaisesRegex(team.TeamError, "overlaps"):
            self.claim("core:AF-GC-003", "bob", ["core:src"])
        self.claim("cloud:AF-CLD-001", "bob", ["cloud:src"])
        self.assertFalse(team.overlap("core:src/a", "core:src/abc"))
        self.assertTrue(team.overlap("core:src/a", "core:src/a/b.py"))
        self.assertTrue(team.overlap("core:src/A", "core:src/a/b.py"))

    def test_shared_resource_lock_blocks_other_repository(self):
        self.initial["tasks"]["core:AF-GC-001"]["resources"] = ["artifact-contract"]
        self.initial["tasks"]["cloud:AF-CLD-001"]["resources"] = ["artifact-contract"]
        self.write_state(self.initial)
        team.git("push", "--quiet", "origin", "team-state", cwd=self.seed)
        self.claim()
        with self.assertRaisesRegex(team.TeamError, "shared resource"):
            self.claim("cloud:AF-CLD-001", "bob", ["cloud:docs"])

    def test_block_releases_locks_but_requires_owner_release_before_claim(self):
        self.claim()
        self.transition("block", "core:AF-GC-001", "alice", "Waiting on dependency")
        self.claim("core:AF-GC-003", "bob", ["core:src"])
        with self.assertRaisesRegex(team.TeamError, "not available"):
            self.claim(worker="carol")
        self.transition("release", "core:AF-GC-001", "alice")
        self.assertEqual(self.registry.read()["tasks"]["core:AF-GC-001"]["status"], "planned")

    def test_real_concurrent_updates_retry_and_preserve_both_events(self):
        barrier = threading.Barrier(2)
        class RacingRegistry(team.Registry):
            first = True
            def _fetch(self, path):
                state = super()._fetch(path)
                if self.first:
                    self.first = False
                    barrier.wait(timeout=15)
                return state
        def submit(key, worker, scopes):
            return self.claim(key, worker, scopes, RacingRegistry(str(self.remote)))
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(submit, "core:AF-GC-001", "alice", [])
            second = pool.submit(submit, "cloud:AF-CLD-001", "bob", ["cloud:src"])
            first.result(timeout=30)
            second.result(timeout=30)
        state = self.registry.read()
        self.assertEqual(len(state["events"]), 2)
        self.assertEqual(state["tasks"]["core:AF-GC-001"]["owner"], "alice")
        self.assertEqual(state["tasks"]["cloud:AF-CLD-001"]["owner"], "bob")

    def test_ambiguous_success_is_detected_without_duplicate_event(self):
        real_run = team.run
        hidden = False
        def lose_response(args, *pargs, **kwargs):
            nonlocal hidden
            result = real_run(args, *pargs, **kwargs)
            if args[:3] == ["git", "push", "--porcelain"] and not hidden:
                hidden = True
                return subprocess.CompletedProcess(args, 1, "", "lost response")
            return result
        with mock.patch.object(team, "run", side_effect=lose_response):
            self.claim()
        self.assertTrue(hidden)
        self.assertEqual(len(self.registry.read()["events"]), 1)

    def test_review_and_complete_require_exact_merged_pr_evidence(self):
        self.claim()
        url = "https://github.com/HappyMiha/AgentFactory/pull/42"
        data = {"state": "OPEN", "mergedAt": None, "mergeCommit": {"oid": "c" * 40}, "baseRefName": "main", "headRefName": "team/alice/core-af-gc-001", "headRefOid": "a" * 40, "url": url}
        real_run = team.run
        def gh(args, *pargs, **kwargs):
            if args[0] == "gh":
                return subprocess.CompletedProcess(args, 0, json.dumps(data), "")
            return real_run(args, *pargs, **kwargs)
        with mock.patch.object(team, "run", side_effect=gh):
            self.transition("review", "core:AF-GC-001", "alice", pr=url)
            with self.assertRaisesRegex(team.TeamError, "not merged"):
                self.transition("complete", "core:AF-GC-001", "alice", pr=url)
            data.update(state="MERGED", mergedAt="2026-09-05T12:00:00Z", headRefOid="b" * 40)
            with self.assertRaisesRegex(team.TeamError, "reviewed head"):
                self.transition("complete", "core:AF-GC-001", "alice", pr=url)
            data["headRefOid"] = "a" * 40
            self.transition("complete", "core:AF-GC-001", "alice", pr=url)
        done = self.registry.read()["tasks"]["core:AF-GC-001"]
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["scopes"], [])
        self.assertEqual(done["completed_commit"], "c" * 40)
        self.assertEqual(done["reviewed_head"], "a" * 40)

    def test_pr_wrong_branch_base_or_repository_rejected(self):
        url = "https://github.com/HappyMiha/AgentFactory/pull/42"
        data = {"state": "MERGED", "mergedAt": "today", "baseRefName": "dev", "headRefName": "team/alice/wrong", "headRefOid": "a" * 40, "url": url}
        with mock.patch.object(team, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(data), "")):
            with self.assertRaisesRegex(team.TeamError, "exact claimed branch"):
                team.pr_details(url, "core:AF-GC-001", "team/alice/core-af-gc-001")
        with self.assertRaisesRegex(team.TeamError, "task's GitHub"):
            team.pr_details(url, "cloud:AF-CLD-001", "team/alice/cloud-af-cld-001")

    def test_preflight_accepts_claimed_paths_and_rejects_wrong_owner(self):
        path, bare, branch = self.checkout()
        self.claim()
        self.commit_file(path)
        self.assertEqual(team.preflight(self.registry, path, "alice", "core"), "core:AF-GC-001")
        with self.assertRaises(team.TeamError):
            team.preflight(self.registry, path, "bob", "core")
        self.commit_file(path, "outside.txt")
        with self.assertRaisesRegex(team.TeamError, "outside the claim"):
            team.preflight(self.registry, path, "alice", "core")

    def test_push_rejects_main_tags_deletion_multiple_refs_and_non_ff(self):
        path, bare, branch = self.checkout()
        self.claim()
        self.commit_file(path)
        head = team.git("rev-parse", "HEAD", cwd=path)
        zero = "0" * 40
        valid = f"refs/heads/{branch} {head} refs/heads/{branch} {zero}\n"
        self.assertEqual(team.preflight(self.registry, path, "alice", "core", push=["origin", str(bare)], stdin=valid, claim_id=self.token()), "core:AF-GC-001")
        head_ref = f"HEAD {head} refs/heads/{branch} {zero}\n"
        self.assertEqual(team.preflight(self.registry, path, "alice", "core", push=["origin", str(bare)], stdin=head_ref, claim_id=self.token()), "core:AF-GC-001")
        for invalid in ("", valid + valid, valid.replace(f"refs/heads/{branch}", "refs/heads/main"), valid.replace(f"refs/heads/{branch}", "refs/tags/v1"), valid.replace(head, zero)):
            with self.assertRaises(team.TeamError):
                team.preflight(self.registry, path, "alice", "core", push=["origin", str(bare)], stdin=invalid, claim_id=self.token())
        team.git("push", "--quiet", "origin", branch, cwd=path)
        team.git("reset", "--hard", "HEAD~1", cwd=path)
        self.commit_file(path, value="replacement\n")
        new_head = team.git("rev-parse", "HEAD", cwd=path)
        non_ff = f"refs/heads/{branch} {new_head} refs/heads/{branch} {head}\n"
        with self.assertRaisesRegex(team.TeamError, "Non-fast-forward"):
            team.preflight(self.registry, path, "alice", "core", push=["origin", str(bare)], stdin=non_ff, claim_id=self.token())

    def test_claim_generations_fence_stale_owner_and_branch_reuse(self):
        self.claim()
        old_token = self.token()
        self.transition("release", "core:AF-GC-001", "alice")
        with self.assertRaisesRegex(team.TeamError, "cannot be reused"):
            self.claim()
        team.claim(self.registry, "core:AF-GC-001", "alice", [], "team/alice/core-af-gc-001-new")
        with self.assertRaisesRegex(team.TeamError, "stale"):
            team.transition(self.registry, "block", "core:AF-GC-001", "alice", claim_id=old_token)
        self.assertEqual(self.registry.read()["tasks"]["core:AF-GC-001"]["status"], "claimed")

    def test_rescope_is_atomic_and_keeps_required_scopes(self):
        self.claim()
        self.claim("core:AF-GC-003", "bob", ["core:tests"])
        with self.assertRaisesRegex(team.TeamError, "overlaps"):
            team.transition(self.registry, "rescope", "core:AF-GC-001", "alice", claim_id=self.token(), scopes=["core:tests"])
        state = team.transition(self.registry, "rescope", "core:AF-GC-001", "alice", claim_id=self.token(), scopes=["core:docs"])
        self.assertEqual(state["tasks"]["core:AF-GC-001"]["scopes"], ["core:docs", "core:src/one"])

    def test_registry_rejects_cycles_and_accepts_only_catalogued_maintenance(self):
        state = json.loads(json.dumps(self.initial))
        state["tasks"]["core:AF-GC-001"]["dependencies"] = ["core:AF-GC-002"]
        with self.assertRaisesRegex(team.TeamError, "cycle"):
            team.validate_state(state)
        self.initial["tasks"]["core:TEAM-SETUP"] = task()
        self.write_state(self.initial)
        team.git("push", "--quiet", "origin", "team-state", cwd=self.seed)
        team.claim(self.registry, "core:TEAM-SETUP", "alice", ["core:scripts"], "team/alice/core-team-setup")
        with self.assertRaisesRegex(team.TeamError, "Unknown task"):
            team.claim(self.registry, "cloud:TEAM-SETUP", "bob", ["cloud:scripts"], "team/bob/cloud-team-setup")

    def test_stale_main_and_dirty_tree_are_rejected(self):
        path, bare, branch = self.checkout()
        self.claim()
        self.commit_file(path)
        team.git("switch", "--quiet", "main", cwd=path)
        self.commit_file(path, "upstream.txt")
        team.git("push", "--quiet", "origin", "main", cwd=path)
        team.git("switch", "--quiet", branch, cwd=path)
        with self.assertRaisesRegex(team.TeamError, "current origin/main"):
            team.preflight(self.registry, path, "alice", "core")
        (path / "untracked.txt").write_text("draft\n", encoding="utf-8")
        with self.assertRaisesRegex(team.TeamError, "clean"):
            team.preflight(self.registry, path, "alice", "core")

    def test_ci_detached_range_does_not_fetch_origin(self):
        path, bare, branch = self.checkout()
        self.claim()
        self.commit_file(path)
        team.git("switch", "--quiet", "--detach", "HEAD", cwd=path)
        real_run = team.run
        def no_origin_fetch(args, *pargs, **kwargs):
            if args[:2] == ["git", "fetch"] and "origin" in args:
                self.fail("CI range mode must use its already-fetched main without origin credentials")
            return real_run(args, *pargs, **kwargs)
        with mock.patch.object(team, "run", side_effect=no_origin_fetch):
            self.assertEqual(team.preflight(self.registry, path, "alice", "core", branch, "origin/main...HEAD"), "core:AF-GC-001")


if __name__ == "__main__":
    unittest.main()
