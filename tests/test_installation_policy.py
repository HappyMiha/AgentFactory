from dataclasses import replace
from datetime import timedelta
import unittest
import uuid
from unittest.mock import patch

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


class InstallationLivePolicyTests(unittest.TestCase):
    def setUp(self):
        from test_installation_journal import InstallationJournalTests
        from test_live_stages import LiveStageExecutionTests
        self.fixture = InstallationJournalTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.storage = self.fixture.storage
        with self.fixture.archive.stage(self.fixture.catalog) as staged:
            self.publication = self.fixture.prepare(staged)
        live = LiveStageExecutionTests()
        live.workspace = self.fixture.root; live.storage = self.storage; live.counter = 0
        live.project_id = AutonomousMissionService(self.storage).get(self.fixture.mission).project_id
        create_task = self.storage.create_task
        create_worktree = self.storage.create_managed_worktree
        # The synthetic existing live-stage fixture must declare tool_use and
        # assign the actual installation workspace as its managed worktree.
        with patch.object(self.storage, 'create_task', side_effect=lambda item:
                          create_task(replace(item, permissions=['read_project', 'tool_use', 'worktree_write']))), \
             patch.object(self.storage, 'create_managed_worktree', side_effect=lambda **kw:
                          create_worktree(**(kw | {'path': str(self.fixture.root)}))):
            self.run, _, self.launch = live.fixture()
        self.binding = InstallationPolicyBinding(self.fixture.intents)

    def request(self, **changes):
        return self.binding.publication_request(self.fixture.mission, 'Founder',
            **({'publication_id': self.publication['operation_id'], 'launch': self.launch,
                'runtime_id': 'direct-cli'} | changes))

    def test_publication_uses_real_stage_and_database_scope_without_approval(self):
        request = self.request()
        self.assertEqual(request.effect_digest, self.publication['request_digest'])
        self.assertEqual((request.run_id, request.stage_id), (self.run, 'implementation'))
        self.assertEqual(request.worktree_id, str(self.launch.binding.worktree_id))
        self.assertEqual(request.permissions, ('read_project', 'tool_use', 'worktree_write'))
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM scoped_execution_approvals').fetchone()[0], 0)
        self.assertEqual(self.fixture.publications.view(self.fixture.mission, 'Founder',
            self.publication['operation_id'])['state'], 'reserved')

    def test_real_stage_approval_binds_package_and_consumes_only_once(self):
        from agent_factory.live_stages import LiveStageExecution
        request = self.request()
        gate = LiveStageExecution(self.storage).request_approval(request, requested_by='Founder')
        self.storage.decide_scoped_approval(gate.approval_id, 'approved', actor='Founder')
        self.assertEqual(self.request(), request)  # Still valid while waiting for approval consumption.
        scope = {'approval_id': gate.approval_id, 'assignment_id': self.launch.assignment_id,
                 'attempt_id': self.launch.binding.attempt_id}
        policy = ControlPlanePolicy(self.storage)
        with self.assertRaises(PermissionError):
            policy.authorize(replace(request, effect_digest='b'*64), **scope)
        self.assertEqual(policy.authorize(request, **scope).outcome, PolicyOutcome.ALLOW)
        with self.assertRaisesRegex(InstallationConflict, 'already_approved'): self.request()
        row = self.storage.db.execute('SELECT * FROM stage_approval_consumptions').fetchone()
        self.assertEqual(row['request_digest'], request.digest)
        self.assertEqual(row['run_id'], self.run)

    def test_prebound_effect_must_match_before_current_intent_reservation(self):
        expected = self.request()
        matching = replace(self.launch, effect_digest=self.publication['request_digest'])
        self.assertEqual(self.request(launch=matching), expected)
        before = self.storage.db.total_changes
        with patch.object(self.binding, 'request', side_effect=AssertionError('Must reject before reserving intent')):
            with self.assertRaisesRegex(InstallationConflict, 'publication_launch_effect_mismatch'):
                self.request(launch=replace(self.launch, effect_digest='b'*64))
        self.assertEqual(self.storage.db.total_changes, before)
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM scoped_execution_approvals').fetchone()[0], 0)
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM worker_sessions').fetchone()[0], 0)

    def test_wrong_live_scope_or_permissions_cannot_prepare_effect_request(self):
        variants = [replace(self.launch, binding=replace(self.launch.binding, run_id=self.run+999)),
                    replace(self.launch, binding=replace(self.launch.binding, stage_id='missing')),
                    replace(self.launch, binding=replace(self.launch.binding, worktree_id=99999)),
                    replace(self.launch, binding=replace(self.launch.binding, attempt_id=99999)),
                    replace(self.launch, item=replace(self.launch.item, project_id=99999)),
                    replace(self.launch, item=replace(self.launch.item, permissions=['worktree_write']))]
        for launch in variants:
            with self.subTest(launch=launch.binding), self.assertRaises(InstallationConflict):
                self.request(launch=launch)
        with self.assertRaises(InstallationConflict): self.request(runtime_id='different-runtime')
        with self.assertRaises(ValueError): self.request(launch=replace(self.launch, assignment_id=True))

    def test_installation_root_must_match_the_managed_worktree(self):
        self.fixture.review.workspace = self.fixture.root/'outside-worktree'
        with self.assertRaisesRegex(InstallationConflict, 'outside_worktree'): self.request()

    def test_preparation_does_not_commit_an_enclosing_caller_transaction(self):
        self.storage.db.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaisesRegex(ValueError, 'outside a caller transaction'): self.request()
            self.assertTrue(self.storage.db.in_transaction)
            self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM scoped_execution_approvals').fetchone()[0], 0)
        finally:
            self.storage.db.rollback()

    def test_stale_lease_expired_intent_and_unknown_publication_deny_preparation(self):
        with self.assertRaises(PermissionError):
            self.request(launch=replace(self.launch, fencing_token=self.launch.fencing_token+1))
        self.fixture.now += timedelta(hours=1)
        with self.assertRaisesRegex(InstallationConflict, 'review_expired'): self.request()
        self.fixture.now -= timedelta(hours=1)
        self.fixture.intents.journal.mark_unknown(self.publication['operation_id'], event_key='unknown', evidence={})
        with self.assertRaisesRegex(InstallationConflict, 'publication_not_reserved'): self.request()




class InstallationAdmittedPolicyTests(unittest.TestCase):
    def setUp(self):
        from test_installation_journal import InstallationJournalTests
        self.fixture = InstallationJournalTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.storage = self.fixture.storage
        with self.fixture.archive.stage(self.fixture.catalog) as staged:
            self.publication = self.fixture.prepare(staged)
        self.binding = InstallationPolicyBinding(self.fixture.intents)

    def request(self, *, launch):
        return self.binding.publication_request(self.fixture.mission, 'Founder',
            publication_id=self.publication['operation_id'], launch=launch, runtime_id='direct-cli')

    def admitted_publication_launch(self):
        from agent_factory.worker_admission import WorkerAdmissionService
        from test_worker_admission_runtime import WorkerAdmissionRuntimeTests
        admitted = WorkerAdmissionRuntimeTests()
        admitted.storage = self.storage; admitted.root = self.fixture.root
        admitted.counter = 0; admitted.qualifications = {}
        admitted.service = WorkerAdmissionService(self.storage)
        task = admitted.task
        create_task = self.storage.create_task
        create_worktree = self.storage.create_managed_worktree
        project = AutonomousMissionService(self.storage).get(self.fixture.mission).project_id
        # Synthetic qualification and driver only. The saved publication digest
        # exists before admission; the managed path belongs to its actual project.
        with patch.object(admitted, 'task', side_effect=lambda **kw: task(**(kw | {'project_id': project}))), \
             patch.object(self.storage, 'create_task', side_effect=lambda item:
                          create_task(replace(item, permissions=['read_project', 'tool_use', 'worktree_write']))), \
             patch.object(self.storage, 'create_managed_worktree', side_effect=lambda **kw:
                          create_worktree(**(kw | {'path': str(self.fixture.root)}))):
            return admitted.launch_fixture(effect_digest=self.publication['request_digest'])

    def test_saved_publication_reaches_admitted_runtime_once_without_publishing(self):
        import json
        from agent_factory.worker_runtime import DirectCLIWorkerRuntime
        from test_worker_admission_runtime import AdmissionDriver
        admission, receipt, launch = self.admitted_publication_launch()
        request = self.request(launch=launch)
        self.assertEqual(request.effect_digest, admission.effect_digest)
        self.assertEqual(request.digest, launch.approval.request_digest)
        driver = AdmissionDriver()
        runtime = DirectCLIWorkerRuntime(self.storage, driver)
        session = runtime.start(launch)
        self.assertEqual(runtime.start(launch).id, session.id)
        self.assertEqual(len(driver.starts), 1)
        stored = json.loads(self.storage.runtime_session(session.id)['request_json'])
        self.assertEqual(stored['effect_digest'], self.publication['request_digest'])
        row = self.storage.db.execute('SELECT runtime_session_id FROM worker_admissions WHERE id=?',
                                      (receipt.admission_id,)).fetchone()
        self.assertEqual(row[0], session.id)
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM stage_approval_consumptions').fetchone()[0], 1)
        self.assertEqual(self.fixture.publications.view(self.fixture.mission, 'Founder',
            self.publication['operation_id'])['state'], 'reserved')
        self.assertFalse((self.fixture.root/self.publication['relative_target']).exists())
        with self.assertRaisesRegex(InstallationConflict, 'already_approved'):
            self.request(launch=launch)


if __name__=='__main__': unittest.main()
