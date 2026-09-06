from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
import json
from unittest.mock import patch

from agent_factory.installation_intent import InstallationIntents
from agent_factory.autonomous_mission import AutonomousMissionService
from agent_factory.game_planning import GamePlanning
from agent_factory.installation_plan import load_catalog
from agent_factory.installation_review import InstallationReview, InstallationConflict
from agent_factory.storage import SQLiteStorage
from test_installation_review import create_game, HOST, NOW


class InstallationIntentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.path = self.root/'state.db'
        self.storage = SQLiteStorage(self.path); self.addCleanup(self.storage.close)
        self.mission = create_game(self.storage)
        self.host = deepcopy(HOST); self.catalog = load_catalog(); self.now = NOW
        self.review = self.review_for(self.storage)
        self.intents = InstallationIntents(self.review)
        self.plan = self.review.prepare(self.mission, 'Founder', command_id=str(uuid.uuid4()))

    def review_for(self, storage):
        return InstallationReview(storage, self.root, probe=lambda *_:deepcopy(self.host),
                                  catalog=lambda:deepcopy(self.catalog), clock=lambda:self.now)

    def approve(self, decision='approved'):
        return self.review.decide(self.mission,'Founder',plan_id=self.plan['id'],digest=self.plan['digest'],
                                  decision=decision,command_id=str(uuid.uuid4()))

    def reserve(self, **changes):
        return self.intents.reserve(self.mission,'Founder',**({'plan_id':self.plan['id'],
                                     'digest':self.plan['digest']} | changes))

    def count(self):
        return self.storage.db.execute('SELECT COUNT(*) FROM autonomous_mission_operations').fetchone()[0]

    def test_saved_single_copy_approval_cannot_reserve_after_budget_upgrade(self):
        from agent_factory.installation_plan import build_plan, InstallationPlan
        def legacy_plan(*args, **kwargs):
            document = build_plan(*args, **kwargs).document()
            for step in document['steps']:
                parts = step.pop('disk_budget_components')
                step['disk_budget_bytes'] = parts['source_download_bytes'] + parts['extraction_bytes']
            document['disk_budget_bytes'] = sum(step['disk_budget_bytes'] for step in document['steps'])
            return InstallationPlan(json.dumps(document, sort_keys=True, separators=(',', ':')))
        # Persist and approve through the old plan shape, without editing any
        # immutable database rows. The new implementation then reads that DB.
        with patch('agent_factory.installation_review.build_plan', legacy_plan):
            self.plan = self.review.prepare(self.mission, 'Founder', command_id=str(uuid.uuid4()))
            self.approve()
            historical = self.reserve()
        with self.assertRaisesRegex(InstallationConflict, 'plan_changed'):
            self.reserve()
        self.assertEqual(self.intents.view(self.mission, 'Founder', historical['operation_id']), historical)
        self.assertEqual(self.count(), 1)
        fresh = self.review.prepare(self.mission, 'Founder', command_id=str(uuid.uuid4()))
        self.assertGreater(fresh['plan']['disk_budget_bytes'], self.plan['plan']['disk_budget_bytes'])
        self.assertNotEqual(fresh['digest'], self.plan['digest'])
        self.plan = fresh
        self.approve()
        self.assertEqual(self.reserve()['state'], 'reserved')

    def test_approved_intent_is_durable_bound_and_never_execution_authority(self):
        self.approve(); result = self.reserve()
        self.assertEqual(result['state'],'reserved'); self.assertFalse(result['execution_eligible'])
        self.assertEqual(result['plan_digest'],self.plan['digest'])
        self.assertEqual(result['plan'],self.plan['plan'])
        operation = self.intents.journal.get(result['operation_id'])
        self.assertEqual(operation.operation_class.value,'installation')
        self.assertEqual(operation.reconciliation_policy.value,'verify_only')
        self.assertEqual(len(self.intents.journal.events(operation.id)),1)
        self.assertEqual(self.reserve(),result); self.assertEqual(self.count(),1)
        other = SQLiteStorage(self.path)
        try:
            reopened = InstallationIntents(self.review_for(other))
            self.assertEqual(reopened.view(self.mission,'Founder',operation.id),result)
            self.assertEqual(reopened.reserve(self.mission,'Founder',plan_id=self.plan['id'],digest=self.plan['digest']),result)
        finally: other.close()
        self.assertFalse((self.root/'tools').exists())

    def test_missing_rejected_or_substituted_approval_cannot_reserve(self):
        with self.assertRaises(InstallationConflict): self.reserve()
        self.approve('rejected')
        with self.assertRaises(InstallationConflict): self.reserve()
        with self.assertRaises(InstallationConflict): self.reserve(digest='0'*64)
        with self.assertRaises(KeyError): self.intents.reserve(self.mission,'Other',plan_id=self.plan['id'],digest=self.plan['digest'])
        self.assertEqual(self.count(),0)

    def test_current_source_host_capacity_catalogue_and_latest_plan_are_required(self):
        self.approve()
        for mutation in ('host','capacity','catalogue'):
            with self.subTest(mutation=mutation):
                host, catalog = deepcopy(self.host), deepcopy(self.catalog)
                if mutation == 'host': self.host['workspace']='other-workspace'
                if mutation == 'capacity': self.host['free_bytes']=1
                if mutation == 'catalogue': self.catalog['packages']['godot-editor']['sha256']='0'*64
                with self.assertRaises(InstallationConflict): self.reserve()
                self.host, self.catalog = host, catalog
                self.assertEqual(self.count(),0)
        self.review.prepare(self.mission,'Founder',command_id=str(uuid.uuid4()))
        with self.assertRaisesRegex(InstallationConflict,'newer_plan_exists'): self.reserve()
        self.assertEqual(self.count(),0)

    def test_slow_observation_crossing_expiry_reserves_nothing(self):
        self.approve(); self.now=NOW+timedelta(minutes=14,seconds=59)
        def slow(*_):
            self.now += timedelta(seconds=2)
            return deepcopy(self.host)
        self.review.probe=slow
        with self.assertRaisesRegex(InstallationConflict,'review_expired'): self.reserve()
        self.assertEqual(self.count(),0)

    def test_historical_read_after_expiry_never_renews_reservation(self):
        self.approve(); result=self.reserve(); self.now += timedelta(hours=1)
        self.assertEqual(self.intents.view(self.mission,'Founder',result['operation_id']),result)
        with self.assertRaisesRegex(InstallationConflict,'review_expired'): self.reserve()
        with self.assertRaises(KeyError): self.intents.view(self.mission,'Other',result['operation_id'])
        self.assertEqual(self.count(),1)

    def test_fenced_mission_cannot_reserve_or_replay_as_a_new_intent(self):
        self.approve()
        result=self.reserve()
        missions=AutonomousMissionService(self.storage)
        missions.transition_disposition(self.mission,'PAUSED',actor='Founder',command_id=str(uuid.uuid4()),
            expected_version=missions.get(self.mission).version,reason='Pause fixture')
        with self.assertRaisesRegex(InstallationConflict,'mission_is_fenced'): self.reserve()
        self.assertEqual(self.count(),1)
        self.assertEqual(self.intents.view(self.mission,'Founder',result['operation_id']),result)

    def test_changed_saved_game_revision_cannot_reserve_old_approval(self):
        self.approve()
        planning=GamePlanning(self.storage); game=planning.view(self.mission,'Founder')
        fields=deepcopy(game['fields']); fields['visual_style']='A revised style.'
        planning.save(self.mission,'Founder',fields=fields,command_id=str(uuid.uuid4()),
                      expected_revision_id=game['revision_id'],expected_source_digest=game['source_digest'])
        with self.assertRaises(InstallationConflict): self.reserve()
        self.assertEqual(self.count(),0)

    def test_two_database_connections_reserve_one_immutable_operation(self):
        self.approve()
        def reserve(_):
            storage=SQLiteStorage(self.path)
            try:
                return InstallationIntents(self.review_for(storage)).reserve(self.mission,'Founder',
                    plan_id=self.plan['id'],digest=self.plan['digest'])
            finally: storage.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,range(2)))
        self.assertEqual(results[0],results[1]); self.assertEqual(self.count(),1)
        with self.assertRaises(sqlite3.DatabaseError), self.storage.db:
            self.storage.db.execute("UPDATE autonomous_mission_operations SET request_json='{}' WHERE id=?",(results[0]['operation_id'],))

    def test_current_validation_never_reserves_or_writes_and_reopens(self):
        self.approve(); saved = self.reserve()
        before = self.storage.db.total_changes
        with patch.object(self.intents.journal, 'reserve', side_effect=AssertionError('No reservation allowed')):
            self.assertEqual(self.intents.current(self.mission, 'Founder', saved['operation_id']), saved)
        self.assertEqual(self.storage.db.total_changes, before)
        self.assertFalse(self.storage.db.in_transaction)
        other = SQLiteStorage(self.path)
        try:
            self.assertEqual(InstallationIntents(self.review_for(other)).current(
                self.mission, 'Founder', saved['operation_id']), saved)
        finally: other.close()
        self.assertEqual(len(self.intents.journal.events(saved['operation_id'])), 1)
        self.assertFalse(saved['execution_eligible'])

    def test_current_success_and_failure_preserve_caller_transaction(self):
        self.approve(); saved = self.reserve()
        self.storage.db.execute('CREATE TABLE caller_fixture (value TEXT)')
        self.storage.db.commit()
        other = SQLiteStorage(self.path); self.addCleanup(other.close)
        self.storage.db.execute('BEGIN IMMEDIATE')
        self.storage.db.execute("INSERT INTO caller_fixture VALUES ('pending')")
        try:
            self.assertEqual(self.intents.current(self.mission, 'Founder', saved['operation_id']), saved)
            self.now += timedelta(hours=1)
            with self.assertRaisesRegex(InstallationConflict, 'review_expired'):
                self.intents.current(self.mission, 'Founder', saved['operation_id'])
            self.assertTrue(self.storage.db.in_transaction)
            self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM caller_fixture').fetchone()[0], 1)
            self.assertEqual(other.db.execute('SELECT COUNT(*) FROM caller_fixture').fetchone()[0], 0)
        finally: self.storage.db.rollback()
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM caller_fixture').fetchone()[0], 0)

    def test_current_rejects_changed_host_space_catalogue_and_newer_plan(self):
        self.approve(); saved = self.reserve()
        for mutation in ('host', 'capacity', 'catalogue'):
            host, catalog = deepcopy(self.host), deepcopy(self.catalog)
            if mutation == 'host': self.host['workspace'] = 'other'
            if mutation == 'capacity': self.host['free_bytes'] = 1
            if mutation == 'catalogue': self.catalog['packages']['godot-editor']['sha256'] = '0'*64
            try:
                with self.assertRaises(InstallationConflict):
                    self.intents.current(self.mission, 'Founder', saved['operation_id'])
            finally: self.host, self.catalog = host, catalog
        self.review.prepare(self.mission, 'Founder', command_id=str(uuid.uuid4()))
        with self.assertRaisesRegex(InstallationConflict, 'newer_plan_exists'):
            self.intents.current(self.mission, 'Founder', saved['operation_id'])
        self.assertEqual(self.intents.view(self.mission, 'Founder', saved['operation_id']), saved)

    def test_current_rejects_unknown_operation_and_wrong_actor_or_identifier(self):
        self.approve(); saved = self.reserve()
        for value in (True, 0, -1, '1', 2**63):
            with self.assertRaises(ValueError): self.intents.current(self.mission, 'Founder', value)
        with self.assertRaises(KeyError): self.intents.current(self.mission, 'Other', saved['operation_id'])
        self.intents.journal.mark_unknown(saved['operation_id'], event_key='lost', evidence={})
        with self.assertRaisesRegex(InstallationConflict, 'not_reserved'):
            self.intents.current(self.mission, 'Founder', saved['operation_id'])

    def test_current_rejects_resumed_mission_with_changed_fence(self):
        self.approve(); saved = self.reserve()
        missions = AutonomousMissionService(self.storage)
        for disposition in ('PAUSED', 'RUNNING'):
            missions.transition_disposition(self.mission, disposition, actor='Founder', command_id=str(uuid.uuid4()),
                expected_version=missions.get(self.mission).version, reason='Current-intent fixture')
            with self.assertRaises(InstallationConflict):
                self.intents.current(self.mission, 'Founder', saved['operation_id'])
        self.assertEqual(self.intents.view(self.mission, 'Founder', saved['operation_id']), saved)

    def test_current_writer_lock_blocks_scope_change_until_caller_rollback(self):
        self.approve(); saved = self.reserve()
        other = SQLiteStorage(self.path); self.addCleanup(other.close)
        other.db.execute('PRAGMA busy_timeout=0')
        missions = AutonomousMissionService(other)
        def pause():
            missions.transition_disposition(self.mission, 'PAUSED', actor='Founder', command_id=str(uuid.uuid4()),
                expected_version=missions.get(self.mission).version, reason='Concurrent pause fixture')
        self.storage.db.execute('BEGIN')
        try:
            self.intents.current(self.mission, 'Founder', saved['operation_id'])
            with self.assertRaises(sqlite3.OperationalError): pause()
            self.assertTrue(self.storage.db.in_transaction)
        finally: self.storage.db.rollback()
        pause()
        with self.assertRaisesRegex(InstallationConflict, 'mission_is_fenced'):
            self.intents.current(self.mission, 'Founder', saved['operation_id'])

    def test_current_stale_wal_reader_cannot_validate_old_scope(self):
        self.approve(); saved = self.reserve()
        other = SQLiteStorage(self.path); self.addCleanup(other.close)
        self.storage.db.execute('BEGIN')
        self.storage.db.execute('SELECT version FROM autonomous_missions WHERE id=?', (self.mission,)).fetchone()
        missions = AutonomousMissionService(other)
        missions.transition_disposition(self.mission, 'PAUSED', actor='Founder', command_id=str(uuid.uuid4()),
            expected_version=missions.get(self.mission).version, reason='Stale reader fixture')
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.intents.current(self.mission, 'Founder', saved['operation_id'])
            self.assertTrue(self.storage.db.in_transaction)
        finally: self.storage.db.rollback()
        with self.assertRaisesRegex(InstallationConflict, 'mission_is_fenced'):
            self.intents.current(self.mission, 'Founder', saved['operation_id'])


if __name__=='__main__': unittest.main()
