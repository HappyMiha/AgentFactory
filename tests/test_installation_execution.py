"""Real SQLite and Windows file publication; synthetic worker qualification only."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import os
import threading
import unittest
from unittest.mock import patch

from agent_factory.installation_execution import InstallationExecutor
from agent_factory.installation_review import InstallationConflict
from agent_factory.storage import SQLiteStorage
from agent_factory.worker_runtime import DirectCLIWorkerRuntime
import agent_factory.installation_execution as execution
import test_installation_policy as policy_fixture
from test_worker_admission_runtime import AdmissionDriver


class InstallationExecutionTests(unittest.TestCase):
    def setUp(self):
        self.base = policy_fixture.InstallationAdmittedPolicyTests()
        self.base.setUp(); self.addCleanup(self.base.doCleanups)
        self.fixture = self.base.fixture
        self.storage = self.fixture.storage
        _, self.admission, self.launch = self.base.admitted_publication_launch()
        self.runtime = DirectCLIWorkerRuntime(self.storage, AdmissionDriver())
        self.session = self.runtime.start(self.launch)
        self.executor = InstallationExecutor(self.fixture.intents, self.runtime)
        self.record = self.base.publication

    def validate(self, **changes):
        args = {'mission': self.fixture.mission, 'actor': 'Founder', 'publication_id': self.record['operation_id'],
                'session_id': self.session.id, 'launch': self.launch, 'state': 'reserved'} | changes
        with self.storage._policy_transaction():
            return self.executor._validate(**args)

    def publish(self, staged, **changes):
        return self.executor.publish(self.fixture.mission, 'Founder',
            **({'publication_id': self.record['operation_id'], 'session_id': self.session.id,
                'launch': self.launch, 'staged': staged} | changes))

    def test_running_admitted_scope_requires_exact_effect_session_and_current_policy(self):
        operation, _ = self.validate()
        self.assertEqual(operation.request_digest, self.launch.effect_digest)
        for changes in ({'session_id': self.session.id+999},
                        {'launch': replace(self.launch, effect_digest='b'*64)},
                        {'launch': replace(self.launch, approval=replace(self.launch.approval, gate_id=99999))}):
            with self.assertRaises((PermissionError, InstallationConflict)):
                self.validate(**changes)
        self.storage.suspend_runtime_session(self.session.id, reason='Fixture pause')
        with self.assertRaises(PermissionError): self.validate()

    def test_expired_intent_and_changed_host_deny_post_consumption(self):
        self.fixture.now += timedelta(hours=1)
        with self.assertRaisesRegex(InstallationConflict, 'review_expired'): self.validate()
        self.fixture.now -= timedelta(hours=1)
        self.fixture.host['workspace'] = 'other'
        with self.assertRaises(InstallationConflict): self.validate()
        self.assertEqual(self.fixture.intents.journal.get(self.record['operation_id']).latest_event.lifecycle.value, 'reserved')

    def test_alias_journal_record_cannot_reuse_the_same_consumed_effect(self):
        journal = self.fixture.intents.journal
        original = journal.get(self.record['operation_id'])
        alias = journal.reserve(mission_id=self.fixture.mission, actor='Founder', operation_key='alias-publication',
            operation_class=original.operation_class, reconciliation_policy=original.reconciliation_policy,
            request=original.request, expected_mission_version=original.mission_version,
            expected_backlog_revision_id=original.backlog_revision_id,
            expected_execution_epoch_id=original.execution_epoch_id,
            expected_checkpoint_id=original.checkpoint_id, expected_fencing_token=original.control_fencing_token)
        self.assertEqual(alias.operation.request_digest, self.launch.effect_digest)
        with self.assertRaisesRegex(InstallationConflict, 'journal_scope_mismatch'):
            self.validate(publication_id=alias.operation.id)

    def test_publish_refuses_enclosing_transaction_without_committing_it(self):
        self.storage.db.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaisesRegex(ValueError, 'outside a caller transaction'): self.publish(None)
            self.assertTrue(self.storage.db.in_transaction)
        finally: self.storage.db.rollback()

    def test_emergency_stop_and_expired_assignment_deny_current_execution(self):
        self.storage.set_emergency_stop(True, actor='Founder', reason='Executor fixture')
        with self.assertRaises(PermissionError): self.validate()
        self.storage.set_emergency_stop(False, actor='Founder', reason='Executor fixture reset')
        with self.storage.db:
            self.storage.db.execute("UPDATE leases SET expires_at='2000-01-01T00:00:00+00:00' WHERE assignment_id=?",
                                    (self.launch.assignment_id,))
        with self.assertRaises(PermissionError): self.validate()

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows admitted publication')
    def test_actual_publish_commits_start_before_files_and_never_replays(self):
        original = execution.publish_staged
        def inspect(staged, **kwargs):
            self.assertFalse(self.storage.db.in_transaction)
            with closing(SQLiteStorage(self.fixture.path)) as other:
                from agent_factory.durable_workflow import MissionOperationJournal
                self.assertEqual(MissionOperationJournal(other).get(self.record['operation_id']).latest_event.lifecycle.value, 'running')
                self.assertEqual(other.db.execute('SELECT COUNT(*) FROM stage_approval_consumptions').fetchone()[0], 1)
                self.assertEqual(other.db.execute("SELECT COUNT(*) FROM autonomous_mission_operation_leases WHERE status='ACTIVE'").fetchone()[0], 1)
            return original(staged, **kwargs)
        with self.fixture.archive.stage(self.fixture.catalog) as staged, patch.object(execution, 'publish_staged', side_effect=inspect) as publisher:
            result = self.publish(staged)
            self.assertEqual(result['state'], 'completed')
            self.assertEqual(self.fixture.publications.observe(self.fixture.mission, 'Founder', self.record['operation_id'])['state'], 'matched')
            with self.assertRaisesRegex(InstallationConflict, 'requires_reconciliation'): self.publish(staged)
            self.assertEqual(publisher.call_count, 1)
        self.assertEqual(self.fixture.intents.view(self.fixture.mission, 'Founder', self.record['intent_id'])['state'], 'reserved')
        self.assertFalse(result['execution_eligible'])

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows lost-completion recovery')
    def test_lost_completion_is_unknown_then_reconciles_without_copy(self):
        journal = self.fixture.intents.journal
        # Both wrappers use the same durable journal, but separate Python instances.
        with self.fixture.archive.stage(self.fixture.catalog) as staged, \
             patch.object(self.executor.publications.journal, 'complete', side_effect=OSError('Synthetic lost completion')):
            with self.assertRaises(OSError): self.publish(staged)
            self.assertEqual(journal.get(self.record['operation_id']).latest_event.lifecycle.value, 'unknown')
            with self.assertRaisesRegex(InstallationConflict, 'requires_reconciliation'): self.publish(staged)
        result = self.fixture.publications.reconcile_unknown(self.fixture.mission, 'Founder',
            self.record['operation_id'], event_key='host-reconcile')
        self.assertEqual(result['state'], 'reconciled')
        self.assertEqual(len(self.runtime.driver.starts), 1)

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows pre-rename denial')
    def test_expiry_after_copy_prevents_rename_and_leaves_unknown_no_retry(self):
        original = execution.publish_staged
        def expire(staged, **kwargs):
            authorize = kwargs['authorize']
            def deny_after_copy(receipt):
                self.fixture.now += timedelta(hours=1)
                return authorize(receipt)
            return original(staged, **(kwargs | {'authorize': deny_after_copy}))
        with self.fixture.archive.stage(self.fixture.catalog) as staged, patch.object(execution, 'publish_staged', side_effect=expire):
            with self.assertRaisesRegex(InstallationConflict, 'review_expired'): self.publish(staged)
        self.assertFalse((self.fixture.root/self.record['relative_target']).exists())
        self.assertEqual(self.fixture.intents.journal.get(self.record['operation_id']).latest_event.lifecycle.value, 'unknown')

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows concurrent publication')
    def test_two_real_connections_dispatch_one_publisher(self):
        from agent_factory.installation_intent import InstallationIntents
        entered, release = threading.Event(), threading.Event()
        original = execution.publish_staged
        def hold(staged, **kwargs):
            entered.set()
            if not release.wait(10): raise RuntimeError('Fixture barrier timed out')
            return original(staged, **kwargs)
        def publish(staged):
            with closing(SQLiteStorage(self.fixture.path)) as other:
                executor = InstallationExecutor(InstallationIntents(self.fixture.review_for(other)),
                    DirectCLIWorkerRuntime(other, AdmissionDriver()))
                return executor.publish(self.fixture.mission, 'Founder', publication_id=self.record['operation_id'],
                    session_id=self.session.id, launch=self.launch, staged=staged)
        with self.fixture.archive.stage(self.fixture.catalog) as staged, \
             patch.object(execution, 'publish_staged', side_effect=hold) as publisher, \
             ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(publish, staged)
            try:
                self.assertTrue(entered.wait(10))
                with self.assertRaisesRegex(InstallationConflict, 'requires_reconciliation'):
                    pool.submit(publish, staged).result(timeout=10)
            finally: release.set()
            self.assertEqual(first.result(timeout=10)['state'], 'completed')
            self.assertEqual(publisher.call_count, 1)

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows existing target preservation')
    def test_existing_target_is_preserved_and_mapped_network_drive_denied(self):
        target = self.fixture.root/self.record['relative_target']
        with self.fixture.archive.stage(self.fixture.catalog) as staged:
            with patch.object(execution.ctypes.windll.kernel32, 'GetDriveTypeW', return_value=4):
                with self.assertRaisesRegex(ValueError, 'local fixed drive'): self.publish(staged)
            self.assertEqual(self.fixture.intents.journal.get(self.record['operation_id']).latest_event.lifecycle.value, 'reserved')
            self.assertFalse(target.exists())
            target.mkdir(parents=True); sentinel = target/'keep.txt'; sentinel.write_bytes(b'unmanaged')
            with self.assertRaises(FileExistsError): self.publish(staged)
            self.assertEqual(sentinel.read_bytes(), b'unmanaged')
            self.assertEqual(self.fixture.intents.journal.get(self.record['operation_id']).latest_event.lifecycle.value, 'unknown')

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows published payload lookup')
    def test_payload_lookup_rehashes_files_and_keeps_paths_relative(self):
        publications = self.fixture.publications
        with self.fixture.archive.stage(self.fixture.catalog) as staged:
            self.publish(staged)
        self.fixture.now += timedelta(hours=1)  # Historical artifacts do not renew consent.
        before = self.storage.db.total_changes
        payload = publications.read_payload(self.fixture.mission, 'Founder', self.record['operation_id'])
        self.assertEqual(payload['relative_payload'], self.record['relative_target']+'/payload')
        self.assertEqual(payload['files'], self.record['receipt']['manifest']['files'])
        self.assertTrue(payload['publication_verified'])
        self.assertFalse(payload['engine_qualified']); self.assertFalse(payload['execution_eligible'])
        self.assertEqual(self.storage.db.total_changes, before)
        # Returned manifests are detached; a caller cannot change journal evidence.
        payload['files'].clear()
        self.assertTrue(publications.read_payload(self.fixture.mission, 'Founder', self.record['operation_id'])['files'])
        root = self.fixture.root/self.record['relative_target']/'payload'
        victim = root/self.record['receipt']['manifest']['files'][0]['path']
        victim.write_bytes(b'changed')
        with self.assertRaisesRegex(InstallationConflict, 'payload_not_verified'):
            publications.read_payload(self.fixture.mission, 'Founder', self.record['operation_id'])

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows reconciled payload lookup')
    def test_payload_lookup_requires_reconciliation_and_current_host(self):
        publications = self.fixture.publications
        with self.assertRaisesRegex(InstallationConflict, 'not_completed'):
            publications.read_payload(self.fixture.mission, 'Founder', self.record['operation_id'])
        with self.fixture.archive.stage(self.fixture.catalog) as staged, \
             patch.object(self.executor.publications.journal, 'complete', side_effect=OSError('Lost completion')):
            with self.assertRaises(OSError): self.publish(staged)
        with self.assertRaisesRegex(InstallationConflict, 'not_completed'):
            publications.read_payload(self.fixture.mission, 'Founder', self.record['operation_id'])
        publications.reconcile_unknown(self.fixture.mission, 'Founder', self.record['operation_id'], event_key='lookup-recovery')
        self.assertTrue(publications.read_payload(self.fixture.mission, 'Founder', self.record['operation_id'])['publication_verified'])
        with self.assertRaises(KeyError): publications.read_payload(self.fixture.mission, 'Other', self.record['operation_id'])
        self.fixture.host['workspace'] = 'different'
        with self.assertRaisesRegex(InstallationConflict, 'payload_not_verified'):
            publications.read_payload(self.fixture.mission, 'Founder', self.record['operation_id'])


if __name__ == '__main__': unittest.main()
