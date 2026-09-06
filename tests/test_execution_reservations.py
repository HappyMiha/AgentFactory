"""Real SQLite races and reservation lifecycle regression coverage."""
import concurrent.futures
import sqlite3
import threading
import unittest

import test_execution_telemetry as fixtures
from agent_factory.execution_telemetry import BudgetExceeded, ExecutionBudgets, ExecutionTelemetryService
from agent_factory.storage import SQLiteStorage


class ExecutionReservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExecutionTelemetryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.storage = self.fixture.storage
        self.service = ExecutionTelemetryService(self.storage)

    def trace(self, **caps):
        limits = dict(max_tokens=100, max_cost_usd=1.0, max_stages=10, max_retries=1, max_tool_calls=10)
        limits.update(caps)
        return self.fixture.trace(ExecutionBudgets(**limits))[0].id

    @staticmethod
    def usage(service, trace, stage, key, tokens=20, cost=0.2, calls=2):
        return service.ingest(trace, idempotency_key=key, stage_key=stage,
                              duration_ms=10, tokens=tokens, estimated_cost_usd=cost, tool_calls=calls)

    def parallel(self, actions):
        barrier = threading.Barrier(len(actions))
        def run(action):
            storage = SQLiteStorage(self.fixture.workspace / 'state.db')
            try:
                barrier.wait(timeout=10)
                try:
                    return action(ExecutionTelemetryService(storage))
                except BudgetExceeded:
                    return 'blocked'
            finally:
                storage.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(actions)) as pool:
            return list(pool.map(run, actions))

    def test_concurrent_pending_reservations_cannot_overbook_each_resource(self):
        for estimate in ({'estimated_tokens': 75}, {'estimated_cost_usd': .75}, {'estimated_tool_calls': 7}):
            with self.subTest(estimate=estimate):
                trace = self.trace()
                results = self.parallel([
                    lambda s, key=key: s.reserve_stage(trace, key, **estimate)
                    for key in ('a', 'b')
                ])
                self.assertCountEqual(results, [True, 'blocked'])
                self.assertEqual(self.service.state(trace).stages_reserved, 1)
                self.assertEqual(self.service.state(trace).status, 'paused')

    def test_concurrent_replay_grants_only_once_and_binds_estimates(self):
        trace = self.trace()
        results = self.parallel([lambda s: s.reserve_stage(trace, 'a', estimated_tokens=75)] * 2)
        self.assertCountEqual(results, [True, False])
        with self.assertRaisesRegex(ValueError, 'different estimate'):
            self.service.reserve_stage(trace, 'a', estimated_tokens=1)
        self.assertEqual(self.service.state(trace).stages_reserved, 1)

    def test_partial_usage_offsets_only_its_own_hold(self):
        trace = self.trace()
        self.service.reserve_stage(trace, 'a', estimated_tokens=75, estimated_cost_usd=.75, estimated_tool_calls=7)
        self.usage(self.service, trace, 'a', 'partial')
        self.assertTrue(self.service.reserve_stage(trace, 'b', estimated_tokens=25, estimated_cost_usd=.25, estimated_tool_calls=3))
        with self.assertRaises(BudgetExceeded):
            self.service.reserve_stage(trace, 'c', estimated_tokens=1)
        self.assertEqual(self.service.state(trace).tokens, 20)

    def test_settlement_releases_unused_estimate_without_refunding_actual_usage(self):
        trace = self.trace()
        self.service.reserve_stage(trace, 'a', estimated_tokens=75, estimated_cost_usd=.75, estimated_tool_calls=7)
        self.usage(self.service, trace, 'a', 'final')
        self.assertTrue(self.service.settle_stage(trace, 'a', reason='final provider usage received'))
        self.assertFalse(self.service.settle_stage(trace, 'a', reason='final provider usage received'))
        self.assertFalse(self.service.reserve_stage(trace, 'a', estimated_tokens=75, estimated_cost_usd=.75, estimated_tool_calls=7))
        self.assertTrue(self.service.reserve_stage(trace, 'b', estimated_tokens=80, estimated_cost_usd=.8, estimated_tool_calls=8))
        state = self.usage(self.service, trace, 'a', 'final', tokens=999)
        self.assertEqual((state.tokens, state.estimated_cost_usd, state.tool_calls), (20, .2, 2))
        with self.assertRaisesRegex(ValueError, 'after reservation closure'):
            self.usage(self.service, trace, 'a', 'late')
        with self.assertRaisesRegex(ValueError, 'different closure'):
            self.service.release_stage(trace, 'a', reason='no execution', confirmed_no_effect=True)
        with self.assertRaises(BudgetExceeded):
            self.service.reserve_stage(trace, 'c', estimated_cost_usd=.01)

    def test_release_requires_known_no_effect_and_no_usage(self):
        trace = self.trace()
        self.service.reserve_stage(trace, 'a', estimated_tokens=100)
        with self.assertRaises(ValueError):
            self.service.release_stage(trace, 'a', reason='timeout')
        with self.assertRaises(ValueError):
            self.service.settle_stage(trace, 'a', reason='unknown result')
        with self.assertRaises(ValueError):
            self.service._close_stage(trace, 'a', state='unknown', reason='timeout')
        self.assertTrue(self.service.release_stage(trace, 'a', reason='cancelled before dispatch', confirmed_no_effect=True))
        self.assertFalse(self.service.release_stage(trace, 'a', reason='cancelled before dispatch', confirmed_no_effect=True))
        self.assertTrue(self.service.reserve_stage(trace, 'b', estimated_tokens=100))
        self.usage(self.service, trace, 'b', 'zero', tokens=0, cost=0, calls=0)
        with self.assertRaises(ValueError):
            self.service.release_stage(trace, 'b', reason='has sample', confirmed_no_effect=True)
        self.assertTrue(self.service.settle_stage(trace, 'b', reason='known zero usage'))
        self.assertEqual(self.service.state(trace).stages_reserved, 2)  # Attempts are never refunded.

    def test_unknown_reservation_and_terminal_trace_default_deny(self):
        trace = self.trace()
        with self.assertRaises(ValueError):
            self.service.release_stage(trace, 'missing', reason='missing', confirmed_no_effect=True)
        self.service.reserve_stage(trace, 'a', estimated_tokens=100)
        self.service.finish(trace, succeeded=False, reason='worker result unknown')
        self.assertFalse(self.service.reserve_stage(trace, 'a', estimated_tokens=100))
        with self.assertRaises(BudgetExceeded):
            self.service.reserve_stage(trace, 'b')
        with self.assertRaises(ValueError):
            self.service.release_stage(trace, 'a', reason='timeout', confirmed_no_effect=True)
        with self.assertRaises(BudgetExceeded):
            self.service.record_retry(trace, 'retry')
        self.assertEqual(self.service.state(trace).status, 'failed')
        self.assertEqual(self.service._outstanding(trace)[0], 100)

    def test_restart_retains_unknown_hold(self):
        trace = self.trace()
        self.service.reserve_stage(trace, 'a', estimated_tokens=75)
        other = SQLiteStorage(self.fixture.workspace / 'state.db')
        try:
            service = ExecutionTelemetryService(other)
            with self.assertRaises(BudgetExceeded):
                service.reserve_stage(trace, 'b', estimated_tokens=75)
        finally:
            other.close()

    def test_usage_underestimate_pauses_against_other_pending_commitments(self):
        trace = self.trace()
        self.service.reserve_stage(trace, 'a', estimated_tokens=50)
        self.service.reserve_stage(trace, 'b', estimated_tokens=50)
        state = self.usage(self.service, trace, 'a', 'actual', tokens=60, cost=0, calls=0)
        self.assertEqual(state.tokens, 60)
        self.assertEqual(state.status, 'paused')
        self.assertIn('commitments', state.terminal_reason)
        self.service.settle_stage(trace, 'a', reason='final')
        self.assertEqual(self.service.state(trace).status, 'paused')

    def test_concurrent_samples_and_replay_never_lose_or_double_charge_usage(self):
        trace = self.trace()
        results = self.parallel([lambda s, key=key: self.usage(s, trace, 'legacy', key)
                                 for key in ('first', 'second')])
        self.assertEqual(len(results), 2)
        self.parallel([lambda s: self.usage(s, trace, 'legacy', 'first')] * 2)
        state = self.service.state(trace)
        self.assertEqual((state.tokens, state.estimated_cost_usd, state.tool_calls, state.duration_ms), (40, .4, 4, 20))
        with self.assertRaisesRegex(ValueError, 'already has usage'):
            self.service.reserve_stage(trace, 'legacy', estimated_tokens=60)

    def test_concurrent_settlement_is_idempotent(self):
        trace = self.trace()
        self.service.reserve_stage(trace, 'a', estimated_tokens=100)
        self.usage(self.service, trace, 'a', 'final')
        results = self.parallel([lambda s: s.settle_stage(trace, 'a', reason='final')] * 2)
        self.assertCountEqual(results, [True, False])
        self.assertEqual(self.service.state(trace).tokens, 20)

    def test_decimal_cost_boundary_is_not_float_addition_overage(self):
        trace = self.trace(max_cost_usd=.3)
        self.service.reserve_stage(trace, 'a', estimated_cost_usd=.1)
        self.service.reserve_stage(trace, 'b', estimated_cost_usd=.2)
        self.usage(self.service, trace, 'a', 'a', tokens=0, cost=.1, calls=0)
        state = self.usage(self.service, trace, 'b', 'b', tokens=0, cost=.2, calls=0)
        self.assertEqual(state.status, 'active')
        self.assertEqual(state.estimated_cost_usd, .3)

    def test_outer_transaction_is_not_committed_and_failure_rolls_back_local_work(self):
        trace = self.trace()
        db = self.storage.db
        db.execute('BEGIN IMMEDIATE')
        self.service.reserve_stage(trace, 'a', estimated_tokens=50)
        self.assertTrue(db.in_transaction)
        with self.assertRaises(ValueError):
            self.service.reserve_stage(trace, 'a', estimated_tokens=20)
        self.assertTrue(db.in_transaction)
        self.assertEqual(self.service.state(trace).stages_reserved, 1)
        db.rollback()
        self.assertEqual(self.service.state(trace).stages_reserved, 0)
        self.assertTrue(self.service.reserve_stage(trace, 'a', estimated_tokens=100))

    def test_waiting_writer_observes_rolled_back_reservation_not_uncommitted_grant(self):
        trace = self.trace()
        ready, proceed = threading.Event(), threading.Event()
        def writer():
            storage = SQLiteStorage(self.fixture.workspace / 'state.db')
            try:
                ready.set()
                if not proceed.wait(10):
                    raise TimeoutError('Writer not released')
                return ExecutionTelemetryService(storage).reserve_stage(trace, 'second', estimated_tokens=100)
            finally:
                storage.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(writer)
            try:
                self.assertTrue(ready.wait(10))
                self.storage.db.execute('BEGIN IMMEDIATE')
                self.service.reserve_stage(trace, 'first', estimated_tokens=100)
                proceed.set()
                with self.assertRaises(concurrent.futures.TimeoutError):
                    future.result(timeout=.1)
            finally:
                self.storage.db.rollback()
                proceed.set()
            self.assertTrue(future.result(timeout=10))
        self.assertEqual(self.service.state(trace).stages_reserved, 1)
        self.assertEqual(self.storage.db.execute(
            'SELECT stage_key FROM execution_stage_reservations WHERE trace_id=?', (trace,)
        ).fetchone()[0], 'second')

    def test_closure_is_immutable_and_sql_cannot_append_usage_after_release(self):
        trace = self.trace()
        self.service.reserve_stage(trace, 'a', estimated_tokens=100)
        self.service.release_stage(trace, 'a', reason='not dispatched', confirmed_no_effect=True)
        for sql in ("UPDATE execution_reservation_closures SET state='settled'",
                    "DELETE FROM execution_reservation_closures"):
            with self.assertRaisesRegex(sqlite3.DatabaseError, 'immutable'):
                with self.storage.db:
                    self.storage.db.execute(sql)
        with self.assertRaisesRegex(sqlite3.DatabaseError, 'closed'):
            with self.storage.db:
                self.storage.db.execute('''INSERT INTO execution_usage_samples(
                    identity,trace_id,idempotency_key,stage_key,duration_ms,tokens,estimated_cost_usd,tool_calls,metadata_json)
                    VALUES('late',?,'late','a',0,1,0,0,'{}')''', (trace,))


if __name__ == '__main__':
    unittest.main()
