"""Publish one saved package from an already admitted, running host session.

No default route invokes this service. Runtime provisioning, downloads and engine
qualification remain separate. A failed attempt is observed, never retried here.
"""
from dataclasses import asdict
import ctypes
import hashlib
import json
import os
from pathlib import Path

from .control_plane import MissionControlFenceService, MissionOperationKind
from .game_planning import GamePlanning
from .installation_archive import StagedArchive
from .installation_intent import InstallationIntents
from .installation_journal import InstallationPublicationJournal
from .installation_manifest import manifest_for_stage
from .installation_publication import _directory, publish_staged
from .installation_review import InstallationConflict
from .policy import ControlPlanePolicy, PolicyOutcome
from .worker_admission import WorkerAdmissionService
from .worker_runtime import RuntimeLaunch, WorkerRuntime


class InstallationExecutor:
    def __init__(self, intents, runtime):
        if type(intents) is not InstallationIntents or not isinstance(runtime, WorkerRuntime):
            raise ValueError('Trusted installation intents and worker runtime required')
        if intents.storage is not runtime.storage:
            raise ValueError('Installer and runtime must share their storage connection')
        self.intents, self.runtime = intents, runtime
        self.storage = intents.storage
        self.publications = InstallationPublicationJournal(intents)

    def _validate(self, mission, actor, publication_id, session_id, launch, state):
        """Called under a writer lock; never consumes another stage approval."""
        if not self.storage.db.in_transaction:
            raise RuntimeError('Publication validation requires writer exclusion')
        operation, _, receipt = self.publications._record(mission, actor, publication_id)
        if operation.latest_event.lifecycle.value != state:
            raise InstallationConflict('publication_requires_reconciliation')
        self.intents.current(mission, actor, operation.request['intent_id'])
        if type(launch) is not RuntimeLaunch or launch.effect_digest != operation.request_digest:
            raise InstallationConflict('publication_launch_effect_mismatch')
        policy = self.runtime._mutable_policy_request(launch)
        if policy is None or not {'tool_use', 'worktree_write'} <= set(policy.permissions):
            raise PermissionError('Publication requires exact mutable installation permissions')
        admitted = WorkerAdmissionService(self.storage).validate_launch_in_transaction(launch, self.runtime.runtime_id)
        if admitted is None or admitted['runtime_session_id'] != session_id:
            raise PermissionError('Publication session must match its admitted runtime')
        session = self.storage.runtime_session(session_id)
        scope = launch.durable_scope()
        digest = hashlib.sha256(json.dumps({'scope': scope, 'agent': asdict(launch.agent),
            'item': asdict(launch.item), 'approval': asdict(launch.approval)},
            sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        expected_session = json.loads(json.dumps({**scope, 'admission_start_digest': digest}))
        if (session['status'] != 'running' or session['runtime'] != self.runtime.runtime_id
                or session['assignment_id'] != launch.assignment_id
                or json.loads(session['request_json']) != expected_session):
            raise PermissionError('Publication requires its exact running session')
        project = GamePlanning(self.storage)._mission(mission, actor).project_id
        if launch.item.project_id != project:
            raise PermissionError('Publication task belongs to another project')
        tree = self.storage.db.execute('SELECT path FROM worktrees WHERE id=?',
                                       (launch.binding.worktree_id,)).fetchone()
        normalize = lambda path: os.path.normcase(os.path.abspath(path))
        if normalize(tree['path']) != normalize(self.intents.review.workspace):
            raise PermissionError('Publication workspace differs from the admitted worktree')
        consumed = self.storage.db.execute('''SELECT c.*,a.status AS approval_status
            FROM stage_approval_consumptions c JOIN scoped_execution_approvals a ON a.id=c.approval_id
            WHERE c.approval_id=?''', (launch.approval.gate_id,)).fetchone()
        if (not consumed or consumed['approval_status'] != 'consumed'
                or consumed['assignment_id'] != launch.assignment_id
                or consumed['attempt_id'] != launch.binding.attempt_id
                or consumed['run_id'] != launch.binding.run_id or consumed['stage_id'] != admitted['stage_id']
                or consumed['request_digest'] != policy.digest):
            raise PermissionError('Publication requires its exact consumed stage approval')
        if ControlPlanePolicy(self.storage).evaluate(policy).outcome is PolicyOutcome.DENY:
            raise PermissionError('Current policy denies publication')
        return operation, receipt

    def publish(self, mission, actor, *, publication_id, session_id, launch, staged):
        if self.storage.db.in_transaction:
            raise ValueError('Publish must run outside a caller transaction')
        if any(type(value) is not int or value < 1 for value in (publication_id, session_id)):
            raise ValueError('Actual publication and session identifiers required')
        if os.name != 'nt':
            raise NotImplementedError('Publication executor supports Windows only')
        workspace = _directory(self.intents.review.workspace)
        # A mapped network share can have a drive letter; reject it as well as UNC.
        if str(workspace).startswith('\\\\') or ctypes.windll.kernel32.GetDriveTypeW(str(workspace.anchor)) != 3:
            raise ValueError('Publication requires a private local fixed drive')
        if type(staged) is not StagedArchive:
            raise ValueError('Verified staged archive required')
        manifest = manifest_for_stage(staged)
        journal = self.publications.journal
        with self.storage.db:
            self.storage._begin_immediate()
            operation, receipt = self._validate(mission, actor, publication_id, session_id, launch, 'reserved')
            if manifest.document() != receipt.document()['manifest']:
                raise InstallationConflict('publication_stage_changed')
            # The state check and start are serialized. Even an identical replay
            # cannot reuse a previous running/completed start as new authority.
            journal.start(publication_id, event_key=f'host-start:{session_id}')
        control = MissionControlFenceService(self.storage)
        lease = None
        try:
            lease = control.begin_operation(operation_id=f'publication:{operation.identity}',
                mission_id=mission, execution_epoch_id=operation.execution_epoch_id,
                child_job_id=operation.child_job_id, operation_kind=MissionOperationKind.INSTALLATION,
                expected_fencing_token=operation.control_fencing_token,
                request={'publication_id': publication_id, 'session_id': session_id,
                         'effect_digest': operation.request_digest})

            def authorize(expected):
                if expected != receipt:
                    raise PermissionError('Publication receipt changed')
                with self.storage._policy_transaction():
                    self._validate(mission, actor, publication_id, session_id, launch, 'running')
                    active = self.storage.db.execute('SELECT status FROM autonomous_mission_operation_leases WHERE id=?',
                                                     (lease.id,)).fetchone()
                    if not active or active['status'] != 'ACTIVE':
                        raise PermissionError('Installation operation is no longer active')
                return True

            authorize(receipt)  # Before creating parent directories or private copies.
            self.storage.append_runtime_event(session_id, kind='status', mutable=True,
                payload={'state': 'installation_publication_started', 'publication_id': publication_id})
            parent = workspace
            for part in Path(operation.request['relative_target']).parts[:-1]:
                _directory(parent)
                parent = parent/part
                try: parent.mkdir()
                except FileExistsError: pass
                _directory(parent)
            result = publish_staged(staged, parent=parent, expected=receipt, authorize=authorize)
            journal.complete(publication_id, event_key=f'host-complete:{session_id}',
                result={'publication_verified': True, 'execution_eligible': False},
                evidence={'receipt_digest': receipt.digest, 'publication': result, 'session_id': session_id})
            return self.publications.view(mission, actor, publication_id)
        except Exception as error:
            try:
                journal.mark_unknown(publication_id, event_key=f'host-unknown:{session_id}',
                    evidence={'error_type': type(error).__name__, 'session_id': session_id})
            except Exception:
                error.add_note('Publication outcome could not be recorded; observe before any recovery')
            raise
        finally:
            if lease is not None:
                control.finish_operation(lease.operation_id, reason='Synchronous publication call ended; outcome is in journal')
