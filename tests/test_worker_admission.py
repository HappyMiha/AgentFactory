"""Transactional admission tests using synthetic local workers and real SQLite.

These fixtures provide no remote-worker, provider or engine qualification evidence.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent_factory.adapters import HEALTH_DIMENSIONS
from agent_factory.models import WorkItem
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_admission import (
    AdmissionConflictError, AdmissionDeniedError, AdmissionRequest,
    CapacityUnavailableError, WorkerAdmissionService,
)


class AdmissionFixture(unittest.TestCase):
    """Shared fixture helpers, with no test methods inherited by the runtime suite."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / 'admission.db'
        self.storage = SQLiteStorage(self.path)
        self.service = WorkerAdmissionService(self.storage)
        self.counter = 0
        self.qualifications = {}

    def tearDown(self):
        self.storage.close()
        self.temporary.cleanup()

    def task(self, *, project_id=None, mutable=False):
        self.counter += 1
        if project_id is None:
            project_id = self.storage.create_project(
                f'Project {self.counter}', 'Synthetic admission fixture')
        task_id = self.storage.create_task(WorkItem(
            title=f'Task {self.counter}', description='Bounded synthetic work',
            project_id=project_id,
            permissions=['read_project', *(['worktree_write'] if mutable else [])],
        ))
        run_id = self.storage.start_durable_run(
            project_id=project_id, task_id=task_id,
            workflow_id=f'admission-{self.counter}', workflow_version='1',
            definition={'id': f'admission-{self.counter}'},
            stages=[{'id': 'implementation', 'depends_on': []},
                    {'id': 'review', 'depends_on': ['implementation']}],
        )
        self.storage.transition_durable_stage(
            run_id, 'implementation', 'running', {'reason': 'test fixture ready'})
        return project_id, task_id, run_id

    def qualify(self, worker='worker-a', *, provider='synthetic-provider',
                role='Implementation Worker', capabilities=('code', 'test'),
                status='qualified', ttl_seconds=3600):
        return self.storage.record_worker_qualification(
            worker_id=worker, provider_id=provider, role=role,
            capabilities=list(capabilities),
            dimensions={name: {'status': 'pass', 'evidence': 'synthetic fixture'}
                        for name in HEALTH_DIMENSIONS},
            evidence={'fixture': True, 'worker': worker}, status=status,
            ttl_seconds=ttl_seconds,
        )

    def counts(self):
        return {table: self.storage.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                for table in ('assignments', 'leases', 'attempts', 'events')}

    def configure(self, *, capacity=1, workers=(('worker-a', 'tenant-a'),)):
        self.pool = self.service.configure_pool(
            pool_id='physical-pool', allowed_runtimes=('direct-cli',),
            valid_until=datetime.now(timezone.utc) + timedelta(hours=1),
            capacity=capacity, actor='fixture-coordinator', reason='Synthetic capacity only')
        for worker, tenant in workers:
            self.service.bind_worker(
                worker_id=worker, pool_id='physical-pool', tenant_id=tenant,
                actor='fixture-coordinator', reason='Synthetic worker mapping')
            self.qualifications[worker] = self.qualify(worker)

    def request(self, *, worker='worker-a', tenant='tenant-a', mutable=False):
        project, task, run = self.task(mutable=mutable)
        self.service.bind_project(
            project_id=project, tenant_id=tenant, authority_digest='a' * 64,
            actor='fixture-coordinator', reason='Synthetic authenticated ownership')
        lifecycle = self.storage.db.execute(
            'SELECT version FROM worker_lifecycle WHERE worker_id=?', (worker,)).fetchone()
        return AdmissionRequest(
            request_id=f'request-{self.counter}', tenant_id=tenant, project_id=project,
            task_id=task, run_id=run, stage_key='implementation', worker_id=worker,
            runtime='direct-cli', provider_id='synthetic-provider', role='Implementation Worker',
            required_capabilities=('code',), qualification_id=self.qualifications[worker],
            expected_pool_version=1, expected_worker_version=1, expected_project_version=1,
            expected_lifecycle_version=int(lifecycle['version']), ttl_seconds=60,
            conflict_domains=(f'path:task-{task}',),
        )

    def stop(self, receipt, *, now=None):
        return self.service.reconcile_stopped(
            admission_id=receipt.admission_id, fencing_token=receipt.fencing_token,
            evidence_digest='e' * 64, actor='fixture-coordinator',
            reason='Synthetic exact-fence stop confirmation', now=now)

    def qualification_with_timestamp(self, source_id, valid_until, suffix):
        # Insert an immutable historical-format fixture; never disable triggers
        # or rewrite accepted evidence just to test timestamp normalization.
        cursor = self.storage.db.execute('''
            INSERT INTO worker_qualifications(
                identity,worker_id,provider_id,role,capabilities_json,dimensions_json,
                evidence_json,evidence_digest,status,valid_until)
            SELECT identity||?,worker_id,provider_id,role,capabilities_json,dimensions_json,
                   evidence_json,evidence_digest,status,?
            FROM worker_qualifications WHERE id=?
        ''', (suffix, valid_until, source_id))
        self.storage.db.commit()
        return int(cursor.lastrowid)


class WorkerAdmissionTests(AdmissionFixture):
    def test_atomic_single_slot_across_projects_tenants_and_aliases(self):
        self.configure(workers=(('worker-a', 'tenant-a'), ('worker-b', 'tenant-b')))
        requests = [self.request(), self.request(worker='worker-b', tenant='tenant-b')]
        barrier = threading.Barrier(2)

        def compete(request):
            with closing(SQLiteStorage(self.path)) as connection:
                service = WorkerAdmissionService(connection)
                barrier.wait(timeout=8)
                try:
                    return ('won', service.admit(request))
                except CapacityUnavailableError:
                    return ('blocked', None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(compete, request) for request in requests]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(sorted(result[0] for result in results), ['blocked', 'won'])
        self.assertEqual(self.counts()['assignments'], 1)
        self.assertEqual(self.counts()['leases'], 1)
        self.assertEqual(self.counts()['attempts'], 1)
        receipt = next(result[1] for result in results if result[0] == 'won')
        self.assertEqual(receipt.pool_id, 'physical-pool')
        self.assertTrue(self.storage.integrity_check()['ok'])

    def test_pool_allows_n_slots_but_aliases_do_not_multiply_capacity(self):
        self.configure(capacity=2, workers=(('worker-a', 'tenant-a'), ('worker-b', 'tenant-b')))
        first = self.service.admit(self.request())
        self.service.admit(self.request(worker='worker-b', tenant='tenant-b'))
        third = self.request()
        with self.assertRaises(CapacityUnavailableError):
            self.service.admit(third)
        self.assertEqual(self.stop(first).status, 'stopped')
        admitted = self.service.admit(third)
        self.assertNotEqual(admitted.assignment_id, first.assignment_id)
        self.assertGreater(admitted.fencing_token, first.fencing_token)

    def test_exact_replay_reuses_receipt_and_changed_scope_conflicts(self):
        self.configure()
        request = self.request()
        first = self.service.admit(request)
        before = self.counts()
        replay = self.service.admit(request)
        self.assertEqual(replay.admission_id, first.admission_id)
        self.assertEqual(replay.attempt_id, first.attempt_id)
        self.assertEqual(self.counts(), before)
        for changes in ({'ttl_seconds': 61}, {'required_capabilities': ('code', 'test')},
                        {'conflict_domains': ('path:elsewhere',)}):
            with self.subTest(changes=changes), self.assertRaises(AdmissionConflictError):
                self.service.admit(replace(request, **changes))
        self.assertEqual(self.counts(), before)

    def test_unbound_or_wrong_tenant_and_execution_identity_fail_before_claim(self):
        self.configure()
        request = self.request()
        project, task, run = self.task()
        variants = [
            replace(request, tenant_id='tenant-other'),
            replace(request, project_id=project, task_id=task, run_id=run),
            replace(request, project_id=project), replace(request, task_id=task),
            replace(request, run_id=run), replace(request, stage_key='missing'),
            replace(request, worker_id='unregistered'),
            replace(request, provider_id='other-provider'), replace(request, role='Reviewer'),
            replace(request, required_capabilities=('unsupported-tool',)),
            replace(request, runtime='other-runtime'),
        ]
        before = self.counts()
        for index, invalid in enumerate(variants):
            with self.subTest(case=index), self.assertRaises((AdmissionDeniedError, KeyError)):
                self.service.admit(replace(invalid, request_id=f'invalid-{index}'))
        self.assertEqual(self.counts(), before)

    def test_stage_dependencies_and_finished_run_cannot_be_admitted(self):
        self.configure()
        request = self.request()
        with self.assertRaises(AdmissionDeniedError):
            self.service.admit(replace(request, stage_key='review'))
        self.storage.finish_run(request.run_id, 'failed')
        with self.assertRaises(AdmissionDeniedError):
            self.service.admit(request)
        self.assertEqual(self.counts()['assignments'], 0)

    def test_latest_failed_qualification_never_falls_back_to_earlier_success(self):
        self.configure()
        request = self.request()
        failed = self.qualify(status='failed')
        for qualification in (request.qualification_id, failed):
            with self.subTest(qualification=qualification), self.assertRaises(AdmissionDeniedError):
                self.service.admit(replace(request, qualification_id=qualification))
        self.assertEqual(self.counts()['assignments'], 0)

    def test_stale_versions_and_nonactive_lifecycle_are_denied(self):
        self.configure()
        request = self.request()
        for field in ('expected_pool_version', 'expected_worker_version',
                      'expected_project_version', 'expected_lifecycle_version'):
            with self.subTest(field=field), self.assertRaises(AdmissionConflictError):
                self.service.admit(replace(request, **{field: 99}))
        self.storage.set_worker_lifecycle('worker-a', 'draining', reason='Synthetic drain')
        with self.assertRaises(AdmissionDeniedError):
            self.service.admit(replace(request, expected_lifecycle_version=2))
        self.storage.set_worker_lifecycle('worker-a', 'active', reason='Synthetic restored')
        with self.assertRaises(AdmissionConflictError):
            self.service.admit(request)
        self.assertEqual(self.counts()['assignments'], 0)

    def test_expiration_normalizes_sqlite_and_offset_timestamps(self):
        self.configure(capacity=2)
        request = self.request()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        past_but_lexically_later = (now - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=3))).isoformat()
        past = self.qualification_with_timestamp(
            request.qualification_id, past_but_lexically_later, ':offset-past')
        with self.assertRaises(AdmissionDeniedError):
            self.service.admit(replace(request, qualification_id=past), now=now)
        future_but_lexically_earlier = (now + timedelta(minutes=5)).astimezone(timezone(timedelta(hours=-3))).isoformat()
        future = self.qualification_with_timestamp(
            request.qualification_id, future_but_lexically_earlier, ':offset-future')
        receipt = self.service.admit(replace(request, qualification_id=future), now=now)
        self.assertEqual(receipt.status, 'occupied')

    def test_injected_attempt_failure_rolls_back_claim_lease_event_and_admission(self):
        self.configure()
        request = self.request()
        before = self.counts()
        with patch.object(self.storage, '_create_assignment_attempt_in_transaction',
                          side_effect=RuntimeError('synthetic failure after assignment')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                self.service.admit(request)
        self.assertEqual(self.counts(), before)
        self.assertFalse(self.storage.db.in_transaction)
        self.assertEqual(self.service.admit(request).status, 'occupied')

    def test_registered_alias_cannot_bypass_admission_but_unregistered_local_keeps_working(self):
        self.configure()
        request = self.request()
        with self.assertRaises(PermissionError):
            self.storage.claim_runnable_task(request.task_id, 'worker-a', 'direct-cli')
        with self.assertRaises(PermissionError):
            self.storage.claim_runnable_task(request.task_id, 'unregistered-alias', 'direct-cli')
        _, local_task, _ = self.task()
        local = self.storage.claim_runnable_task(local_task, 'legacy-local', 'direct-cli')
        self.assertEqual(local.worker, 'legacy-local')

    def test_expiry_denies_renewal_but_holds_capacity_until_exact_stop(self):
        self.configure(workers=(('worker-a', 'tenant-a'), ('worker-b', 'tenant-b')))
        now = datetime.now(timezone.utc)
        request = self.request()
        first = self.service.admit(replace(request, ttl_seconds=1), now=now)
        later = now + timedelta(seconds=2)
        with self.assertRaises(PermissionError):
            self.storage.renew_task_lease(first.assignment_id, first.fencing_token, now=later)
        other = self.request(worker='worker-b', tenant='tenant-b')
        with self.assertRaises(CapacityUnavailableError):
            self.service.admit(other, now=later)
        with self.assertRaises(AdmissionDeniedError):
            self.service.reconcile_stopped(
                admission_id=first.admission_id, fencing_token=first.fencing_token + 1,
                evidence_digest='e' * 64, actor='fixture-coordinator', reason='Wrong fence', now=later)
        with self.assertRaises(CapacityUnavailableError):
            self.service.admit(other, now=later)
        self.stop(first, now=later)
        second = self.service.admit(other, now=later)
        self.stop(first, now=later)
        with self.assertRaises(CapacityUnavailableError):
            self.service.admit(self.request(), now=later)
        self.assertEqual(second.status, 'occupied')

    def test_quarantine_fences_existing_lease_without_freeing_pool(self):
        self.configure(workers=(('worker-a', 'tenant-a'), ('worker-b', 'tenant-b')))
        first = self.service.admit(self.request())
        self.storage.set_worker_lifecycle('worker-a', 'quarantined', reason='Synthetic quarantine')
        with self.assertRaises(PermissionError):
            self.storage.renew_task_lease(first.assignment_id, first.fencing_token)
        with self.assertRaises(PermissionError):
            self.storage.assert_fenced_lease(first.assignment_id, first.fencing_token)
        with self.assertRaises(CapacityUnavailableError):
            self.service.admit(self.request(worker='worker-b', tenant='tenant-b'))
        self.stop(first)
        self.assertEqual(self.service.admit(self.request(worker='worker-b', tenant='tenant-b')).status,
                         'occupied')

    def test_terminal_run_stage_or_attempt_fences_renewal_without_freeing_pool(self):
        self.configure(workers=(('worker-a', 'tenant-a'), ('worker-b', 'tenant-b')))
        for entity in ('run', 'stage', 'attempt'):
            with self.subTest(entity=entity):
                request = self.request()
                first = self.service.admit(request)
                if entity == 'run':
                    self.storage.finish_run(request.run_id, 'failed')
                elif entity == 'stage':
                    self.storage.transition_durable_stage(request.run_id, request.stage_key, 'failed', {})
                else:
                    with self.storage.db:
                        self.storage.db.execute("UPDATE attempts SET status='running' WHERE id=?", (first.attempt_id,))
                        self.storage.db.execute("UPDATE attempts SET status='failed' WHERE id=?", (first.attempt_id,))
                with self.assertRaises(PermissionError):
                    self.storage.renew_task_lease(first.assignment_id, first.fencing_token)
                with self.assertRaises(PermissionError):
                    self.storage.assert_fenced_lease(first.assignment_id, first.fencing_token)
                with self.assertRaises(CapacityUnavailableError):
                    self.service.admit(self.request(worker='worker-b', tenant='tenant-b'))
                self.stop(first)

    def test_draining_allows_bounded_renewal_but_reactivation_does_not_revive_old_fence(self):
        self.configure(workers=(('worker-a', 'tenant-a'), ('worker-b', 'tenant-b')))
        first = self.service.admit(self.request())
        self.storage.set_worker_lifecycle('worker-a', 'draining', reason='Synthetic controlled drain')
        renewed = self.storage.renew_task_lease(first.assignment_id, first.fencing_token, ttl_seconds=30)
        self.assertIsInstance(renewed, str)
        self.storage.set_worker_lifecycle('worker-a', 'quarantined', reason='Synthetic quarantine')
        self.storage.set_worker_lifecycle('worker-a', 'active', reason='Synthetic requalified lifecycle')
        with self.assertRaises(PermissionError):
            self.storage.renew_task_lease(first.assignment_id, first.fencing_token)
        with self.assertRaises(PermissionError):
            self.storage.assert_fenced_lease(first.assignment_id, first.fencing_token)
        with self.assertRaises(CapacityUnavailableError):
            self.service.admit(self.request(worker='worker-b', tenant='tenant-b'))

    def test_fenced_artifact_requires_exact_admitted_run_stage_and_provider(self):
        self.configure()
        request = self.request()
        admitted = self.service.admit(request)
        sibling_run = self.storage.start_durable_run(
            project_id=request.project_id, task_id=request.task_id,
            workflow_id='artifact-sibling', workflow_version='1',
            definition={'id': 'artifact-sibling'},
            stages=[{'id': request.stage_key, 'depends_on': []}],
        )
        self.storage.transition_durable_stage(sibling_run, request.stage_key, 'running', {})
        for run_id, stage, provider in (
            (sibling_run, request.stage_key, request.provider_id),
            (request.run_id, 'review', request.provider_id),
            (request.run_id, request.stage_key, 'other-provider'),
        ):
            with self.subTest(run=run_id, stage=stage, provider=provider), self.assertRaises(PermissionError):
                self.storage.add_fenced_artifact(
                    admitted.assignment_id, admitted.fencing_token, run_id, stage, provider,
                    'Mismatched synthetic result', evidence_kind='summary')
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0], 0)
        artifact = self.storage.add_fenced_artifact(
            admitted.assignment_id, admitted.fencing_token, request.run_id,
            request.stage_key, request.provider_id, 'Exact synthetic result', evidence_kind='summary')
        stored = self.storage.db.execute('SELECT * FROM artifacts WHERE id=?', (artifact,)).fetchone()
        self.assertEqual((stored['run_id'], stored['stage'], stored['provider']),
                         (request.run_id, request.stage_key, request.provider_id))

    def test_lease_clock_is_sampled_after_waiting_for_writer_lock(self):
        self.configure()
        for operation in ('renew_task_lease', 'assert_fenced_lease'):
            with self.subTest(operation=operation):
                admitted = self.service.admit(self.request())
                deadline = datetime.fromisoformat(admitted.expires_at)
                clock = [deadline - timedelta(seconds=1)]
                original_begin = self.storage._begin_immediate

                def acquire_after_wait():
                    # Simulate time passing while another writer owns SQLite,
                    # without sleeping or changing the persisted expiry.
                    clock[0] = deadline + timedelta(seconds=1)
                    original_begin()

                with patch('agent_factory.storage._utc', side_effect=lambda value=None: value or clock[0]):
                    with patch.object(self.storage, '_begin_immediate', side_effect=acquire_after_wait):
                        with self.assertRaises(PermissionError):
                            getattr(self.storage, operation)(admitted.assignment_id, admitted.fencing_token)
                row = self.storage.db.execute('SELECT expires_at FROM leases WHERE id=?',
                                              (admitted.lease.lease_id,)).fetchone()
                self.assertEqual(datetime.fromisoformat(row['expires_at']), deadline)
                with self.assertRaises(CapacityUnavailableError):
                    self.service.admit(self.request())
                self.stop(admitted)


if __name__ == '__main__':
    unittest.main()
