"""Synthetic model observations; real Linux sandbox grading, never live AI."""
from dataclasses import replace
import json
import sys
import unittest
from unittest.mock import patch

from agent_factory.credentials import CredentialBroker
from agent_factory.models import WorkItem
from agent_factory.provider_canary_transport import ProviderCanaryTransport
from agent_factory.provider_canary_evaluator import ProviderCanaryEvaluator, CASES, _parse, _value
from agent_factory.sandbox import SandboxManager, SandboxPolicy
import test_provider_connection_scope as fixture


class ArithmeticGrammarTests(unittest.TestCase):
    def test_valid_arithmetic_and_known_wrong_control_grade_differently(self):
        expected = [n*(n+1)//2 for n in CASES]
        self.assertEqual([_value(_parse('n*(n+1)//2'), n) for n in CASES], expected)
        self.assertNotEqual([_value(_parse('n*(n-1)//2'), n) for n in CASES], expected)
        self.assertEqual(_value(_parse('-(-n)+n%2'), 3), 4)

    def test_code_execution_constructs_and_growth_are_rejected(self):
        for expression in ('__import__("os").system("id")', 'open("private")', 'n.real', '[n for n in range(5)]',
                           'lambda: n', 'n ** 100', '1 << n', 'True', '1.5', '"value"', 'unknown',
                           '1; import os', 'n\nimport os', '9'*257, '1001', 'n+'*40+'1', '-'*15+'n', 'é'):
            with self.subTest(expression=expression[:40]), self.assertRaises(ValueError): _parse(expression)
        for expression in ('1000*1000*1000', '1//(n-n)', '1%(n-n)'):
            with self.assertRaises((ValueError, ArithmeticError)): _value(_parse(expression), 1)


class ArithmeticSmokeTests(unittest.TestCase):
    resolver_for = fixture.ProviderConnectionScopeTests.resolver_for

    def setUp(self):
        fixture.ProviderConnectionScopeTests.setUp(self)
        self.tree = self.root/'empty-worktree'; self.tree.mkdir()
        project = self.storage.create_project('Smoke fixture', 'Arithmetic only')
        self.task = self.storage.create_task(WorkItem('Synthetic canary', 'No provider calls', project))
        self.claim = self.storage.claim_runnable_task(self.task, 'worker', 'smoke-fixture')
        self.policy = SandboxPolicy.create(self.root, self.tree, max_seconds=5, max_output_chars=2048)
        self.sandbox = SandboxManager(self.storage, self.root)
        self.transport = ProviderCanaryTransport(self.connections, CredentialBroker(self.storage), self.resolver,
                                                 authorize=lambda **_: True)
        self.evaluator = ProviderCanaryEvaluator(self.transport, self.sandbox)

    def run_smoke(self, **changes):
        return self.evaluator.run(**({'worker_id':'worker','role':'Developer','mission_id':'1',
            'assignment_id':self.claim.assignment_id,'fencing_token':self.claim.fencing_token,'policy':self.policy} | changes))

    def network(self, expression):
        return patch('agent_factory.provider_canary_transport._bounded_request',
                     return_value={'observed_model':'observed-model','text':expression})

    def test_unsupported_windows_denies_before_provider_or_sandbox(self):
        with patch('agent_factory.provider_canary_evaluator.sys.platform', 'win32'), \
             patch.object(self.transport,'observe',side_effect=AssertionError('must not call provider')):
            report = self.run_smoke()
        self.assertEqual(report.status,'unavailable'); self.assertFalse(report.execution_eligible)
        self.assertEqual(report.qualified_capabilities,())

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Actual arithmetic sandbox profile requires Linux')
    def test_actual_bubblewrap_grade_and_wrong_control_cannot_qualify_worker(self):
        for expression, status in (('n*(n+1)//2','passed'), ('n*(n-1)//2','failed'), ('1000*1000*1000','failed')):
            with self.subTest(expression=expression), self.network(expression):
                result = self.run_smoke()
                self.assertEqual(result.status,status)
                self.assertEqual(len(result.sandbox_evidence_digest),64)
                self.assertFalse(result.execution_eligible); self.assertEqual(result.qualified_capabilities,())
                self.assertEqual(result.observed_model,'observed-model')
                self.assertEqual(len(result.observation_digest),64)
        self.assertEqual(list(self.tree.iterdir()),[])
        outputs = [json.loads(path.read_text()) for path in (self.root/'.agent-factory/sandbox-evidence').glob('*/stdout.txt')
                   if path.read_text().strip()]
        self.assertEqual(len(outputs), 2)
        self.assertTrue(all(out['limits'] == {'address_space_bytes': 64*1024**2, 'cpu_seconds': 1} for out in outputs))
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM worker_qualifications').fetchone()[0],0)
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM credential_issuances WHERE status='active'").fetchone()[0],0)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Actual arithmetic sandbox profile requires Linux')
    def test_invalid_candidate_never_reaches_sandbox(self):
        with self.network('open("private")'), patch.object(self.sandbox,'execute',side_effect=AssertionError('must not execute')):
            result = self.run_smoke()
        self.assertEqual(result.status,'failed'); self.assertEqual(result.reason,'candidate_rejected')
        self.assertIsNone(result.sandbox_evidence_digest)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Actual arithmetic sandbox profile requires Linux')
    def test_stale_wrong_worker_lease_and_nonempty_workspace_prevent_network(self):
        with patch.object(self.transport,'observe',side_effect=AssertionError('must not call provider')):
            for changes in ({'fencing_token':self.claim.fencing_token+1}, {'worker_id':'other'},
                            {'policy':replace(self.policy,max_seconds=6)},
                            {'policy':replace(self.policy,worktree=self.root)},
                            {'policy':replace(self.policy,max_output_chars=3000)}):
                self.assertEqual(self.run_smoke(**changes).status,'unavailable')
            sentinel = self.tree/'keep'; sentinel.write_bytes(b'unchanged')
            self.assertEqual(self.run_smoke().status,'unavailable'); self.assertEqual(sentinel.read_bytes(),b'unchanged')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Actual arithmetic sandbox profile requires Linux')
    def test_expired_lease_after_provider_prevents_grading(self):
        original = self.transport.observe
        def observe_then_expire(**kwargs):
            observation = original(**kwargs)
            self.storage.db.execute("UPDATE leases SET expires_at='2000-01-01T00:00:00Z' WHERE assignment_id=?",(self.claim.assignment_id,))
            self.storage.db.commit()
            return observation
        with self.network('n'), patch.object(self.transport,'observe',side_effect=observe_then_expire), \
             patch.object(self.sandbox,'execute',side_effect=AssertionError('must not execute')):
            self.assertEqual(self.run_smoke().status,'unavailable')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Actual arithmetic sandbox profile requires Linux')
    def test_disconnected_observation_after_actual_grading_cannot_pass(self):
        original = self.sandbox.execute
        def execute_then_disconnect(*args, **kwargs):
            result = original(*args, **kwargs)
            self.connections.disconnect(self.connection,actor='Owner',tenant='local')
            return result
        with self.network('n*(n+1)//2'), patch.object(self.sandbox,'execute',side_effect=execute_then_disconnect):
            result = self.run_smoke()
        self.assertEqual(result.status,'unavailable'); self.assertFalse(result.execution_eligible)


if __name__=='__main__': unittest.main()
