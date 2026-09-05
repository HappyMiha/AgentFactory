"""Current selected-route evidence. Configured capability is not qualification."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Callable, Mapping

from .autonomous_backlog_approval import AutonomousBacklogApprovalService
from .autonomous_authorization import AutonomousAuthorizationService
from .autonomous_mission import AutonomousMissionService
from .mission_checkpoints import MissionCheckpointService

MANIFEST = 'agentfactory.environment.json'
TOOLS = {'git': ('git', '--version'), 'python': (sys.executable, '--version'),
         'godot': ('godot', '--version'), 'node': ('node', '--version')}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result


@dataclass(frozen=True)
class Observation:
    installed: bool = False
    authenticated: bool = False
    qualified: bool = False
    mode: str = 'unknown'
    detail: str = 'No actual-state verifier configured'
    next_action: str = 'Configure and run the selected verifier.'
    identity: str = ''
    provider_id: str = ''

    @property
    def ready(self):
        return (self.installed is True and self.authenticated is True
                and self.qualified is True and self.mode == 'live' and bool(self.identity))


class EnvironmentNotReady(RuntimeError):
    pass


class EnvironmentReadiness:
    """Only trusted in-process adapters may produce observations; no uploaded proofs."""
    def __init__(self, storage, *, probes: Mapping[str, Callable] | None = None, clock=None):
        self.storage = storage
        self.probes = dict(probes or {})
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def git(repository, *args):
        try:
            result = subprocess.run(['git', '-C', str(repository), *args], capture_output=True,
                                    timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise EnvironmentNotReady('Git is missing or its repository check failed; repair Git and rerun checks.') from None
        if result.returncode or len(result.stdout) > 65536:
            raise EnvironmentNotReady('Approved repository or environment manifest is unavailable; check the approved Git revision.')
        try:
            return result.stdout.decode('utf-8').strip()
        except UnicodeError:
            raise EnvironmentNotReady('Approved environment data must be valid UTF-8.') from None

    def context(self, approval_id):
        approval = AutonomousBacklogApprovalService(self.storage).get(approval_id)
        authority = AutonomousAuthorizationService(self.storage).get_authorization(approval.authorization_id)
        epoch = MissionCheckpointService(self.storage).get_epoch(approval.execution_epoch_id)
        repository = Path(authority.repository_path).resolve()
        mission = AutonomousMissionService(self.storage).get(approval.mission_id)
        if (mission.active_execution_epoch_id != epoch.id or mission.active_backlog_revision_id != approval.revision_id
                or AutonomousAuthorizationService._role_manifest(mission) != authority.role_model_manifest
                or mission.configuration.allowed_local_tool_profile != authority.tool_profile):
            raise EnvironmentNotReady('Approved environment binding changed; approve the current plan and rerun checks.')
        if authority.revoked:
            raise EnvironmentNotReady('Execution authority was revoked; obtain a new approved plan.')
        branch = self.git(repository, 'branch', '--show-current')
        if branch != authority.epoch_branch:
            raise EnvironmentNotReady('Workspace branch differs from the approved epoch; restore the approved branch.')
        self.git(repository, 'merge-base', '--is-ancestor', epoch.base_git_commit_sha, 'HEAD')
        object_name = f'{epoch.base_git_commit_sha}:{MANIFEST}'
        try:
            if int(self.git(repository, 'cat-file', '-s', object_name)) > 65536:
                raise EnvironmentNotReady('Approved environment manifest exceeds 64 KiB; reduce and reapprove it.')
            raw = self.git(repository, 'show', object_name)
        except (UnicodeError, ValueError):
            raise EnvironmentNotReady('Approved environment manifest is invalid UTF-8 JSON.') from None
        try:
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('Duplicate field')
                    result[key] = value
                return result
            profile = json.loads(raw, object_pairs_hook=unique_pairs)
            if set(profile) != {'schema_version', 'profile', 'tools', 'services'} or type(profile['schema_version']) is not int or profile['schema_version'] != 1:
                raise ValueError()
            if profile['profile'] != authority.tool_profile:
                raise ValueError()
            for key in ('tools', 'services'):
                if (not isinstance(profile[key], list) or len(profile[key]) > 32
                        or any(not isinstance(x, str) or not x or len(x) > 80 for x in profile[key])
                        or len(set(profile[key])) != len(profile[key])):
                    raise ValueError()
            if not profile['tools']:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise EnvironmentNotReady('Invalid selected environment profile; commit explicit tools/services and approve that Git revision.') from None
        binding = {'approval_id': approval.id, 'approval_digest': approval.approval_digest,
                   'mission_id': approval.mission_id, 'revision_id': approval.revision_id,
                   'revision_digest': approval.revision_digest, 'epoch_id': epoch.id,
                   'base_commit': epoch.base_git_commit_sha, 'branch': branch,
                   'repository': str(repository), 'profile_digest': digest(profile),
                   'role_model_digest': authority.role_model_manifest_digest,
                   'policy_digest': authority.policy_digest}
        requirements = {'workspace': {'repository': str(repository), 'branch': branch}}
        for tool in profile['tools']:
            requirements['tool:' + tool] = {'tool': tool}
        for service in profile['services']:
            requirements['service:' + service] = {'service': service}
        models = authority.role_model_manifest.get('role_models', {})
        if not models:
            raise EnvironmentNotReady('Approved plan has no explicit role/model assignments.')
        for role, model in sorted(models.items()):
            requirements['model:' + role] = {'role': role, 'model': model,
                                            'provider_ids': list(authority.provider_ids)}
        return binding, requirements

    def observe(self, key, requirement):
        if key in self.probes:
            return self.probes[key](dict(requirement))
        if key == 'workspace':
            repository = Path(requirement['repository'])
            with tempfile.TemporaryDirectory(prefix='.af-readiness-', dir=repository) as folder:
                path = Path(folder) / 'write.tmp'
                path.write_bytes(b'readiness')
                target = path.with_suffix('.renamed')
                path.rename(target)
                if target.read_bytes() != b'readiness':
                    raise OSError('Workspace readback failed')
            return Observation(True, True, True, 'live', 'Workspace read/write/rename succeeded.',
                               'Continue with the selected route.', str(repository))
        if key.startswith('tool:') and requirement['tool'] in TOOLS:
            command = TOOLS[requirement['tool']]
            executable = shutil.which(command[0])
            if not executable:
                return Observation(detail='Required tool is not installed.', next_action='Install the selected tool, then rerun checks.')
            # Fixed read-only argv; never execute commands supplied by a plan or model.
            with tempfile.TemporaryFile() as output:
                result = subprocess.run([executable, *command[1:]], stdout=output, stderr=output,
                                        timeout=5, check=False, stdin=subprocess.DEVNULL)
                output.seek(0)
                version = output.read(4097)
            if result.returncode or not version.strip() or len(version) > 4096:
                return Observation(installed=True, mode='live', detail='Required version probe failed.',
                                   next_action='Repair the selected tool and rerun checks.')
            return Observation(True, True, True, 'live', 'Actual version command passed.',
                               'Continue with the selected route.', hashlib.sha256(version).hexdigest())
        return Observation(detail='Selected service/model has no verified current qualification.',
                           next_action='Register its trusted actual-state verifier and rerun checks.')

    def assess(self, approval_id):
        binding, requirements = self.context(approval_id)
        started = self.clock()
        checks = []
        for key, requirement in requirements.items():
            try:
                observed = self.observe(key, requirement)
                if not isinstance(observed, Observation):
                    raise ValueError('Invalid observation')
                if (any(type(getattr(observed, field)) is not bool for field in ('installed', 'authenticated', 'qualified'))
                        or observed.mode not in ('live', 'simulation', 'unknown')
                        or any(not isinstance(getattr(observed, field), str) or len(getattr(observed, field)) > 1024
                               for field in ('detail', 'next_action', 'identity', 'provider_id'))):
                    raise ValueError('Invalid bounded observation')
                if key.startswith('model:') and observed.ready and (
                    observed.identity != requirement['model']
                    or observed.provider_id not in requirement['provider_ids']
                ):
                    observed = Observation(detail='Verified model/provider differs from the approved assignment.',
                                           next_action='Qualify the exact selected model and provider.')
            except Exception as error:
                observed = Observation(detail=f'Actual-state probe failed ({type(error).__name__}).',
                                       next_action='Repair the selected probe and rerun checks.')
            checks.append({'key': key, 'requirement': requirement,
                           **asdict(observed), 'ready': observed.ready})
        # A long-running check cannot produce evidence already outside its validity window.
        expires = started + timedelta(seconds=300)
        ready = all(row['ready'] for row in checks) and self.clock() < expires
        report = {'binding': binding, 'requirements_digest': digest(requirements), 'checks': checks,
                  'status': 'ready' if ready else 'blocked', 'mode': 'live' if ready else 'unqualified',
                  'checked_at': started.isoformat(), 'expires_at': expires.isoformat(),
                  'next_action': 'Start the approved development route.' if ready else
                  next((c['next_action'] for c in checks if not c['ready']), 'Rerun expired checks.')}
        with self.storage.db:
            cursor = self.storage.db.execute('INSERT INTO environment_readiness_reports '
                '(approval_id,report_json,report_digest,created_at) VALUES(?,?,?,?)',
                (approval_id, json.dumps(report, sort_keys=True), digest(report), started.isoformat()))
        return {'id': cursor.lastrowid, **report}

    def current(self, approval_id):
        binding, requirements = self.context(approval_id)
        row = self.storage.db.execute('SELECT * FROM environment_readiness_reports WHERE approval_id=? ORDER BY id DESC LIMIT 1',
                                      (approval_id,)).fetchone()
        if not row:
            raise EnvironmentNotReady('Required environment checks are missing; run checks for the approved plan.')
        report = json.loads(row['report_json'])
        if digest(report) != row['report_digest']:
            raise EnvironmentNotReady('Readiness evidence integrity failed; investigate and rerun checks.')
        if report['binding'] != binding or report['requirements_digest'] != digest(requirements):
            raise EnvironmentNotReady('Environment evidence belongs to a different plan/profile; rerun checks.')
        if not timestamp(report['checked_at']) <= self.clock() < timestamp(report['expires_at']):
            raise EnvironmentNotReady('Environment checks expired; rerun actual-state checks.')
        return {'id': row['id'], **report}

    def require_ready(self, approval_id):
        report = self.current(approval_id)
        if report['status'] != 'ready' or report['mode'] != 'live' or not all(c['ready'] for c in report['checks']):
            raise EnvironmentNotReady(report['next_action'])
        return report
