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
    def test_release_tags_are_distinct_per_service_and_attempt(self):
        core = {'id': 'core', 'service': 'lokvetia'}
        identity = {'id': 'identity', 'service': 'identity'}
        self.assertNotEqual(deploy.release_image(core, 'revision-first'), deploy.release_image(core, 'revision-second'))
        self.assertNotEqual(deploy.release_image(core, 'revision-first'), deploy.release_image(identity, 'revision-first'))

    def test_missing_manifest_can_be_archived_without_pausing_immutable_container(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'image.tar'
            calls = []
            def execute(args, **kwargs):
                calls.append(args)
                if len(calls) == 1:
                    raise deploy.DeployError('No such image: old-manifest')
                if args[1] == 'commit':
                    return 'sha256:recovery'
                archive.with_suffix('.partial').write_bytes(b'recovery-image')
                return ''
            with patch.object(deploy, 'command', side_effect=execute):
                deploy.archive_image('old-container', {'Image': 'old-manifest', 'HostConfig': {'ReadonlyRootfs': True}}, archive)
            self.assertEqual(archive.read_bytes(), b'recovery-image')
            self.assertIn('--pause=false', calls[1])
            self.assertEqual(deploy.read_json(archive.with_suffix('.json'))['source_container'], 'old-container')

    def test_mutable_container_is_not_snapshotted_during_live_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(deploy, 'command', side_effect=deploy.DeployError('No such image')) as execute:
                with self.assertRaises(deploy.DeployError):
                    deploy.archive_image('mutable', {'Image': 'missing', 'HostConfig': {'ReadonlyRootfs': False}}, Path(folder) / 'image.tar')
            self.assertEqual(execute.call_count, 1)

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


class ReleaseHistoryTests(unittest.TestCase):
    """Finished attempts stay visible after the next one starts."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.project = {'id': 'core', 'name': 'Lokvetia Core', 'service': 'lokvetia',
                        'repository': 'HappyMiha/Lokvetia-Core', 'host': 'test.lokvetia.com'}

    def controller(self):
        return deploy.Controller({'state_root': str(self.root), 'runtime_bundle': str(self.root),
                                  'projects': [self.project]})

    def history(self, controller):
        return controller.status['history'].get('core', [])

    def test_only_a_finished_attempt_is_remembered(self):
        controller = self.controller()
        controller.report(self.project, 'build')
        controller.report(self.project, 'activate')
        self.assertEqual(self.history(controller), [])
        controller.report(self.project, 'success', 'success', commit='a' * 40,
                          finished_at='2026-09-11T10:00:00+00:00')
        self.assertEqual(len(self.history(controller)), 1)
        self.assertEqual(self.history(controller)[0]['state'], 'success')

    def test_the_newest_attempt_is_listed_first(self):
        controller = self.controller()
        controller.report(self.project, 'failure', 'failure', commit='a' * 40,
                          finished_at='2026-09-11T10:00:00+00:00', error='first')
        controller.report(self.project, 'success', 'success', commit='b' * 40,
                          finished_at='2026-09-11T11:00:00+00:00')
        self.assertEqual([entry['commit'][:1] for entry in self.history(controller)], ['b', 'a'])

    def test_repeating_one_attempt_does_not_duplicate_its_entry(self):
        controller = self.controller()
        for _ in range(3):
            controller.report(self.project, 'failure', 'failure', commit='a' * 40,
                              finished_at='2026-09-11T10:00:00+00:00', error='same attempt')
        self.assertEqual(len(self.history(controller)), 1)

    def test_the_list_stays_bounded(self):
        controller = self.controller()
        for index in range(deploy.HISTORY_PER_PROJECT + 7):
            controller.report(self.project, 'success', 'success', commit=f'{index:040d}',
                              finished_at=f'2026-09-11T10:{index:02d}:00+00:00')
        self.assertEqual(len(self.history(controller)), deploy.HISTORY_PER_PROJECT)
        self.assertTrue(self.history(controller)[0]['commit'].endswith(str(
            deploy.HISTORY_PER_PROJECT + 6)))

    def test_a_long_error_is_truncated_before_publication(self):
        controller = self.controller()
        controller.report(self.project, 'failure', 'failure', commit='a' * 40,
                          finished_at='2026-09-11T10:00:00+00:00', error='x' * 9000)
        self.assertEqual(len(self.history(controller)[0]['error']), deploy.HISTORY_ERROR_LIMIT)

    def test_history_survives_a_controller_restart(self):
        controller = self.controller()
        controller.report(self.project, 'success', 'success', commit='a' * 40,
                          finished_at='2026-09-11T10:00:00+00:00')
        self.assertEqual(len(self.history(self.controller())), 1)

    def test_published_state_without_history_upgrades_in_place(self):
        public = self.root / 'public'
        public.mkdir(parents=True, exist_ok=True)
        deploy.atomic_json(public / 'status.json',
                           {'projects': {'core': {'phase': 'success'}}, 'updated_at': '2026-09-11T09:00:00+00:00'})
        controller = self.controller()
        self.assertEqual(controller.status['history'], {})
        controller.report(self.project, 'failure', 'failure', commit='a' * 40,
                          finished_at='2026-09-11T10:00:00+00:00', error='boom')
        published = deploy.read_json(public / 'status.json')
        self.assertEqual(published['history']['core'][0]['error'], 'boom')

    def test_a_rollback_result_is_carried_into_the_entry(self):
        controller = self.controller()
        controller.report(self.project, 'failure', 'failure', commit='a' * 40, rollback='success',
                          finished_at='2026-09-11T10:00:00+00:00', error='health check failed')
        self.assertEqual(self.history(controller)[0]['rollback'], 'success')


    def test_repeated_terminal_report_without_timestamp_keeps_one_entry(self):
        controller = self.controller()
        with patch.object(deploy, 'now', side_effect=[f'time-{i}' for i in range(20)]):
            for _ in range(3):
                controller.report(self.project, 'failure', 'failure', commit='a' * 40)
        self.assertEqual(len(self.history(controller)), 1)

    def test_two_attempts_of_one_revision_are_retained_even_in_the_same_second(self):
        controller = self.controller()
        for attempt in ('first', 'second'):
            controller.report(self.project, 'failure', 'failure', commit='a' * 40,
                              attempt_id=attempt, finished_at='same-second')
        self.assertEqual(len(self.history(controller)), 2)
