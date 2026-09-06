"""Actual SQLite metadata fences with synthetic credentials/evaluator evidence."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent_factory.credential_connections import CredentialConnections
from agent_factory.provider_connection_scope import ProviderConnectionBinding, ProviderConnectionScopeResolver
from agent_factory.provider_qualification import CHECKS, CanonicalModels, ProviderQualificationService, QualificationDenied
from agent_factory.storage import SQLiteStorage
from test_credential_connections import MemoryStore


class ProviderConnectionScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = MemoryStore()
        self.connections = CredentialConnections(self.root/'connections.db', store=self.store)
        self.connection = self.connections.connect(actor='Owner', tenant='local', provider='openai',
                                                   secret='synthetic-private-key-for-fixture')['id']
        self.storage = SQLiteStorage(self.root/'core.db'); self.addCleanup(self.storage.close)
        self.now = datetime.now(timezone.utc)
        self.qualifications = ProviderQualificationService(self.storage,
            CanonicalModels({('openai', 'observed-model'): 'fixture:canonical-model'}), clock=lambda: self.now)
        self.binding = ProviderConnectionBinding('worker', 'Developer', 'Owner', 'local', self.connection,
                                                 'openai', 'requested-model', 'a'*64, 'coding')
        self.resolver = self.resolver_for()

    def resolver_for(self, binding=None, connections=None, qualifications=None):
        return ProviderConnectionScopeResolver(connections or self.connections,
            qualifications or self.qualifications, [binding or self.binding])

    def scope(self, resolver=None):
        return (resolver or self.resolver).scope(worker_id='worker', role='Developer', purpose='coding')

    def record(self, *, passed=True):
        scope = self.scope()
        return self.qualifications.record(worker_id='worker', role='Developer', scope=scope,
            observed_model='observed-model', suite_version='synthetic-only.v1', artifact_digest='b'*64,
            observation_digest='c'*64, checks={key: passed for key in CHECKS['coding']})

    def resolve(self):
        return self.resolver.resolve(worker_id='worker', role='Developer', purpose='coding')

    def test_active_metadata_alone_has_no_qualification_or_secret_access(self):
        with patch.object(self.store, 'get', side_effect=AssertionError('must not read secret')):
            scope = self.scope()
            self.assertEqual(scope.connection, self.connection)
            self.assertEqual(len(scope.connection_generation), 64)
            with self.assertRaises(QualificationDenied): self.resolve()
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM worker_qualifications').fetchone()[0], 0)
        self.assertNotIn('synthetic-private-key', repr(scope))

    def test_binding_and_current_metadata_are_detached_immutable_snapshots(self):
        bindings = [self.binding]
        resolver = ProviderConnectionScopeResolver(self.connections, self.qualifications, bindings)
        bindings.clear()
        self.assertEqual(self.scope(resolver), self.scope())
        with self.assertRaises(FrozenInstanceError): self.binding.actor = 'Other'
        with self.connections.current_metadata(self.connection, actor='Owner', tenant='local') as metadata:
            with self.assertRaises(TypeError): metadata['status'] = 'revoked'

    def test_restart_resolves_exact_existing_qualification(self):
        self.record(); receipt = self.resolve()
        restarted = CredentialConnections(self.root/'connections.db', store=self.store)
        resolver = self.resolver_for(connections=restarted)
        self.assertEqual(resolver.revalidate(receipt), receipt)
        self.assertEqual(self.scope(resolver), receipt.scope)

    def test_disconnect_and_reconnect_do_not_revive_old_receipts(self):
        self.record(); receipt = self.resolve()
        self.store.fail_delete = True
        self.assertTrue(self.connections.disconnect(self.connection, actor='Owner', tenant='local')['os_removal_pending'])
        for operation in (self.scope, self.resolve, lambda: self.resolver.revalidate(receipt)):
            with self.assertRaisesRegex(QualificationDenied, 'connection_unavailable'): operation()
        other = self.connections.connect(actor='Owner', tenant='local', provider='openai', secret='synthetic-new-key')['id']
        resolver = self.resolver_for(replace(self.binding, connection=other))
        self.assertNotEqual(self.scope(resolver).connection_generation, receipt.scope.connection_generation)
        with self.assertRaisesRegex(QualificationDenied, 'connection_scope_changed'): resolver.revalidate(receipt)
        with self.assertRaises(QualificationDenied): resolver.resolve(worker_id='worker', role='Developer', purpose='coding')

    def test_cross_owner_tenant_provider_and_pending_connections_fail(self):
        for changes in ({'actor':'Other'}, {'tenant':'other'}, {'provider':'anthropic'}):
            with self.subTest(changes=changes), self.assertRaises(QualificationDenied):
                self.scope(self.resolver_for(replace(self.binding, **changes)))
        with self.connections._db() as db:
            db.execute("UPDATE connections SET status='pending' WHERE id=?", (self.connection,))
        with self.assertRaises(QualificationDenied): self.scope()

    def test_changed_configuration_model_and_purpose_reject_prior_evidence(self):
        self.record(); receipt = self.resolve()
        for changes in ({'configuration_digest':'d'*64}, {'requested_model':'another-model'}, {'purpose':'review'}):
            resolver = self.resolver_for(replace(self.binding, **changes))
            with self.subTest(changes=changes), self.assertRaises(QualificationDenied): resolver.revalidate(receipt)
        for changes in ({'worker_id':'other'}, {'role':'QA'}, {'purpose':'review'}, {'worker_id':[]}):
            with self.assertRaises(QualificationDenied):
                self.resolver.resolve(**({'worker_id':'worker','role':'Developer','purpose':'coding'} | changes))

    def test_copied_database_cannot_replay_original_namespace_generation(self):
        self.record(); receipt = self.resolve()
        copy = self.root/'copied.db'; shutil.copyfile(self.connections.database, copy)
        resolver = self.resolver_for(connections=CredentialConnections(copy, store=self.store))
        self.assertNotEqual(self.scope(resolver).connection_generation, receipt.scope.connection_generation)
        with self.assertRaisesRegex(QualificationDenied, 'connection_scope_changed'): resolver.revalidate(receipt)

    def test_core_latest_receipt_lifecycle_and_expiry_still_apply(self):
        self.record(); old = self.resolve()
        self.record()
        with self.assertRaises(QualificationDenied): self.resolver.revalidate(old)
        receipt = self.resolve()
        self.storage.set_worker_lifecycle('worker', 'quarantined', reason='Synthetic fixture')
        with self.assertRaises(QualificationDenied): self.resolver.revalidate(receipt)
        self.storage.set_worker_lifecycle('worker', 'active', reason='Synthetic fixture')
        self.now += timedelta(hours=2)
        with self.assertRaises(QualificationDenied): self.resolve()
        self.now -= timedelta(hours=2); self.record(passed=False)
        with self.assertRaises(QualificationDenied): self.resolve()

    def test_disconnect_serializes_with_qualification_read_across_instances(self):
        entered = threading.Event(); release = threading.Event(); disconnected = threading.Event()
        errors = []; results = []
        class BlockingQualification:
            def resolve(_, **kwargs):
                entered.set()
                if not release.wait(5): raise AssertionError('fixture timeout')
                return kwargs['scope']
        resolver = self.resolver_for(qualifications=BlockingQualification())
        def resolve():
            try: results.append(resolver.resolve(worker_id='worker', role='Developer', purpose='coding'))
            except Exception as error: errors.append(error)
        def disconnect():
            try:
                CredentialConnections(self.connections.database, store=self.store).disconnect(
                    self.connection, actor='Owner', tenant='local')
                disconnected.set()
            except Exception as error: errors.append(error)
        reader = threading.Thread(target=resolve); reader.start()
        writer = threading.Thread(target=disconnect)
        try:
            self.assertTrue(entered.wait(5))
            # A separate actual SQLite writer must fail while qualification reads.
            with sqlite3.connect(self.connections.database, timeout=0) as db:
                with self.assertRaises(sqlite3.OperationalError): db.execute('BEGIN IMMEDIATE')
            writer.start(); self.assertFalse(disconnected.is_set())
        finally:
            release.set(); reader.join(6)
            if writer.ident is not None: writer.join(6)
        self.assertFalse(reader.is_alive()); self.assertFalse(writer.is_alive())
        self.assertEqual(errors, []); self.assertEqual(len(results), 1); self.assertTrue(disconnected.is_set())
        with self.assertRaises(QualificationDenied): self.scope()

    def test_invalid_duplicate_or_unbounded_bindings_are_rejected(self):
        for bindings in ([], [self.binding]*65, [self.binding, self.binding], [{}]):
            with self.assertRaises(ValueError): ProviderConnectionScopeResolver(self.connections, self.qualifications, bindings)
        for changes in ({'connection':'not-a-reference'}, {'configuration_digest':'bad'}, {'purpose':'admin'}, {'role':' '}):
            with self.assertRaises(ValueError): replace(self.binding, **changes)
        with self.assertRaises(QualificationDenied): self.resolver.revalidate({'approved':True})


if __name__ == '__main__': unittest.main()
