"""Trusted local connection bindings for existing Core qualification consumers.

No evaluator, provider login, secret inspection or execution authority is added.
Returned scopes/receipts are snapshots; resolve again at each consuming boundary.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import re
import sqlite3
from types import MappingProxyType

from .credential_connections import PROVIDERS
from .provider_qualification import QualificationDenied, QualificationReceipt, QualificationScope


@dataclass(frozen=True)
class ProviderConnectionBinding:
    worker_id: str
    role: str
    actor: str
    tenant: str
    connection: str
    provider: str
    requested_model: str
    configuration_digest: str
    purpose: str

    def __post_init__(self):
        for value in (self.worker_id, self.role):
            if (not isinstance(value, str) or not 0 < len(value) <= 256
                    or not value.isprintable() or value != value.strip()):
                raise ValueError('Invalid binding identifier')
        self.scope('validation-only')
        if not re.fullmatch('[a-f0-9]{32}', self.connection) or self.provider not in PROVIDERS:
            raise ValueError('Unsupported local connection binding')

    def scope(self, generation):
        return QualificationScope(self.actor, self.tenant, self.connection, generation,
                                  self.provider, self.requested_model, self.configuration_digest, self.purpose)


class ProviderConnectionScopeResolver:
    """Host-supplied immutable bindings; never construct these from browser JSON.

    Core qualification checks run while the local metadata transaction excludes
    disconnect. After return, a snapshot can become stale: this is not a lease,
    a provider-side revocation check or a replacement for credential execution.
    """

    def __init__(self, connections, qualifications, bindings):
        if not isinstance(bindings, (list, tuple)) or not 1 <= len(bindings) <= 64:
            raise ValueError('Expected 1 to 64 trusted connection bindings')
        indexed = {}
        for binding in bindings:
            if type(binding) is not ProviderConnectionBinding:
                raise ValueError('Expected a trusted connection binding')
            key = (binding.worker_id, binding.role, binding.purpose)
            if key in indexed:
                raise ValueError('Duplicate connection binding')
            indexed[key] = binding
        self.connections = connections
        self.qualifications = qualifications
        self._bindings = MappingProxyType(indexed)

    @contextmanager
    def _current(self, worker_id, role, purpose):
        if not all(isinstance(value, str) for value in (worker_id, role, purpose)):
            raise QualificationDenied('connection_binding_unavailable')
        binding = self._bindings.get((worker_id, role, purpose))
        if binding is None:
            raise QualificationDenied('connection_binding_unavailable')
        try:
            with self.connections.current_metadata(binding.connection, actor=binding.actor, tenant=binding.tenant) as current:
                if current['provider'] != binding.provider:
                    raise QualificationDenied('connection_provider_changed')
                yield binding.scope(current['generation'])
        except QualificationDenied:
            raise
        except PermissionError:
            raise QualificationDenied('connection_unavailable') from None
        except sqlite3.Error:
            raise QualificationDenied('connection_state_unavailable') from None

    def scope(self, *, worker_id, role, purpose):
        """Local metadata snapshot for a separately trusted evaluator, not evidence."""
        with self._current(worker_id, role, purpose) as scope:
            return scope

    def resolve(self, *, worker_id, role, purpose):
        with self._current(worker_id, role, purpose) as scope:
            return self.qualifications.resolve(worker_id=worker_id, role=role, scope=scope)

    def revalidate(self, receipt):
        if not isinstance(receipt, QualificationReceipt):
            raise QualificationDenied('qualification_receipt_required')
        with self._current(receipt.worker_id, receipt.role, receipt.scope.purpose) as scope:
            if scope != receipt.scope:
                raise QualificationDenied('connection_scope_changed')
            return self.qualifications.revalidate(receipt)
