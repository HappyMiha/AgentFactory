from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import json
import os
import threading
import unittest
import uuid

from agent_factory.installation_journal import InstallationPublicationJournal
from agent_factory.installation_publication import PublicationReceipt, publish_staged
from agent_factory.installation_review import InstallationConflict
from agent_factory.storage import SQLiteStorage
import test_installation_archive as archive_fixture
import test_installation_intent as intent_fixture


class InstallationJournalTests(unittest.TestCase):
    review_for = intent_fixture.InstallationIntentTests.review_for
    approve = intent_fixture.InstallationIntentTests.approve
    reserve = intent_fixture.InstallationIntentTests.reserve

    def setUp(self):
        intent_fixture.InstallationIntentTests.setUp(self)
        self.archive = archive_fixture.InstallationArchiveTests()
        self.archive.setUp(); self.addCleanup(self.archive.doCleanups)
        self.catalog = self.archive.archive()
        self.plan = self.review.prepare(self.mission, 'Founder', command_id=str(uuid.uuid4()))
        self.approve(); self.intent = self.reserve()
        self.publications = InstallationPublicationJournal(self.intents)

    def prepare(self, staged, **changes):
        return self.publications.reserve(self.mission, 'Founder',
            **({'intent_id': self.intent['operation_id'], 'staged': staged} | changes))

    def test_exact_receipt_persists_in_existing_journal_and_replay_is_readable(self):
        with self.archive.stage(self.catalog) as staged:
            record = self.prepare(staged)
            self.assertEqual(self.prepare(staged), record)
            self.assertEqual(record['state'], 'reserved'); self.assertFalse(record['execution_eligible'])
            operation = self.intents.journal.get(record['operation_id'])
            self.assertEqual(operation.request['receipt'], record['receipt'])
            self.assertEqual(operation.reconciliation_policy.value, 'verify_only')
            self.assertEqual(len(self.intents.journal.events(operation.id)), 1)
            self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM scoped_execution_approvals').fetchone()[0], 0)
            self.assertFalse((self.root/record['relative_target']).exists())
        other = SQLiteStorage(self.path)
        try:
            from agent_factory.installation_intent import InstallationIntents
            reopened = InstallationPublicationJournal(InstallationIntents(self.review_for(other)))
            self.assertEqual(reopened.view(self.mission, 'Founder', record['operation_id']), record)
        finally:
            other.close()

    def test_wrong_owner_package_source_and_non_publication_operation_reject(self):
        with self.archive.stage(self.catalog) as staged:
            with self.assertRaises(InstallationConflict): self.prepare(replace(staged, sha256='b'*64))
            with self.assertRaises(InstallationConflict): self.prepare(replace(staged, package_id='unrequested'))
            record = self.prepare(staged)
            with self.assertRaises(KeyError): self.publications.view(self.mission, 'Other', record['operation_id'])
            with self.assertRaises(InstallationConflict):
                self.publications.view(self.mission, 'Founder', self.intent['operation_id'])

    def test_expired_plan_blocks_new_reservation_but_preserves_old_evidence(self):
        with self.archive.stage(self.catalog) as staged:
            record = self.prepare(staged)
            self.now += timedelta(hours=1)
            with self.assertRaisesRegex(InstallationConflict, 'review_expired'): self.prepare(staged)
            self.assertEqual(self.publications.view(self.mission, 'Founder', record['operation_id']), record)
            self.assertEqual(self.publications.observe(self.mission, 'Founder', record['operation_id'])['state'], 'absent')

    def test_reconciliation_of_absence_never_grants_automatic_retry(self):
        with self.archive.stage(self.catalog) as staged: record = self.prepare(staged)
        operation = record['operation_id']
        self.intents.journal.mark_unknown(operation, event_key='lost-before-publication', evidence={})
        result = self.publications.reconcile_unknown(self.mission, 'Founder', operation, event_key='observe-once')
        self.assertEqual(result['state'], 'needs_attention'); self.assertFalse(result['execution_eligible'])
        self.assertFalse(self.intents.journal.get(operation).execute)
        self.assertEqual(self.publications.reconcile_unknown(self.mission, 'Founder', operation,
            event_key='observe-once'), result)

    def test_changed_host_and_unmanaged_target_are_not_adopted(self):
        with self.archive.stage(self.catalog) as staged: record = self.prepare(staged)
        target = self.root/record['relative_target']; target.mkdir(parents=True)
        sentinel = target/'unmanaged'; sentinel.write_bytes(b'keep')
        self.assertEqual(self.publications.observe(self.mission, 'Founder', record['operation_id'])['state'], 'conflict')
        self.host['workspace'] = 'different'
        self.assertEqual(self.publications.observe(self.mission, 'Founder', record['operation_id'])['state'], 'indeterminate')
        self.assertEqual(sentinel.read_bytes(), b'keep')
        self.intents.journal.mark_unknown(record['operation_id'], event_key='unknown', evidence={})
        result = self.publications.reconcile_unknown(self.mission, 'Founder', record['operation_id'], event_key='observe')
        self.assertEqual(result['state'], 'needs_attention')
        self.assertEqual(sentinel.read_bytes(), b'keep')

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows publication plus SQLite recovery')
    def test_lost_completion_reopens_expected_receipt_and_adopts_without_republication(self):
        with self.archive.stage(self.catalog) as staged:
            record = self.prepare(staged)
            target = self.root/record['relative_target']; target.parent.mkdir(parents=True)
            receipt = PublicationReceipt(json.dumps(record['receipt'], sort_keys=True, separators=(',', ':')))
            def fixture_authorize(_):
                # Tests only: exercise real journal/filesystem, not real runtime
                # admission or production policy approval.
                self.intents.journal.start(record['operation_id'], event_key='fixture-start')
                return True
            publish_staged(staged, parent=target.parent, expected=receipt, authorize=fixture_authorize)
            self.intents.journal.mark_unknown(record['operation_id'], event_key='lost-response', evidence={})
        other = SQLiteStorage(self.path)
        try:
            from agent_factory.installation_intent import InstallationIntents
            reopened = InstallationPublicationJournal(InstallationIntents(self.review_for(other)))
            result = reopened.reconcile_unknown(self.mission, 'Founder', record['operation_id'], event_key='recover')
            self.assertEqual(result['state'], 'reconciled'); self.assertFalse(result['execution_eligible'])
            operation = reopened.journal.get(record['operation_id'])
            self.assertTrue(operation.latest_event.result['publication_verified'])
            self.assertFalse(operation.execute)
            self.assertEqual(reopened.reconcile_unknown(self.mission, 'Founder', record['operation_id'], event_key='recover'), result)
            self.assertEqual((target/'payload/folder/game.txt').read_bytes(), b'game')
            self.assertEqual(reopened.journal.get(self.intent['operation_id']).latest_event.lifecycle.value, 'reserved')
        finally:
            other.close()

    def test_second_database_connection_reuses_single_publication_record(self):
        with self.archive.stage(self.catalog) as staged:
            first = self.prepare(staged)
            other = SQLiteStorage(self.path)
            try:
                from agent_factory.installation_intent import InstallationIntents
                second = InstallationPublicationJournal(InstallationIntents(self.review_for(other)))
                self.assertEqual(second.reserve(self.mission, 'Founder', intent_id=self.intent['operation_id'], staged=staged), first)
                self.assertEqual(len(second.journal.events(first['operation_id'])), 1)
            finally:
                other.close()

    def test_concurrent_reservations_create_one_publication_operation(self):
        from agent_factory.installation_intent import InstallationIntents
        barrier = threading.Barrier(2)
        with self.archive.stage(self.catalog) as staged:
            def reserve(_):
                storage = SQLiteStorage(self.path)
                try:
                    service = InstallationPublicationJournal(InstallationIntents(self.review_for(storage)))
                    barrier.wait(timeout=10)
                    return service.reserve(self.mission, 'Founder', intent_id=self.intent['operation_id'], staged=staged)
                finally:
                    storage.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                records = list(pool.map(reserve, range(2)))
            self.assertEqual(records[0], records[1])
            self.assertEqual(len(self.intents.journal.events(records[0]['operation_id'])), 1)

    @unittest.skipIf(os.name == 'nt', 'Actual POSIX linked parent observation')
    def test_linked_missing_target_is_indeterminate_and_neighbour_is_untouched(self):
        with self.archive.stage(self.catalog) as staged: record = self.prepare(staged)
        neighbour = self.root/'neighbour'; neighbour.mkdir()
        sentinel = neighbour/'keep'; sentinel.write_bytes(b'keep')
        os.symlink(neighbour, self.root/'tools', target_is_directory=True)
        observed = self.publications.observe(self.mission, 'Founder', record['operation_id'])
        self.assertEqual(observed['state'], 'indeterminate')
        self.assertEqual(sentinel.read_bytes(), b'keep')


if __name__ == '__main__': unittest.main()
