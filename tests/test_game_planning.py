"""Immutable manual game plans: no execution or source rewriting."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import tempfile
import unittest
import uuid
from agent_factory.storage import SQLiteStorage
from agent_factory.mission_intake import AutonomousMissionIntakeService
from agent_factory.game_planning import GamePlanning, PlanningConflict, template

class GamePlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.db'
        self.storage=SQLiteStorage(self.path);self.addCleanup(lambda:self.storage.close())
        self.original='  My huge multiplayer world with trading, islands and flying.\nKeep the ambition.  '
        self.result=AutonomousMissionIntakeService(self.storage).create_from_text(
            name='Islands',mission_owner='Founder',actor='Founder',specification=self.original,command_id=str(uuid.uuid4()))
        self.ident=self.result.mission.id;self.plans=GamePlanning(self.storage)
    def save(self,fields=None,**overrides):
        view=self.plans.view(self.ident,'Founder')
        args=dict(fields=fields or view['fields'],command_id=str(uuid.uuid4()),
                  expected_revision_id=view['latest_revision_id'] or 0,expected_source_digest=view['source_digest'])
        return self.plans.save(self.ident,'Founder',**(args|overrides))
    def test_edit_restart_revert_and_source_preservation_without_execution(self):
        before=self.plans.view(self.ident,'Founder');self.assertEqual(before['history'],[])
        one=self.save();two=self.save(one['fields']|{'goal':'Reach the blue island.'})
        three=self.save(one['fields'])
        self.assertEqual(len(three['history']),3)
        self.assertEqual(self.plans.view(self.ident,'Founder',one['revision_id'])['fields'],one['fields'])
        self.storage.close();self.storage=SQLiteStorage(self.path);self.plans=GamePlanning(self.storage)
        self.assertEqual(self.plans.view(self.ident,'Founder')['fields'],one['fields'])
        self.assertEqual(AutonomousMissionIntakeService(self.storage).current_source(self.ident).content,self.original)
        mission=self.storage.db.execute('SELECT * FROM autonomous_missions WHERE id=?',(self.ident,)).fetchone()
        self.assertEqual(mission['phase'],'DRAFT');self.assertIsNone(mission['active_execution_epoch_id'])
        self.assertIsNone(mission['active_backlog_revision_id'])
        for table in ('work_items','workflow_runs'):
            self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
        self.assertFalse(three['execution_ready']);self.assertFalse(three['ai_plan_accepted'])
    def test_replay_and_stale_editor(self):
        view=self.plans.view(self.ident,'Founder');cmd=str(uuid.uuid4())
        one=self.save(command_id=cmd)
        replay=self.save(command_id=cmd,expected_revision_id=0)
        self.assertEqual(one['revision_id'],replay['revision_id'])
        with self.assertRaises(ValueError):self.save(template()|{'goal':'different'},command_id=cmd,expected_revision_id=0)
        with self.assertRaises(PlanningConflict):self.save(expected_revision_id=0)
        with self.assertRaises(PlanningConflict):self.save(expected_source_digest='0'*64)
        self.assertEqual(len(self.plans.view(self.ident,'Founder')['history']),1)
    def test_edited_rules_are_authoritative_over_genre_suggestions(self):
        for genre in ('platformer','collector','puzzle'):
            with self.subTest(genre=genre):
                fields=template(genre)|{'controls':'Use voice commands only.',
                    'goal':'Reach the tower without collecting items.',
                    'lose_rule':'Falling respawns only the player; preserve all collected items and objective progress.'}
                plan=self.save(fields)
                criteria=' '.join(c for task in plan['tasks'] for c in task['acceptance_criteria'])
                for key in ('controls','goal','lose_rule'):self.assertIn(fields[key],criteria)
                for forbidden in ('resets the player and objective state','increments progress exactly once','all required tokens','Only legal tile moves','matches the displayed target','reset permits a second'):
                    self.assertNotIn(forbidden,criteria)

    def test_owner_and_version_validation(self):
        with self.assertRaises(KeyError):self.plans.view(self.ident,'Other')
        with self.assertRaises(KeyError):self.plans.save(self.ident,'Other',fields=template(),command_id=str(uuid.uuid4()),expected_revision_id=0,expected_source_digest=self.result.source.source_digest)
        for value in (None,True,33,{},'bad'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.save(expected_source_digest=value)
        for value in (True,-1,'1'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.save(expected_revision_id=value)
    def test_genres_have_game_specific_executable_tasks_and_bounded_questions(self):
        for genre,phrase in [('platformer','jump'),('collector','token'),('puzzle','tile')]:
            with self.subTest(genre=genre):
                plan=self.save(template(genre))
                self.assertEqual(len(plan['tasks']),5)
                self.assertIn(phrase,str(plan['tasks']).lower())
                for item in plan['tasks']:
                    self.assertTrue(item['source_references'][0].startswith('core-source:'))
                    for field in ('acceptance_criteria','validation_method','definition_of_done','expected_artifacts','required_components','required_infrastructure'):
                        self.assertTrue(item[field])
        plan=self.save(template()|{key:'' for key in ('goal','controls','lose_rule','first_playable')})
        self.assertEqual(len(plan['questions']),3);self.assertEqual(plan['unresolved_count'],4)
        self.assertFalse(plan['execution_ready'])
    def test_reviewable_fixtures_preserve_ambition_and_declare_genre_contracts(self):
        examples=json.loads((Path(__file__).resolve().parents[1]/'examples/game-planning-fixtures.json').read_text(encoding='utf-8'))['examples']
        self.assertEqual(len(examples),4)
        for example in examples:
            with self.subTest(example=example['name']):
                result=AutonomousMissionIntakeService(self.storage).create_from_text(name=example['name'],
                    mission_owner='Founder',actor='Founder',specification=example['source'],command_id=str(uuid.uuid4()))
                fields=template(example['genre'])|{key:example[key] for key in ('first_playable','deferred_scope')}
                view=self.plans.save(result.mission.id,'Founder',fields=fields,command_id=str(uuid.uuid4()),expected_revision_id=0,expected_source_digest=result.source.source_digest)
                self.assertEqual(view['source_text'],example['source'])
                self.assertEqual(view['fields']['first_playable'],example['first_playable'])
                self.assertEqual(len(view['tasks']),5);self.assertFalse(view['execution_ready'])
                self.assertTrue(all(result.source.source_digest in task['source_references'][0] for task in view['tasks']))

    def test_other_planning_workflow_and_non_draft_are_not_overwritten(self):
        from agent_factory.game_planning import proposal
        from agent_factory.backlog_revisions import BacklogRevisionService
        plan=proposal(template(),self.result.source);plan.source_metadata.clear()
        BacklogRevisionService(self.storage).create_revision(mission_id=self.ident,proposal=plan,
            origin='HUMAN',created_by='Founder',command_id=str(uuid.uuid4()),rationale='Existing independent workflow')
        with self.assertRaises(PlanningConflict):self.plans.view(self.ident,'Founder')
        with self.assertRaises(PlanningConflict):self.plans.save(self.ident,'Founder',fields=template(),command_id=str(uuid.uuid4()),expected_revision_id=1,expected_source_digest=self.result.source.source_digest)
        from agent_factory.autonomous_mission import AutonomousMissionService
        missions=AutonomousMissionService(self.storage)
        missions.transition_phase(self.ident,'SPECIFICATION_ANALYSIS',actor='Founder',
            command_id=str(uuid.uuid4()),expected_version=missions.get(self.ident).version,reason='Existing analysis workflow')
        with self.assertRaises(PlanningConflict):self.plans.save(self.ident,'Founder',fields=template(),command_id=str(uuid.uuid4()),expected_revision_id=1,expected_source_digest=self.result.source.source_digest)

    def test_source_update_invalidates_binding_and_preserves_old_revision(self):
        from agent_factory.autonomous_mission import AutonomousMissionService
        old=self.save();mission=AutonomousMissionService(self.storage).get(self.ident)
        source=AutonomousMissionIntakeService(self.storage).update_from_text(self.ident,
            specification='A revised ambition with flying islands.',actor='Founder',command_id=str(uuid.uuid4()),
            reason='Owner revises original requirements',expected_mission_version=mission.version,expected_source_version=1)
        view=self.plans.view(self.ident,'Founder')
        self.assertTrue(view['stale']);self.assertEqual(view['bound_source_version'],1)
        self.assertEqual(view['source_version'],2)
        with self.assertRaises(PlanningConflict):self.save(expected_source_digest=old['source_digest'])
        new=self.save();self.assertFalse(new['stale']);self.assertEqual(new['bound_source_version'],2)
        self.assertTrue(self.plans.view(self.ident,'Founder',old['revision_id'])['stale'])

    def test_two_writers_cannot_silently_replace_each_other(self):
        digest=self.result.source.source_digest
        def writer(goal):
            storage=SQLiteStorage(self.path)
            try:
                return GamePlanning(storage).save(self.ident,'Founder',fields=template()|{'goal':goal},command_id=str(uuid.uuid4()),expected_revision_id=0,expected_source_digest=digest)
            except PlanningConflict:return 'conflict'
            finally:storage.close()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(writer,['A','B']))
        self.assertEqual(results.count('conflict'),1)
        self.assertEqual(len(self.plans.view(self.ident,'Founder')['history']),1)

if __name__=='__main__':unittest.main()
