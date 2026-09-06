from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

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


if __name__=='__main__': unittest.main()
