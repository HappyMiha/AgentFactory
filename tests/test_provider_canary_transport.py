"""Synthetic HTTPS responses and real child/SQLite boundaries; no provider calls."""
from dataclasses import replace
import json
import multiprocessing
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_factory import provider_canary_transport as transport
from agent_factory.credentials import CredentialBroker
from agent_factory.provider_qualification import QualificationDenied
import test_provider_connection_scope as fixture


def silent_child(pipe, marker, *_):
    try:
        Path(marker).write_text('child entered', encoding='utf-8')
        time.sleep(60)
    finally:
        pipe.close()


def observation_child(pipe, *_):
    pipe.send_bytes(b'{"observed_model":"fixture-observed","text":"fixture candidate"}')
    pipe.close()


def response(text='candidate', model='observed-model'):
    return {'model': model, 'status': 'completed', 'output': [
        {'type': 'message', 'role': 'assistant', 'status': 'completed',
         'content': [{'type': 'output_text', 'text': text}]}]}


class CanaryWireTests(unittest.TestCase):
    def test_only_provider_envelope_supplies_identity_and_completed_text(self):
        payload = response('{"model":"invented-by-generated-text"}')
        parsed = transport._decode(200, json.dumps(payload).encode())
        self.assertEqual(parsed['observed_model'], 'observed-model')
        for bad in (response(''), response('x'*2049), response(model='bad model'),
                    response() | {'status': 'incomplete'}, response() | {'output': [{'type': 'function_call'}]}):
            self.assertEqual(transport._decode(200, json.dumps(bad).encode()), {'error': 'response_unqualified'})
        self.assertEqual(transport._decode(200, b'x'*65537), {'error': 'response_too_large'})
        self.assertEqual(transport._decode(200, b'not JSON'), {'error': 'response_unqualified'})
        self.assertEqual(transport._decode(200, b'{"model":"one","model":"two"}'), {'error': 'response_unqualified'})

    def test_errors_are_bounded_without_guessing_budget_or_exposing_body(self):
        for status, reason in ((401, 'authentication_failed'), (403, 'access_denied'),
                               (404, 'model_or_route_unavailable'), (429, 'quota_or_rate_limit'),
                               (302, 'provider_unavailable'), (500, 'provider_unavailable')):
            self.assertEqual(transport._decode(status, b'private provider detail'), {'error': reason})

    def test_fixed_https_single_request_and_response_limit(self):
        calls = []
        class Connection:
            def request(self, method, path, **kwargs): calls.append((method, path, kwargs))
            def getresponse(self): return self
            status = 200
            def read(self, limit):
                self.limit = limit
                return json.dumps(response()).encode()
            def close(self): self.closed = True
        connection = Connection()
        with patch.object(transport.http.client, 'HTTPSConnection', return_value=connection) as factory:
            self.assertEqual(transport._request('synthetic-key', 'requested', 'bounded fixture')['text'], 'candidate')
        self.assertEqual(factory.call_args.args, ('api.openai.com',))
        self.assertEqual(factory.call_args.kwargs['timeout'], 10)
        self.assertEqual(len(calls), 1); self.assertEqual(calls[0][:2], ('POST', '/v1/responses'))
        body = json.loads(calls[0][2]['body'])
        self.assertEqual(body, {'model': 'requested', 'input': 'bounded fixture', 'max_output_tokens': 512,
                                'store': False, 'stream': False, 'tools': []})
        self.assertEqual(connection.limit, 65537); self.assertTrue(connection.closed)

    def test_actual_spawn_response_and_timeout_leave_no_live_child(self):
        before = {p.pid for p in multiprocessing.active_children()}
        with patch.object(transport, '_child', observation_child):
            result = transport._bounded_request('synthetic-secret', 'fixture', 'fixture')
        self.assertEqual(result['observed_model'], 'fixture-observed')
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as folder:
            marker = str(Path(folder)/'entered.txt')
            with patch.object(transport, '_child', silent_child), patch.object(transport, 'DEADLINE_SECONDS', 2):
                self.assertEqual(transport._bounded_request(marker, 'fixture', 'fixture'), {'error': 'request_timeout'})
            self.assertEqual(Path(marker).read_text(), 'child entered')
        self.assertLess(time.monotonic()-started, 7)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before)


class CanaryAdmissionTests(unittest.TestCase):
    setUp = fixture.ProviderConnectionScopeTests.setUp
    resolver_for = fixture.ProviderConnectionScopeTests.resolver_for

    def client(self, authorize=None):
        return transport.ProviderCanaryTransport(self.connections, CredentialBroker(self.storage),
                                                 self.resolver, authorize=authorize)

    def observe(self, client, **changes):
        return client.observe(**({'worker_id': 'worker', 'role': 'Developer', 'purpose': 'coding',
                                  'mission_id': '1', 'prompt': 'Private synthetic canary source'} | changes))

    def test_default_denial_and_per_call_authority_prevent_network(self):
        with patch.object(transport, '_bounded_request', side_effect=AssertionError('network forbidden')):
            with self.assertRaisesRegex(QualificationDenied, 'canary_authority_required'):
                self.observe(self.client())
            for authorize in (lambda **_: False, lambda **_: 'yes', lambda **_: 1):
                with self.assertRaisesRegex(QualificationDenied, 'canary_authority_required'):
                    self.observe(self.client(authorize))
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM credential_issuances WHERE status='active'").fetchone()[0], 0)

    def test_real_broker_persists_hashes_only_and_never_qualifies(self):
        authorities = []
        def allow(**scope): authorities.append(scope); return True
        candidate = 'private synthetic generated candidate'
        with patch.object(transport, '_bounded_request', return_value={'observed_model': 'observed-model', 'text': candidate}) as request:
            result = self.observe(self.client(allow))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result.text, candidate); self.assertNotIn(candidate, repr(result))
        self.assertEqual(authorities[0]['max_calls'], 1); self.assertEqual(authorities[0]['max_output_tokens'], 512)
        self.assertEqual(authorities[0]['scope'], result.scope)
        self.assertEqual(authorities[0]['request_digest'], result.request_digest)
        dump = '\n'.join(self.storage.db.iterdump())
        for private in (candidate, 'Private synthetic canary source', 'synthetic-private-key-for-fixture'):
            self.assertNotIn(private, dump)
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM worker_qualifications').fetchone()[0], 0)
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM credential_issuances WHERE status='active'").fetchone()[0], 0)
        with self.assertRaises(QualificationDenied): self.resolver.resolve(worker_id='worker', role='Developer', purpose='coding')

    def test_quota_and_secret_echo_do_not_return_text_or_leave_handles(self):
        for wire, reason in (({'error': 'quota_or_rate_limit'}, 'quota_or_rate_limit'),
                             ({'observed_model': 'observed-model', 'text': 'synthetic-private-key-for-fixture'}, 'response_unqualified')):
            with patch.object(transport, '_bounded_request', return_value=wire):
                with self.assertRaisesRegex(QualificationDenied, reason): self.observe(self.client(lambda **_: True))
        self.assertEqual(self.storage.db.execute("SELECT COUNT(*) FROM credential_issuances WHERE status='active'").fetchone()[0], 0)

    def test_authority_exception_and_late_disconnect_do_not_return_observation(self):
        def broken(**_): raise RuntimeError('private authority exception')
        with patch.object(transport, '_bounded_request', side_effect=AssertionError('network forbidden')):
            with self.assertRaisesRegex(QualificationDenied, '^canary_authority_required$'):
                self.observe(self.client(broken))
        original = self.connections.execute
        def execute_then_disconnect(*args, **kwargs):
            result = original(*args, **kwargs)
            self.connections.disconnect(self.connection, actor='Owner', tenant='local')
            return result
        with patch.object(self.connections, 'execute', side_effect=execute_then_disconnect), \
             patch.object(transport, '_bounded_request', return_value={'observed_model': 'observed-model', 'text': 'fixture'}):
            with self.assertRaises(QualificationDenied): self.observe(self.client(lambda **_: True))

    def test_disconnected_connection_and_secret_prompt_cannot_call_provider(self):
        client = self.client(lambda **_: True)
        with patch.object(transport, '_bounded_request', side_effect=AssertionError('network forbidden')):
            with self.assertRaises(QualificationDenied): self.observe(client, prompt='synthetic-private-key-for-fixture')
            self.connections.disconnect(self.connection, actor='Owner', tenant='local')
            with self.assertRaises(QualificationDenied): self.observe(client)

    def test_unsupported_route_and_unbounded_input_fail_before_network(self):
        client = self.client(lambda **_: True)
        with patch.object(transport, '_bounded_request', side_effect=AssertionError('network forbidden')):
            for changes in ({'prompt': 'x'*4097}, {'prompt': ''}, {'mission_id': 'bad id'}):
                with self.assertRaises(ValueError): self.observe(client, **changes)
            scope = self.resolver.scope(worker_id='worker', role='Developer', purpose='coding')
            with patch.object(self.resolver, 'scope', return_value=replace(scope, provider='anthropic')):
                with self.assertRaisesRegex(QualificationDenied, 'canary_route_unavailable'): self.observe(client)


if __name__ == '__main__': unittest.main()
