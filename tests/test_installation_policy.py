from dataclasses import replace
from datetime import timedelta
import unittest
import uuid

from agent_factory.autonomous_mission import AutonomousMissionService
from agent_factory.installation_policy import InstallationPolicyBinding
from agent_factory.installation_review import InstallationConflict
from agent_factory.models import WorkItem
from agent_factory.policy import ControlPlanePolicy, PolicyOutcome
import test_installation_intent as fixture


class InstallationPolicyTests(unittest.TestCase):
    review_for=fixture.InstallationIntentTests.review_for
    approve=fixture.InstallationIntentTests.approve
    reserve=fixture.InstallationIntentTests.reserve

    def setUp(self):
        fixture.InstallationIntentTests.setUp(self)
        self.approve(); self.intent=self.reserve()
        project=AutonomousMissionService(self.storage).get(self.mission).project_id
        self.task=self.storage.create_task(WorkItem('Setup fixture','No execution',project))
        self.binding=InstallationPolicyBinding(self.intents)

    def request(self, **changes):
        return self.binding.request(self.mission,'Founder',**({'operation_id':self.intent['operation_id'],
            'task_id':self.task,'worker_id':'fixture-host','runtime_id':'fixture-local',
            'worktree_id':'fixture-worktree'} | changes))

    def grant(self, request):
        approval=self.storage.request_scoped_approval(request=request.canonical(),requested_by='Founder')
        self.storage.decide_scoped_approval(approval,'approved',actor='Founder')
        return approval

    def test_request_is_stable_exact_and_does_not_grant_or_start(self):
        request=self.request()
        self.assertEqual(request,self.request())
        self.assertIn(self.intent['request_digest'],request.stage_id)
        self.assertIn(self.intent['operation_identity'],request.stage_id)
        self.assertIsNone(request.run_id)
        self.assertEqual(request.permissions,('tool_use','worktree_write'))
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM scoped_execution_approvals').fetchone()[0],0)
        self.assertEqual(self.intents.view(self.mission,'Founder',self.intent['operation_id'])['state'],'reserved')
        self.assertEqual(ControlPlanePolicy(self.storage).evaluate(request).outcome,PolicyOutcome.REQUIRE_APPROVAL)

    def test_existing_policy_approval_is_exact_and_one_use(self):
        request=self.request(); approval=self.grant(request); policy=ControlPlanePolicy(self.storage)
        with self.assertRaises((ValueError,PermissionError)):
            policy.authorize(replace(request,worktree_id='different'),approval_id=approval)
        self.assertEqual(policy.authorize(request,approval_id=approval).outcome,PolicyOutcome.ALLOW)
        with self.assertRaises((ValueError,PermissionError)):
            policy.authorize(request,approval_id=approval)

    def test_new_intent_cannot_consume_old_approval(self):
        old=self.request(); approval=self.grant(old)
        self.plan=self.review.prepare(self.mission,'Founder',command_id=str(uuid.uuid4()))
        self.approve(); new_intent=self.reserve()
        with self.assertRaisesRegex(InstallationConflict,'newer_plan_exists'): self.request()
        self.intent=new_intent; new=self.request()
        self.assertNotEqual(old.digest,new.digest)
        with self.assertRaises((ValueError,PermissionError)):
            ControlPlanePolicy(self.storage).authorize(new,approval_id=approval)

    def test_project_id_is_not_confused_with_autonomous_mission_id(self):
        from test_installation_review import create_game
        self.storage.create_project('Padding','Force IDs to differ')
        self.mission=create_game(self.storage)
        project=AutonomousMissionService(self.storage).get(self.mission).project_id
        self.assertNotEqual(project,self.mission)
        self.plan=self.review.prepare(self.mission,'Founder',command_id=str(uuid.uuid4()))
        self.approve(); self.intent=self.reserve()
        self.task=self.storage.create_task(WorkItem('Setup second','No execution',project))
        request=self.request(); self.assertEqual(request.mission_id,project)
        self.assertGreater(self.grant(request),0)

    def test_foreign_task_owner_and_invalid_host_identity_are_rejected(self):
        foreign=self.storage.create_project('Other','Other project')
        task=self.storage.create_task(WorkItem('Other task','Not this game',foreign))
        with self.assertRaises(InstallationConflict): self.request(task_id=task)
        with self.assertRaises(KeyError):
            self.binding.request(self.mission,'Other',operation_id=self.intent['operation_id'],task_id=self.task,
                worker_id='fixture-host',runtime_id='fixture-local',worktree_id='fixture-worktree')
        for changes in ({'worker_id':' '},{'runtime_id':'bad\nidentity'},{'worktree_id':None},{'task_id':True}):
            with self.assertRaises(ValueError): self.request(**changes)

    def test_expired_or_changed_host_cannot_prepare_new_policy_request(self):
        self.now += timedelta(hours=1)
        with self.assertRaisesRegex(InstallationConflict,'review_expired'): self.request()
        self.now -= timedelta(hours=1); self.host['workspace']='changed'
        with self.assertRaises(InstallationConflict): self.request()


if __name__=='__main__': unittest.main()
