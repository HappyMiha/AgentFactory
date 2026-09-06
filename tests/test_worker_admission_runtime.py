"""Exact admitted launch and replay fences through the real Core runtime boundary."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import threading
import unittest
from unittest.mock import Mock, patch

from agent_factory.context_packages import ContextPackageBuilder
from agent_factory.live_stages import LiveStageExecution
from agent_factory.models import Agent
from agent_factory.policy import PolicyRequest
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_admission import AdmissionConflictError, CapacityUnavailableError
from agent_factory.worker_runtime import (
    CodexCLIWorkerRuntime, DirectCLIWorkerRuntime, RuntimeBinding, RuntimeDriver,
    RuntimeDriverEvent, RuntimeLaunch,
)
from test_worker_admission import AdmissionFixture


class AdmissionDriver(RuntimeDriver):
    """A counting synthetic driver; it never starts a process or calls a model."""
    mutation_boundary_on_start = True

    def __init__(self):
        self.lock = threading.Lock()
        self.starts = []
        self.entered = threading.Event()
        self.release = None
        self.raise_after_start = False
        self.cancelled = []
        self.resumes = []
        self.heartbeats = []

    def start(self, launch, *, control_session_id=None):
        with self.lock:
            self.starts.append(control_session_id)
            external_id = f'synthetic-session-{len(self.starts)}'
        self.entered.set()
        if self.release is not None and not self.release.wait(10):
            raise RuntimeError('Synthetic start barrier timed out')
        if self.raise_after_start:
            raise ConnectionError('Synthetic start response lost after external acceptance')
        return external_id

    def resume(self, external_session_id):
        self.resumes.append(external_session_id)

    def heartbeat(self, external_session_id):
        self.heartbeats.append(external_session_id)

    def cancel(self, external_session_id):
        self.cancelled.append(external_session_id)

    def collect_events(self, external_session_id):
        return [RuntimeDriverEvent('status', {'state': 'running'})]

    def finalize(self, external_session_id):
        return 'succeeded'


class WorkerAdmissionRuntimeTests(AdmissionFixture):
    def launch_fixture(self, *, mutable=True):
        self.configure()
        request = self.request(mutable=mutable)
        receipt = self.service.admit(request)
        worktree = self.storage.create_managed_worktree(
            assignment_id=receipt.assignment_id, fencing_token=receipt.fencing_token,
            repository=str(self.root / 'repository'), base_sha='a' * 40,
            branch=f'fixture/task-{request.task_id}', path=str(self.root / 'worktree'),
            attempt_id=receipt.attempt_id,
        )
        self.storage.transition_managed_worktree(worktree, 'ready')
        package = ContextPackageBuilder(self.storage, self.root).build(
            task_id=request.task_id, run_id=request.run_id,
            assignment_id=receipt.assignment_id, fencing_token=receipt.fencing_token,
            base_sha='a' * 40,
        )
        launch = RuntimeLaunch(
            assignment_id=receipt.assignment_id, fencing_token=receipt.fencing_token,
            agent=Agent(request.worker_id, request.worker_id, request.role, True,
                        request.provider_id, 'Synthetic bounded worker'),
            item=self.storage.get_task(request.task_id), context=package.payload,
            context_digest=package.digest,
            binding=RuntimeBinding(request.run_id, request.stage_key, receipt.attempt_id,
                                   worktree, ('read_file', 'write_file') if mutable else ('read_file',)),
            mutable=mutable, permission_bridge_id='synthetic-bridge' if mutable else None,
        )
        if mutable:
            policy = PolicyRequest(
                mission_id=request.project_id, task_id=request.task_id, run_id=request.run_id,
                stage_id=request.stage_key, worker_id=request.worker_id, runtime_id=request.runtime,
                worktree_id=str(worktree), permissions=tuple(sorted(launch.item.permissions)),
            )
            live = LiveStageExecution(self.storage)
            gate = live.request_approval(policy, requested_by='synthetic-owner')
            approval = live.decide(gate.approval_id, 'approved', actor='synthetic-owner')
            launch = replace(launch, approval=approval)
        return request, receipt, launch

    def approval_status(self, launch):
        return self.storage.db.execute(
            'SELECT status FROM scoped_execution_approvals WHERE id=?',
            (launch.approval.gate_id,)).fetchone()[0]

    def assert_not_launched(self, launch, driver):
        self.assertEqual(driver.starts, [])
        self.assertEqual(self.approval_status(launch), 'approved')
        self.assertEqual(self.storage.db.execute(
            'SELECT COUNT(*) FROM worker_sessions WHERE assignment_id=?',
            (launch.assignment_id,)).fetchone()[0], 0)

    def test_exact_scope_is_checked_before_approval_or_driver(self):
        request, receipt, launch = self.launch_fixture()
        _, other_task, other_run = self.task()
        other_claim = self.storage.claim_runnable_task(
            other_task, 'unregistered-local', 'direct-cli',
            conflict_domains=('path:other-task',))
        other_attempt = self.storage.create_assignment_attempt(
            other_claim.assignment_id, other_claim.fencing_token)
        other_tree = self.storage.create_managed_worktree(
            assignment_id=other_claim.assignment_id, fencing_token=other_claim.fencing_token,
            repository=str(self.root / 'repository'), base_sha='a' * 40,
            branch='fixture/other', path=str(self.root / 'other-tree'), attempt_id=other_attempt)
        self.storage.transition_managed_worktree(other_tree, 'ready')
        sibling_run = self.storage.start_durable_run(
            project_id=request.project_id, task_id=request.task_id,
            workflow_id='sibling-workflow', workflow_version='1',
            definition={'id': 'sibling-workflow'},
            stages=[{'id': request.stage_key, 'depends_on': []}],
        )
        self.storage.transition_durable_stage(sibling_run, request.stage_key, 'running', {})
        sibling_context = ContextPackageBuilder(self.storage, self.root).build(
            task_id=request.task_id, run_id=sibling_run, assignment_id=receipt.assignment_id,
            fencing_token=receipt.fencing_token, base_sha='a' * 40,
        )
        driver = AdmissionDriver()
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        variants = [
            replace(launch, binding=None),
            replace(launch, binding=replace(launch.binding, run_id=other_run)),
            replace(launch, binding=replace(launch.binding, run_id=sibling_run)),
            replace(launch, context=sibling_context.payload, context_digest=sibling_context.digest),
            replace(launch, binding=replace(launch.binding, stage_id='review')),
            replace(launch, binding=replace(launch.binding, stage_id='absent')),
            replace(launch, binding=replace(launch.binding, attempt_id=other_attempt)),
            replace(launch, binding=replace(launch.binding, worktree_id=other_tree)),
            replace(launch, agent=replace(launch.agent, provider='other-provider')),
            replace(launch, agent=replace(launch.agent, role='Reviewer')),
            replace(launch, agent=replace(launch.agent, enabled=False)),
            replace(launch, item=replace(launch.item, permissions=[*launch.item.permissions, 'network'])),
            replace(launch, item=replace(launch.item, kind='epic')),
            replace(launch, item=replace(launch.item, budget=replace(launch.item.budget, max_tokens=999999))),
        ]
        for index, invalid in enumerate(variants):
            with self.subTest(case=index), self.assertRaises((PermissionError, ValueError, KeyError)):
                runtime.start(invalid)
            self.assert_not_launched(launch, driver)
        self.storage.transition_managed_worktree(launch.binding.worktree_id, 'retained')
        with self.assertRaises(PermissionError):
            runtime.start(launch)
        self.assert_not_launched(launch, driver)

    def test_readonly_admitted_assignment_still_requires_exact_binding(self):
        _, _, launch = self.launch_fixture(mutable=False)
        driver = AdmissionDriver()
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        with self.assertRaises(PermissionError):
            runtime.start(replace(launch, binding=None))
        self.assertEqual(driver.starts, [])
        session = runtime.start(launch)
        self.assertEqual(session.status, 'running')
        self.assertEqual(len(driver.starts), 1)

    def test_finished_attempt_cannot_launch_even_readonly_worker(self):
        _, receipt, launch = self.launch_fixture(mutable=False)
        with self.storage.db:
            self.storage.db.execute("UPDATE attempts SET status='running' WHERE id=?", (receipt.attempt_id,))
            self.storage.db.execute("UPDATE attempts SET status='succeeded' WHERE id=?", (receipt.attempt_id,))
        driver = AdmissionDriver()
        with self.assertRaises(PermissionError):
            DirectCLIWorkerRuntime(self.storage, driver).start(launch)
        self.assertEqual(driver.starts, [])
        self.assertEqual(self.storage.db.execute(
            'SELECT COUNT(*) FROM worker_sessions WHERE assignment_id=?',
            (launch.assignment_id,)).fetchone()[0], 0)

    def test_concurrent_and_replayed_start_use_one_external_call_and_one_approval(self):
        _, _, launch = self.launch_fixture()
        driver = AdmissionDriver()
        driver.release = threading.Event()

        def start():
            with closing(SQLiteStorage(self.path)) as connection:
                return DirectCLIWorkerRuntime(connection, driver).start(launch)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(start)
            try:
                self.assertTrue(driver.entered.wait(4), 'First launch must reach the real runtime driver')
                second = pool.submit(start)
                observed = second.result(timeout=4)
                self.assertEqual(observed.status, 'starting')
                self.assertEqual(len(driver.starts), 1)
            finally:
                driver.release.set()
            started = first.result(timeout=5)
        self.assertEqual(started.id, observed.id)
        replayed = DirectCLIWorkerRuntime(self.storage, driver).start(launch)
        self.assertEqual(replayed.id, started.id)
        self.assertEqual(len(driver.starts), 1)
        self.assertEqual(self.approval_status(launch), 'consumed')
        self.assertEqual(self.storage.db.execute(
            'SELECT COUNT(*) FROM stage_approval_consumptions WHERE assignment_id=?',
            (launch.assignment_id,)).fetchone()[0], 1)
        with self.assertRaises((AdmissionConflictError, PermissionError)):
            DirectCLIWorkerRuntime(self.storage, driver).start(
                replace(launch, permission_bridge_id='changed-bridge'))
        self.assertEqual(len(driver.starts), 1)

    def test_uncertain_external_start_keeps_capacity_and_never_restarts_on_replay(self):
        _, receipt, launch = self.launch_fixture()
        driver = AdmissionDriver()
        driver.raise_after_start = True
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        with self.assertRaises(ConnectionError):
            runtime.start(launch)
        row = self.storage.runtime_session(driver.starts[0])
        self.assertEqual(row['status'], 'starting')
        self.assertIsNone(row['external_session_id'])
        replay = runtime.start(launch)
        self.assertEqual(replay.id, row['id'])
        self.assertEqual(len(driver.starts), 1)
        with self.assertRaises(CapacityUnavailableError):
            self.service.admit(self.request())
        self.assertEqual(self.approval_status(launch), 'consumed')
        errors = self.storage.db.execute(
            "SELECT COUNT(*) FROM runtime_session_events WHERE session_id=? AND kind='error'",
            (row['id'],)).fetchone()[0]
        self.assertGreaterEqual(errors, 1)

    def test_quarantine_rejects_start_before_approval_and_keeps_occupied_capacity(self):
        _, _, launch = self.launch_fixture()
        self.storage.set_worker_lifecycle('worker-a', 'quarantined', reason='Synthetic safety stop')
        driver = AdmissionDriver()
        with self.assertRaises(PermissionError):
            DirectCLIWorkerRuntime(self.storage, driver).start(launch)
        self.assert_not_launched(launch, driver)

    def test_generic_session_creation_cannot_bypass_admitted_runtime_reservation(self):
        _, _, launch = self.launch_fixture()
        with self.assertRaises(PermissionError):
            self.storage.create_runtime_session(
                assignment_id=launch.assignment_id, runtime='direct-cli',
                request=launch.durable_scope(), context_digest=launch.context_digest,
                fencing_token=launch.fencing_token)
        self.assertEqual(self.storage.db.execute(
            'SELECT COUNT(*) FROM worker_sessions WHERE assignment_id=?',
            (launch.assignment_id,)).fetchone()[0], 0)

    def test_expired_tool_admission_and_success_finalization_fail_but_cancel_remains_available(self):
        _, receipt, launch = self.launch_fixture(mutable=False)
        driver = AdmissionDriver()
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        later = datetime.fromisoformat(receipt.expires_at) + timedelta(seconds=1)
        with patch('agent_factory.storage._utc', return_value=later):
            with self.assertRaises(PermissionError):
                runtime.admit_tool_operation(session.id, operation_id='expired-tool', tool_name='read_file')
            with self.assertRaises(PermissionError):
                self.storage.finalize_runtime_session(session.id, status='succeeded', result={'status': 'succeeded'})
            self.assertEqual(self.storage.runtime_session(session.id)['status'], 'running')
            self.assertTrue(self.storage.finalize_runtime_session(
                session.id, status='cancelled', result={'status': 'cancelled'}))
        self.assertEqual(len(driver.starts), 1)
        with self.assertRaises(CapacityUnavailableError):
            self.service.admit(self.request())

    def test_revoked_tool_admission_does_not_reach_external_operation_boundary(self):
        _, receipt, launch = self.launch_fixture(mutable=False)
        driver = AdmissionDriver()
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        self.stop(receipt)
        with patch.object(runtime, '_begin_control_operation') as external_admission:
            with self.assertRaises(PermissionError):
                runtime.admit_tool_operation(session.id, operation_id='revoked-tool', tool_name='read_file')
            external_admission.assert_not_called()
        self.assertEqual(self.storage.runtime_session(session.id)['status'], 'cancelled')

    def test_cancelled_session_cannot_resume_heartbeat_or_admit_tools(self):
        _, _, launch = self.launch_fixture(mutable=False)
        driver = AdmissionDriver()
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        self.storage.cancel_runtime_session(session.id, reason='Synthetic terminal cancellation')
        operations = (
            lambda: runtime.resume(session.id),
            lambda: runtime.heartbeat(session.id),
            lambda: runtime.admit_tool_operation(session.id, operation_id='cancelled-tool', tool_name='read_file'),
        )
        for index, operation in enumerate(operations):
            with self.subTest(operation=index):
                with patch.object(runtime, '_begin_control_operation', return_value=None) as control_boundary:
                    with self.assertRaises(PermissionError):
                        operation()
                    control_boundary.assert_not_called()
                self.assertEqual(driver.resumes, [])
                self.assertEqual(driver.heartbeats, [])
        self.assertEqual(self.storage.runtime_session(session.id)['status'], 'cancelled')

    def test_suspended_heartbeat_is_denied_before_driver_or_control_operation(self):
        _, _, launch = self.launch_fixture(mutable=False)
        driver = AdmissionDriver()
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        self.storage.suspend_runtime_session(session.id, reason='Synthetic paused worker')
        with patch.object(runtime, '_begin_control_operation', return_value=None) as control_boundary:
            with self.assertRaises(PermissionError):
                runtime.heartbeat(session.id)
            control_boundary.assert_not_called()
        self.assertEqual(driver.heartbeats, [])
        self.assertEqual(self.storage.runtime_session(session.id)['status'], 'suspended')

    def test_failed_legacy_runtime_cannot_be_registered_after_assignment_release(self):
        self.configure(workers=())
        for external_identity_known in (False, True):
            with self.subTest(external_identity_known=external_identity_known):
                worker = f'legacy-worker-{external_identity_known}'
                project_id, task_id, run_id = self.task()
                claim = self.storage.claim_runnable_task(task_id, worker, 'direct-cli')
                self.storage.create_assignment_attempt(claim.assignment_id, claim.fencing_token)
                package = ContextPackageBuilder(self.storage, self.root).build(
                    task_id=task_id, run_id=run_id, assignment_id=claim.assignment_id,
                    fencing_token=claim.fencing_token, base_sha='a' * 40,
                )
                launch = RuntimeLaunch(
                    assignment_id=claim.assignment_id, fencing_token=claim.fencing_token,
                    agent=Agent(worker, worker, 'Implementation Worker', True,
                                'synthetic-provider', 'Synthetic legacy worker'),
                    item=self.storage.get_task(task_id), context=package.payload,
                    context_digest=package.digest, mutable=False,
                )
                driver = AdmissionDriver()
                driver.raise_after_start = not external_identity_known
                runtime = DirectCLIWorkerRuntime(self.storage, driver)
                if external_identity_known:
                    session = runtime.start(launch)
                    self.storage.finalize_runtime_session(
                        session.id, status='failed', result={'status': 'failed'})
                else:
                    with self.assertRaises(ConnectionError):
                        runtime.start(launch)
                row = self.storage.runtime_session(driver.starts[0])
                self.assertEqual(row['status'], 'failed')
                self.assertEqual(row['external_session_id'] is not None, external_identity_known)
                self.storage.release_task_lease(
                    claim.assignment_id, claim.fencing_token, outcome='cancelled')
                with self.assertRaises(AdmissionConflictError):
                    self.service.bind_worker(
                        worker_id=worker, pool_id='physical-pool', tenant_id='tenant-a',
                        actor='fixture-coordinator', reason='Synthetic legacy migration')
                self.assertIsNone(self.storage.db.execute(
                    'SELECT worker_id FROM worker_admission_workers WHERE worker_id=?',
                    (worker,)).fetchone())
                with self.assertRaises(AdmissionConflictError):
                    self.service.bind_project(
                        project_id=project_id, tenant_id='tenant-a', authority_digest='a' * 64,
                        actor='fixture-coordinator', reason='Synthetic uncertain project migration')
                self.assertIsNone(self.storage.db.execute(
                    'SELECT project_id FROM worker_admission_projects WHERE project_id=?',
                    (project_id,)).fetchone())
                self.assertEqual(self.storage.runtime_session(row['id'])['status'], 'failed')
                self.assertEqual(len(driver.starts), 1)

    def test_wrong_runtime_cannot_control_admitted_session_but_owner_can_cancel_after_expiry(self):
        _, receipt, launch = self.launch_fixture(mutable=False)
        driver = AdmissionDriver()
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        wrong_driver = Mock(spec=RuntimeDriver)
        for method in ('resume', 'heartbeat', 'collect_events', 'finalize', 'cancel'):
            getattr(wrong_driver, method).side_effect = AssertionError('Wrong runtime reached driver')
        wrong_runtime = CodexCLIWorkerRuntime(self.storage, wrong_driver)
        operations = (
            ('resume', lambda: wrong_runtime.resume(session.id)),
            ('heartbeat', lambda: wrong_runtime.heartbeat(session.id)),
            ('collect_events', lambda: wrong_runtime.collect_events(session.id)),
            ('finalize', lambda: wrong_runtime.finalize(session.id)),
            ('tool', lambda: wrong_runtime.admit_tool_operation(
                session.id, operation_id='wrong-runtime-tool', tool_name='read_file')),
            ('fallback', lambda: wrong_runtime.assert_fallback_allowed(session.id)),
            ('cancel', lambda: wrong_runtime.cancel(session.id, reason='Wrong runtime cancellation')),
        )
        before = dict(self.storage.runtime_session(session.id))
        for name, operation in operations:
            with self.subTest(operation=name):
                with patch.object(wrong_runtime, '_begin_control_operation', return_value=None) as control_boundary:
                    with self.assertRaises(PermissionError):
                        operation()
                    control_boundary.assert_not_called()
                self.assertEqual(wrong_driver.mock_calls, [])
                self.assertEqual(dict(self.storage.runtime_session(session.id)), before)
        later = datetime.fromisoformat(receipt.expires_at) + timedelta(seconds=1)
        with patch('agent_factory.storage._utc', return_value=later):
            cancelled = runtime.cancel(session.id, reason='Synthetic stop after lease expiry')
        self.assertEqual(cancelled.status, 'cancelled')
        self.assertEqual(driver.cancelled, [session.external_session_id])
        self.assertEqual(self.storage.db.execute(
            'SELECT occupancy_state FROM worker_admissions WHERE id=?',
            (receipt.admission_id,)).fetchone()[0], 'occupied')


if __name__ == '__main__':
    unittest.main()
