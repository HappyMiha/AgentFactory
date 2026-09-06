"""Existing policy authority composed with caller transactions and exact effects."""
import concurrent.futures
from dataclasses import replace
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

import test_execution_telemetry as telemetry_fixture
import test_live_stages as live_fixture
from agent_factory.execution_telemetry import ExecutionBudgets, ExecutionTelemetryService
from agent_factory.live_stages import LiveStageExecution
from agent_factory.policy import ControlPlanePolicy, PolicyOutcome, PolicyRequest
from agent_factory.storage import SQLiteStorage


class PolicyCompositionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = telemetry_fixture.ExecutionTelemetryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.storage = self.fixture.storage
        self.trace, task, run = self.fixture.trace(ExecutionBudgets(100, 1, 5, 1, 10))
        project = self.storage.db.execute('SELECT project_id FROM work_items WHERE id=?', (task,)).fetchone()[0]
        self.request = PolicyRequest(project, task, run, 'execute', 'fixture-worker',
                                     'fixture-runtime', None, ('execute_provider',), 'a'*64)
        self.policy = ControlPlanePolicy(self.storage)
        self.telemetry = ExecutionTelemetryService(self.storage)

    def approval(self, request=None):
        key = self.storage.request_scoped_approval(request=(request or self.request).canonical(), requested_by='host')
        self.storage.decide_scoped_approval(key, 'approved', actor='owner')
        return key

    def status(self, key, storage=None):
        return (storage or self.storage).db.execute(
            'SELECT status FROM scoped_execution_approvals WHERE id=?', (key,)
        ).fetchone()[0]

    def decisions(self):
        return self.storage.db.execute('SELECT COUNT(*) FROM policy_decisions').fetchone()[0]

    def test_legacy_canonical_bytes_and_preexisting_hash_are_unchanged(self):
        # Bytes/hash captured from accepted Core35's pre-effect PolicyRequest.
        request = PolicyRequest(1, 2, None, 'implementation', 'fixture-worker',
                                'fixture-runtime', None, ('tool_use', 'execute_provider', 'tool_use'))
        expected = ('{"mission_id":1,"permissions":["execute_provider","tool_use"],"run_id":null,'
                    '"runtime_id":"fixture-runtime","stage_id":"implementation","task_id":2,'
                    '"worker_id":"fixture-worker","worktree_id":null}')
        self.assertEqual(json.dumps(request.canonical(), sort_keys=True, separators=(',', ':')), expected)
        self.assertEqual(request.digest, '3190b3c06e9cf857695b5a7dfe832e9e525cbf432d0e512ec09b95153a76ce11')
        self.assertEqual(self.storage._policy_digest(json.loads(expected)), request.digest)
        self.assertNotIn('effect_digest', replace(request, effect_digest=None).canonical())
        legacy = replace(self.request, effect_digest=None)
        key = self.approval(legacy)
        self.assertEqual(self.policy.authorize(legacy, approval_id=key).outcome, PolicyOutcome.ALLOW)

    def test_effect_is_persisted_in_audit_and_replay_cannot_authorize_again(self):
        key = self.approval()
        self.assertEqual(self.request.stage_id, 'execute')
        for wrong in (replace(self.request, effect_digest=None), replace(self.request, effect_digest='b'*64)):
            with self.assertRaisesRegex(PermissionError, 'scope does not match'):
                self.policy.authorize(wrong, approval_id=key)
            self.assertEqual(self.status(key), 'approved')
        self.policy.authorize(self.request, approval_id=key)
        row = self.storage.db.execute("SELECT request_json FROM policy_decisions WHERE outcome='allow'").fetchone()
        self.assertEqual(json.loads(row[0])['effect_digest'], 'a'*64)
        other = SQLiteStorage(self.fixture.workspace/'state.db')
        try:
            with self.assertRaisesRegex(PermissionError, 'consumed'):
                ControlPlanePolicy(other).authorize(self.request, approval_id=key)
        finally:
            other.close()
        self.assertEqual(self.decisions(), 2)

    def test_legacy_approval_cannot_silently_gain_an_effect_binding(self):
        key = self.approval(replace(self.request, effect_digest=None))
        with self.assertRaisesRegex(PermissionError, 'scope does not match'):
            self.policy.authorize(self.request, approval_id=key)
        self.assertEqual(self.status(key), 'approved')

    def test_malformed_or_unknown_fields_are_rejected_at_all_raw_boundaries(self):
        key = self.approval()
        good = self.request.canonical()
        bad = [good | {'extra': True}, {k: v for k, v in good.items() if k != 'stage_id'},
               good | {'permissions': 'execute_provider'}, good | {'permissions': [1]},
               good | {'task_id': True}, good | {'run_id': -1}, good | {'stage_id': ''}]
        for digest in (None, '', 'A'*64, 'a'*63, 'a'*65, True, 123, {}, 'a'*64+'\n'):
            bad.append(good | {'effect_digest': digest})
            if digest is not None:
                with self.assertRaises(ValueError):
                    replace(self.request, effect_digest=digest)
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.storage.request_scoped_approval(request=value, requested_by='host')
                with self.assertRaises(ValueError):
                    self.storage.consume_scoped_approval(key, request=value, request_digest=self.request.digest)
                with self.assertRaises(ValueError):
                    self.storage.record_policy_decision(request=value, request_digest=self.request.digest,
                        outcome='allow', reason='fixture', policy_version=1)
        self.assertEqual(self.status(key), 'approved')
        self.assertEqual(self.decisions(), 0)

    def test_outer_rollback_restores_budget_approval_and_decisions_together(self):
        key = self.approval()
        other = SQLiteStorage(self.fixture.workspace/'state.db')
        try:
            self.storage.db.execute('BEGIN IMMEDIATE')
            self.telemetry.reserve_stage(self.trace.id, 'call', estimated_tokens=75)
            self.assertEqual(self.policy.authorize(self.request, approval_id=key).outcome, PolicyOutcome.ALLOW)
            self.assertTrue(self.storage.db.in_transaction)
            self.assertEqual(self.status(key, other), 'approved')
            self.assertEqual(ExecutionTelemetryService(other).state(self.trace.id).stages_reserved, 0)
            self.storage.db.rollback()
            self.assertEqual(self.status(key), 'approved')
            self.assertEqual(self.decisions(), 0)
            self.assertEqual(self.telemetry.state(self.trace.id).stages_reserved, 0)
        finally:
            self.storage.db.rollback()
            other.close()

    def test_outer_commit_persists_one_budget_hold_and_one_consumption(self):
        key = self.approval()
        with self.storage.db:
            self.storage.db.execute('BEGIN IMMEDIATE')
            self.telemetry.reserve_stage(self.trace.id, 'call', estimated_tokens=75)
            self.policy.authorize(self.request, approval_id=key)
            self.assertTrue(self.storage.db.in_transaction)
        other = SQLiteStorage(self.fixture.workspace/'state.db')
        try:
            self.assertEqual(self.status(key, other), 'consumed')
            self.assertEqual(ExecutionTelemetryService(other).state(self.trace.id).stages_reserved, 1)
            with self.assertRaises(PermissionError):
                ControlPlanePolicy(other).authorize(self.request, approval_id=key)
        finally:
            other.close()

    def test_audit_failure_rolls_back_authorize_unit_but_preserves_caller_work(self):
        for outer in (False, True):
            with self.subTest(outer=outer):
                key = self.approval()
                if outer:
                    self.storage.db.execute('BEGIN IMMEDIATE')
                    self.telemetry.reserve_stage(self.trace.id, 'call', estimated_tokens=75)
                original = self.storage._event
                def fail_last(kind, *args, **kwargs):
                    if kind == 'policy.allow':
                        raise OSError('synthetic audit failure after consumption')
                    return original(kind, *args, **kwargs)
                with patch.object(self.storage, '_event', side_effect=fail_last):
                    with self.assertRaises(OSError):
                        self.policy.authorize(self.request, approval_id=key)
                self.assertEqual(self.storage.db.in_transaction, outer)
                self.assertEqual(self.status(key), 'approved')
                self.assertEqual(self.decisions(), 0)
                self.assertEqual(self.telemetry.state(self.trace.id).stages_reserved, int(outer))
                self.storage.db.rollback()

    def test_request_and_decision_also_preserve_caller_rollback(self):
        self.storage.db.execute('BEGIN IMMEDIATE')
        key = self.approval()
        self.assertTrue(self.storage.db.in_transaction)
        self.storage.db.rollback()
        self.assertIsNone(self.storage.db.execute('SELECT id FROM scoped_execution_approvals WHERE id=?', (key,)).fetchone())

    def test_expiry_is_durable_standalone_but_rollbackable_inside_caller(self):
        for outer in (False, True):
            with self.subTest(outer=outer):
                key = self.approval()
                with self.storage.db:
                    self.storage.db.execute("UPDATE scoped_execution_approvals SET expires_at='2000-01-01' WHERE id=?", (key,))
                if outer:
                    self.storage.db.execute('BEGIN IMMEDIATE')
                with self.assertRaisesRegex(PermissionError, 'expired'):
                    self.policy.authorize(self.request, approval_id=key)
                self.assertEqual(self.storage.db.in_transaction, outer)
                self.assertEqual(self.status(key), 'expired')
                self.storage.db.rollback()
                self.assertEqual(self.status(key), 'approved' if outer else 'expired')

    def test_concurrent_connections_can_consume_an_approval_only_once(self):
        key = self.approval()
        barrier = threading.Barrier(2)
        def consume(_):
            other = SQLiteStorage(self.fixture.workspace/'state.db')
            try:
                barrier.wait(timeout=10)
                try:
                    return ControlPlanePolicy(other).authorize(self.request, approval_id=key).outcome.value
                except PermissionError:
                    return 'replay_denied'
            finally:
                other.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(consume, range(2))), ['allow', 'replay_denied'])
        self.assertEqual(self.decisions(), 2)
        self.assertEqual(self.status(key), 'consumed')

    def test_waiting_consumer_observes_outer_rollback_before_authorizing(self):
        key = self.approval()
        ready, proceed = threading.Event(), threading.Event()
        def consume():
            other = SQLiteStorage(self.fixture.workspace/'state.db')
            try:
                ready.set()
                if not proceed.wait(10):
                    raise TimeoutError()
                return ControlPlanePolicy(other).authorize(self.request, approval_id=key).outcome
            finally:
                other.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(consume)
            try:
                self.assertTrue(ready.wait(10))
                self.storage.db.execute('BEGIN IMMEDIATE')
                self.policy.authorize(self.request, approval_id=key)
                proceed.set()
                with self.assertRaises(concurrent.futures.TimeoutError):
                    future.result(timeout=.1)
            finally:
                self.storage.db.rollback()
                proceed.set()
            self.assertEqual(future.result(timeout=10), PolicyOutcome.ALLOW)
        self.assertEqual(self.decisions(), 2)

    def test_stale_wal_snapshot_cannot_authorize_after_emergency_stop(self):
        key = self.approval()
        self.storage.db.execute('PRAGMA journal_mode=WAL')
        other = SQLiteStorage(self.fixture.workspace/'state.db')
        try:
            self.storage.db.execute('BEGIN')
            self.storage.db.execute('SELECT * FROM policy_state').fetchone()
            other.set_emergency_stop(True, actor='owner', reason='fixture stop')
            with self.assertRaises(sqlite3.OperationalError):
                self.policy.authorize(self.request, approval_id=key)
            self.assertTrue(self.storage.db.in_transaction)
            self.storage.db.rollback()
            self.assertEqual(self.status(key), 'cancelled')  # Emergency stop revokes approved gates.
            self.assertEqual(self.policy.authorize(self.request, approval_id=key).outcome, PolicyOutcome.DENY)
        finally:
            self.storage.db.rollback()
            other.close()

    def test_effect_digest_retains_real_live_stage_and_attempt_binding(self):
        fixture = live_fixture.LiveStageExecutionTests()
        fixture.setUp()
        try:
            run, request, launch = fixture.fixture()
            effect = replace(request, effect_digest='b'*64)
            gate = LiveStageExecution(fixture.storage).request_approval(effect, requested_by='host')
            fixture.storage.decide_scoped_approval(gate.approval_id, 'approved', actor='owner')
            with fixture.storage.db:
                fixture.storage.db.execute('BEGIN IMMEDIATE')
                result = ControlPlanePolicy(fixture.storage).authorize(effect, approval_id=gate.approval_id,
                    assignment_id=launch.assignment_id, attempt_id=launch.binding.attempt_id)
                self.assertEqual(result.outcome, PolicyOutcome.ALLOW)
                self.assertTrue(fixture.storage.db.in_transaction)
            row = fixture.storage.db.execute('SELECT * FROM stage_approval_consumptions').fetchone()
            actual_stage = fixture.storage.durable_stages(run)[0]
            self.assertEqual(row['stage_id'], actual_stage['id'])
            self.assertEqual(row['run_id'], run)
            self.assertEqual(row['attempt_id'], launch.binding.attempt_id)
            self.assertEqual(row['request_digest'], effect.digest)
            self.assertEqual(actual_stage['stage_key'], 'implementation')
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
