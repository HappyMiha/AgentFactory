"""Actual Git/Python/filesystem probes plus explicitly synthetic model observations."""
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from agent_factory.coding_delivery import AutonomousCodingDeliveryService
from agent_factory.environment_readiness import EnvironmentReadiness, EnvironmentNotReady, Observation
from agent_factory.web import create_app
from tests.test_autonomous_child_orchestration import AutonomousChildFixture
from tests.test_autonomous_preapproval_workflow import run_git


class EnvironmentReadinessTests(AutonomousChildFixture, unittest.TestCase):
    def setUp(self):
        self.create_fixture()
        self.addCleanup(self.close_fixture)

    def approve(self):
        self.approved = self.approve_fixture(readiness=False)
        self.ident = self.approved.approval.id
        self.readiness = EnvironmentReadiness(self.storage)
        return self.approved

    def profile(self, **changes):
        path = self.repository / 'agentfactory.environment.json'
        document = json.loads(path.read_text()); document.update(changes)
        path.write_text(json.dumps(document))
        run_git(self.repository, 'add', path.name)
        run_git(self.repository, 'commit', '-m', 'Selected environment requirements')
        self.base_commit = run_git(self.repository, 'rev-parse', 'HEAD')

    def enter(self):
        return AutonomousCodingDeliveryService(self.storage, self.capabilities).enter_development(
            self.mission.id, expected_mission_version=self.approved.approval.result_mission_version,
            command_id='readiness-enter')

    def test_missing_checks_do_not_advance_any_environment_phase(self):
        self.approve()
        with self.assertRaisesRegex(EnvironmentNotReady, 'missing'):
            self.enter()
        self.assertEqual(self.missions.get(self.mission.id).phase.value, 'APPROVED')

    def test_empty_workspace_without_engine_cannot_return_ready(self):
        self.profile(tools=['godot'])
        self.approve()
        with patch('agent_factory.environment_readiness.shutil.which', return_value=None):
            report = self.readiness.assess(self.ident)
        godot = next(c for c in report['checks'] if c['key'] == 'tool:godot')
        self.assertFalse(godot['installed']); self.assertIn('Install', godot['next_action'])
        self.assertEqual(report['status'], 'blocked')
        with self.assertRaises(EnvironmentNotReady): self.enter()

    def test_live_tools_do_not_qualify_a_model_by_implication(self):
        self.approve(); report = self.readiness.assess(self.ident)
        self.assertTrue(all(c['ready'] for c in report['checks'] if not c['key'].startswith('model:')))
        self.assertTrue(all(not c['qualified'] for c in report['checks'] if c['key'].startswith('model:')))
        self.assertEqual(report['status'], 'blocked')

    def test_current_complete_report_permits_entry_and_survives_reopen(self):
        self.approve(); report = self.record_fixture_readiness(self.approved)
        self.assertEqual(report['status'], 'ready')
        self.assertEqual(EnvironmentReadiness(self.storage).require_ready(self.ident)['id'], report['id'])
        self.assertEqual(self.enter().phase.value, 'DEVELOPMENT')

    def test_other_plan_evidence_is_rejected_even_with_a_valid_checksum(self):
        from agent_factory.environment_readiness import digest
        self.approve()
        report = self.record_fixture_readiness(self.approved)
        report.pop('id')
        report['binding']['revision_id'] += 1
        report['binding']['revision_digest'] = 'f' * 64
        # Simulate a trusted producer storing an otherwise valid receipt for the
        # wrong plan. Immutability/checksums alone must not authorize its use.
        with self.storage.db:
            self.storage.db.execute('INSERT INTO environment_readiness_reports '
                '(approval_id,report_json,report_digest,created_at) VALUES(?,?,?,?)',
                (self.ident, json.dumps(report), digest(report), report['checked_at']))
        with self.assertRaisesRegex(EnvironmentNotReady, 'different plan'):
            self.enter()
        self.assertEqual(self.missions.get(self.mission.id).phase.value, 'APPROVED')

    def test_expired_and_future_reports_deny_entry(self):
        self.approve(); report = self.record_fixture_readiness(self.approved)
        checked = datetime.fromisoformat(report['checked_at'])
        for moment in (checked - timedelta(seconds=1), checked + timedelta(seconds=301)):
            with self.subTest(moment=moment):
                with self.assertRaisesRegex(EnvironmentNotReady, 'expired'):
                    EnvironmentReadiness(self.storage, clock=lambda: moment).require_ready(self.ident)

    def test_latest_failed_probe_invalidates_previous_pass(self):
        self.approve(); self.record_fixture_readiness(self.approved)
        self.readiness.assess(self.ident)
        with self.assertRaises(EnvironmentNotReady): self.enter()
        self.assertEqual(self.missions.get(self.mission.id).phase.value, 'APPROVED')

    def test_rerun_rechecks_real_tool_state_and_repairs_failure(self):
        self.approve()
        with patch('agent_factory.environment_readiness.shutil.which', return_value=None):
            failed = self.record_fixture_readiness(self.approved)
        self.assertEqual(failed['status'], 'blocked')
        passed = self.record_fixture_readiness(self.approved)
        self.assertGreater(passed['id'], failed['id']); self.assertEqual(passed['status'], 'ready')

    def test_simulation_and_wrong_model_cannot_qualify_selected_route(self):
        self.approve()
        _, requirements = self.readiness.context(self.ident)
        key = next(k for k in requirements if k.startswith('model:'))
        requirement = requirements[key]
        for observation in (
            Observation(True, True, True, 'simulation', identity=requirement['model'], provider_id='local'),
            Observation(True, True, True, 'live', identity='other:model', provider_id='local'),
            Observation(True, True, True, 'live', identity=requirement['model'], provider_id='unselected'),
        ):
            with self.subTest(observation=observation):
                self.readiness.probes[key] = lambda r: observation
                report = self.readiness.assess(self.ident)
                self.assertFalse(next(c for c in report['checks'] if c['key'] == key)['ready'])

    def test_unselected_provider_is_never_probed(self):
        self.approve()
        def unrelated(_): raise AssertionError('Unselected provider was probed')
        self.readiness.probes['model:unselected'] = unrelated
        report = self.readiness.assess(self.ident)
        self.assertNotIn('model:unselected', [c['key'] for c in report['checks']])

    def test_unknown_selected_service_is_actionable_blocker(self):
        self.profile(services=['selected-runtime'])
        self.approve(); report = self.record_fixture_readiness(self.approved)
        row = next(c for c in report['checks'] if c['key'] == 'service:selected-runtime')
        self.assertFalse(row['ready']); self.assertIn('verifier', row['next_action'])

    def test_probe_exception_is_not_silently_passed(self):
        self.approve()
        def broken(_): raise OSError('private diagnostic')
        self.readiness.probes['workspace'] = broken
        report = self.readiness.assess(self.ident)
        self.assertFalse(report['checks'][0]['ready'])
        self.assertNotIn('private diagnostic', json.dumps(report))

    def test_upgrade_from_72_preserves_data_without_manufacturing_ready_evidence(self):
        from contextlib import closing
        import agent_factory.storage as module
        path = self.workspace / 'before-readiness.db'
        with patch.object(module, 'MIGRATIONS', tuple(m for m in module.MIGRATIONS if m[0] <= 72)):
            with closing(module.SQLiteStorage(path)) as previous:
                ident = previous.create_project('Preserved project', 'Before readiness reports')
                self.assertIsNone(previous.db.execute("SELECT name FROM sqlite_master WHERE name='environment_readiness_reports'").fetchone())
        with closing(module.SQLiteStorage(path)) as upgraded:
            self.assertEqual(upgraded.db.execute('SELECT name FROM projects WHERE id=?', (ident,)).fetchone()[0], 'Preserved project')
            self.assertEqual(upgraded.db.execute('SELECT COUNT(*) FROM environment_readiness_reports').fetchone()[0], 0)

    def test_reports_are_immutable(self):
        self.approve(); report = self.record_fixture_readiness(self.approved)
        for statement in ('UPDATE environment_readiness_reports SET report_json=report_json',
                          'DELETE FROM environment_readiness_reports'):
            with self.assertRaises(sqlite3.IntegrityError): self.storage.db.execute(statement)
        self.storage.db.rollback()
        self.assertEqual(self.readiness.require_ready(self.ident)['id'], report['id'])

    def test_working_tree_profile_cannot_weaken_approved_requirements(self):
        self.profile(tools=['godot'])
        self.approve()
        (self.repository / 'agentfactory.environment.json').write_text('{}')
        _, requirements = self.readiness.context(self.ident)
        self.assertIn('tool:godot', requirements)

    def test_wrong_branch_invalidates_report(self):
        self.approve(); self.record_fixture_readiness(self.approved)
        run_git(self.repository, 'checkout', '-b', 'unapproved-branch')
        with self.assertRaisesRegex(EnvironmentNotReady, 'branch'): self.readiness.require_ready(self.ident)

    def test_missing_approved_profile_blocks_even_if_working_copy_has_one(self):
        run_git(self.repository, 'rm', 'agentfactory.environment.json')
        run_git(self.repository, 'commit', '-m', 'No approved profile')
        self.base_commit = run_git(self.repository, 'rev-parse', 'HEAD')
        self.approve()
        (self.repository / 'agentfactory.environment.json').write_text('{"tools":["python"]}')
        with self.assertRaisesRegex(EnvironmentNotReady, 'manifest'): self.readiness.assess(self.ident)

    def test_api_reports_missing_failed_and_rechecked_states(self):
        self.approve()
        with TestClient(create_app(self.repository, self.database), base_url='http://localhost') as client:
            url = f'/api/autonomous-missions/{self.mission.id}/environment'
            response = client.get(url); self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'blocked')
            response = client.post(url + '/check')
            self.assertEqual(response.status_code, 200); self.assertEqual(response.json()['status'], 'blocked')
            self.assertTrue(response.json()['checks'])
            self.assertEqual(client.get(url).json()['id'], response.json()['id'])
