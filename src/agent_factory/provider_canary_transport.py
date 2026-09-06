"""One bounded credential-backed observation for a separately trusted evaluator.

No qualification writer, default model, browser route or automatic authority.
The child only speaks HTTPS; it never executes returned text or loads tools.
"""
from dataclasses import dataclass, field
import hashlib
import http.client
import json
import multiprocessing
import re
import ssl

from .provider_qualification import QualificationDenied, QualificationScope

MAX_INPUT_BYTES = 4096
MAX_OUTPUT_TOKENS = 512
MAX_BODY_BYTES = 65536
MAX_TEXT_BYTES = 2048
DEADLINE_SECONDS = 15
OPERATION = 'provider_canary_observation'
TOOL = 'openai-responses-canary-v1'


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9._:/-]{1,128}', value) is not None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate response field')
        result[key] = value
    return result


def _decode(status, body):
    """Never interpret generated text as provider identity or authority."""
    if len(body) > MAX_BODY_BYTES:
        return {'error': 'response_too_large'}
    if status != 200:
        # 429 does not prove whether budget or a transient rate limit was hit.
        return {'error': {401: 'authentication_failed', 403: 'access_denied',
                         404: 'model_or_route_unavailable', 429: 'quota_or_rate_limit'}.get(status, 'provider_unavailable')}
    try:
        data = json.loads(body, object_pairs_hook=_unique)
        model = data['model']
        if not _identifier(model) or data['status'] != 'completed':
            raise ValueError()
        pieces = []
        for item in data['output']:
            if item['type'] == 'reasoning':
                continue
            if item['type'] != 'message' or item['role'] != 'assistant' or item['status'] != 'completed':
                raise ValueError()
            for part in item['content']:
                if part['type'] != 'output_text' or not isinstance(part['text'], str):
                    raise ValueError()
                pieces.append(part['text'])
        text = ''.join(pieces)
        if not text or len(text.encode()) > MAX_TEXT_BYTES:
            raise ValueError()
        return {'observed_model': model, 'text': text}
    except (ValueError, KeyError, TypeError, UnicodeError):
        return {'error': 'response_unqualified'}


def _request(secret, model, prompt):
    """Fixed endpoint, verified TLS, no proxy discovery, redirects or retries."""
    connection = http.client.HTTPSConnection('api.openai.com', timeout=10,
                                             context=ssl.create_default_context())
    try:
        body = _json({'model': model, 'input': prompt, 'max_output_tokens': MAX_OUTPUT_TOKENS,
                      'store': False, 'stream': False, 'tools': []}).encode()
        connection.request('POST', '/v1/responses', body=body,
                           headers={'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/json'})
        response = connection.getresponse()
        return _decode(response.status, response.read(MAX_BODY_BYTES + 1))
    finally:
        connection.close()


def _child(pipe, secret, model, prompt):
    try:
        try:
            result = _request(secret, model, prompt)
            # Reject even a credential echo before crossing IPC or writing evidence.
            if secret in _json(result):
                result = {'error': 'response_unqualified'}
        except Exception:
            result = {'error': 'network_unavailable'}
        payload = _json(result).encode()
        if len(payload) > 3500:
            payload = b'{"error":"response_too_large"}'
        pipe.send_bytes(payload)
    finally:
        pipe.close()


def _bounded_request(secret, model, prompt):
    context = multiprocessing.get_context('spawn')
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(writer, secret, model, prompt), daemon=True)
    started = False
    try:
        process.start(); started = True
        writer.close()
        # The child emits at most 3500 bytes, so join cannot wait on a large pipe write.
        process.join(DEADLINE_SECONDS)
        if process.is_alive():
            return {'error': 'request_timeout'}
        if process.exitcode != 0 or not reader.poll():
            return {'error': 'network_unavailable'}
        return json.loads(reader.recv_bytes(3500))
    except (OSError, ValueError, EOFError):
        return {'error': 'network_unavailable'}
    finally:
        if started:
            if process.is_alive():
                process.terminate(); process.join(1)
            if process.is_alive():
                process.kill(); process.join(1)
            process.close()
        reader.close(); writer.close()


@dataclass(frozen=True)
class CanaryObservation:
    scope: QualificationScope
    observed_model: str
    text: str = field(repr=False)
    request_digest: str
    observation_digest: str


class ProviderCanaryTransport:
    """Trusted host must atomically authorize/charge each exact bounded request.

    authorize(scope=..., mission_id=..., operation=..., request_digest=...,
    max_calls=1, max_input_bytes=4096, max_output_tokens=512, deadline_seconds=15)
    must return exactly
    True after current policy/account/budget checks. It is invoked inside existing
    connection admission immediately before the child starts. No resolver denies.
    A timeout can still incur provider charges; this layer never retries it.
    """
    def __init__(self, connections, broker, resolver, *, authorize=None):
        if resolver.connections is not connections:
            raise ValueError('Current connection resolver required')
        self.connections, self.broker, self.resolver = connections, broker, resolver
        self.authorize = authorize

    def observe(self, *, worker_id, role, purpose, mission_id, prompt):
        if not _identifier(mission_id) or not isinstance(prompt, str) or not 0 < len(prompt.encode()) <= MAX_INPUT_BYTES:
            raise ValueError('Invalid bounded canary request')
        scope = self.resolver.scope(worker_id=worker_id, role=role, purpose=purpose)
        if scope.provider != 'openai' or not _identifier(scope.requested_model):
            raise QualificationDenied('canary_route_unavailable')
        if not callable(self.authorize):
            raise QualificationDenied('canary_authority_required')
        observation = []
        request_digest = _digest(_json({'scope': scope.__dict__, 'mission_id': mission_id,
                                       'prompt_digest': _digest(prompt), 'tool': TOOL,
                                       'max_input_bytes': MAX_INPUT_BYTES,
                                       'max_output_tokens': MAX_OUTPUT_TOKENS,
                                       'deadline_seconds': DEADLINE_SECONDS}))

        def execute(environment, arguments):
            # This callback runs while CredentialConnections excludes disconnect.
            try:
                allowed = self.authorize(scope=scope, mission_id=mission_id, operation=OPERATION,
                    request_digest=request_digest, max_calls=1, max_input_bytes=MAX_INPUT_BYTES,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    deadline_seconds=DEADLINE_SECONDS)
            except Exception:
                allowed = False
            if allowed is not True:
                return {'error': 'canary_authority_required'}
            result = _bounded_request(environment['OPENAI_API_KEY'], scope.requested_model, prompt)
            if 'error' in result:
                return result
            if environment['OPENAI_API_KEY'] in _json(result):
                return {'error': 'response_unqualified'}
            observation.append(result)
            # Broker audit persists only bounded identity and hashes, never generated text.
            return {'observed_model': result['observed_model'], 'text_digest': _digest(result['text']),
                    'observation_digest': _digest(_json({'request_digest': request_digest, 'result': result}))}

        try:
            summary = self.connections.execute(scope.connection, actor=scope.actor, tenant=scope.tenant,
                broker=self.broker, mission_id=mission_id, tool_key=TOOL, operation=OPERATION,
                preapproved_operations={OPERATION}, prompt=prompt,
                arguments={'request_digest': request_digest}, executor=execute)
        except Exception:
            raise QualificationDenied('credential_observation_unavailable') from None
        if 'error' in summary:
            raise QualificationDenied(summary['error'])
        current = self.resolver.scope(worker_id=worker_id, role=role, purpose=purpose)
        if current != scope:
            raise QualificationDenied('connection_scope_changed')
        return CanaryObservation(scope, summary['observed_model'], observation[0]['text'],
                                 request_digest, summary['observation_digest'])
