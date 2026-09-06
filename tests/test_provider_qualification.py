"""Synthetic trusted-host evidence; no provider, credential or model invocation."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from agent_factory.adapters import HEALTH_DIMENSIONS
from agent_factory.agent_router import AgentRouter, RoutingCandidate
from agent_factory.provider_qualification import (
    CAPABILITIES, CHECKS, CanonicalModels, ProviderQualificationService,
    QualificationDenied, QualificationScope,
)
from agent_factory.roles import ContractField, RoleDefinition, RoleRegistry
from agent_factory.storage import SQLiteStorage
from agent_factory.workforce import RolePoolRequirement, WorkforceCandidate, WorkforceComposer


class ProviderQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state.db'
        self.storage = SQLiteStorage(self.path)
        self.now = datetime.now(timezone.utc)
        self.identities = CanonicalModels({('cloud-a', 'observed-a'): 'family:model-a',
            ('reseller', 'renamed-a'): 'family:model-a', ('cloud-b', 'observed-b'): 'family:model-b'})
        self.service = ProviderQualificationService(self.storage, self.identities, clock=lambda: self.now)
        RoleRegistry(self.storage).register(RoleDefinition(
            id='evaluator', version='1.0.0', purpose='Synthetic qualification contract',
            responsibilities=('Evaluate synthetic evidence',),
            inputs=(ContractField('task', 'object'),), outputs=(ContractField('result', 'object'),),
            tools=('read_file',), permissions=('read_project',), limits=(('max_seconds', 60),),
            evidence=(ContractField('digest', 'string'),)))

    def tearDown(self):
        self.storage.close()
        self.temp.cleanup()

    def scope(self, *, provider='cloud-a', purpose='coding', requested='selected-alias'):
        return QualificationScope('synthetic-owner', 'tenant-a', 'opaque-connection', 'generation-1',
            provider, requested, 'a' * 64, purpose)

    def record(self, worker='worker-a', *, scope=None, observed='observed-a', passed=True):
        scope = scope or self.scope()
        return self.service.record(worker_id=worker, role='Evaluator', scope=scope,
            observed_model=observed, suite_version='synthetic-fixture.v1',
            artifact_digest='b' * 64, observation_digest='c' * 64,
            checks={key: passed for key in CHECKS[scope.purpose]})

    def receipt(self, worker='worker-a', scope=None):
        return self.service.resolve(worker_id=worker, role='Evaluator', scope=scope or self.scope())

    @staticmethod
    def candidate(worker, scope):
        return RoutingCandidate(worker, scope.provider, scope.requested_model, .9, .1, 1, 10, 0)

    def route(self, scopes, *, key='test-route', producer=None):
        return AgentRouter(self.storage, qualification_service=self.service).route(
            decision_key=key, role_id='evaluator', role_version='1.0.0', qualification_role='Evaluator',
            required_capabilities={CAPABILITIES[next(iter(scopes.values())).purpose]},
            candidates=tuple(self.candidate(worker, scope) for worker, scope in scopes.items()),
            strategy='fallback', qualification_scopes=scopes, producer_receipt=producer)

    def pool(self, scopes, *, producer=None, replicas=1):
        return RolePoolRequirement(key='capability', role_id='evaluator', role_version='1.0.0',
            qualification_role='Evaluator', required_capabilities=(CAPABILITIES[next(iter(scopes.values())).purpose],),
            pool_strategy='fixed', routing_strategy='fallback', minimum_replicas=replicas,
            maximum_replicas=replicas, arbitration_rule='single' if replicas == 1 else 'unanimous',
            candidates=tuple(WorkforceCandidate(self.candidate(w, s)) for w, s in scopes.items()),
            require_model_independence=replicas > 1, qualification_scopes=tuple(scopes.items()),
            producer_receipt=producer)

    def compose(self, pool, key='test-composition'):
        return WorkforceComposer(self.storage, qualification_service=self.service).compose(
            composition_key=key, mission_key='synthetic-mission', pools=(pool,), budget=10)

    def test_immutable_receipt_survives_restart_and_separates_requested_observed_identity(self):
        ident = self.record()
        receipt = self.receipt()
        self.assertEqual(receipt.qualification_id, ident)
        self.assertEqual(receipt.scope.requested_model, 'selected-alias')
        self.assertEqual(receipt.effective_model, 'observed-a')
        self.assertEqual(receipt.canonical_model, 'family:model-a')
        for statement in ('UPDATE worker_qualifications SET status=\'failed\' WHERE id=?',
                          'DELETE FROM worker_qualifications WHERE id=?'):
            with self.assertRaises(sqlite3.IntegrityError):
                self.storage.db.execute(statement, (ident,))
            self.storage.db.rollback()
        self.storage.close()
        self.storage = SQLiteStorage(self.path)
        self.service = ProviderQualificationService(self.storage, self.identities, clock=lambda: self.now)
        self.assertEqual(self.service.revalidate(receipt), receipt)

    def test_every_scope_dimension_and_role_are_bound(self):
        self.record()
        for field, value in (
            ('actor', 'other'), ('tenant', 'other'), ('connection', 'other'),
            ('connection_generation', 'generation-2'), ('provider', 'reseller'),
            ('requested_model', 'other-alias'), ('configuration_digest', 'd' * 64), ('purpose', 'review')):
            with self.subTest(field=field), self.assertRaises(QualificationDenied):
                self.receipt(scope=replace(self.scope(), **{field: value}))
        with self.assertRaises(QualificationDenied):
            self.service.resolve(worker_id='worker-a', role='Other role', scope=self.scope())

    def test_failed_latest_result_and_lifecycle_revoke_old_receipt(self):
        self.record()
        receipt = self.receipt()
        self.storage.set_worker_lifecycle('worker-a', 'quarantined', reason='Synthetic revoke')
        with self.assertRaises(QualificationDenied):
            self.service.revalidate(receipt)
        self.storage.set_worker_lifecycle('worker-a', 'active', reason='Synthetic requalification')
        self.record(passed=False)
        with self.assertRaises(QualificationDenied):
            self.service.revalidate(receipt)
        with self.assertRaises(QualificationDenied):
            self.receipt()

    def test_expiry_future_issue_and_changed_identity_mapping_deny(self):
        self.record()
        receipt = self.receipt()
        self.now += timedelta(hours=1)
        with self.assertRaises(QualificationDenied): self.service.revalidate(receipt)
        self.now -= timedelta(hours=2)
        with self.assertRaises(QualificationDenied): self.service.revalidate(receipt)
        self.now += timedelta(hours=1)
        changed = ProviderQualificationService(self.storage,
            CanonicalModels({('cloud-a', 'observed-a'): 'family:different'}), clock=lambda: self.now)
        with self.assertRaises(QualificationDenied): changed.revalidate(receipt)

    def test_unknown_observation_and_json_smoke_never_grant_capability(self):
        with self.assertRaises(QualificationDenied): self.record(observed='selected-alias')
        self.storage.record_worker_qualification(worker_id='worker-a', provider_id='cloud-a', role='Evaluator',
            capabilities=['cloud_coding'], dimensions={key: {} for key in HEALTH_DIMENSIONS},
            evidence={'scope': 'local-role-contract-smoke-only', 'passed': True}, status='qualified', ttl_seconds=3600)
        with self.assertRaises(QualificationDenied): self.receipt()
        with self.assertRaises(RuntimeError): self.route({'worker-a': self.scope()})
        result = self.compose(self.pool({'worker-a': self.scope()}))
        self.assertNotEqual(result.status, 'ready')

    def test_check_types_purpose_suite_digests_and_lifetime_are_strict(self):
        params = dict(worker_id='worker-a', role='Evaluator', scope=self.scope(),
            observed_model='observed-a', suite_version='fixture', artifact_digest='b' * 64,
            observation_digest='c' * 64, checks={key: True for key in CHECKS['coding']})
        for change in ({'ttl_seconds': True}, {'ttl_seconds': 86401}, {'ttl_seconds': 0},
                       {'checks': {'json_smoke': True}}, {'checks': {key: 1 for key in CHECKS['coding']}},
                       {'suite_version': ''}, {'artifact_digest': 'invalid'}, {'observation_digest': 'invalid'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.service.record(**(params | change))
        self.assertEqual(self.storage.db.execute('SELECT COUNT(*) FROM worker_qualifications').fetchone()[0], 0)

    def test_forged_receipt_fields_cannot_substitute_canonical_identity(self):
        self.record()
        with self.assertRaises(QualificationDenied):
            self.service.revalidate(replace(self.receipt(), canonical_model='family:forged'))

    def test_review_excludes_producer_alias_from_entire_fallback_chain(self):
        self.record('producer')
        producer = self.receipt('producer')
        alias = self.scope(provider='reseller', purpose='review', requested='different-label')
        other = self.scope(provider='cloud-b', purpose='review')
        self.record('alias-reviewer', scope=alias, observed='renamed-a')
        self.record('other-reviewer', scope=other, observed='observed-b')
        decision = self.route({'alias-reviewer': alias, 'other-reviewer': other}, producer=producer)
        self.assertEqual(decision.fallback_chain, ('other-reviewer',))
        self.assertIn('producer_model_conflict', decision.excluded[0]['reasons'])
        self.assertEqual(decision.eligible[0]['model_identity'], 'family:model-b')
        with self.assertRaises(RuntimeError):
            self.route({'other-reviewer': other}, key='missing-producer')
        forged = replace(producer, canonical_model='family:another')
        with self.assertRaises(RuntimeError):
            self.route({'alias-reviewer': alias}, key='forged-producer', producer=forged)

    def test_routing_replay_revalidates_all_fallback_receipts(self):
        first, second = self.scope(), self.scope(provider='cloud-b')
        self.record('one', scope=first)
        self.record('two', scope=second, observed='observed-b')
        scopes = {'one': first, 'two': second}
        old = self.route(scopes)
        self.assertEqual(self.route(scopes), old)
        self.storage.set_worker_lifecycle('two', 'offline', reason='Synthetic fallback revoke')
        with self.assertRaises(QualificationDenied): self.route(scopes)
        fresh = self.route(scopes, key='fresh-decision')
        self.assertEqual(fresh.fallback_chain, ('one',))

    def test_workforce_uses_canonical_identity_and_revalidates_replay(self):
        first = self.scope()
        alias = self.scope(provider='reseller', requested='another-label')
        self.record('one', scope=first)
        self.record('alias', scope=alias, observed='renamed-a')
        result = self.compose(self.pool({'one': first, 'alias': alias}, replicas=2))
        self.assertNotEqual(result.status, 'ready')
        self.assertTrue(any(gap['kind'] == 'independence' for gap in result.gaps))
        pool = self.pool({'one': first})
        valid = self.compose(pool, 'valid')
        self.assertEqual(valid.status, 'ready')
        self.assertEqual(self.compose(pool, 'valid'), valid)
        self.record('one', passed=False)
        with self.assertRaises(QualificationDenied): self.compose(pool, 'valid')

    def test_workforce_review_requires_producer_and_no_exception_can_mint_identity(self):
        self.record('producer')
        alias = self.scope(provider='reseller', purpose='review')
        self.record('reviewer', scope=alias, observed='renamed-a')
        result = self.compose(self.pool({'reviewer': alias}, producer=self.receipt('producer')))
        self.assertNotEqual(result.status, 'ready')
        self.assertIn('producer_model_conflict', result.pools[0]['qualifications'][0]['reasons'])

    def test_scope_cannot_be_omitted_from_one_candidate(self):
        self.record()
        with self.assertRaises(ValueError):
            AgentRouter(self.storage, qualification_service=self.service).route(
                decision_key='missing-scope', role_id='evaluator', role_version='1.0.0',
                qualification_role='Evaluator', required_capabilities={'cloud_coding'},
                candidates=(self.candidate('worker-a', self.scope()),), strategy='fallback',
                qualification_scopes={})

    def test_configured_service_cannot_fall_back_to_legacy_profile(self):
        self.record()
        router = AgentRouter(self.storage, qualification_service=self.service)
        with self.assertRaises(QualificationDenied):
            router.route(decision_key='legacy-bypass', role_id='evaluator', role_version='1.0.0',
                qualification_role='Evaluator', required_capabilities={'cloud_coding'},
                candidates=(self.candidate('worker-a', self.scope()),), strategy='fallback')
        with self.assertRaises(QualificationDenied):
            self.compose(replace(self.pool({'worker-a': self.scope()}), qualification_scopes=()))

    def test_producer_actor_scope_and_revocation_invalidate_review_replay(self):
        self.record('producer')
        producer = self.receipt('producer')
        scope = self.scope(provider='cloud-b', purpose='review')
        self.record('reviewer', scope=scope, observed='observed-b')
        self.route({'reviewer': scope}, producer=producer)
        self.storage.set_worker_lifecycle('producer', 'offline', reason='Synthetic producer revoke')
        with self.assertRaises(RuntimeError): self.route({'reviewer': scope}, producer=producer)
        self.storage.set_worker_lifecycle('producer', 'active', reason='Synthetic restore')
        foreign = replace(self.scope(), actor='other-actor')
        self.record('foreign-producer', scope=foreign)
        with self.assertRaises(RuntimeError):
            self.route({'reviewer': scope}, key='foreign-producer', producer=self.receipt('foreign-producer', foreign))

    def test_legacy_composition_request_shape_stays_unchanged(self):
        self.record()
        pool = replace(self.pool({'worker-a': self.scope()}), qualification_scopes=())
        composer = WorkforceComposer(self.storage)
        first = composer.compose(composition_key='legacy', mission_key='fixture', pools=(pool,), budget=10)
        request = json.loads(self.storage.db.execute(
            'SELECT request_json FROM workforce_compositions WHERE id=?', (first.id,)).fetchone()[0])
        self.assertNotIn('qualification_scopes', request['pools'][0])
        self.assertNotIn('producer_receipt', request['pools'][0])
        self.assertEqual(composer.compose(composition_key='legacy', mission_key='fixture', pools=(pool,), budget=10), first)

    def test_workforce_cannot_mix_tenants_across_individually_valid_pools(self):
        self.record('one')
        other = replace(self.scope(), tenant='tenant-b')
        self.record('two', scope=other)
        first = self.pool({'one': self.scope()})
        second = replace(self.pool({'two': other}), key='other-pool')
        with self.assertRaises(QualificationDenied):
            WorkforceComposer(self.storage, qualification_service=self.service).compose(
                composition_key='cross-tenant', mission_key='fixture', pools=(first, second), budget=10)


if __name__ == '__main__':
    unittest.main()
