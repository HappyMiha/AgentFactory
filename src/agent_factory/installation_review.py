"""Owner-bound persistent review; never an installer or execution approval."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import uuid

from .game_planning import GamePlanning, PlanningConflict
from .installation_plan import InstallationPlan, build_plan, changed_fields, load_catalog


class InstallationConflict(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _command(value):
    if not isinstance(value, str):
        raise ValueError('invalid_command')
    return str(uuid.UUID(value))


def observe_workspace(workspace, catalog):
    """Read only fixed target metadata and destination capacity; no binary launch.

    Existing targets have unknown provenance until a future installer supplies
    verified receipts. They are conflicts, never inferred successful installs.
    """
    root = Path(workspace).resolve()
    machine = platform.machine().casefold()
    host_platform = ('windows-x86_64' if platform.system() == 'Windows' and machine in {'amd64', 'x86_64'}
                     else 'unsupported-host')
    inventory = {}
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        free = None
    for key, package in catalog['packages'].items():
        path = root
        for part in package['target'].split('/'):
            path = path / part
            # A link/reparse ancestor cannot be treated as an isolated destination.
            try:
                attributes = path.lstat()
            except FileNotFoundError:
                attributes = None
            if path.is_symlink() or (attributes and getattr(attributes, 'st_file_attributes', 0) & 0x400):
                inventory[key] = {'version': '0', 'sha256': '0' * 64, 'managed': False,
                                  'target': 'unresolved-link', 'location_kind': 'external_label'}
                break
            if attributes and path != root / package['target'] and not path.is_dir():
                inventory[key] = {'version': '0', 'sha256': '0' * 64, 'managed': False,
                                  'target': path.relative_to(root).as_posix()}
                break
        else:
            if os.path.lexists(path):
                inventory[key] = {'version': '0', 'sha256': '0' * 64, 'managed': False,
                                  'target': package['target']}
    return {'platform': host_platform, 'free_bytes': free, 'inventory': inventory,
            'host': _digest([platform.node(), platform.system(), machine]),
            'workspace': _digest(os.path.normcase(str(root)))}


class InstallationReview:
    def __init__(self, storage, workspace, *, probe=None, catalog=None, clock=None):
        self.storage = storage
        self.workspace = Path(workspace)
        self.probe = probe or observe_workspace
        self.catalog = catalog or load_catalog
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self):
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('aware_time_required')
        return now.astimezone(timezone.utc)

    def _game(self, mission, actor):
        game = GamePlanning(self.storage).view(mission, actor)
        if not game['editable'] or game['stale']:
            raise InstallationConflict('game_plan_changed')
        if game['revision_id'] is None:
            raise InstallationConflict('save_game_plan_first')
        if game['fields']['engine'] != 'godot':
            raise InstallationConflict('engine_installation_not_supported')
        return game

    def _proposal(self, mission, actor, offline, *, reviewed_free=None, preserve_free=False):
        game = self._game(mission, actor)
        catalog = self.catalog()
        host = self.probe(self.workspace, catalog)
        plan = build_plan(['godot-export-templates'],
                          context={'tenant': 'local', 'project': f"{mission}:{game['source_digest']}:{game['revision_id']}",
                                   'host': host['host'], 'workspace': host['workspace']},
                          platform=host['platform'], inventory=host['inventory'], offline=offline,
                          free_bytes=reviewed_free if preserve_free else host['free_bytes'], catalog=catalog)
        return plan, host['free_bytes']

    def _latest(self, mission):
        return self.storage.db.execute('SELECT * FROM installation_review_plans WHERE mission_id=? ORDER BY id DESC LIMIT 1', (mission,)).fetchone()

    def _response(self, row):
        plan = InstallationPlan(row['plan_json'])
        if plan.digest != row['plan_digest']:
            raise ValueError('stored_plan_integrity_failed')
        decision = self.storage.db.execute('SELECT decision,created_at FROM installation_review_decisions WHERE plan_id=?', (row['id'],)).fetchone()
        prior = self.storage.db.execute('SELECT plan_json FROM installation_review_plans WHERE mission_id=? AND id<? ORDER BY id DESC LIMIT 1', (row['mission_id'], row['id'])).fetchone()
        return {'id': row['id'], 'digest': plan.digest, 'plan': plan.document(),
                'changed_fields': changed_fields(InstallationPlan(prior['plan_json']), plan) if prior else [],
                'created_at': row['created_at'], 'expires_at': row['expires_at'],
                'decision': dict(decision) if decision else None, 'execution_eligible': False}

    def view(self, mission, actor):
        # Ownership applies even when the latest game revision cannot be prepared.
        GamePlanning(self.storage)._mission(mission, actor)
        row = self._latest(mission)
        result = {'review': self._response(row) if row else None, 'execution_eligible': False}
        if row:
            result['expired'] = self._now() >= datetime.fromisoformat(row['expires_at'])
        return result

    def prepare(self, mission, actor, *, command_id, offline=False):
        command_id = _command(command_id)
        if type(offline) is not bool:
            raise ValueError('invalid_offline_choice')
        request_digest = _digest([mission, actor, offline])
        with self.storage.db:
            self.storage._begin_immediate()
            GamePlanning(self.storage)._mission(mission, actor)
            previous = self.storage.db.execute('SELECT * FROM installation_review_plans WHERE actor=? AND command_id=?', (actor, command_id)).fetchone()
            if previous:
                if previous['request_digest'] != request_digest:
                    raise InstallationConflict('command_changed')
                return self._response(previous)
            plan, _ = self._proposal(mission, actor, offline)
            now = self._now()
            cur = self.storage.db.execute('''INSERT INTO installation_review_plans
                (mission_id,actor,command_id,request_digest,plan_digest,plan_json,created_at,expires_at)
                VALUES(?,?,?,?,?,?,?,?)''', (mission, actor, command_id, request_digest, plan.digest,
                json.dumps(plan.document(), sort_keys=True, separators=(',', ':')), now.isoformat(), (now + timedelta(minutes=15)).isoformat()))
            return self._response(self.storage.db.execute('SELECT * FROM installation_review_plans WHERE id=?', (cur.lastrowid,)).fetchone())

    def decide(self, mission, actor, *, plan_id, digest, decision, command_id):
        command_id = _command(command_id)
        if type(plan_id) is not int or not 0 < plan_id < 2**63 or decision not in {'approved', 'rejected'}:
            raise ValueError('invalid_decision')
        with self.storage.db:
            self.storage._begin_immediate()
            GamePlanning(self.storage)._mission(mission, actor)
            row = self.storage.db.execute('SELECT * FROM installation_review_plans WHERE id=? AND mission_id=? AND actor=?', (plan_id, mission, actor)).fetchone()
            if row is None:
                raise KeyError('review_not_found')
            plan = InstallationPlan(row['plan_json'])
            if plan.digest != digest or plan.digest != row['plan_digest']:
                raise InstallationConflict('plan_changed')
            prior = self.storage.db.execute('SELECT * FROM installation_review_decisions WHERE actor=? AND command_id=?', (actor, command_id)).fetchone()
            if prior:
                if (prior['plan_id'], prior['plan_digest'], prior['decision']) != (plan_id, digest, decision):
                    raise InstallationConflict('command_changed')
                return self._response(row)  # Exact replay is a read of a receipt, never renewed authority.
            if self.storage.db.execute('SELECT 1 FROM installation_review_decisions WHERE plan_id=?', (plan_id,)).fetchone():
                raise InstallationConflict('decision_already_saved')
            if self._latest(mission)['id'] != plan_id:
                raise InstallationConflict('newer_plan_exists')
            if self._now() >= datetime.fromisoformat(row['expires_at']):
                raise InstallationConflict('review_expired')
            document = plan.document()
            fresh, free = self._proposal(mission, actor, document['offline'], reviewed_free=document['free_bytes'], preserve_free=True)
            if changed_fields(plan, fresh):
                raise InstallationConflict('plan_changed')
            if decision == 'approved':
                if document['requires_manual_action']:
                    raise InstallationConflict('manual_action_required')
                if free is None or free < document['disk_budget_bytes']:
                    raise InstallationConflict('disk_space_changed')
            self.storage.db.execute('''INSERT INTO installation_review_decisions
                (plan_id,actor,command_id,plan_digest,decision,created_at) VALUES(?,?,?,?,?,?)''',
                (plan_id, actor, command_id, digest, decision, self._now().isoformat()))
            return self._response(row)
