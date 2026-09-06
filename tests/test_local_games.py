"""Durability, owner isolation and navigation contracts; synthetic sources only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient
from agent_factory.application import AgentFactoryService
from agent_factory.local_games import LocalGames, GameConflict
from agent_factory.mission_intake import AutonomousMissionIntakeService
from agent_factory.storage import SQLiteStorage
from agent_factory.web import create_app


def command():
    return str(uuid.uuid4())


class LocalGamesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.path = self.root/'state.db'
        self.storage = SQLiteStorage(self.path); self.addCleanup(lambda: self.storage.close())
        self.games = LocalGames(self.storage, self.root)
        self.draft = self.games.create('Founder', command())

    def save(self, **changes):
        fields = {key: self.draft[key] for key in ('title', 'idea', 'model_key', 'view_step')}
        self.draft = self.games.save(self.draft['id'], 'Founder', command(), self.draft['revision'], **(fields | changes))
        return self.draft

    def prepared(self):
        return self.save(title='Garden', idea='Keep these exact words.\nNo purchases.',
                         model_key=self.games.model_choices()[0]['key'], view_step=2)

    def test_restart_preserves_exact_text_step_and_validation_error(self):
        self.save(view_step=4)
        self.assertEqual(self.draft['error_code'], 'idea_required')
        self.storage.close(); self.storage = SQLiteStorage(self.path)
        self.games = LocalGames(self.storage, self.root)
        self.assertEqual(self.games.detail(self.draft['id'], 'Founder'), self.draft)
        self.save(idea='  Незмінний текст\n☃  ', view_step=1)
        self.save(view_step=0)
        self.assertEqual(self.draft['idea'], '  Незмінний текст\n☃  ')

    def test_commands_replay_without_revisions_or_cross_owner_access(self):
        cmd = command(); one = self.games.create('Founder', cmd)
        self.assertEqual(self.games.create('Founder', cmd), one)
        fields = dict(title='Changed', idea='words', model_key='', view_step=1)
        cmd = command()
        saved = self.games.save(one['id'], 'Founder', cmd, 1, **fields)
        self.assertEqual(self.games.save(one['id'], 'Founder', cmd, 1, **fields), saved)
        with self.assertRaises(GameConflict):
            self.games.save(one['id'], 'Founder', cmd, 1, **(fields | {'idea':'other'}))
        with self.assertRaises(GameConflict):
            self.games.save(one['id'], 'Founder', command(), 1, **fields)
        for method in (self.games.detail, self.games.versions):
            with self.assertRaises(KeyError): method(one['id'], 'Other')
        self.assertEqual(self.games.list('Other')['total'], 0)

    def test_submit_creates_only_one_owner_bound_draft_and_freezes_source(self):
        self.prepared(); cmd = command(); revision = self.draft['revision']
        result = self.games.materialize(self.draft['id'], 'Founder', cmd, revision)
        self.assertEqual(self.games.materialize(self.draft['id'], 'Founder', cmd, revision), result)
        self.assertEqual(result['project']['phase'], 'DRAFT')
        self.assertIsNone(result['latest_working']); self.assertTrue(result['source_locked'])
        mission = self.storage.db.execute('SELECT * FROM autonomous_missions').fetchone()
        self.assertIsNone(mission['active_execution_epoch_id'])
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM work_items').fetchone()[0], 0)
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM workflow_runs').fetchone()[0], 0)
        with self.assertRaises(KeyError): self.games.project(result['mission_id'], 'Other')
        with self.assertRaises(GameConflict):
            self.games.save(self.draft['id'], 'Founder', command(), result['revision'], title='Other', idea='Other', model_key='', view_step=0)

    def test_ambiguous_intake_failure_recovers_after_restart_without_duplicate_mission(self):
        self.prepared(); original = AutonomousMissionIntakeService.create_from_text
        def interrupted(service, **kwargs):
            original(service, **kwargs)
            raise RuntimeError('synthetic interrupted response')
        with patch.object(AutonomousMissionIntakeService, 'create_from_text', interrupted):
            with self.assertRaises(RuntimeError):
                self.games.materialize(self.draft['id'], 'Founder', command(), self.draft['revision'])
        self.storage.close(); self.storage = SQLiteStorage(self.path); self.games = LocalGames(self.storage, self.root)
        saved = self.games.detail(self.draft['id'], 'Founder')
        self.assertEqual(saved['error_code'], 'intake_pending'); self.assertTrue(saved['source_locked'])
        result = self.games.materialize(saved['id'], 'Founder', command(), saved['revision'])
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM autonomous_missions').fetchone()[0], 1)
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM projects').fetchone()[0], 1)
        self.assertIsNotNone(result['mission_id'])

    def test_concurrent_submissions_use_one_core_intake(self):
        self.prepared(); draft = self.draft
        def submit(_):
            with closing(SQLiteStorage(self.path)) as storage:
                return LocalGames(storage, self.root).materialize(draft['id'], 'Founder', command(), draft['revision'])['mission_id']
        with ThreadPoolExecutor(2) as pool:
            ids = list(pool.map(submit, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM projects').fetchone()[0], 1)

    def test_history_over_200_is_searchable_paged_and_immutable(self):
        for index in range(205): self.save(idea=f'Original {index}', view_step=1)
        page = self.games.versions(self.draft['id'], 'Founder', offset=200, limit=20)
        self.assertEqual(page['total'], 206); self.assertEqual(len(page['items']), 6)
        found = self.games.versions(self.draft['id'], 'Founder', q='Original 204')
        self.assertEqual(found['total'], 1)
        self.assertEqual(self.games.versions(self.draft['id'], 'Founder', q='%')['total'], 0)
        for sql in ('UPDATE local_game_draft_versions SET revision=999', 'DELETE FROM local_game_draft_versions'):
            with self.assertRaises(sqlite3.IntegrityError): self.storage.db.execute(sql)
            self.storage.db.rollback()

    def test_invalid_unicode_or_configuration_never_submits(self):
        with self.assertRaises(ValueError): self.save(idea='\ud800')
        self.prepared()
        config = self.root/'config'; config.mkdir(); (config/'providers.json').write_text('{"providers": []}')
        with self.assertRaisesRegex(ValueError, 'model_unavailable'):
            self.games.materialize(self.draft['id'], 'Founder', command(), self.draft['revision'])
        self.assertFalse(self.games.detail(self.draft['id'], 'Founder')['source_locked'])
        (config/'providers.json').write_text('invalid')
        with self.assertRaisesRegex(ValueError, 'provider_catalog_unavailable'): self.games.model_choices()

    def test_upgrade_from_73_preserves_existing_project(self):
        from agent_factory import storage as module
        old = self.root/'old.db'
        with patch.object(module, 'MIGRATIONS', tuple(m for m in module.MIGRATIONS if m[0] <= 73)):
            with closing(SQLiteStorage(old)) as db: project = db.create_project('Existing', '')
        with closing(SQLiteStorage(old)) as db:
            self.assertEqual(db.db.execute('SELECT name FROM projects WHERE id=?', (project,)).fetchone()[0], 'Existing')
            game = LocalGames(db, self.root).create('Founder', command())
            self.assertEqual(game['revision'], 1)


class LocalGamesApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.path = self.root/'state.db'
        env = patch.dict(os.environ, {'AGENT_FACTORY_API_TOKEN':'synthetic-games-token', 'AGENT_FACTORY_API_ACTOR':'Founder', 'AGENT_FACTORY_API_ROLE':'operations_owner', 'AGENT_FACTORY_API_SCOPES':'read,write,approve,control'})
        env.start(); self.addCleanup(env.stop)
        self.client = TestClient(create_app(self.root, self.path), base_url='http://localhost');self.addCleanup(self.client.close)
        self.headers = {'Authorization':'Bearer synthetic-games-token'}

    def test_auth_confirmation_owner_and_bounded_inputs(self):
        response = self.client.post('/api/games/starts', json={'command_id':command()})
        self.assertEqual(response.status_code, 401); self.assertFalse(self.path.exists())
        draft = self.client.post('/api/games/starts', headers=self.headers, json={'command_id':command()}).json()
        url = '/api/games/starts/'+draft['id']
        fields = dict(command_id=command(), expected_revision=1, title='Garden', idea='Keep original', model_key='ollama/local:qwen2.5-coder:7b', view_step=2)
        self.assertEqual(self.client.post(url+'/save', headers=self.headers, json=fields|{'actor':'Other'}).status_code, 422)
        self.assertEqual(self.client.post(url+'/save', headers=self.headers, json=fields|{'expected_revision':True}).status_code, 422)
        saved = self.client.post(url+'/save', headers=self.headers, json=fields).json()
        submit = dict(command_id=command(), expected_revision=saved['revision'], confirmed=True)
        self.assertEqual(self.client.post(url+'/submit', headers=self.headers, json=submit).status_code, 400)
        result = self.client.post(url+'/submit', headers=self.headers|{'X-Agent-Factory-Confirm':'true'}, json=submit)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['project']['phase'], 'DRAFT')
        for query in ('limit=201', 'offset=-1', 'q='+'x'*201):
            self.assertEqual(self.client.get('/api/games/starts?'+query, headers=self.headers).status_code, 422)
        with patch.dict(os.environ, {'AGENT_FACTORY_API_ACTOR':'Other'}):
            self.assertEqual(self.client.get(url, headers=self.headers).status_code, 404)
        self.assertEqual(result.headers['cache-control'], 'no-store')

    def test_large_work_list_search_and_real_filter_values(self):
        with closing(SQLiteStorage(self.path)) as storage:
            service = AgentFactoryService(storage, workspace=self.root)
            project = service.create_project('Large').project_id
            for index in range(205):
                item = service.create_work_item(project_id=project, title=f'Task {index:03}', description='needle' if index==204 else 'ordinary', inputs={'priority':'HIGH'})
            service.claim_work_item(item.id, 'coding-worker-codex')
        page = self.client.get('/api/work-items?offset=200&limit=50', headers=self.headers).json()
        self.assertEqual(page['total'], 205); self.assertEqual(len(page['items']), 5)
        found = self.client.get('/api/work-items?q=NEEDLE', headers=self.headers).json()
        self.assertEqual(found['total'], 1); self.assertEqual(found['items'][0]['id'], item.id)
        filters = self.client.get('/api/work-item-filters', headers=self.headers).json()
        self.assertEqual(filters['priority'], ['high']); self.assertEqual(filters['kind'], ['task'])
        self.assertEqual(filters['assignee'], ['coding-worker-codex'])

    def test_home_and_operations_are_distinct_protected_shells(self):
        home = self.client.get('/', headers=self.headers)
        self.assertIn('Мої ігри', home.text); self.assertNotIn('work-filters', home.text)
        self.assertIn('work-filters', self.client.get('/operations', headers=self.headers).text)
        self.assertIn('Operator access token', self.client.get('/operations').text)
