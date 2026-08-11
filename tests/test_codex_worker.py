import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_factory.codex_worker import CODEX_EXEC_ARGS, CodexCLIProcessDriver
from agent_factory.candidate_changes import CandidateChangeService
from agent_factory.coding_delivery import CodingDeliveryService
from agent_factory.context_packages import ContextPackageBuilder
from agent_factory.evaluation import EvaluationService
from agent_factory.execution_telemetry import ExecutionBudgets, ExecutionTelemetryService
from agent_factory.live_stages import LiveStageExecution
from agent_factory.local_recovery import LocalRecoveryService
from agent_factory.models import Agent, WorkItem
from agent_factory.policy import PolicyRequest
from agent_factory.providers import ProcessSupervisor
from agent_factory.sandbox import SandboxBackend, SandboxManager
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_runtime import CodexCLIWorkerRuntime, RuntimeBinding, RuntimeLaunch
from agent_factory.worktrees import WorktreeManager
from agent_factory.validators import VALIDATOR_CATEGORIES, ValidatorPack, ValidatorRunner


FAKE_CODEX = r'''
import json
import sys
import time
from pathlib import Path

mode = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "normal"
if "--version" in sys.argv:
    print("codex-cli 9.9.9-test")
    raise SystemExit(0)
if "--help" in sys.argv:
    if mode != "bad-help":
        print("--sandbox workspace-write --ephemeral --json --cd")
    raise SystemExit(0)
prompt = sys.stdin.read()
if mode == "sleep" or '"description":"sleep"' in prompt:
    time.sleep(60)
Path("src").mkdir(exist_ok=True)
Path("src/change.py").write_text("implemented = True\n", encoding="utf-8")
print(json.dumps({"type":"item.completed","item":{"type":"command_execution","command":"python -m unittest","status":"completed","exit_code":0}}), flush=True)
print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"Implemented scoped change; tests reported by handoff."}}), flush=True)
'''


class RecordingSupervisor(ProcessSupervisor):
    def __init__(self):
        super().__init__()
        self.terminations = 0

    def terminate_tree(self, proc):
        self.terminations += 1
        return super().terminate_tree(proc)


class DirectBackend(SandboxBackend):
    name = "candidate-test"

    def availability(self):
        return True, "test"

    def wrap(self, policy, command, control_dir):
        del policy, control_dir
        return list(command)


class CodexImplementationWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.repository = self.workspace / "repository"
        self.repository.mkdir()
        self.git = shutil.which("git")
        if not self.git:
            self.skipTest("git unavailable")
        self.git_run("init")
        self.git_run("config", "user.email", "worker@example.invalid")
        self.git_run("config", "user.name", "Worker Test")
        (self.repository / "README.md").write_text("base\n", encoding="utf-8")
        self.git_run("add", "README.md")
        self.git_run("commit", "-m", "base")
        self.base_sha = self.git_run("rev-parse", "HEAD").stdout.strip().casefold()
        self.storage = SQLiteStorage(self.workspace / ".agent-factory" / "state.db")
        self.project_id = self.storage.create_project("Codex worker", "AF-049")
        self.script = self.workspace / "fake_codex.py"
        self.script.write_text(FAKE_CODEX, encoding="utf-8")

    def tearDown(self):
        if hasattr(self, "storage"):
            self.storage.close()
        self.temporary.cleanup()

    def git_run(self, *args):
        completed = subprocess.run(
            [self.git, "-C", str(self.repository), *args], shell=False,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, check=False,
        )
        if completed.returncode:
            self.fail(completed.stderr)
        return completed

    def fixture(self, *, description="implement", mode="normal", max_seconds=5, extra_criterion=False):
        acceptance_criteria = ["A scoped file changes"]
        if extra_criterion:
            acceptance_criteria.append("A reviewer verifies release readiness")
        task_id = self.storage.create_task(WorkItem(
            f"Codex task {time.time_ns()}", description, self.project_id,
            acceptance_criteria=acceptance_criteria,
            permissions=["read_project", "worktree_write", "tool_use"],
        ))
        run_id = self.storage.start_durable_run(
            project_id=self.project_id, task_id=task_id,
            workflow_id=f"codex-{task_id}", workflow_version="1",
            definition={"id": f"codex-{task_id}"},
            stages=[{"id": "implementation", "depends_on": []}],
        )
        self.storage.transition_durable_stage(run_id, "implementation", "running", {"reason": "dispatch"})
        claim = self.storage.claim_runnable_task(
            task_id, "coding-worker-codex", "codex-cli",
            conflict_domains=[f"path:codex-{task_id}"],
        )
        attempt_id = self.storage.create_assignment_attempt(claim.assignment_id, claim.fencing_token)
        worktree = WorktreeManager(self.storage, self.workspace, git_executable=self.git).provision(
            assignment_id=claim.assignment_id, fencing_token=claim.fencing_token,
            repository=self.repository, base_sha=self.base_sha, attempt_id=attempt_id,
        )
        package = ContextPackageBuilder(self.storage, self.workspace).build(
            task_id=task_id, run_id=run_id, assignment_id=claim.assignment_id,
            fencing_token=claim.fencing_token, base_sha=self.base_sha,
        )
        request = PolicyRequest(
            mission_id=self.project_id, task_id=task_id, run_id=run_id,
            stage_id="implementation", worker_id="coding-worker-codex",
            runtime_id="codex-cli", worktree_id=str(worktree.id),
            permissions=tuple(sorted(self.storage.get_task(task_id).permissions)),
        )
        live = LiveStageExecution(self.storage)
        gate = live.request_approval(request, requested_by="founder")
        approval = live.decide(gate.approval_id, "approved", actor="founder")
        launch = RuntimeLaunch(
            assignment_id=claim.assignment_id, fencing_token=claim.fencing_token,
            agent=Agent("coding-worker-codex", "Codex", "Implementation Worker", True, "codex", "Implement", model=""),
            item=self.storage.get_task(task_id), context=package.payload,
            context_digest=package.digest,
            binding=RuntimeBinding(run_id, "implementation", attempt_id, worktree.id, ("read_file", "write_file")),
            approval=approval, mutable=True,
        )
        supervisor = RecordingSupervisor()
        driver = CodexCLIProcessDriver(
            self.storage, self.workspace, executable_candidates=(sys.executable,),
            executable_args=(str(self.script), mode), max_seconds=max_seconds,
            supervisor=supervisor,
        )
        return launch, worktree, driver, supervisor

    def test_qualified_worker_records_candidate_commands_exit_and_handoff(self):
        protected = self.workspace / "protected.txt"
        protected.write_text("control-plane\n", encoding="utf-8")
        launch, worktree, driver, _ = self.fixture()
        health = driver.health(Path(worktree.path))
        self.assertTrue(health.healthy)
        runtime = CodexCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        result = runtime.finalize(session.id)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(protected.read_text(encoding="utf-8"), "control-plane\n")

        row = self.storage.db.execute("SELECT * FROM codex_worker_results").fetchone()
        self.assertEqual(json.loads(row["changed_files_json"]), ["src/change.py"])
        self.assertEqual(len(row["diff_digest"]), 64)
        self.assertEqual(json.loads(row["executed_commands_json"])[0]["command"], "python -m unittest")
        self.assertIn("Implemented scoped change", json.loads(row["handoff_json"])["summary"])
        invocation = json.loads(row["invocation_json"])
        self.assertIn("--sandbox", invocation)
        self.assertIn("workspace-write", invocation)
        self.assertIn("--ask-for-approval", invocation)
        self.assertIn("never", invocation)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", invocation)
        self.assertNotIn("--add-dir", invocation)
        self.assertEqual(tuple(invocation[3:3 + len(CODEX_EXEC_ARGS)]), CODEX_EXEC_ARGS)
        profile = json.loads(row["permission_profile_json"])
        self.assertEqual(profile["additional_write_directories"], [])
        self.assertIn("merge", profile["forbidden_authorities"])
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute("UPDATE codex_worker_results SET status='failed' WHERE id=?", (row["id"],))

    def test_timeout_and_cancel_terminate_the_process_tree(self):
        launch, _, driver, supervisor = self.fixture(mode="sleep", max_seconds=1)
        runtime = CodexCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        self.assertEqual(runtime.finalize(session.id).status, "failed")
        self.assertEqual(
            self.storage.db.execute("SELECT status FROM codex_worker_results WHERE worker_session_id=?", (session.id,)).fetchone()[0],
            "timed_out",
        )
        self.assertGreaterEqual(supervisor.terminations, 1)

        launch, _, driver, supervisor = self.fixture(mode="sleep", max_seconds=30)
        runtime = CodexCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        cancelled = runtime.cancel(session.id, reason="operator stop")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertGreaterEqual(supervisor.terminations, 1)
        self.assertEqual(
            self.storage.db.execute("SELECT status FROM codex_worker_results WHERE worker_session_id=?", (session.id,)).fetchone()[0],
            "cancelled",
        )

    def test_unqualified_interface_fails_before_task_process(self):
        launch, _, _, _ = self.fixture()
        driver = CodexCLIProcessDriver(
            self.storage, self.workspace, executable_candidates=(sys.executable,),
            executable_args=(str(self.script), "bad-help"), max_seconds=1,
        )
        self.assertFalse(driver.health().healthy)
        with self.assertRaisesRegex(RuntimeError, "not qualified"):
            CodexCLIWorkerRuntime(self.storage, driver).start(launch)
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM codex_worker_results").fetchone()[0], 0)

    def validated_candidate(self, *, failing=False, extra_criterion=False):
        launch, worktree, driver, _ = self.fixture(extra_criterion=extra_criterion)
        runtime = CodexCLIWorkerRuntime(self.storage, driver)
        runtime.finalize(runtime.start(launch).id)
        worker_result = self.storage.db.execute(
            "SELECT * FROM codex_worker_results ORDER BY id DESC LIMIT 1"
        ).fetchone()
        commands = {}
        for category in VALIDATOR_CATEGORIES:
            code = "raise SystemExit(2)" if failing and category == "lint" else "print('ok')"
            commands[category] = (sys.executable, "-c", code)
        pack = ValidatorPack.create("candidate-pack", commands)
        ValidatorRunner(
            self.storage, self.workspace,
            SandboxManager(self.storage, self.workspace, backend=DirectBackend()),
        ).run(
            assignment_id=launch.assignment_id, fencing_token=launch.fencing_token,
            attempt_id=launch.binding.attempt_id, worktree_id=worktree.id,
            candidate_digest=worker_result["diff_digest"], pack=pack,
            criterion_mappings={
                category: ("A scoped file changes",) for category in VALIDATOR_CATEGORIES
            }, max_seconds=5,
        )
        return worker_result, worktree

    def test_validated_candidate_commit_and_pr_plan_preserve_base_branch(self):
        worker_result, worktree = self.validated_candidate()
        base_before = self.git_run("rev-parse", "HEAD").stdout.strip()
        service = CandidateChangeService(self.storage, self.workspace, git_executable=self.git)
        candidate = service.create(worker_result["id"], stable_task_id="AF-051")
        self.assertEqual(candidate.base_sha, self.base_sha)
        self.assertEqual(candidate.changed_files, ("src/change.py",))
        self.assertIn("AF-051", candidate.commit_message)
        self.assertEqual(self.git_run("rev-parse", "HEAD").stdout.strip(), base_before)
        self.assertEqual(
            subprocess.run(
                [self.git, "-C", worktree.path, "log", "-1", "--pretty=%s"],
                capture_output=True, text=True, check=True,
            ).stdout.strip(),
            "AF-051: candidate change",
        )
        plan_id, gate_id = service.plan_pull_request(
            candidate.id, repo="example/repository", base_branch="main",
            title="AF-051 candidate", body="Validated candidate",
        )
        plan = json.loads(self.storage.github_plan(plan_id)["plan_json"])
        self.assertEqual(plan["operations"][0]["action"], "create_pull_request")
        self.assertEqual(
            self.storage.db.execute("SELECT status FROM github_mutation_gates WHERE id=?", (gate_id,)).fetchone()[0],
            "pending",
        )

    def test_failed_validation_cannot_become_pr_ready(self):
        worker_result, _ = self.validated_candidate(failing=True)
        with self.assertRaisesRegex(PermissionError, "Failed or incomplete"):
            CandidateChangeService(self.storage, self.workspace, git_executable=self.git).create(
                worker_result["id"], stable_task_id="AF-051"
            )
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM candidate_change_artifacts").fetchone()[0], 0)

    def test_restart_after_local_commit_adopts_exact_commit_without_duplicate(self):
        worker_result, worktree = self.validated_candidate()
        git_environment = CandidateChangeService._environment()
        subprocess.run(
            [self.git, "-C", worktree.path, "add", "--", "src/change.py"],
            check=True, capture_output=True, text=True, env=git_environment,
        )
        subprocess.run(
            [self.git, "-C", worktree.path, "commit", "-m", "AF-057: candidate change"],
            check=True, capture_output=True, text=True, env=git_environment,
        )
        committed_head = subprocess.run(
            [self.git, "-C", worktree.path, "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, env=git_environment,
        ).stdout.strip()

        candidate = CandidateChangeService(
            self.storage, self.workspace, git_executable=self.git
        ).create(worker_result["id"], stable_task_id="AF-057")

        self.assertEqual(candidate.head_sha, committed_head)
        self.assertEqual(
            subprocess.run(
                [self.git, "-C", worktree.path, "rev-list", "--count", self.base_sha + "..HEAD"],
                check=True, capture_output=True, text=True, env=git_environment,
            ).stdout.strip(),
            "1",
        )

    @staticmethod
    def review_payload(request):
        return {
            "summary": "Independent evidence review passed.",
            "criteria": [
                {
                    "criterion": criterion.criterion,
                    "verdict": "pass",
                    "confidence": 0.94,
                    "concerns": [],
                    "dissent": ["No dissent recorded"],
                }
                for criterion in request.criteria
            ],
        }

    def test_independent_evaluation_records_versioned_criterion_verdict(self):
        worker_result, _ = self.validated_candidate()
        candidate = CandidateChangeService(
            self.storage, self.workspace, git_executable=self.git
        ).create(worker_result["id"], stable_task_id="AF-020")
        reviewer = Agent(
            "independent-reviewer", "Reviewer", "Reviewer", True,
            "openai", "Review evidence", model="gpt-independent",
        )
        service = EvaluationService(self.storage)
        result = service.evaluate(
            candidate.id, reviewer=reviewer, rubric_id="coding-change",
            rubric_version="1.0.0", review=self.review_payload,
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.verdicts[0].criterion, "A scoped file changes")
        self.assertEqual(result.verdicts[0].confidence, 0.94)
        self.assertTrue(all(item["primary"] for item in result.verdicts[0].primary_evidence))
        row = self.storage.db.execute(
            "SELECT * FROM evaluation_runs WHERE id=?", (result.id,)
        ).fetchone()
        self.assertEqual(row["producer_model"], "provider:codex")
        self.assertEqual(row["reviewer_model"], "gpt-independent")
        self.assertEqual(row["rubric_version"], "1.0.0")
        verdict = self.storage.db.execute(
            "SELECT * FROM criterion_verdicts WHERE evaluation_id=?", (result.id,)
        ).fetchone()
        self.assertEqual(json.loads(verdict["concerns_json"]), [])
        self.assertEqual(json.loads(verdict["dissent_json"]), ["No dissent recorded"])
        with self.assertRaisesRegex(sqlite3.DatabaseError, "immutable"):
            self.storage.db.execute(
                "UPDATE criterion_verdicts SET confidence=0 WHERE id=?", (verdict["id"],)
            )

        calls = []
        replay = service.evaluate(
            candidate.id, reviewer=reviewer, rubric_id="coding-change",
            rubric_version="1.0.0", review=lambda request: calls.append(request),
        )
        self.assertEqual(replay.id, result.id)
        self.assertEqual(calls, [])

        def reject(request):
            payload = self.review_payload(request)
            payload["criteria"][0]["verdict"] = "fail"
            payload["criteria"][0]["concerns"] = ["Release evidence is insufficient"]
            return payload

        rejected = service.evaluate(
            candidate.id, reviewer=reviewer, rubric_id="coding-change",
            rubric_version="2.0.0", review=reject,
        )
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.verdicts[0].concerns, ("Release evidence is insufficient",))

    def test_evaluation_denies_producer_model_before_review(self):
        worker_result, _ = self.validated_candidate()
        candidate = CandidateChangeService(
            self.storage, self.workspace, git_executable=self.git
        ).create(worker_result["id"], stable_task_id="AF-020")
        calls = []
        producer = Agent(
            "same-model", "Same model", "Reviewer", True,
            "codex", "Review", model="",
        )
        with self.assertRaisesRegex(PermissionError, "cannot review its own"):
            EvaluationService(self.storage).evaluate(
                candidate.id, reviewer=producer, rubric_id="coding-change",
                rubric_version="1.0.0", review=lambda request: calls.append(request),
            )
        self.assertEqual(calls, [])
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone()[0], 0)

    def test_failed_deterministic_suite_never_invokes_model_review(self):
        worker_result, worktree = self.validated_candidate(failing=True)
        with self.storage.db:
            cursor = self.storage.db.execute(
                """INSERT INTO candidate_change_artifacts(
                       identity,codex_result_id,task_id,stable_task_id,worktree_id,
                       base_sha,head_sha,branch,diff_digest,changed_files_json,
                       commit_message,validation_digest
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.storage._identity("invalid-candidate"), worker_result["id"],
                    worker_result["task_id"], "AF-020", worker_result["worktree_id"],
                    self.base_sha, "f" * 40, worktree.branch, worker_result["diff_digest"],
                    worker_result["changed_files_json"], "AF-020: invalid candidate", "e" * 64,
                ),
            )
            candidate_id = int(cursor.lastrowid)
        calls = []
        reviewer = Agent(
            "independent-reviewer", "Reviewer", "Reviewer", True,
            "openai", "Review", model="gpt-independent",
        )
        with self.assertRaisesRegex(PermissionError, "failed before model review"):
            EvaluationService(self.storage).evaluate(
                candidate_id, reviewer=reviewer, rubric_id="coding-change",
                rubric_version="1.0.0", review=lambda request: calls.append(request),
            )
        self.assertEqual(calls, [])
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone()[0], 0)

    def test_required_criterion_without_primary_evidence_fails_acceptance_before_review(self):
        worker_result, _ = self.validated_candidate(extra_criterion=True)
        candidate = CandidateChangeService(
            self.storage, self.workspace, git_executable=self.git
        ).create(worker_result["id"], stable_task_id="AF-020")
        calls = []
        reviewer = Agent(
            "independent-reviewer", "Reviewer", "Reviewer", True,
            "openai", "Review", model="gpt-independent",
        )
        with self.assertRaisesRegex(PermissionError, "lack primary evidence"):
            EvaluationService(self.storage).evaluate(
                candidate.id, reviewer=reviewer, rubric_id="coding-change",
                rubric_version="1.0.0", review=lambda request: calls.append(request),
            )
        self.assertEqual(calls, [])
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM evaluation_runs").fetchone()[0], 0)

    def delivery_service(self):
        candidates = CandidateChangeService(
            self.storage, self.workspace, git_executable=self.git
        )
        return CodingDeliveryService(
            self.storage, candidates, EvaluationService(self.storage)
        )

    def independent_reviewer(self):
        return Agent(
            "delivery-reviewer", "Delivery reviewer", "Reviewer", True,
            "openai", "Review", model="gpt-delivery-reviewer",
        )

    def test_end_to_end_delivery_is_replay_safe_and_stops_at_gated_pr_plan(self):
        worker_result, _ = self.validated_candidate()
        service = self.delivery_service()
        delivery = service.start(
            worker_result["id"], logical_attempt_key="AF-053:logical:success",
            stable_task_id="AF-053", max_repair_iterations=3,
        )
        awaiting = service.process(
            delivery.id, worker_result["id"], reviewer=self.independent_reviewer(),
            rubric_id="coding-delivery", rubric_version="1.0.0",
            review=self.review_payload,
        )
        self.assertEqual(awaiting.status, "awaiting_founder")
        self.assertIsNotNone(awaiting.candidate_id)
        self.assertIsNotNone(awaiting.evaluation_id)
        counts = {
            table: self.storage.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "codex_worker_results", "worktrees", "candidate_change_artifacts",
                "evaluation_runs", "approval_gates",
            )
        }
        replay = service.process(
            delivery.id, worker_result["id"], reviewer=self.independent_reviewer(),
            rubric_id="coding-delivery", rubric_version="1.0.0",
            review=lambda request: self.fail("reviewer called during checkpoint replay"),
        )
        self.assertEqual(replay, awaiting)
        self.assertEqual(counts, {
            table: self.storage.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in counts
        })

        ready = service.founder_decide(
            delivery.id, "approved", actor="Founder", note="Evidence accepted",
            repo="example/repository", base_branch="main", title="AF-053 delivery",
            body="Founder-approved candidate",
        )
        self.assertEqual(ready.status, "pr_ready")
        self.assertIsNotNone(ready.github_plan_id)
        self.assertIsNotNone(ready.github_gate_id)
        plan = json.loads(self.storage.github_plan(ready.github_plan_id)["plan_json"])
        self.assertEqual(plan["operations"][0]["action"], "create_pull_request")
        self.assertNotIn("merge", json.dumps(plan).casefold())
        gate = self.storage.db.execute(
            "SELECT status FROM github_mutation_gates WHERE id=?", (ready.github_gate_id,)
        ).fetchone()
        self.assertEqual(gate["status"], "pending")
        self.assertEqual(
            self.storage.db.execute("SELECT COUNT(*) FROM github_mutation_reports").fetchone()[0], 0
        )
        replay_ready = service.founder_decide(
            delivery.id, "approved", actor="Founder", note="Evidence accepted",
            repo="example/repository", base_branch="main", title="AF-053 delivery",
            body="Founder-approved candidate",
        )
        self.assertEqual(replay_ready, ready)
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM candidate_pr_plans").fetchone()[0], 1)
        telemetry = ExecutionTelemetryService(self.storage)
        trace = telemetry.create(
            task_id=int(worker_result["task_id"]), run_id=int(worker_result["run_id"]),
            budgets=ExecutionBudgets(1000, 5.0, 8, 3, 20),
        )
        link_types = set(telemetry.link_delivery(trace.id, delivery.id))
        self.assertTrue({
            "task", "workflow", "worker_process", "worktree", "validator",
            "coding_delivery", "candidate", "evaluation", "stage_approval",
            "founder_approval", "github_approval",
        } <= link_types)
        before_restart = LocalRecoveryService(self.storage).snapshot(int(worker_result["run_id"]))
        self.assertIsNotNone(before_restart.lease)
        self.assertIsNotNone(before_restart.context)
        self.assertIsNotNone(before_restart.worktree)
        self.assertIn("github", {item["kind"] for item in before_restart.pending_approvals})
        self.storage.close()
        self.storage = SQLiteStorage(self.workspace / ".agent-factory" / "state.db")
        restored = LocalRecoveryService(self.storage).snapshot(int(worker_result["run_id"]))
        self.assertEqual(restored.stages, before_restart.stages)
        self.assertEqual(restored.lease["fencing_token"], before_restart.lease["fencing_token"])
        self.assertEqual(restored.context["digest"], before_restart.context["digest"])
        self.assertEqual(restored.worktree["id"], before_restart.worktree["id"])
        self.assertEqual(restored.pending_approvals, before_restart.pending_approvals)

    def test_validation_failure_returns_to_same_or_policy_replacement_worker(self):
        worker_result, _ = self.validated_candidate(failing=True)
        service = self.delivery_service()
        delivery = service.start(
            worker_result["id"], logical_attempt_key="AF-053:logical:repair",
            stable_task_id="AF-053", max_repair_iterations=2,
        )
        calls = []
        repair = service.process(
            delivery.id, worker_result["id"], reviewer=self.independent_reviewer(),
            rubric_id="coding-delivery", rubric_version="1.0.0",
            review=lambda request: calls.append(request),
        )
        self.assertEqual(repair.status, "active")
        self.assertEqual(repair.repair_iterations, 1)
        self.assertEqual(repair.current_worker_id, "coding-worker-codex")
        self.assertEqual(calls, [])

        replacement_result, _ = self.validated_candidate(failing=True)
        replacement_delivery = service.start(
            replacement_result["id"], logical_attempt_key="AF-053:logical:replacement",
            stable_task_id="AF-053", max_repair_iterations=2,
        )
        replacement = service.process(
            replacement_delivery.id, replacement_result["id"],
            reviewer=self.independent_reviewer(), rubric_id="coding-delivery",
            rubric_version="1.0.0", review=lambda request: calls.append(request),
            replacement_selector=lambda worker, failure: "compatible-codex-replacement",
        )
        self.assertEqual(replacement.status, "active")
        self.assertEqual(replacement.current_worker_id, "compatible-codex-replacement")

    def test_repair_iteration_cap_fails_deterministically(self):
        worker_result, _ = self.validated_candidate(failing=True)
        service = self.delivery_service()
        delivery = service.start(
            worker_result["id"], logical_attempt_key="AF-053:logical:exhausted",
            stable_task_id="AF-053", max_repair_iterations=1,
        )
        exhausted = service.process(
            delivery.id, worker_result["id"], reviewer=self.independent_reviewer(),
            rubric_id="coding-delivery", rubric_version="1.0.0",
            review=self.review_payload,
        )
        self.assertEqual(exhausted.status, "failed")
        self.assertEqual(exhausted.repair_iterations, 1)
        row = self.storage.db.execute(
            "SELECT terminal_reason FROM coding_delivery_runs WHERE id=?", (delivery.id,)
        ).fetchone()
        self.assertEqual(row["terminal_reason"], "maximum repair iterations reached")


if __name__ == "__main__":
    unittest.main()
