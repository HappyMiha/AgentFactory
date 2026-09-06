"""Bind a setup intent to the existing exact policy request, without granting it."""
from .game_planning import GamePlanning
from .installation_intent import InstallationIntents
from .installation_review import InstallationConflict
from .policy import PolicyRequest


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
