"""Bind a setup intent to the existing exact policy request, without granting it."""
import os

from .game_planning import GamePlanning
from .installation_intent import InstallationIntents
from .installation_journal import InstallationPublicationJournal
from .installation_review import InstallationConflict
from .policy import PolicyRequest
from .worker_runtime import RuntimeLaunch


def _identity(value):
    if (not isinstance(value,str) or not 0<len(value)<=128 or not value.isprintable()
            or value!=value.strip()):
        raise ValueError('Invalid trusted execution identity')
    return value


class InstallationPolicyBinding:
    """Trusted host supplies actual task/worker/runtime/worktree identities.

    This is not a registration or worker-admission service. Callers must obtain
    those identities from current host configuration, never browser JSON. The
    returned PolicyRequest still requires the existing explicit policy approval.
    """
    def __init__(self, intents):
        if type(intents) is not InstallationIntents:
            raise ValueError('Expected trusted installation intents')
        self.intents=intents
        self.storage=intents.storage

    def publication_request(self, mission, actor, *, publication_id, launch, runtime_id):
        """Bind a saved publication to an existing live stage, without launching.

        Host supplies the real launch. This verifies its live database scope but
        does not replace runtime admission or approve/consume the returned request.
        The installer workspace must be the launch's managed worktree, because
        worktree_write cannot authorize writes to a different project directory.
        """
        if type(launch) is not RuntimeLaunch or launch.binding is None or not launch.mutable:
            raise ValueError('Expected an existing mutable live-stage launch')
        if self.storage.db.in_transaction:
            raise ValueError('Prepare publication scope outside a caller transaction')
        if any(type(value) is not int or value < 1 for value in (
                launch.assignment_id, launch.fencing_token, launch.binding.run_id,
                launch.binding.attempt_id, launch.binding.worktree_id)):
            raise ValueError('Expected actual live-stage identifiers')
        runtime_id = _identity(runtime_id)
        publications = InstallationPublicationJournal(self.intents)
        publication = publications.view(mission, actor, publication_id)
        if publication['state'] != 'reserved':
            raise InstallationConflict('publication_not_reserved')
        if launch.effect_digest is not None and launch.effect_digest != publication['request_digest']:
            raise InstallationConflict('publication_launch_effect_mismatch')
        binding = launch.binding
        # Reuse current plan/owner/host validation. This remains a snapshot;
        # runtime admission must repeat it at the eventual effect boundary.
        legacy = self.request(mission, actor, operation_id=publication['intent_id'],
            task_id=launch.item.id, worker_id=launch.agent.id, runtime_id=runtime_id,
            worktree_id=str(binding.worktree_id))
        with self.storage._policy_transaction():
            self.storage.assert_fenced_lease(launch.assignment_id, launch.fencing_token)
            assignment = self.storage.db.execute('SELECT * FROM assignments WHERE id=?',
                                                (launch.assignment_id,)).fetchone()
            attempt = self.storage.db.execute('SELECT * FROM attempts WHERE id=?', (binding.attempt_id,)).fetchone()
            stage = self.storage.db.execute('''SELECT s.status,r.task_id FROM workflow_stages s
                JOIN workflow_runs r ON r.id=s.run_id WHERE s.run_id=? AND s.stage_key=?''',
                (binding.run_id, binding.stage_id)).fetchone()
            worktree = self.storage.db.execute('SELECT * FROM worktrees WHERE id=?', (binding.worktree_id,)).fetchone()
            task = self.storage.get_task(launch.item.id)
            if (not assignment or assignment['task_id'] != task.id or assignment['agent_id'] != launch.agent.id
                    or assignment['runtime'] != runtime_id or task.project_id != legacy.mission_id
                    or launch.item.project_id != task.project_id
                    or not attempt or attempt['assignment_id'] != launch.assignment_id
                    or attempt['status'] not in {'claimed', 'running'}
                    or not stage or stage['task_id'] != task.id or stage['status'] not in {'running', 'waiting_approval'}
                    or not worktree or worktree['assignment_id'] != launch.assignment_id
                    or worktree['attempt_id'] != binding.attempt_id or worktree['status'] not in {'ready', 'dirty'}):
                raise InstallationConflict('publication_live_scope_mismatch')
            if self.storage.db.execute('SELECT 1 FROM stage_approval_consumptions WHERE attempt_id=?',
                                       (binding.attempt_id,)).fetchone():
                raise InstallationConflict('publication_attempt_already_approved')
            normalize = lambda path: os.path.normcase(os.path.abspath(path))
            if normalize(worktree['path']) != normalize(self.intents.review.workspace):
                raise InstallationConflict('publication_workspace_outside_worktree')
            permissions = tuple(sorted(set(task.permissions)))
            if (not {'tool_use', 'worktree_write'} <= set(permissions)
                    or permissions != tuple(sorted(set(launch.item.permissions)))):
                raise InstallationConflict('publication_task_permissions_mismatch')
            return PolicyRequest(mission_id=task.project_id, task_id=task.id,
                run_id=binding.run_id, stage_id=binding.stage_id, worker_id=assignment['agent_id'],
                runtime_id=assignment['runtime'], worktree_id=str(binding.worktree_id),
                permissions=permissions, effect_digest=publication['request_digest'])

    def request(self, mission, actor, *, operation_id, task_id, worker_id, runtime_id, worktree_id):
        if (type(operation_id) is not int or operation_id<1 or type(task_id) is not int or task_id<1):
            raise ValueError('Invalid installation scope')
        worker_id=_identity(worker_id); runtime_id=_identity(runtime_id); worktree_id=_identity(worktree_id)
        with self.storage.db:
            self.storage._begin_immediate()
            actual=GamePlanning(self.storage)._mission(mission,actor)
            task=self.storage.db.execute('SELECT project_id FROM work_items WHERE id=?',(task_id,)).fetchone()
            if not task or task['project_id']!=actual.project_id:
                raise InstallationConflict('installation_task_project_mismatch')
            intent=self.intents.view(mission,actor,operation_id)
            if intent['state']!='reserved':
                raise InstallationConflict('installation_intent_not_reserved')
            # A historical read alone is insufficient for a new approval request.
            # This rechecks current consent/source/host/capacity and mission fence.
            fresh=self.intents.reserve(mission,actor,plan_id=intent['plan_id'],digest=intent['plan_digest'])
            if fresh!=intent:
                raise InstallationConflict('installation_intent_changed')
            # Policy's mission_id is the work item's project ID. It is NOT the
            # autonomous_missions primary key. Preserve the existing contract.
            return PolicyRequest(mission_id=actual.project_id,task_id=task_id,run_id=None,
                stage_id=f"installation/{intent['operation_identity']}/{intent['request_digest']}",
                worker_id=worker_id,runtime_id=runtime_id,worktree_id=worktree_id,
                permissions=('tool_use','worktree_write'))
