from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid

from agent_factory.game_planning import GamePlanning
from agent_factory.installation_plan import load_catalog
from agent_factory.installation_review import InstallationReview, InstallationConflict, observe_workspace
from agent_factory.mission_intake import AutonomousMissionIntakeService
from agent_factory.storage import SQLiteStorage, MIGRATIONS

NOW = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
HOST = {'platform':'windows-x86_64', 'free_bytes':20*1024**3, 'inventory':{}, 'host':'fixture-host', 'workspace':'fixture-workspace'}


def create_game(storage):
    mission = AutonomousMissionIntakeService(storage).create_from_text(
        name='Garden', mission_owner='Founder', actor='Founder', specification='Collect three tokens.', command_id=str(uuid.uuid4())).mission.id
    service = GamePlanning(storage)
    view = service.view(mission, 'Founder')
    service.save(mission, 'Founder', fields=view['fields'], command_id=str(uuid.uuid4()),
                 expected_revision_id=0, expected_source_digest=view['source_digest'])
    return mission


class InstallationReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.path = self.root/'state.db'
        self.storage = SQLiteStorage(self.path); self.addCleanup(self.storage.close)
        self.mission = create_game(self.storage)
        self.host = deepcopy(HOST); self.catalog = load_catalog(); self.now = NOW
        self.service = InstallationReview(self.storage,self.root,probe=lambda *_:deepcopy(self.host),
                                          catalog=lambda:deepcopy(self.catalog),clock=lambda:self.now)

    def prepare(self, **kw):
        return self.service.prepare(self.mission,'Founder',**({'command_id':str(uuid.uuid4())}|kw))

    def command(self, plan, **kw):
        return {'plan_id':plan['id'], 'digest':plan['digest'], 'decision':'approved', 'command_id':str(uuid.uuid4())}|kw

    def decide(self, command):
        return self.service.decide(self.mission,'Founder',**command)

    def test_approval_and_rejection_survive_reopen_without_execution(self):
        for decision in ('approved','rejected'):
            plan = self.prepare(); result = self.decide(self.command(plan,decision=decision))
            self.assertEqual(result['decision']['decision'],decision)
            self.assertFalse(result['execution_eligible'])
            other = SQLiteStorage(self.path)
            try:
                reopened = InstallationReview(other,self.root).view(self.mission,'Founder')
                self.assertEqual(reopened['review']['decision'],result['decision'])
            finally: other.close()
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM scoped_execution_approvals').fetchone()[0],0)

    def test_no_duplicate_on_lost_response_replay_and_changed_command_conflicts(self):
        key = str(uuid.uuid4()); plan = self.prepare(command_id=key)
        self.assertEqual(self.prepare(command_id=key),plan)
        with self.assertRaises(InstallationConflict):self.prepare(command_id=key,offline=True)
        command = self.command(plan); first = self.decide(command)
        self.now += timedelta(hours=1)
        self.assertEqual(self.decide(command),first)
        with self.assertRaises(InstallationConflict):self.decide(command|{'decision':'rejected'})
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM installation_review_decisions').fetchone()[0],1)

    def test_owner_digest_expiry_newer_snapshot_and_immutable_records(self):
        plan = self.prepare()
        with self.assertRaises(KeyError): self.service.view(self.mission,'Other')
        with self.assertRaises(KeyError): self.service.decide(self.mission,'Other',**self.command(plan))
        with self.assertRaises(InstallationConflict):self.decide(self.command(plan,digest='0'*64))
        self.prepare()
        with self.assertRaisesRegex(InstallationConflict,'newer'):self.decide(self.command(plan))
        current = self.prepare();self.now += timedelta(minutes=15)
        with self.assertRaisesRegex(InstallationConflict,'expired'):self.decide(self.command(current))
        with self.assertRaises(sqlite3.IntegrityError),self.storage.db:
            self.storage.db.execute("UPDATE installation_review_plans SET plan_digest=?",('0'*64,))

    def test_changes_to_source_scope_and_host_are_rechecked_before_decision(self):
        for mutate in (
            lambda:self.catalog['packages']['godot-editor'].update(url='https://example.com/changed.zip'),
            lambda:self.catalog['packages']['godot-editor'].update(sha256='1'*64),
            lambda:self.catalog['packages']['godot-editor'].update(requires_admin=True),
            lambda:self.host.update(workspace='different-workspace'),
            lambda:self.host.update(inventory={'other':{'version':'0','sha256':'0'*64,'target':'./tools','managed':False}}),
        ):
            self.host=deepcopy(HOST);self.catalog=load_catalog();plan=self.prepare();mutate()
            with self.assertRaisesRegex(InstallationConflict,'plan_changed'):self.decide(self.command(plan))
        self.host=deepcopy(HOST);self.catalog=load_catalog();plan=self.prepare()
        game=GamePlanning(self.storage);view=game.view(self.mission,'Founder')
        game.save(self.mission,'Founder',fields=view['fields']|{'goal':'Different goal.'},command_id=str(uuid.uuid4()),
                  expected_revision_id=view['revision_id'],expected_source_digest=view['source_digest'])
        with self.assertRaisesRegex(InstallationConflict,'plan_changed'):self.decide(self.command(plan))
        new_plan=self.prepare()
        self.assertIn('context.project',new_plan['changed_fields'])
        self.assertIsNone(new_plan['decision'])

    def test_space_is_rechecked_without_digest_churn_and_manual_can_be_rejected(self):
        plan=self.prepare();self.host['free_bytes']-=1024
        self.assertEqual(self.decide(self.command(plan))['decision']['decision'],'approved')
        plan=self.prepare();self.host['free_bytes']=1
        with self.assertRaisesRegex(InstallationConflict,'disk_space'):self.decide(self.command(plan))
        plan=self.prepare()
        with self.assertRaisesRegex(InstallationConflict,'manual'):self.decide(self.command(plan))
        self.assertEqual(self.decide(self.command(plan,decision='rejected'))['decision']['decision'],'rejected')

    def test_concurrent_incompatible_decisions_cannot_both_commit(self):
        plan=self.prepare();barrier=threading.Barrier(2)
        def decide(decision):
            storage=SQLiteStorage(self.path)
            try:
                service=InstallationReview(storage,self.root,probe=lambda *_:deepcopy(HOST),clock=lambda:NOW)
                barrier.wait(timeout=10)
                try:service.decide(self.mission,'Founder',**self.command(plan,decision=decision));return 'saved'
                except InstallationConflict:return 'conflict'
            finally:storage.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(decide,['approved','rejected'])),['saved','conflict'])

    def test_actual_workspace_probe_never_infers_existing_binary_provenance(self):
        target=self.root/self.catalog['packages']['godot-editor']['target'];target.mkdir(parents=True)
        observation=observe_workspace(self.root,self.catalog)
        self.assertEqual(observation['inventory']['godot-editor']['sha256'],'0'*64)
        self.assertGreater(observation['free_bytes'],0)
        target.rmdir();target.parent.rmdir();(self.root/'tools'/'godot-editor').write_text('not a directory')
        observation=observe_workspace(self.root,self.catalog)
        self.assertEqual(observation['inventory']['godot-editor']['target'],'tools/godot-editor')

    def test_v75_upgrade_preserves_existing_project_and_new_records_are_durable(self):
        path=self.root/'old.db';db=sqlite3.connect(path)
        db.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        for version,script in MIGRATIONS:
            if version>75:break
            db.executescript(script);db.execute('INSERT INTO schema_migrations(version) VALUES(?)',(version,))
        db.execute("INSERT INTO projects(name,description) VALUES('keep','original')");db.commit();db.close()
        migrated=SQLiteStorage(path)
        try:
            self.assertEqual(tuple(migrated.db.execute('SELECT name,description FROM projects').fetchone()),('keep','original'))
            self.assertEqual(migrated.db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],76)
        finally:migrated.close()
