"""One bounded credential-backed observation for a separately trusted evaluator.

No qualification writer, default model, browser route or automatic authority.
The child only speaks HTTPS; it never executes returned text or loads tools.
"""
from dataclasses import asdict, dataclass, field
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
HTTP_TIMEOUT_SECONDS = 10
MAX_IPC_BYTES = 3500
STOP_JOIN_SECONDS = 1
OPERATION = 'provider_canary_observation'
TOOL = 'openai-responses-canary-v1'
# Exact across JSON integer consumers; a metadata bound, not a spending limit.
MAX_USAGE_TOKENS = 2**53 - 1


@dataclass(frozen=True)
class CanaryTokenUsage:
    """Provider-reported totals, not a bill, price or settlement instruction."""
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def __post_init__(self):
        if any(type(value) is not int or not 0 <= value <= MAX_USAGE_TOKENS
               for value in (self.input_tokens, self.output_tokens, self.total_tokens)):
            raise ValueError('Usage requires bounded nonnegative integer tokens')
        if self.input_tokens + self.output_tokens != self.total_tokens:
            raise ValueError('Usage total must equal input plus output tokens')


def _reported_usage(value):
    """Map OpenAI Responses aggregate fields only; unknown is never zero."""
    if not isinstance(value, dict):
        return None
    try:
        return CanaryTokenUsage(**{name: value[name] for name in
            ('input_tokens', 'output_tokens', 'total_tokens')})
    except (KeyError, TypeError, ValueError):
        return None


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9._:/-]{1,128}', value) is not None


def _wire_body(model, prompt):
    return _json({'model': model, 'input': prompt, 'max_output_tokens': MAX_OUTPUT_TOKENS,
                  'store': False, 'stream': False, 'tools': []}).encode()


def _transport_contract():
    return {'method': 'POST', 'endpoint': 'https://api.openai.com/v1/responses', 'tool': TOOL,
            'max_calls': 1, 'max_input_bytes': MAX_INPUT_BYTES, 'max_output_tokens': MAX_OUTPUT_TOKENS,
            'max_body_bytes': MAX_BODY_BYTES, 'max_text_bytes': MAX_TEXT_BYTES,
            'max_ipc_bytes': MAX_IPC_BYTES, 'http_timeout_seconds': HTTP_TIMEOUT_SECONDS,
            'deadline_seconds': DEADLINE_SECONDS, 'deadline_origin': 'after_child_startup',
            'stop_join_seconds': STOP_JOIN_SECONDS}


@dataclass(frozen=True)
class PreparedCanaryRequest:
    """Non-authoritative hashes and scope; contains no prompt or credential."""
    worker_id: str
    role: str
    scope: QualificationScope
    mission_id: str
    prompt_digest: str
    body_digest: str
    request_digest: str
    transport_snapshot: str

    def __post_init__(self):
        if type(self.scope) is not QualificationScope or not _identifier(self.mission_id):
            raise ValueError('Invalid prepared canary scope')
        for value in (self.worker_id, self.role):
            if (not isinstance(value, str) or not 0 < len(value) <= 256
                    or not value.isprintable() or value != value.strip()):
                raise ValueError('Invalid prepared worker binding')
        for value in (self.prompt_digest, self.body_digest, self.request_digest):
            if not isinstance(value, str) or re.fullmatch('[a-f0-9]{64}', value) is None:
                raise ValueError('Invalid prepared request digest')
        if type(self.transport_snapshot) is not str or self.transport_snapshot != _json(_transport_contract()):
            raise ValueError('Prepared transport contract is not current')

    def canonical(self):
        return asdict(self)

    @property
    def digest(self):
        return _digest(_json(self.canonical()))


def prepare_canary_request(*, worker_id, role, scope, mission_id, prompt):
    """Pure preparation from an already resolved scope; no I/O or authority."""
    if not _identifier(mission_id) or not isinstance(prompt, str) or not 0 < len(prompt.encode()) <= MAX_INPUT_BYTES:
        raise ValueError('Invalid bounded canary request')
    if type(scope) is not QualificationScope:
        raise ValueError('An immutable resolved connection scope is required')
    if scope.provider != 'openai' or not _identifier(scope.requested_model):
        raise QualificationDenied('canary_route_unavailable')
    prompt_digest = _digest(prompt)
    # Preserve the exact pre-existing transport request hash for legacy callers.
    request_digest = _digest(_json({'scope': scope.__dict__, 'mission_id': mission_id,
                                   'prompt_digest': prompt_digest, 'tool': TOOL,
                                   'max_input_bytes': MAX_INPUT_BYTES,
                                   'max_output_tokens': MAX_OUTPUT_TOKENS,
                                   'deadline_seconds': DEADLINE_SECONDS}))
    return PreparedCanaryRequest(worker_id, role, scope, mission_id, prompt_digest,
        hashlib.sha256(_wire_body(scope.requested_model, prompt)).hexdigest(), request_digest,
        _json(_transport_contract()))


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
        result = {'observed_model': model, 'text': text}
        usage = _reported_usage(data.get('usage'))
        if usage is not None:
            result['usage'] = asdict(usage)
        return result
    except (ValueError, KeyError, TypeError, UnicodeError):
        return {'error': 'response_unqualified'}


def _request(secret, model, prompt):
    """Fixed endpoint, verified TLS, no proxy discovery, redirects or retries."""
    connection = http.client.HTTPSConnection('api.openai.com', timeout=HTTP_TIMEOUT_SECONDS,
                                             context=ssl.create_default_context())
    try:
        body = _wire_body(model, prompt)
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
        if len(payload) > MAX_IPC_BYTES:
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
        return json.loads(reader.recv_bytes(MAX_IPC_BYTES))
    except (OSError, ValueError, EOFError):
        return {'error': 'network_unavailable'}
    finally:
        if started:
            if process.is_alive():
                process.terminate(); process.join(STOP_JOIN_SECONDS)
            if process.is_alive():
                process.kill(); process.join(STOP_JOIN_SECONDS)
            process.close()
        reader.close(); writer.close()


@dataclass(frozen=True)
class CanaryObservation:
    scope: QualificationScope
    observed_model: str
    text: str = field(repr=False)
    request_digest: str
    observation_digest: str
    usage: CanaryTokenUsage | None = None

    def __post_init__(self):
        if self.usage is not None and type(self.usage) is not CanaryTokenUsage:
            raise ValueError('Observation usage must be immutable validated token metadata')


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

    def prepare(self, *, worker_id, role, purpose, mission_id, prompt):
        """Resolve current non-secret metadata, then prepare without dispatch."""
        if not _identifier(mission_id) or not isinstance(prompt, str) or not 0 < len(prompt.encode()) <= MAX_INPUT_BYTES:
            raise ValueError('Invalid bounded canary request')
        scope = self.resolver.scope(worker_id=worker_id, role=role, purpose=purpose)
        return prepare_canary_request(worker_id=worker_id, role=role, scope=scope,
                                      mission_id=mission_id, prompt=prompt)

    def observe(self, *, worker_id, role, purpose, mission_id, prompt, prepared=None):
        current_request = self.prepare(worker_id=worker_id, role=role, purpose=purpose,
                                       mission_id=mission_id, prompt=prompt)
        if prepared is not None and (type(prepared) is not PreparedCanaryRequest or prepared != current_request):
            raise QualificationDenied('canary_preparation_changed')
        scope = current_request.scope
        if not callable(self.authorize):
            raise QualificationDenied('canary_authority_required')
        observation = []
        request_digest = current_request.request_digest

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
            # Revalidate at the IPC consumer and exclude unrecognized metadata.
            usage = _reported_usage(result.get('usage'))
            result = {'observed_model': result['observed_model'], 'text': result['text']}
            if usage is not None:
                result['usage'] = asdict(usage)
            observation.append(result)
            # Broker audit persists bounded identity, counts and hashes, never text.
            return {'observed_model': result['observed_model'], 'text_digest': _digest(result['text']),
                    'observation_digest': _digest(_json({'request_digest': request_digest, 'result': result})),
                    **({'usage': result['usage']} if usage is not None else {})}

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
                                 request_digest, summary['observation_digest'],
                                 _reported_usage(observation[0].get('usage')))
