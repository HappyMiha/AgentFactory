import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deploy_controller', ROOT / 'scripts' / 'autodeploy.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class DeploymentSafetyTests(unittest.TestCase):
    def test_schema_removal_or_change_is_blocked(self):
        self.assertFalse(deploy.compatible({'state.db': 'old'}, {}))
        self.assertFalse(deploy.compatible({'state.db': 'old'}, {'state.db': 'new'}))
        self.assertTrue(deploy.compatible({'state.db': 'old'}, {'state.db': 'old', 'new.db': 'new'}))

    def test_atomic_publication_does_not_touch_client_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            live = root / 'client.db'
            with closing(sqlite3.connect(live)) as db, db:
                db.execute('CREATE TABLE writes(value TEXT)')
                db.execute("INSERT INTO writes VALUES ('saved during release')")
            routes = root / 'routes.json'
            deploy.atomic_json(routes, {'test.lokvetia.com': {'container': 'new'}})
            controller = object.__new__(deploy.Controller)
            controller.routes_path = routes
            controller.rollback_route({'host': 'test.lokvetia.com'}, {'container': 'old'})
            self.assertEqual(deploy.read_json(routes)['test.lokvetia.com']['container'], 'old')
            with closing(sqlite3.connect(live)) as db:
                self.assertEqual(db.execute('SELECT value FROM writes').fetchone()[0], 'saved during release')

    def test_rollback_preserves_other_project_routing(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = object.__new__(deploy.Controller)
            controller.routes_path = Path(folder) / 'routes.json'
            deploy.atomic_json(controller.routes_path, {'core': {'container': 'new'}, 'cloud': {'container': 'cloud'}})
            controller.rollback_route({'host': 'core'}, {'container': 'old'})
            self.assertEqual(deploy.read_json(controller.routes_path)['cloud'], {'container': 'cloud'})

    def test_corrupt_state_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            path.write_text('{broken')
            with self.assertRaises(json.JSONDecodeError):
                deploy.read_json(path, {})

    def test_failed_ci_cannot_be_deployed(self):
        controller = object.__new__(deploy.Controller)
        with patch.object(deploy, 'command', return_value='[{"status":"completed","conclusion":"failure"}]'):
            self.assertFalse(controller.checks_passed({'repository': 'HappyMiha/Lokvetia-Core'}, 'a' * 40))

    def test_missing_ci_cannot_be_deployed(self):
        controller = object.__new__(deploy.Controller)
        with patch.object(deploy, 'command', return_value='[]'):
            self.assertFalse(controller.checks_passed({'repository': 'HappyMiha/Lokvetia-Core'}, 'a' * 40))

    def test_invalid_repository_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(deploy.DeployError):
                deploy.Controller({'state_root': folder, 'runtime_bundle': folder, 'projects': [{'repository': 'attacker/repo'}]})

    def test_online_sqlite_snapshot_includes_committed_wal_writes(self):
        snapshot_file = ROOT / 'ops' / 'test-deploy' / 'snapshot.py'
        if not snapshot_file.exists():
            self.skipTest('Snapshot implementation is owned by Core')
        module_spec = importlib.util.spec_from_file_location('snapshot', snapshot_file)
        snapshot = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(snapshot)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'live'; source.mkdir()
            db = sqlite3.connect(source / 'state.db')
            try:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE records(value TEXT)')
                db.execute("INSERT INTO records VALUES ('committed')"); db.commit()
                snapshot.backup(source, root / 'backup')
                with closing(sqlite3.connect(root / 'backup' / 'state.db')) as backup:
                    self.assertEqual(backup.execute('SELECT value FROM records').fetchone()[0], 'committed')
                self.assertFalse((root / 'backup' / 'state.db-wal').exists())
            finally:
                db.close()


if __name__ == '__main__':
    unittest.main()
