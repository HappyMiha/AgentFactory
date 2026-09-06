"""Production adapter contract tests; mocked inference does not qualify a host."""
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from agent_factory import environment_model_probe as probe
from agent_factory import local_role_qualification as canary
from agent_factory.environment_readiness import EnvironmentReadiness, EnvironmentNotReady, digest
from agent_factory.models import ProviderCapabilities, ProviderResult
from agent_factory.coding_delivery import AutonomousCodingDeliveryService
from tests.test_autonomous_child_orchestration import AutonomousChildFixture

MODEL = 'local:qwen2.5-coder:7b'
MODEL_DIGEST = 'a' * 64


def synthetic_result():
    return {'results': [{'role': r, 'passed': True, 'api_output_tokens': 25,
        'cli_effective_model': MODEL, 'cli_diagnostics': {'returncode': 0}} for r in canary.ROLES],
        'summary': {'scope': 'local-role-contract-smoke-only', 'roles': 7,
        'model_digest': MODEL_DIGEST, 'profile_sha256': hashlib.sha256(canary.PROFILE.read_bytes()).hexdigest(),
        'api_limit_tokens': 96, 'request_timeout_seconds': 60,
        'cli_combined_output_limit_chars': 16384, 'cli_json_limit_chars': 1024,
        'cli_hard_token_limit': None, 'total_budget_seconds': 240}}


class EnvironmentModelProbeTests(AutonomousChildFixture, unittest.TestCase):
    def setUp(self):
        config = next(p for p in json.loads(canary.PROFILE.read_bytes())['providers'] if p['id'] == 'ollama')
        self.create_fixture(provider_id='ollama', model=MODEL, capability=ProviderCapabilities.from_config(config))
        self.addCleanup(self.close_fixture)
        self.approved = self.approve_fixture(readiness=False)
        self.ident = self.approved.approval.id
        self.readiness = EnvironmentReadiness(self.storage)
        self.inventory = self.enterContext(patch.object(probe, 'model_inventory', return_value=MODEL_DIGEST))
        self.runner = self.enterContext(patch.object(probe, 'qualify', return_value=synthetic_result()))

    def test_explicit_live_collector_persists_bound_report_and_default_gate_reads_it(self):
        report = self.readiness.assess(self.ident, run_live=True)
        self.assertEqual(report['status'], 'ready', report)
        self.runner.assert_called_once()
        receipt = report['model_qualification']
        self.assertEqual(receipt['model_digest'], MODEL_DIGEST)
        self.assertEqual(receipt['binding_digest'], digest(report['binding']))
        self.assertEqual(EnvironmentReadiness(self.storage).require_ready(self.ident)['id'], report['id'])
        entered = AutonomousCodingDeliveryService(self.storage, self.capabilities).enter_development(
            self.mission.id, expected_mission_version=self.approved.approval.result_mission_version,
            command_id='qualified-route-enter')
        self.assertEqual(entered.phase.value, 'DEVELOPMENT')
        self.runner.assert_called_once()  # reading/entering never repeats inference

    def test_default_assessment_and_http_cannot_authorize_inference(self):
        from fastapi.testclient import TestClient
        from agent_factory.web import create_app
        self.assertEqual(self.readiness.assess(self.ident)['status'], 'blocked')
        with TestClient(create_app(self.repository, self.database), base_url='http://localhost') as client:
            result = client.post(f'/api/autonomous-missions/{self.mission.id}/environment/check', json={'run_live': True})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['status'], 'blocked')
        self.runner.assert_not_called(); self.inventory.assert_not_called()

    def test_failed_fresh_run_supersedes_success_and_sanitizes_error(self):
        passed = self.readiness.assess(self.ident, run_live=True)
        self.runner.side_effect = RuntimeError('private canary diagnostic')
        blocked = self.readiness.assess(self.ident, run_live=True)
        self.assertGreater(blocked['id'], passed['id'])
        self.assertEqual(blocked['status'], 'blocked')
        self.assertNotIn('private canary diagnostic', json.dumps(blocked))
        with self.assertRaises(EnvironmentNotReady): self.readiness.require_ready(self.ident)

    def test_missing_duplicate_wrong_model_or_profile_results_are_rejected(self):
        variants = []
        r = synthetic_result(); r['results'].pop(); variants.append(r)
        r = synthetic_result(); r['results'][-1] = r['results'][0]; variants.append(r)
        r = synthetic_result(); r['results'][0]['cli_effective_model'] = 'wrong:model'; variants.append(r)
        r = synthetic_result(); r['summary']['profile_sha256'] = 'f' * 64; variants.append(r)
        r = synthetic_result(); r['summary']['model_digest'] = 'f' * 64; variants.append(r)
        r = synthetic_result(); r['results'][0]['passed'] = False; variants.append(r)
        for result in variants:
            with self.subTest(result=result):
                self.runner.return_value = result
                self.assertEqual(self.readiness.assess(self.ident, run_live=True)['status'], 'blocked')

    def test_model_replacement_invalidates_existing_receipt_without_inference(self):
        self.readiness.assess(self.ident, run_live=True)
        self.inventory.return_value = 'b' * 64
        with self.assertRaises(EnvironmentNotReady): self.readiness.require_ready(self.ident)
        self.runner.assert_called_once()

    def test_effective_provider_override_blocks_before_inference(self):
        directory = self.repository / '.agent-factory/config'; directory.mkdir(parents=True)
        (directory / 'providers.json').write_text('{}')
        self.assertEqual(self.readiness.assess(self.ident, run_live=True)['status'], 'blocked')
        self.runner.assert_not_called(); self.inventory.assert_not_called()

    def test_emergency_stop_denies_new_and_existing_qualification(self):
        self.readiness.assess(self.ident, run_live=True)
        self.storage.set_emergency_stop(True, actor='Founder', reason='Stop local tests')
        with self.assertRaises(EnvironmentNotReady): self.readiness.require_ready(self.ident)
        self.assertEqual(self.readiness.assess(self.ident, run_live=True)['status'], 'blocked')
        self.runner.assert_called_once()

    def test_authority_rechecked_between_requests(self):
        def interrupted(model, *, before_request):
            before_request()
            self.storage.set_emergency_stop(True, actor='Founder', reason='Stop between requests')
            before_request()
            self.fail('Second request must not start')
        self.runner.side_effect = interrupted
        self.assertEqual(self.readiness.assess(self.ident, run_live=True)['status'], 'blocked')

    def test_receipt_expiry_cannot_be_extended_by_revalidation(self):
        report = self.readiness.assess(self.ident, run_live=True)
        from agent_factory.environment_readiness import timestamp
        self.readiness.clock = lambda: timestamp(report['checked_at']) + timedelta(seconds=301)
        with self.assertRaises(EnvironmentNotReady): self.readiness.require_ready(self.ident)
        self.runner.assert_called_once()

    def test_unsupported_route_never_calls_live_collector(self):
        binding, requirements = self.readiness.context(self.ident)
        for value in requirements.values():
            if 'model' in value: value['model'] = 'remote:unsupported'
        with self.assertRaises(ValueError): probe.collect(self.readiness, self.ident, binding, requirements)
        self.runner.assert_not_called(); self.inventory.assert_not_called()

    def test_cli_refuses_absent_live_authorization(self):
        result = subprocess.run([sys.executable, 'scripts/check_environment.py', '--database', str(self.database),
            '--mission-id', str(self.mission.id)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires --run-live', result.stderr)


class CanaryTransportTests(unittest.TestCase):
    def test_reused_producer_checks_all_seven_roles_and_returns_exact_bounded_results(self):
        from io import BytesIO
        requests = []
        def open_request(request, timeout):
            self.assertGreater(timeout, 0); self.assertLessEqual(timeout, 60)
            requests.append(request)
            if request.full_url.endswith('/api/tags'):
                body = {'models': [{'name': 'qwen2.5-coder:7b', 'digest': MODEL_DIGEST}]}
            else:
                data = json.loads(request.data)
                self.assertEqual(data['options']['num_predict'], 96)
                role = canary.ROLES[len([r for r in requests if r.data]) - 1]
                body = {'model': data['model'], 'done': True, 'eval_count': 25,
                        'response': json.dumps({'role': role, 'mode': 'read_only', 'writes': []})}
            return BytesIO(json.dumps(body).encode())
        def execute(provider_self, agent, item, context, approval):
            return ProviderResult(True, provider='ollama',
                content=json.dumps({'role': agent.role, 'mode': 'read_only', 'writes': []}),
                metadata={'effective_model': agent.model, 'returncode': 0})
        with patch.dict(os.environ, {'OLLAMA_HOST': ''}), patch.object(canary, 'build_opener') as opener, patch.object(canary.CLIProvider, 'execute', execute), patch.object(canary.time, 'monotonic', return_value=0):
            opener.return_value.open.side_effect = open_request
            calls = []
            result = canary.qualify('qwen2.5-coder:7b', before_request=lambda: calls.append(True))
        self.assertEqual(len(requests), 9)
        self.assertEqual(len(result['results']), 7)
        self.assertGreaterEqual(len(calls), 17)
        probe.validate_result(result, MODEL, hashlib.sha256(canary.PROFILE.read_bytes()).hexdigest(), MODEL_DIGEST)

    def test_total_budget_expires_before_new_request(self):
        with patch.dict(os.environ, {'OLLAMA_HOST': ''}), patch.object(canary, 'build_opener') as opener, patch.object(canary.time, 'monotonic', side_effect=[0, 241]):
            with self.assertRaises(TimeoutError): canary.qualify('qwen2.5-coder:7b')
            opener.return_value.open.assert_not_called()

    def test_inventory_rejects_remote_endpoint_before_network(self):
        with patch.dict(os.environ, {'OLLAMA_HOST': 'http://remote.example:11434'}), patch.object(probe, 'build_opener') as opener:
            with self.assertRaises(ValueError): probe.model_inventory(MODEL)
            opener.assert_not_called()


@unittest.skipUnless(os.environ.get('AGENTFACTORY_LIVE_ENVIRONMENT_TESTS') == '1',
                     'Opt-in actual local Ollama inference; no model download or service start')
class LiveEnvironmentRouteTests(AutonomousChildFixture, unittest.TestCase):
    def test_installed_local_model_qualifies_and_enters_selected_route(self):
        # Planning/approval input is a synthetic fixture. All readiness probes,
        # seven API/CLI inference pairs, persistence and entry below are real.
        # This is environment acceptance, not end-to-end planning/game acceptance.
        config = next(p for p in json.loads(canary.PROFILE.read_bytes())['providers'] if p['id'] == 'ollama')
        self.create_fixture(provider_id='ollama', model=MODEL, capability=ProviderCapabilities.from_config(config))
        self.addCleanup(self.close_fixture)
        approved = self.approve_fixture(readiness=False)
        readiness = EnvironmentReadiness(self.storage)
        report = readiness.assess(approved.approval.id, run_live=True)
        self.assertEqual(report['status'], 'ready', report['checks'])
        self.assertEqual(readiness.require_ready(approved.approval.id)['id'], report['id'])
        entered = AutonomousCodingDeliveryService(self.storage, self.capabilities).enter_development(
            self.mission.id, expected_mission_version=approved.approval.result_mission_version,
            command_id='live-environment-qualification-entry')
        self.assertEqual(entered.phase.value, 'DEVELOPMENT')
        receipt = report['model_qualification']
        print(json.dumps({'scope': 'actual-local-environment-readiness-with-synthetic-plan-only',
            'model': receipt['model'], 'model_digest': receipt['model_digest'],
            'provider_profile_sha256': receipt['provider_profile_sha256'],
            'binding_digest': receipt['binding_digest'], 'started_at': receipt['started_at'],
            'finished_at': receipt['finished_at'], 'result': receipt['result'],
            'entry_phase': entered.phase.value}), flush=True)
