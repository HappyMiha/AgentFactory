"""Versioned arithmetic smoke evidence, never coding/review qualification.

Only a small expression grammar is interpreted. Generated Python is never
compiled or evaluated, even inside the existing read-only-host sandbox.
"""
import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys

SUITE = 'arithmetic-expression-smoke.v1'
CASES = (0, 1, 2, 3, 7, 13, 32, 63, 100)
PROMPT = ('Return only one arithmetic expression in variable n computing the sum '
          'of integers from 1 through n, for integer n from 0 through 100. '
          'Use only n, integer constants, parentheses, +, -, *, // or %. '
          'No code fences, explanations, imports, calls or statements. Maximum 256 ASCII bytes.')
MAX_INTEGER = 1_000_000


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _parse(expression):
    if not isinstance(expression, str) or not expression.isascii() or not 0 < len(expression) <= 256:
        raise ValueError('candidate_rejected')
    try:
        root = ast.parse(expression.strip(), mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        raise ValueError('candidate_rejected') from None
    pending = [(root, 0)]; count = 0
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
               ast.Load, ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.UAdd, ast.USub)
    while pending:
        node, depth = pending.pop(); count += 1
        if type(node) not in allowed or count > 32 or depth > 8:
            raise ValueError('candidate_rejected')
        if isinstance(node, ast.Name) and node.id != 'n':
            raise ValueError('candidate_rejected')
        if isinstance(node, ast.Constant) and (type(node.value) is not int or abs(node.value) > 1000):
            raise ValueError('candidate_rejected')
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return root.body


def _value(node, n):
    if isinstance(node, ast.Constant):
        result = node.value
    elif isinstance(node, ast.Name):
        result = n
    elif isinstance(node, ast.UnaryOp):
        value = _value(node.operand, n)
        result = -value if isinstance(node.op, ast.USub) else value
    else:
        left, right = _value(node.left, n), _value(node.right, n)
        if isinstance(node.op, ast.Add): result = left + right
        elif isinstance(node.op, ast.Sub): result = left - right
        elif isinstance(node.op, ast.Mult): result = left * right
        elif isinstance(node.op, ast.FloorDiv): result = left // right
        else: result = left % right
    # Multiplication can temporarily reach at most 10**12 (40 bits), then fails.
    if abs(result) > MAX_INTEGER:
        raise ValueError('candidate_integer_limit')
    return result


def _grade_main(expression):
    # This trusted runner is launched with -I -S and has no package dependencies.
    # Limits are installed before parsing candidate data. Unsupported hosts deny.
    if not sys.platform.startswith('linux'):
        return 2
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (64 * 1024**2, 64 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
        node = _parse(expression)
        values = [_value(node, n) for n in CASES]
        print(json.dumps({'suite': SUITE, 'values': values,
            'limits': {'address_space_bytes': resource.getrlimit(resource.RLIMIT_AS)[0],
                       'cpu_seconds': resource.getrlimit(resource.RLIMIT_CPU)[0]}}, separators=(',', ':')))
        return 0
    except (ValueError, ArithmeticError, MemoryError, OSError, RecursionError):
        print('candidate_grading_failed', file=sys.stderr)
        return 2


@dataclass(frozen=True)
class ArithmeticSmokeEvidence:
    status: str
    reason: str
    suite_version: str = SUITE
    request_digest: str | None = None
    observation_digest: str | None = None
    candidate_digest: str | None = None
    sandbox_evidence_digest: str | None = None
    grader_digest: str | None = None
    observed_model: str | None = None
    execution_eligible: bool = False
    qualified_capabilities: tuple = ()


class ProviderCanaryEvaluator:
    """Trusted host supplies the matching worker/mission lease and empty worktree.

    The transport's per-call account/policy/budget authorizer remains required.
    This class writes no qualification record and does not accept passing checks
    from browser JSON, provider text or a caller-supplied grading result.
    """
    def __init__(self, transport, sandbox):
        from .provider_canary_transport import ProviderCanaryTransport
        from .sandbox import SandboxManager
        if (type(transport) is not ProviderCanaryTransport or type(sandbox) is not SandboxManager
                or transport.broker.storage is not sandbox.storage):
            raise ValueError('Shared trusted Core transport and sandbox required')
        self.transport, self.sandbox = transport, sandbox

    def _context(self, worker_id, assignment_id, fencing_token, policy):
        from .sandbox import BubblewrapBackend, SandboxPolicy
        if (not sys.platform.startswith('linux') or type(self.sandbox.backend) is not BubblewrapBackend
                or not self.sandbox.backend.availability()[0]):
            raise PermissionError('smoke_backend_unavailable')
        if (type(policy) is not SandboxPolicy or policy.workspace != self.sandbox.workspace
                or type(policy.max_seconds) is not int or not 1 <= policy.max_seconds <= 5
                or type(policy.max_output_chars) is not int or not 1 <= policy.max_output_chars <= 2048
                or policy.network != 'deny'):
            raise PermissionError('bounded_empty_smoke_workspace_required')
        canonical = SandboxPolicy.create(policy.workspace, policy.worktree, policy.temporary_paths,
            max_seconds=policy.max_seconds, max_output_chars=policy.max_output_chars, network=policy.network)
        if canonical != policy or any(policy.worktree.iterdir()):
            raise PermissionError('bounded_empty_smoke_workspace_required')
        self.sandbox.storage.assert_fenced_lease(assignment_id, fencing_token)
        row = self.sandbox.storage.db.execute('SELECT agent_id FROM assignments WHERE id=?', (assignment_id,)).fetchone()
        if not row or row['agent_id'] != worker_id:
            raise PermissionError('smoke_worker_lease_mismatch')

    def run(self, *, worker_id, role, mission_id, assignment_id, fencing_token, policy):
        evidence = {}
        try:
            self._context(worker_id, assignment_id, fencing_token, policy)
            observation = self.transport.observe(worker_id=worker_id, role=role, purpose='coding',
                                                  mission_id=mission_id, prompt=PROMPT)
            evidence = {'request_digest': observation.request_digest,
                        'observation_digest': observation.observation_digest,
                        'candidate_digest': _digest(observation.text), 'observed_model': observation.observed_model,
                        'grader_digest': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            try:
                _parse(observation.text)
            except ValueError:
                return ArithmeticSmokeEvidence('failed', 'candidate_rejected', **evidence)
            # Lease expiry while awaiting a provider must not admit sandbox work.
            self._context(worker_id, assignment_id, fencing_token, policy)
            result = self.sandbox.execute(assignment_id, fencing_token, policy,
                [sys.executable, '-I', '-S', str(Path(__file__).resolve()), '--grade', observation.text])
            evidence['sandbox_evidence_digest'] = result.evidence_digest
            self._context(worker_id, assignment_id, fencing_token, policy)
            current = self.transport.resolver.scope(worker_id=worker_id, role=role, purpose='coding')
            if current != observation.scope:
                raise PermissionError('smoke_connection_changed')
            if (result.status != 'succeeded' or result.returncode != 0 or result.timed_out
                    or result.output_limit_exceeded or not result.process_tree_contained or result.changed_files
                    or result.policy_digest != policy.digest or len(result.stdout) > 2048):
                return ArithmeticSmokeEvidence('failed', 'candidate_grading_failed', **evidence)
            try:
                report = json.loads(result.stdout)
                values = report['values']
                passed = (set(report) == {'suite', 'values', 'limits'} and report['suite'] == SUITE
                          and report['limits'] == {'address_space_bytes': 64 * 1024**2, 'cpu_seconds': 1}
                          and type(values) is list and len(values) == len(CASES)
                          and all(type(value) is int for value in values)
                          and values == [n * (n + 1) // 2 for n in CASES])
            except (ValueError, KeyError, TypeError):
                passed = False
            return ArithmeticSmokeEvidence('passed' if passed else 'failed',
                'arithmetic_cases_passed' if passed else 'arithmetic_cases_failed', **evidence)
        except Exception:
            # No private provider, storage, policy or filesystem errors in reports.
            return ArithmeticSmokeEvidence('unavailable', 'smoke_context_or_observation_unavailable', **evidence)


if __name__ == '__main__':
    raise SystemExit(_grade_main(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == '--grade' else 2)
