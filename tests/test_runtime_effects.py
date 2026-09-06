"""Exact effects through existing admitted runtime starts; no live effects."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import json
import threading
import unittest
from unittest.mock import patch

import test_live_stages as legacy_fixture
import test_worker_admission_runtime as fixture
from agent_factory.policy import PolicyRequest
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_admission import AdmissionConflictError, AdmissionDeniedError, WorkerAdmissionService
from agent_factory.worker_runtime import DirectCLIWorkerRuntime


class RuntimeEffectTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.WorkerAdmissionRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.storage = self.fixture.storage

    def launch(self, effect='a'*64):
        return self.fixture.launch_fixture(effect_digest=effect)

    def assert_not_started(self, launch, driver):
        self.fixture.assert_not_launched(launch, driver)

    def test_effect_is_bound_in_admission_policy_and_committed_session_before_driver(self):
        request, receipt, launch = self.launch()
        storage = self.storage
        class Driver(fixture.AdmissionDriver):
            def start(inner, value, *, control_session_id=None):
                self.assertFalse(storage.db.in_transaction)
                with closing(SQLiteStorage(self.fixture.path)) as other:
                    session = other.runtime_session(control_session_id)
                    self.assertEqual(json.loads(session['request_json'])['effect_digest'], 'a'*64)
                    self.assertEqual(other.db.execute('SELECT status FROM scoped_execution_approvals WHERE id=?',
                        (launch.approval.gate_id,)).fetchone()[0], 'consumed')
                self.assertEqual(value.effect_digest, request.effect_digest)
                return super().start(value, control_session_id=control_session_id)
        driver = Driver()
        session = DirectCLIWorkerRuntime(storage, driver).start(launch)
        row = storage.db.execute('SELECT * FROM worker_admissions WHERE id=?', (receipt.admission_id,)).fetchone()
        self.assertEqual(json.loads(row['request_json'])['effect_digest'], 'a'*64)
        self.assertEqual(row['runtime_session_id'], session.id)
        consumption = storage.db.execute('SELECT * FROM stage_approval_consumptions').fetchone()
        self.assertEqual(consumption['run_id'], request.run_id)
        self.assertEqual(consumption['stage_id'], receipt.stage_id)
        self.assertEqual(consumption['attempt_id'], receipt.attempt_id)
        self.assertEqual(consumption['request_digest'], launch.approval.request_digest)
        self.assertEqual(len(driver.starts), 1)

    def test_missing_or_substituted_launch_effect_rejects_before_reservation(self):
        _, _, launch = self.launch()
        driver = fixture.AdmissionDriver()
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        for effect in (None, 'b'*64):
            with self.assertRaisesRegex(AdmissionDeniedError, 'effect'):
                runtime.start(replace(launch, effect_digest=effect))
            self.assert_not_started(launch, driver)

    def test_legacy_admission_cannot_gain_effect_at_launch(self):
        _, _, launch = self.launch(None)
        driver = fixture.AdmissionDriver()
        with self.assertRaisesRegex(AdmissionDeniedError, 'effect'):
            DirectCLIWorkerRuntime(self.storage, driver).start(replace(launch, effect_digest='a'*64))
        self.assert_not_started(launch, driver)

    def test_approval_for_different_effect_rejects_before_start_reservation(self):
        request, _, launch = self.launch()
        policy = PolicyRequest(request.project_id, request.task_id, request.run_id, request.stage_key,
            request.worker_id, request.runtime, str(launch.binding.worktree_id), tuple(launch.item.permissions), 'b'*64)
        gate = self.storage.request_scoped_approval(request=policy.canonical(), requested_by='host')
        self.storage.decide_scoped_approval(gate, 'approved', actor='owner')
        wrong = replace(launch, approval=replace(launch.approval, gate_id=gate, request_digest=policy.digest))
        driver = fixture.AdmissionDriver()
        with self.assertRaisesRegex(PermissionError, 'envelope'):
            DirectCLIWorkerRuntime(self.storage, driver).start(wrong)
        self.assert_not_started(launch, driver)
        self.assertEqual(self.storage.db.execute('SELECT status FROM scoped_execution_approvals WHERE id=?',
            (gate,)).fetchone()[0], 'approved')

    def test_real_stage_attempt_and_worktree_substitution_still_rejects(self):
        request, _, launch = self.launch()
        driver = fixture.AdmissionDriver()
        for binding in (replace(launch.binding, stage_id='invented-effect-stage'),
                        replace(launch.binding, attempt_id=launch.binding.attempt_id+999),
                        replace(launch.binding, worktree_id=launch.binding.worktree_id+999),
                        replace(launch.binding, run_id=request.run_id+999)):
            with self.assertRaises(PermissionError):
                DirectCLIWorkerRuntime(self.storage, driver).start(replace(launch, binding=binding))
            self.assert_not_started(launch, driver)

    def test_request_replay_binds_effect_and_rejects_add_remove_or_change(self):
        request, receipt, _ = self.launch()
        self.assertEqual(self.fixture.service.admit(request).admission_id, receipt.admission_id)
        for effect in (None, 'b'*64):
            with self.assertRaisesRegex(AdmissionConflictError, 'another admission scope'):
                self.fixture.service.admit(replace(request, effect_digest=effect))

    def test_invalid_digests_and_readonly_effect_launch_are_rejected(self):
        request, _, launch = self.launch()
        for effect in ('', 'A'*64, 'a'*63, 'a'*65, 'a'*64+'\n', 1, True, {}):
            with self.subTest(effect=effect):
                with self.assertRaises(ValueError):
                    replace(request, effect_digest=effect)
                with self.assertRaises(ValueError):
                    replace(launch, effect_digest=effect)
        with self.assertRaisesRegex(ValueError, 'mutable approval'):
            replace(launch, mutable=False)

    def test_no_effect_keeps_old_durable_shape_and_start_digest(self):
        request, receipt, launch = self.launch(None)
        self.assertNotIn('effect_digest', request.canonical())
        self.assertNotIn('effect_digest', launch.durable_scope())
        row = self.storage.db.execute('SELECT * FROM worker_admissions WHERE id=?', (receipt.admission_id,)).fetchone()
        old_request = asdict(request); del old_request['effect_digest']
        encoded = json.dumps(old_request, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        self.assertEqual(row['request_json'], encoded)
        self.assertEqual(row['request_digest'], hashlib.sha256(encoded.encode()).hexdigest())
        old_start = hashlib.sha256(json.dumps({'scope': launch.durable_scope(), 'agent': asdict(launch.agent),
            'item': asdict(launch.item), 'approval': asdict(launch.approval)},
            sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        driver = fixture.AdmissionDriver()
        session = DirectCLIWorkerRuntime(self.storage, driver).start(launch)
        stored = json.loads(self.storage.runtime_session(session.id)['request_json'])
        self.assertNotIn('effect_digest', stored)
        self.assertEqual(stored['admission_start_digest'], old_start)

    def test_concurrent_and_reopened_effect_start_calls_driver_once(self):
        _, _, launch = self.launch()
        driver = fixture.AdmissionDriver(); driver.release = threading.Event()
        def start():
            with closing(SQLiteStorage(self.fixture.path)) as connection:
                return DirectCLIWorkerRuntime(connection, driver).start(launch)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(start)
            try:
                self.assertTrue(driver.entered.wait(10))
                replay = pool.submit(start).result(timeout=10)
                self.assertEqual(replay.status, 'starting')
                self.assertEqual(len(driver.starts), 1)
            finally:
                driver.release.set()
            session = first.result(timeout=10)
        self.assertEqual(session.id, replay.id)
        self.assertEqual(start().id, session.id)
        self.assertEqual(len(driver.starts), 1)
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM stage_approval_consumptions').fetchone()[0], 1)

    def test_lost_effect_start_response_retains_occupancy_and_does_not_retry(self):
        _, receipt, launch = self.launch()
        driver = fixture.AdmissionDriver(); driver.raise_after_start = True
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        with self.assertRaises(ConnectionError):
            runtime.start(launch)
        replay = runtime.start(launch)
        self.assertEqual(replay.status, 'starting')
        self.assertEqual(len(driver.starts), 1)
        self.assertEqual(self.storage.db.execute('SELECT occupancy_state FROM worker_admissions WHERE id=?',
            (receipt.admission_id,)).fetchone()[0], 'occupied')
        with self.assertRaises(PermissionError):
            runtime.start(replace(launch, effect_digest='b'*64))
        self.assertEqual(len(driver.starts), 1)

    def test_start_reservation_failure_rolls_back_before_approval_or_driver(self):
        _, _, launch = self.launch()
        original = self.storage._create_runtime_session_in_transaction
        def fail_after_insert(**kwargs):
            original(**kwargs)
            raise OSError('synthetic reservation persistence failure')
        driver = fixture.AdmissionDriver()
        with patch.object(self.storage, '_create_runtime_session_in_transaction', side_effect=fail_after_insert):
            with self.assertRaises(OSError):
                DirectCLIWorkerRuntime(self.storage, driver).start(launch)
        self.assert_not_started(launch, driver)
        self.assertIsNone(self.storage.db.execute('SELECT runtime_session_id FROM worker_admissions').fetchone()[0])
        DirectCLIWorkerRuntime(self.storage, driver).start(launch)
        self.assertEqual(len(driver.starts), 1)

    def test_unregistered_legacy_assignment_does_not_bypass_effect_admission(self):
        old = legacy_fixture.LiveStageExecutionTests(); old.setUp()
        try:
            _, _, launch = old.fixture()
            driver = fixture.AdmissionDriver()
            with self.assertRaisesRegex(AdmissionDeniedError, 'stored worker admission'):
                DirectCLIWorkerRuntime(old.storage, driver).start(replace(launch, effect_digest='a'*64))
            self.assertEqual(driver.starts, [])
            self.assertEqual(old.storage.db.execute('SELECT COUNT(*) FROM worker_sessions').fetchone()[0], 0)
        finally:
            old.tearDown()


if __name__ == '__main__':
    unittest.main()
