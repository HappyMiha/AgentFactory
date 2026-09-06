"""Reserve the exact reviewed setup intent in Core's existing operation journal.

This trusted-host boundary records intent only. It never starts an operation,
consumes an execution approval, downloads a package or mutates an install target.
"""
from datetime import datetime
import json

from .durable_workflow import MissionOperationJournal, OperationClass, ReconciliationPolicy
from .game_planning import GamePlanning
from .installation_plan import InstallationPlan, changed_fields
from .installation_review import InstallationConflict


class InstallationIntents:
    def __init__(self, review):
        self.review = review
        self.storage = review.storage
        self.journal = MissionOperationJournal(self.storage)

    def _response(self, operation):
        request = operation.request
        if (operation.operation_class != OperationClass.INSTALLATION
                or request.get('kind') != 'installation-intent-v1'):
            raise InstallationConflict('not_an_installation_intent')
        plan = InstallationPlan(json.dumps(request['plan'], sort_keys=True, separators=(',', ':')))
        if plan.digest != request['plan_digest']:
            raise InstallationConflict('installation_intent_changed')
        return {'operation_id': operation.id, 'operation_identity': operation.identity,
                'request_digest': operation.request_digest, 'plan_id': request['plan_id'],
                'decision_id': request['decision_id'], 'plan_digest': plan.digest,
                'plan': plan.document(), 'state': operation.latest_event.lifecycle.value,
                'execution_eligible': False}

    def view(self, mission, actor, operation_id):
        """Read a historical reservation without renewing consent or authority."""
        GamePlanning(self.storage)._mission(mission, actor)
        operation = self.journal.get(operation_id)
        if operation.mission_id != mission or operation.actor != actor:
            raise KeyError('installation_intent_not_found')
        return self._response(operation)

    def reserve(self, mission, actor, *, plan_id, digest):
        """Record a still-current approved draft under the existing mission fence.

        Host composition supplies the authenticated actor and review service.
        Browser JSON is not a source of catalogues, inventories or execution scope.
        New and repeated reserve requests both check current consent; historical
        reads after expiry use view() and cannot authorize another operation.
        """
        if type(plan_id) is not int or not 0 < plan_id < 2**63:
            raise ValueError('invalid_plan_id')
        with self.storage.db:
            # Keep source, consent, host observation and journal reservation under
            # one writer lock. The journal's own nested context commits the insert.
            self.storage._begin_immediate()
            GamePlanning(self.storage)._mission(mission, actor)
            row = self.storage.db.execute('''SELECT * FROM installation_review_plans
                WHERE id=? AND mission_id=? AND actor=?''', (plan_id, mission, actor)).fetchone()
            if row is None:
                raise KeyError('review_not_found')
            plan = InstallationPlan(row['plan_json'])
            if plan.digest != digest or digest != row['plan_digest']:
                raise InstallationConflict('plan_changed')
            decision = self.storage.db.execute('''SELECT * FROM installation_review_decisions
                WHERE plan_id=? AND actor=? AND plan_digest=? AND decision='approved' ''',
                (plan_id, actor, digest)).fetchone()
            if decision is None:
                raise InstallationConflict('approved_review_required')
            if self.review._latest(mission)['id'] != plan_id:
                raise InstallationConflict('newer_plan_exists')
            document = plan.document()
            fresh, free = self.review._proposal(mission, actor, document['offline'],
                reviewed_free=document['free_bytes'], preserve_free=True)
            if changed_fields(plan, fresh) or document['requires_manual_action']:
                raise InstallationConflict('plan_changed')
            if free is None or free < document['disk_budget_bytes']:
                raise InstallationConflict('disk_space_changed')
            if self.review._now() >= datetime.fromisoformat(row['expires_at']):
                raise InstallationConflict('review_expired')
            # No scheduling state is changed here. Draft missions still need the
            # existing RUNNING control disposition for an intent reservation.
            scope = self.storage.db.execute('''SELECT m.version, m.active_backlog_revision_id,
                m.active_execution_epoch_id, m.current_checkpoint_id, m.disposition,
                f.fencing_token, f.disposition AS fence_disposition
                FROM autonomous_missions m JOIN autonomous_mission_control_fences f ON f.mission_id=m.id
                WHERE m.id=?''', (mission,)).fetchone()
            if not scope or scope['disposition'] != 'RUNNING' or scope['fence_disposition'] != 'RUNNING':
                raise InstallationConflict('mission_is_fenced')
            result = self.journal.reserve(mission_id=mission, actor=actor,
                operation_key=f'installation-intent:{plan_id}:{digest}',
                operation_class=OperationClass.INSTALLATION,
                reconciliation_policy=ReconciliationPolicy.VERIFY_ONLY,
                request={'kind':'installation-intent-v1', 'plan_id':plan_id,
                         'decision_id':decision['id'], 'decision_created_at':decision['created_at'],
                         'plan_digest':digest, 'plan':document},
                expected_mission_version=scope['version'],
                expected_backlog_revision_id=scope['active_backlog_revision_id'],
                expected_execution_epoch_id=scope['active_execution_epoch_id'],
                expected_checkpoint_id=scope['current_checkpoint_id'],
                expected_fencing_token=scope['fencing_token'])
            return self._response(result.operation)
