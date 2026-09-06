"""Opt-in production qualification for the bundled local Ollama route."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.request import build_opener, ProxyHandler

from .autonomous_authorization import (AutonomousAuthorizationService,
    AutonomousAuthorizationRequest, AuthorizationOperation, AuthorizationOutcome)
from .autonomous_backlog_approval import AutonomousBacklogApprovalService
from .config import config_path_for_workspace
from .local_role_qualification import PROFILE, ROLES, NoRedirect, qualify
from .models import ProviderCapabilities

SUPPORTED = {'local:qwen2.5-coder:7b', 'local:qwen2.5-coder:14b'}
NEXT_ACTION = ('For the bundled local Ollama route, run scripts/check_environment.py '
               '--database PATH --mission-id ID --run-live on its execution host. '
               'Other models/services need a reviewed verifier.')


def model_inventory(model):
    """Read only the fixed loopback daemon; no proxy, redirects or inference."""
    if os.environ.get('OLLAMA_HOST', '') not in {'', '127.0.0.1:11434', 'http://127.0.0.1:11434'}:
        raise ValueError('Local model endpoint changed')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open('http://127.0.0.1:11434/api/tags', timeout=2) as response:
        raw = response.read(131073)
    if len(raw) > 131072:
        raise ValueError('Model inventory exceeds 128 KiB')
    rows = [row for row in json.loads(raw)['models'] if row.get('name') == model.removeprefix('local:')]
    if len(rows) != 1 or not re.fullmatch(r'[a-f0-9]{64}', rows[0].get('digest', '')):
        raise ValueError('Exact installed model digest unavailable')
    return rows[0]['digest']


def selected_model(requirements):
    selected = [r for k, r in requirements.items() if k.startswith('model:')]
    models = {r['model'] for r in selected}
    if (len(models) != 1 or not models <= SUPPORTED
            or any(r['role'] not in ROLES or 'ollama' not in r['provider_ids'] for r in selected)):
        raise ValueError('Selected route is outside the supported local role/model profile')
    return next(iter(models))


def provider_profile(repository):
    raw = PROFILE.read_bytes()
    if config_path_for_workspace('providers', Path(repository)).read_bytes() != raw:
        raise ValueError('Effective provider override differs from the qualified bundled profile')
    config = next(p for p in json.loads(raw)['providers'] if p['id'] == 'ollama')
    return hashlib.sha256(raw).hexdigest(), ProviderCapabilities.from_config(config)


def check_authority(storage, approval_id, requirements, capability):
    approval = AutonomousBacklogApprovalService(storage).get(approval_id)
    service = AutonomousAuthorizationService(storage, {'ollama': capability})
    authority = service.get_authorization(approval.authorization_id)
    for key, requirement in requirements.items():
        if not key.startswith('model:'):
            continue
        # These IDs name synthetic qualification work, never a delivery child.
        decision = service.resolve(AutonomousAuthorizationRequest(
            mission_id=approval.mission_id, operation=AuthorizationOperation.LOCAL_INFERENCE,
            provider_id='ollama', agent_id='environment-canary:' + requirement['role'],
            task_id=approval.id, role=requirement['role'], model=requirement['model'],
            backlog_revision_id=approval.revision_id, backlog_revision_digest=approval.revision_digest,
            execution_epoch_id=approval.execution_epoch_id, repository_path=authority.repository_path,
            epoch_branch=authority.epoch_branch, tool_profile=authority.tool_profile,
            permissions=('execute_provider',), authorization_id=authority.id))
        if decision.outcome != AuthorizationOutcome.ALLOW_AUTONOMOUS:
            raise PermissionError('Current mission authority denies local qualification')


def validate_result(result, model, profile_sha, installed_digest):
    rows = result['results']; summary = result['summary']
    if (len(rows) != len(ROLES) or {r['role'] for r in rows} != set(ROLES)
            or any(r['passed'] is not True or r['cli_effective_model'] != model
                   or type(r['api_output_tokens']) is not int or not 0 < r['api_output_tokens'] <= 96
                   or r['cli_diagnostics']['returncode'] != 0 for r in rows)
            or summary['scope'] != 'local-role-contract-smoke-only'
            or summary['roles'] != 7 or summary['model_digest'] != installed_digest
            or summary['profile_sha256'] != profile_sha
            or summary['api_limit_tokens'] != 96 or summary['request_timeout_seconds'] != 60
            or summary['cli_combined_output_limit_chars'] != 16384
            or summary['cli_json_limit_chars'] != 1024 or summary['cli_hard_token_limit'] is not None
            or summary['total_budget_seconds'] != 240):
        raise ValueError('Incomplete or mismatched local role qualification')


def collect(readiness, approval_id, binding, requirements):
    """Called only by an explicitly authorized live assessment, never HTTP/polling."""
    from .environment_readiness import digest
    model = selected_model(requirements)
    profile_sha, capability = provider_profile(binding['repository'])
    started = readiness.clock()

    def revalidate():
        if readiness.context(approval_id) != (binding, requirements):
            raise ValueError('Approved route changed during qualification')
        if provider_profile(binding['repository'])[0] != profile_sha:
            raise ValueError('Provider profile changed during qualification')
        check_authority(readiness.storage, approval_id, requirements, capability)

    revalidate()
    installed_digest = model_inventory(model)
    result = qualify(model.removeprefix('local:'), before_request=revalidate)
    validate_result(result, model, profile_sha, installed_digest)
    revalidate()
    if model_inventory(model) != installed_digest:
        raise ValueError('Installed model changed during qualification')
    finished = readiness.clock()
    if not 0 <= (finished - started).total_seconds() <= 240:
        raise TimeoutError('Local qualification exceeded its total time bound')
    return {'schema_version': 1, 'producer': 'bundled-local-role-canary-v1',
            'binding_digest': digest(binding), 'model': model, 'provider_id': 'ollama',
            'model_digest': installed_digest, 'provider_profile_sha256': profile_sha,
            'started_at': started.isoformat(), 'finished_at': finished.isoformat(),
            'live_authority': 'explicit-local-command-and-current-mission-authority',
            'result': result}


def verify_receipt(readiness, approval_id, report, requirements):
    from .environment_readiness import digest, timestamp
    receipt = report['model_qualification']; binding = report['binding']
    model = selected_model(requirements)
    profile_sha, capability = provider_profile(binding['repository'])
    if (receipt['schema_version'] != 1 or receipt['producer'] != 'bundled-local-role-canary-v1'
            or receipt['binding_digest'] != digest(binding) or receipt['model'] != model
            or receipt['provider_id'] != 'ollama' or receipt['provider_profile_sha256'] != profile_sha
            or receipt['live_authority'] != 'explicit-local-command-and-current-mission-authority'
            or not timestamp(report['checked_at']) <= timestamp(receipt['started_at'])
               <= timestamp(receipt['finished_at']) <= readiness.clock()
            or (timestamp(receipt['finished_at']) - timestamp(receipt['started_at'])).total_seconds() > 240):
        raise ValueError('Qualification receipt binding or time bounds changed')
    check_authority(readiness.storage, approval_id, requirements, capability)
    installed_digest = model_inventory(model)
    if receipt['model_digest'] != installed_digest:
        raise ValueError('Qualified model is no longer installed with the same digest')
    validate_result(receipt['result'], model, profile_sha, installed_digest)


def main():
    from .environment_readiness import EnvironmentReadiness, EnvironmentNotReady
    from .storage import SQLiteStorage
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--mission-id', required=True, type=int)
    parser.add_argument('--run-live', action='store_true', help='Authorize up to seven API and seven CLI local synthetic requests, 240 seconds total; no download/start')
    args = parser.parse_args()
    if not args.run_live:
        parser.error('Live qualification requires --run-live; no inference was executed')
    if not args.database.is_file():
        parser.error('Use the existing execution-host database')
    with closing(SQLiteStorage(args.database)) as storage:
        row = storage.db.execute('SELECT a.id FROM autonomous_backlog_approvals a '
            'JOIN autonomous_missions m ON m.id=a.mission_id '
            'WHERE m.id=? AND a.execution_epoch_id=m.active_execution_epoch_id '
            'ORDER BY a.id DESC LIMIT 1', (args.mission_id,)).fetchone()
        if not row:
            parser.error('Mission has no current approved execution epoch')
        try:
            report = EnvironmentReadiness(storage).assess(row['id'], run_live=True)
            print(json.dumps({'report_id': report['id'], 'status': report['status'],
                              'next_action': report['next_action']}))
            return 0 if report['status'] == 'ready' else 1
        except (EnvironmentNotReady, ValueError, PermissionError) as error:
            print(json.dumps({'status': 'blocked', 'error_type': type(error).__name__}))
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
