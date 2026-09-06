"""Synthetic policy cases, not age verification or a qualified minor deployment."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent_factory.connector_eligibility import AdultSetupApproval, CATALOG, catalog_snapshot, setup_decision

AT = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)


def approval_fixture(*, actor='Owner', tenant='local', provider='openai', workspace, **changes):
    approval = AdultSetupApproval(actor=actor, tenant=tenant, provider=provider,
        workspace=str(Path(workspace).absolute()), jurisdiction='synthetic-jurisdiction', review_ref='synthetic-review',
        catalog_revision=catalog_snapshot(at=AT)['revision'], issued_at=AT-timedelta(minutes=1),
        expires_at=AT+timedelta(hours=1), age_band='adult', purpose='adult_self_use',
        account_terms_reviewed=True, data_policy_reviewed=True)
    return replace(approval, **changes)


class ConnectorEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.workspace=Path(self.temp.name)
        self.approval=approval_fixture(workspace=self.workspace)

    def decision(self, approval=None, **changes):
        args=dict(actor='Owner',workspace=self.workspace,at=AT);args.update(changes)
        return setup_decision('openai', approval, **args)

    def test_default_unknown_minors_and_checkbox_cannot_grant_setup(self):
        for value in (None, {}, True, asdict(self.approval)):
            self.assertFalse(self.decision(value)['allowed'])
        for band in ('unknown','under_12','12','13-15','16-17','18','18+',None):
            with self.subTest(band=band):
                self.assertFalse(self.decision(replace(self.approval,age_band=band))['allowed'])
        for purpose in ('guardian','minor_service','adult_supervision','unknown'):
            self.assertFalse(self.decision(replace(self.approval,purpose=purpose))['allowed'])
        self.assertEqual(self.decision(self.approval),{'allowed':True,'reason':'adult_setup_only','expires_at':self.approval.expires_at.isoformat()})

    def test_account_scope_and_workspace_substitution_rejected(self):
        for change in (dict(actor='Other'),dict(tenant='other'),dict(provider='anthropic'),
                       dict(workspace=str(self.workspace/'other')),dict(jurisdiction=''),dict(review_ref=''),
                       dict(account_terms_reviewed=1),dict(data_policy_reviewed=False)):
            with self.subTest(change=change):
                self.assertFalse(self.decision(replace(self.approval,**change))['allowed'])
        self.assertFalse(self.decision(self.approval,tenant='other')['allowed'])
        for provider in ('unknown', [], None):
            self.assertFalse(setup_decision(provider,self.approval,actor='Owner',workspace=self.workspace,at=AT)['allowed'])

    def test_expired_future_naive_overlong_and_changed_catalog_rejected(self):
        for change in (dict(expires_at=AT),dict(issued_at=AT+timedelta(seconds=1)),
                       dict(expires_at=AT+timedelta(days=2)),dict(issued_at=AT.replace(tzinfo=None)),
                       dict(expires_at='tomorrow'),dict(catalog_revision='old')):
            with self.subTest(change=change):
                self.assertFalse(self.decision(replace(self.approval,**change))['allowed'])
        for at in (AT-timedelta(days=1), AT+timedelta(days=31)):
            self.assertEqual(self.decision(self.approval,at=at)['reason'],'terms_review_due')
        with patch.object(Path,'read_bytes',side_effect=OSError('private failure')):
            result=self.decision(self.approval)
        self.assertEqual(result,{'allowed':False,'reason':'eligibility_unavailable'})

    def test_catalog_covers_every_shipped_connector_with_dated_official_sources(self):
        snapshot=catalog_snapshot(at=AT)
        shipped=json.loads((CATALOG.parent/'providers.json').read_text())['providers']
        entries={x['id']:x for x in snapshot['connectors']}
        self.assertTrue({x['id'] for x in shipped} <= entries.keys())
        self.assertEqual(len(entries),len(snapshot['connectors']))
        self.assertTrue(snapshot['current'])
        for key, entry in entries.items():
            self.assertEqual(entry['checked_at'],snapshot['checked_at'])
            if key!='deterministic':self.assertTrue(entry['sources'])
            for source in entry['sources']:self.assertTrue(source['url'].startswith('https://'))
        self.assertEqual(entries['deterministic']['status'],'offline')
        self.assertFalse(any(x.get('login_url') for x in entries.values()))
