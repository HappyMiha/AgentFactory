"""Persist publication evidence and reconcile it through the existing journal.

This service does not start publication or establish execution permission.
"""
import json
from pathlib import Path

from .durable_workflow import OperationClass, OperationObservation, ReconciliationPolicy
from .installation_archive import ArchiveRejected, StagedArchive
from .installation_intent import InstallationIntents
from .installation_plan import _path
from .installation_publication import PublicationReceipt, prepare_publication, observe_publication, _directory
from .installation_review import InstallationConflict


def _receipt(document):
    return PublicationReceipt(json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True))


class InstallationPublicationJournal:
    def __init__(self, intents):
        if type(intents) is not InstallationIntents:
            raise ValueError('Expected trusted installation intents')
        self.intents = intents
        self.storage = intents.storage
        self.journal = intents.journal

    @staticmethod
    def _step(intent, package):
        steps = [step for step in intent['plan']['steps'] if step['package'] == package]
        if len(steps) != 1 or steps[0]['action'] not in {'install', 'update'}:
            raise InstallationConflict('publication_not_in_reviewed_plan')
        return steps[0]

    def reserve(self, mission, actor, *, intent_id, staged):
        """Save expected evidence before an effect, with no execution grant.

        Current intent validation precedes this reservation. An executor must
        repeat it at its own admitted effect boundary; a saved receipt is not
        an atomic lock on future plan, host or source changes.
        """
        if type(intent_id) is not int or intent_id < 1 or type(staged) is not StagedArchive:
            raise ValueError('Expected installation intent and verified stage')
        intent = self.intents.view(mission, actor, intent_id)
        if intent['state'] != 'reserved':
            raise InstallationConflict('installation_intent_not_reserved')
        fresh = self.intents.reserve(mission, actor, plan_id=intent['plan_id'], digest=intent['plan_digest'])
        if fresh != intent:
            raise InstallationConflict('installation_intent_changed')
        step = self._step(intent, staged.package_id)
        if staged.sha256 != step['sha256'] or staged.extracted_bytes > step['extraction_budget_bytes']:
            raise InstallationConflict('publication_source_differs_from_plan')
        target = _path(step['target'])
        receipt = prepare_publication(staged, operation_identity=intent['operation_identity'],
            request_digest=intent['request_digest'], target_name=target.split('/')[-1])
        parent = self.journal.get(intent_id)
        reserved = self.journal.reserve(mission_id=mission, actor=actor,
            operation_key=f"installation-publication:{parent.identity}:{staged.package_id}",
            operation_class=OperationClass.INSTALLATION,
            reconciliation_policy=ReconciliationPolicy.VERIFY_ONLY,
            request={'kind': 'installation-publication-v1', 'intent_id': intent_id,
                     'relative_target': target, 'receipt': receipt.document()},
            expected_mission_version=parent.mission_version,
            expected_backlog_revision_id=parent.backlog_revision_id,
            expected_execution_epoch_id=parent.execution_epoch_id,
            expected_checkpoint_id=parent.checkpoint_id,
            expected_fencing_token=parent.control_fencing_token)
        return self.view(mission, actor, reserved.operation.id)

    def _record(self, mission, actor, operation_id):
        if type(operation_id) is not int or operation_id < 1:
            raise ValueError('Invalid publication operation')
        operation = self.journal.get(operation_id)
        request = operation.request
        if operation.mission_id != mission or operation.actor != actor:
            raise KeyError('publication_not_found')
        if (operation.operation_class != OperationClass.INSTALLATION
                or operation.reconciliation_policy != ReconciliationPolicy.VERIFY_ONLY
                or set(request) != {'kind', 'intent_id', 'relative_target', 'receipt'}
                or request['kind'] != 'installation-publication-v1'):
            raise InstallationConflict('not_a_publication_operation')
        intent = self.intents.view(mission, actor, request['intent_id'])
        receipt = _receipt(request['receipt'])
        document = receipt.document()
        manifest = document['manifest']
        step = self._step(intent, manifest['package_id'])
        if (request['relative_target'] != step['target']
                or document['target_name'] != _path(step['target']).split('/')[-1]
                or document['operation_identity'] != intent['operation_identity']
                or document['request_digest'] != intent['request_digest']
                or manifest['archive_sha256'] != step['sha256']
                or manifest['total_bytes'] > step['extraction_budget_bytes']):
            raise InstallationConflict('publication_intent_binding_changed')
        return operation, intent, receipt

    def view(self, mission, actor, operation_id):
        operation, _, receipt = self._record(mission, actor, operation_id)
        return {'operation_id': operation.id, 'operation_identity': operation.identity,
                'request_digest': operation.request_digest, 'intent_id': operation.request['intent_id'],
                'relative_target': operation.request['relative_target'], 'receipt': receipt.document(),
                'receipt_digest': receipt.digest, 'state': operation.latest_event.lifecycle.value,
                'execution_eligible': False}

    def observe(self, mission, actor, operation_id):
        """Observe only the saved target on its recorded host/workspace."""
        operation, intent, receipt = self._record(mission, actor, operation_id)
        review = self.intents.review
        try:
            host = review.probe(review.workspace, review.catalog())
            context = intent['plan']['context']
            if any(host[key] != context[key] for key in ('host', 'workspace')):
                return {'state': 'indeterminate', 'execution_eligible': False}
            parent = _directory(review.workspace)
            # Walk from the checked workspace. A missing parent means no target;
            # links or unreadable parents must not be mistaken for absence.
            for part in Path(operation.request['relative_target']).parts[:-1]:
                parent = parent/part
                try:
                    _directory(parent)
                except FileNotFoundError:
                    return {'state': 'absent', 'execution_eligible': False}
            return observe_publication(parent, receipt)
        except (OSError, ArchiveRejected, KeyError, ValueError):
            return {'state': 'indeterminate', 'execution_eligible': False}

    def reconcile_unknown(self, mission, actor, operation_id, *, event_key):
        """Adopt proven file publication; never grant retry or whole setup success."""
        self._record(mission, actor, operation_id)
        def observer(_):
            observed = self.observe(mission, actor, operation_id)
            evidence = {'publication': observed, 'execution_eligible': False}
            if observed['state'] == 'matched':
                return OperationObservation.present({'publication_verified': True, 'execution_eligible': False},
                    evidence=evidence, reason='Persisted expected receipt and payload match; executable not qualified')
            if observed['state'] == 'absent':
                return OperationObservation.absent(evidence=evidence, reason='Publication absent; fresh authorization required')
            if observed['state'] == 'conflict':
                return OperationObservation.conflict({}, evidence=evidence, reason='Existing publication differs; preserve files')
            return OperationObservation.indeterminate(evidence=evidence, reason='Publication could not be verified')
        result = self.journal.reconcile_unknown(operation_id, event_key=event_key, observer=observer)
        return self.view(mission, actor, result.id)
