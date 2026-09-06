"""Synthetic HTTPS responses and real child/SQLite boundaries; no provider calls."""
from dataclasses import FrozenInstanceError, asdict, replace
import json
import hashlib
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


def usage_child(pipe, *_):
    # Exercise the production child encoder/size/secret checks with synthetic HTTPS.
    payload = response() | {'usage': {'input_tokens': 12, 'output_tokens': 5, 'total_tokens': 17}}
    with patch.object(transport, '_request', return_value=transport._decode(200, json.dumps(payload).encode())):
        transport._child(pipe, 'synthetic-key', 'fixture', 'fixture')


def response(text='candidate', model='observed-model'):
    return {'model': model, 'status': 'completed', 'output': [
        {'type': 'message', 'role': 'assistant', 'status': 'completed',
         'content': [{'type': 'output_text', 'text': text}]}]}


class CanaryWireTests(unittest.TestCase):
    def test_responses_usage_maps_aggregate_counts_without_double_counting_details(self):
        usage = {'input_tokens': 12, 'output_tokens': 5, 'total_tokens': 17,
                 'input_tokens_details': {'cached_tokens': 9},
                 'output_tokens_details': {'reasoning_tokens': 3}, 'private_extra': 'discard me'}
        parsed = transport._decode(200, json.dumps(response() | {'usage': usage}).encode())
        self.assertEqual(parsed['usage'], {'input_tokens': 12, 'output_tokens': 5, 'total_tokens': 17})
        self.assertNotIn('discard me', json.dumps(parsed))
        # Even valid reported counts beyond the requested cap must not be truncated.
        usage = {'input_tokens': 0, 'output_tokens': 513, 'total_tokens': 513}
        self.assertEqual(transport._decode(200, json.dumps(response() | {'usage': usage}).encode())['usage'], usage)

    def test_missing_partial_malformed_and_wrong_provider_usage_stays_unknown(self):
        valid = {'input_tokens': 12, 'output_tokens': 5, 'total_tokens': 17}
        variants = [None, {}, [], '17', {'prompt_tokens': 12, 'completion_tokens': 5, 'total_tokens': 17}]
        variants += [{k: v for k, v in valid.items() if k != missing} for missing in valid]
        for name in valid:
            variants += [valid | {name: value} for value in
                         (True, False, -1, 1.0, '12', None, [], {}, transport.MAX_USAGE_TOKENS+1)]
        variants += [valid | {'total_tokens': 18},
                     {'input_tokens': transport.MAX_USAGE_TOKENS, 'output_tokens': 1,
                      'total_tokens': transport.MAX_USAGE_TOKENS+1}]
        for usage in variants:
            with self.subTest(usage=usage):
                parsed = transport._decode(200, json.dumps(response() | {'usage': usage}).encode())
                self.assertEqual(parsed, {'observed_model': 'observed-model', 'text': 'candidate'})
        # Generated text cannot become envelope usage.
        parsed = transport._decode(200, json.dumps(response(json.dumps(valid))).encode())
        self.assertNotIn('usage', parsed)

    def test_reported_zero_and_exact_integer_boundary_are_distinct_from_unknown(self):
        for count in (0, transport.MAX_USAGE_TOKENS):
            usage = {'input_tokens': count, 'output_tokens': 0, 'total_tokens': count}
            self.assertEqual(transport._decode(200, json.dumps(response() | {'usage': usage}).encode())['usage'], usage)
        self.assertIsNone(transport._reported_usage(None))

    def test_usage_metadata_is_frozen_and_validated_for_host_callers(self):
        usage = transport.CanaryTokenUsage(12, 5, 17)
        with self.assertRaises(FrozenInstanceError): usage.total_tokens = 0
        for values in ((True, 0, 1), (-1, 1, 0), (1, 2, 4), (0, 1.0, 1),
                       (transport.MAX_USAGE_TOKENS, 1, transport.MAX_USAGE_TOKENS+1)):
            with self.assertRaises(ValueError): transport.CanaryTokenUsage(*values)
        with self.assertRaisesRegex(ValueError, 'immutable'):
            transport.CanaryObservation(None, 'model', 'text', 'request', 'observation', asdict(usage))

    def test_actual_spawn_preserves_usage_through_production_child_encoder(self):
        with patch.object(transport, '_child', usage_child):
            result = transport._bounded_request('synthetic-key', 'fixture', 'fixture')
        self.assertEqual(result['usage'], {'input_tokens': 12, 'output_tokens': 5, 'total_tokens': 17})

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

    def prepare(self, client):
        return client.prepare(worker_id='worker', role='Developer', purpose='coding',
                              mission_id='1', prompt='Private synthetic canary source')

    def test_pure_preparation_uses_resolved_scope_without_io_and_preserves_old_hash(self):
        scope = self.resolver.scope(worker_id='worker', role='Developer', purpose='coding')
        prompt = 'Private synthetic canary source'
        before = self.storage.db.total_changes
        with patch.object(self.resolver, 'scope', side_effect=AssertionError('No resolver I/O')), \
             patch.object(self.store, 'get', side_effect=AssertionError('No secret read')), \
             patch('builtins.open', side_effect=AssertionError('No file I/O')), \
             patch.object(transport.http.client, 'HTTPSConnection', side_effect=AssertionError('No network')):
            prepared = transport.prepare_canary_request(worker_id='worker', role='Developer', scope=scope,
                                                       mission_id='1', prompt=prompt)
        old = {'scope': scope.__dict__, 'mission_id': '1', 'prompt_digest': hashlib.sha256(prompt.encode()).hexdigest(),
               'tool': 'openai-responses-canary-v1', 'max_input_bytes': 4096,
               'max_output_tokens': 512, 'deadline_seconds': 15}
        self.assertEqual(prepared.request_digest, hashlib.sha256(json.dumps(old, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode()).hexdigest())
        self.assertEqual(self.storage.db.total_changes, before)
        self.assertNotIn(prompt, repr(prepared))
        self.assertNotIn(prompt, json.dumps(prepared.canonical()))
        with self.assertRaises(FrozenInstanceError): prepared.mission_id = '2'
        snapshot = prepared.canonical(); snapshot['scope']['actor'] = 'Other'
        self.assertEqual(prepared.scope.actor, 'Owner')

    def test_metadata_preparation_cannot_issue_credentials_reserve_or_authorize(self):
        def forbidden(**_): raise AssertionError('No authority callback')
        client = self.client(forbidden)
        before = '\n'.join(self.storage.db.iterdump())
        with patch.object(self.store, 'get', side_effect=AssertionError('No secret read')), \
             patch.object(client.broker, 'issue', side_effect=AssertionError('No credential issuance')), \
             patch.object(transport, '_bounded_request', side_effect=AssertionError('No dispatch')):
            prepared = self.prepare(client)
        self.assertEqual(before, '\n'.join(self.storage.db.iterdump()))
        self.assertEqual(prepared.scope.connection, self.connection)
        with patch.object(transport, '_bounded_request', side_effect=AssertionError('No dispatch')):
            with self.assertRaisesRegex(QualificationDenied, 'canary_authority_required'):
                self.observe(self.client(), prepared=prepared)

    def test_prepared_body_matches_actual_http_bytes_and_authorized_request(self):
        calls, grants = [], []
        class Connection:
            status = 200
            def request(self, method, path, **kwargs): calls.append((method, path, kwargs['body']))
            def getresponse(self): return self
            def read(self, limit): return json.dumps(response()).encode()
            def close(self): pass
        def authorize(**kwargs): grants.append(kwargs); return True
        client = self.client(authorize)
        prompt = 'A quoted "line"\nwith Unicode: \u0441\u043d\u0456\u0433'
        prepared = client.prepare(worker_id='worker', role='Developer', purpose='coding', mission_id='1', prompt=prompt)
        with patch.object(transport.http.client, 'HTTPSConnection', return_value=Connection()), \
             patch.object(transport, '_bounded_request', side_effect=transport._request):
            observed = self.observe(client, prepared=prepared, prompt=prompt)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ('POST', '/v1/responses'))
        self.assertEqual(json.loads(calls[0][2]), {'model': 'requested-model', 'input': prompt,
            'max_output_tokens': 512, 'store': False, 'stream': False, 'tools': []})
        self.assertEqual(prepared.body_digest, hashlib.sha256(calls[0][2]).hexdigest())
        self.assertEqual(observed.request_digest, prepared.request_digest)
        self.assertEqual(grants[0]['request_digest'], prepared.request_digest)

    def test_tampered_preparation_rejects_before_secret_or_authority(self):
        def forbidden(**_): raise AssertionError('No authority callback')
        client = self.client(forbidden); prepared = self.prepare(client)
        variants = [replace(prepared, **{name: 'b'*64}) for name in ('prompt_digest', 'body_digest', 'request_digest')]
        variants += [replace(prepared, mission_id='2'), replace(prepared, worker_id='other'),
                     replace(prepared, role='Reviewer'), prepared.canonical()]
        for changes in ({'actor': 'Other'}, {'tenant': 'other'}, {'connection_generation': 'new-generation'},
                        {'connection': 'b'*32}, {'requested_model': 'different-model'},
                        {'configuration_digest': 'b'*64}, {'purpose': 'review'}):
            variants.append(replace(prepared, scope=replace(prepared.scope, **changes)))
        with patch.object(self.store, 'get', side_effect=AssertionError('No secret read')), \
             patch.object(transport, '_bounded_request', side_effect=AssertionError('No dispatch')):
            for value in variants:
                with self.subTest(value=value), self.assertRaisesRegex(QualificationDenied, 'canary_preparation_changed'):
                    self.observe(client, prepared=value)
            with self.assertRaisesRegex(QualificationDenied, 'canary_preparation_changed'):
                self.observe(client, prepared=prepared, prompt='Changed prompt')

    def test_old_preparation_rejects_current_scope_or_transport_contract_changes(self):
        client = self.client(lambda **_: True); prepared = self.prepare(client)
        with patch.object(self.store, 'get', side_effect=AssertionError('No secret read')), \
             patch.object(transport, '_bounded_request', side_effect=AssertionError('No dispatch')):
            with patch.object(self.resolver, 'scope', return_value=replace(prepared.scope, configuration_digest='b'*64)):
                with self.assertRaisesRegex(QualificationDenied, 'canary_preparation_changed'):
                    self.observe(client, prepared=prepared)
            # HTTP timeout is deliberately outside the legacy request digest.
            with patch.object(transport, 'HTTP_TIMEOUT_SECONDS', 9):
                current = self.prepare(client)
                self.assertEqual(current.request_digest, prepared.request_digest)
                self.assertNotEqual(current.digest, prepared.digest)
                with self.assertRaisesRegex(QualificationDenied, 'canary_preparation_changed'):
                    self.observe(client, prepared=prepared)
        self.connections.disconnect(self.connection, actor='Owner', tenant='local')
        with patch.object(transport, '_bounded_request', side_effect=AssertionError('No dispatch')):
            with self.assertRaises(QualificationDenied): self.observe(client, prepared=prepared)

    def test_prepared_and_legacy_observe_return_identical_evidence(self):
        client = self.client(lambda **_: True); prepared = self.prepare(client)
        with patch.object(transport, '_bounded_request', return_value={'observed_model': 'observed-model', 'text': 'candidate'}):
            self.assertEqual(self.observe(client, prepared=prepared), self.observe(client))

    def test_usage_is_immutable_bound_in_evidence_and_persisted_without_sensitive_fields(self):
        client = self.client(lambda **_: True)
        wire = {'observed_model': 'observed-model', 'text': 'private synthetic candidate',
                'usage': {'input_tokens': 12, 'output_tokens': 5, 'total_tokens': 17}}
        with patch.object(transport, '_bounded_request', return_value=wire):
            first = self.observe(client)
        self.assertEqual(first.usage, transport.CanaryTokenUsage(12, 5, 17))
        expected = transport._digest(transport._json({'request_digest': first.request_digest, 'result': wire}))
        self.assertEqual(first.observation_digest, expected)
        wire['usage']['input_tokens'] = 13; wire['usage']['total_tokens'] = 18
        self.assertEqual(first.usage.input_tokens, 12)
        with patch.object(transport, '_bounded_request', return_value=wire):
            second = self.observe(client)
        self.assertEqual(first.request_digest, second.request_digest)
        self.assertNotEqual(first.observation_digest, second.observation_digest)
        dump = '\n'.join(self.storage.db.iterdump())
        self.assertIn(first.observation_digest, dump)
        self.assertIn('input_tokens', dump)
        for private in ('private synthetic candidate', 'Private synthetic canary source', 'synthetic-private-key-for-fixture'):
            self.assertNotIn(private, dump)
        for table in ('execution_usage_samples', 'execution_stage_reservations', 'execution_reservation_closures', 'worker_qualifications'):
            self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0], 0)

    def test_unknown_usage_keeps_legacy_observation_hash_and_does_not_infer_zero(self):
        client = self.client(lambda **_: True)
        legacy = {'observed_model': 'observed-model', 'text': 'candidate'}
        for extra in ({}, {'usage': None}, {'usage': {'input_tokens': True, 'output_tokens': 0, 'total_tokens': 1}}):
            with patch.object(transport, '_bounded_request', return_value=legacy | extra):
                result = self.observe(client)
            self.assertIsNone(result.usage)
            self.assertEqual(result.observation_digest, transport._digest(transport._json(
                {'request_digest': result.request_digest, 'result': legacy})))
            old = transport.CanaryObservation(result.scope, result.observed_model, result.text,
                                             result.request_digest, result.observation_digest)
            self.assertEqual(old, result)

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
