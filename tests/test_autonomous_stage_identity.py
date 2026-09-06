"""AF-GC-041: real local stub invocations and denial before provider spawn."""
import asyncio
import json
import sqlite3
import sys
import unittest
from dataclasses import asdict, replace
from contextlib import closing
import agent_factory.storage as storage_module
from unittest.mock import patch

from temporalio.exceptions import ApplicationError
from agent_factory.autonomous_mission import AutonomousMissionConfiguration
from agent_factory.coding_delivery import AutonomousCodingDeliveryService
from agent_factory.models import Agent, WorkItem
from agent_factory.orchestration.temporal.activities import AgentFactoryActivities
from agent_factory.orchestration.temporal.models import AgentFactoryJobInput, StageActivityInput
from agent_factory.providers import CLIProvider
from agent_factory.registry import AgentRegistry
from agent_factory.runtime import AgentRuntime
from tests.test_autonomous_child_orchestration import AutonomousChildFixture


class AutonomousStageIdentityTests(AutonomousChildFixture, unittest.TestCase):
    def setUp(self):
        def configuration(*args, **kwargs):
            kwargs['role_models'] = {**kwargs.get('role_models', {}),
                'Implementation Worker': 'fixture:code', 'Validator': 'fixture:validation',
                'Proxy Reviewer': 'fixture:review', 'Policy Reviewer': 'fixture:policy'}
            return AutonomousMissionConfiguration(*args, **kwargs)
        with patch('tests.test_autonomous_preapproval_workflow.AutonomousMissionConfiguration', side_effect=configuration):
            self.create_fixture()
        self.addCleanup(self.close_fixture)
        approved = self.approve_fixture()
        self.delivery = AutonomousCodingDeliveryService(self.storage, self.capabilities)
        self.delivery.enter_development(self.mission.id,
            expected_mission_version=approved.approval.result_mission_version, command_id='enter-stage-test')
        self.child = self.delivery.prepare_job(self.mission.id, 'INFRA-001', execution_mode='live',
            workflow_definition_id='delivery', command_id='prepare-stage-test')
        self.delivery.authorize_job(self.child.id, command_id='authorize-stage-test')
        self.activities = AgentFactoryActivities(autonomous_provider_capabilities=self.capabilities)
        context, _, _ = self.activities._autonomous_job_context(self.delivery, self.child)
        self.job = AgentFactoryJobInput(job_id=self.child.job_id, run_id=self.child.run_id,
            project_id=self.mission.project_id, task_id=self.child.task_id, workspace=str(self.repository),
            database=str(self.database), mode='live', autonomous_context=context)
        self.agents = [Agent(ident, ident, role, True, 'local', 'Return fixture evidence',
                             ['execute_provider'], 'fixture:' + model)
            for ident, role, model in [('code', 'Implementation Worker', 'code'),
                ('validation', 'Validator', 'validation'), ('review', 'Proxy Reviewer', 'review'),
                ('policy', 'Policy Reviewer', 'policy')]]
        self.path = self.workspace / 'stage-agents.json'
        self.path.write_text(json.dumps({'agents': [asdict(a) for a in self.agents]}))
        self.registry = AgentRegistry(self.path)
        self.provider = CLIProvider('local', sys.executable,
            ['-c', 'import json,sys; print(json.dumps(sys.argv[1:]))', '{model}'],
            workspace=self.repository, allow_execution=True, model_namespace='fixture',
            model_ids=['code', 'validation', 'review', 'policy'], capabilities=self.capabilities['local'])
        self.runtime = AgentRuntime({'local': self.provider}, workspace=self.repository)

    def bind(self, agent, stage=None):
        return self.activities._autonomous_execution_agent(self.storage, self.job, agent,
            stage_key=stage or agent.id, effective_model=self.runtime.effective_model(agent))

    def artifact(self, stage='implementation', producer=None):
        producer = producer or self.agents[0]
        return self.storage.add_artifact(self.child.run_id, stage, producer.id, 'local', 'Fixture',
            producer={'agent_id': producer.id, 'effective_model': producer.model,
                      'model_identity_source': 'qualified_request'})

    def request(self, agent='review', pool=None):
        stage = {'id': 'validation', 'name': 'Review', 'agent': agent,
                 'artifact': 'review.json', 'contract': {'allowed_verdicts': ['PASS', 'FAIL']},
                 'reviewer_pool': pool or [agent], 'review_of': ['implementation']}
        return StageActivityInput(job=self.job, stage=stage, ordinal=2)

    def test_four_stages_keep_distinct_actual_invocation_identities(self):
        identities = []
        for template in self.agents:
            agent, authority = self.bind(template)
            result = self.runtime.run(agent, WorkItem('Fixture', 'Print model', self.mission.project_id,
                                      id=self.child.task_id), {}, authority, mode='live')
            self.assertTrue(result.ok, result.error)
            self.assertEqual(json.loads(result.content), [template.id])
            self.assertEqual(agent.id, template.id)
            self.assertEqual(agent.role, template.role)
            self.assertEqual(result.metadata['effective_model'], template.model)
            self.assertEqual(authority.agent_id, template.id)
            self.assertEqual(authority.permissions, ('execute_provider',))
            identities.append(result.metadata['effective_model'])
        self.assertEqual(len(set(identities)), 4)
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM autonomous_child_stage_assignments').fetchone()[0], 4)

    def test_replay_and_worker_replacement_retain_one_frozen_assignment(self):
        first, _ = self.bind(self.agents[0])
        binding = self.delivery.stage_assignment(self.child.id, 'code')
        self.activities = AgentFactoryActivities(autonomous_provider_capabilities=self.capabilities)
        again, _ = self.bind(self.agents[0])
        self.assertEqual(first, again)
        self.assertEqual(binding, self.delivery.stage_assignment(self.child.id, 'code'))
        with self.assertRaisesRegex(PermissionError, 'Persisted stage assignment changed'):
            self.bind(replace(self.agents[0], instructions='Different instructions'))

    def test_replay_does_not_expand_stage_permissions_with_parent_permissions(self):
        agent, _ = self.bind(self.agents[0])
        self.assertEqual(agent.permissions, ['execute_provider'])
        with self.assertRaises(PermissionError):
            self.bind(replace(self.agents[0], permissions=['execute_provider', 'read_secrets']))

    def test_revoked_parent_authority_denies_a_persisted_assignment(self):
        self.bind(self.agents[0])
        self.delivery.authorizations.revoke_execution_authority(self.child.authorization_id,
            actor='Founder', command_id='revoke-stage-fixture', reason='Fixture revocation')
        with self.assertRaisesRegex(PermissionError, 'Stage authority denied'):
            self.bind(self.agents[0])

    def test_binding_cannot_be_updated_or_deleted(self):
        self.bind(self.agents[0])
        for sql in ['UPDATE autonomous_child_stage_assignments SET effective_model=\'changed\'',
                    'DELETE FROM autonomous_child_stage_assignments']:
            with self.assertRaises(sqlite3.IntegrityError):
                with self.storage.db: self.storage.db.execute(sql)

    def test_migration_from_71_preserves_existing_artifact_identity(self):
        path = self.workspace / 'legacy.db'
        with patch.object(storage_module, 'MIGRATIONS', tuple(m for m in storage_module.MIGRATIONS if m[0] <= 71)):
            with closing(storage_module.SQLiteStorage(path)) as legacy:
                project = legacy.create_project('Legacy', 'Before stage assignments')
                task = legacy.create_task(WorkItem('Existing', 'Keep evidence', project))
                run = legacy.start_run(project, task, 'fixture')
                artifact = legacy.add_artifact(run, 'implementation', 'legacy-agent', 'local', 'Keep this')
        with closing(storage_module.SQLiteStorage(path)) as upgraded:
            row = upgraded.db.execute('SELECT * FROM artifacts WHERE id=?', (artifact,)).fetchone()
            self.assertEqual(row['content'], 'Keep this')
            self.assertEqual(row['run_id'], run)
            self.assertEqual(upgraded.db.execute('SELECT COUNT(*) FROM autonomous_child_stage_assignments').fetchone()[0], 0)

    def test_database_rejects_assignment_with_unrelated_decision_identity(self):
        self.bind(self.agents[0])
        binding = self.delivery.stage_assignment(self.child.id, 'code')
        changed = {**binding['agent'], 'role': 'Unapproved Reviewer'}
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'scope is invalid'):
            with self.storage.db:
                self.storage.db.execute("""INSERT INTO autonomous_child_stage_assignments(
                    child_job_id,stage_key,decision_id,agent_json,effective_model,binding_digest,created_at
                    ) VALUES(?,?,?,?,?,?,?)""", (self.child.id, 'forged', binding['decision_id'],
                    json.dumps(changed), binding['effective_model'], binding['binding_digest'], binding['created_at']))

    def test_mismatched_parent_scope_is_denied(self):
        original = self.job.autonomous_context
        self.job.autonomous_context = replace(original, logical_attempt=original.logical_attempt + 1)
        with self.assertRaisesRegex(PermissionError, 'immutable persisted scope'):
            self.bind(self.agents[0])

    def test_effective_identity_change_on_replay_is_denied(self):
        self.bind(self.agents[0])
        with self.assertRaisesRegex(PermissionError, 'Persisted stage assignment changed'):
            self.activities._autonomous_execution_agent(self.storage, self.job, self.agents[0],
                stage_key='code', effective_model='fixture:review')

    def test_same_model_reviewer_waits_for_operator_without_spawn(self):
        same = replace(self.agents[2], model=self.agents[0].model)
        self.registry.replace(same)
        self.artifact()
        with patch('agent_factory.orchestration.temporal.activities.AgentRegistry', return_value=self.registry), \
             patch('agent_factory.orchestration.temporal.activities.AgentRuntime', return_value=self.runtime), \
             patch.object(self.provider.supervisor, 'spawn') as spawn, \
             patch.object(self.activities, '_correlation', return_value='fixture'):
            with self.assertRaisesRegex(ApplicationError, 'operator decision') as error:
                asyncio.run(self.activities.execute_stage(self.request()))
            self.assertTrue(error.exception.non_retryable)
            spawn.assert_not_called()
        self.assertFalse(self.storage.db.execute("SELECT 1 FROM artifacts WHERE stage='validation'").fetchone())

    def test_role_model_mismatch_is_denied_by_actual_stage_before_spawn(self):
        bad = replace(self.agents[2], model='fixture:policy')
        self.registry.replace(bad)
        self.artifact()
        with patch('agent_factory.orchestration.temporal.activities.AgentRegistry', return_value=self.registry), \
             patch('agent_factory.orchestration.temporal.activities.AgentRuntime', return_value=self.runtime), \
             patch.object(self.provider.supervisor, 'spawn') as spawn, \
             patch.object(self.activities, '_correlation', return_value='fixture'):
            with self.assertRaisesRegex(ApplicationError, 'operator decision'):
                asyncio.run(self.activities.execute_stage(self.request()))
            spawn.assert_not_called()

    def test_replayed_reviewer_does_not_rotate_to_another_agent(self):
        other = replace(self.agents[2], id='other-review')
        self.registry.add(other)
        self.artifact()
        request = self.request(pool=['review', 'other-review'])
        with patch('agent_factory.orchestration.temporal.activities.AgentRuntime', return_value=self.runtime):
            selected = self.activities._stage_agent(self.storage, self.registry, request)
            self.bind(self.registry.get(selected.id), stage='validation')
            replay = self.activities._stage_agent(self.storage, self.registry, request)
        self.assertEqual(selected.id, replay.id)


if __name__ == '__main__':
    unittest.main()
