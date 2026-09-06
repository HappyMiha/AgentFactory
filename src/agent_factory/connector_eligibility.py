"""Dated information and a trusted-host gate for adult credential setup only.

No browser input, saved key, local role, or informational age choice is an
eligibility approval. This module grants neither provider execution nor spend.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

CATALOG = Path(__file__).parent / 'defaults' / 'connector-eligibility.json'
CREDENTIAL_ROUTES = {'openai': 'openai-api', 'anthropic': 'anthropic-api'}


def utc_now():
    return datetime.now(timezone.utc)


def catalog_snapshot(*, at=None):
    raw = CATALOG.read_bytes()
    data = json.loads(raw)
    if data['schema_version'] != 1:
        raise ValueError('unsupported_eligibility_catalog')
    checked = date.fromisoformat(data['checked_at'])
    due = date.fromisoformat(data['review_due'])
    today = (at or utc_now()).date()
    data['current'] = checked <= today <= due and timedelta(0) < due - checked <= timedelta(days=30)
    data['revision'] = hashlib.sha256(raw).hexdigest()
    return data


@dataclass(frozen=True)
class AdultSetupApproval:
    """Trusted host's short-lived review result, never deserialized from HTTP.

    The host resolves revocation on every request. It must have independently
    verified the adult, exact account/contract and jurisdiction before issuance.
    No DOB or identity documents belong here. A fixture is not a live approval.
    """
    actor: str
    tenant: str
    provider: str
    workspace: str
    jurisdiction: str
    review_ref: str
    catalog_revision: str
    issued_at: datetime
    expires_at: datetime
    age_band: str = 'unknown'
    purpose: str = 'unknown'
    account_terms_reviewed: bool = False
    data_policy_reviewed: bool = False


def setup_decision(provider, approval, *, actor, workspace, tenant='local', at=None):
    """Return only public reason codes; never return identity/review material."""
    denied = lambda reason: {'allowed': False, 'reason': reason}
    if type(provider) is not str or provider not in CREDENTIAL_ROUTES:
        return denied('unsupported_route')
    current = at or utc_now()
    try:
        snapshot = catalog_snapshot(at=current)
        if not snapshot['current']:
            return denied('terms_review_due')
        route = next(x for x in snapshot['connectors'] if x['id'] == CREDENTIAL_ROUTES[provider])
        if route['status'] != 'adult_setup_review':
            return denied('route_unavailable')
        if type(approval) is not AdultSetupApproval:
            return denied('adult_review_required')
        if (approval.actor != actor or approval.tenant != tenant or tenant != 'local'
                or approval.provider != provider or not actor
                or approval.workspace != str(Path(workspace).absolute())):
            return denied('approval_scope_mismatch')
        if approval.age_band != 'adult' or approval.purpose != 'adult_self_use':
            return denied('minor_route_unavailable')
        if (approval.account_terms_reviewed is not True or approval.data_policy_reviewed is not True
                or not isinstance(approval.jurisdiction, str) or not approval.jurisdiction.strip()
                or not isinstance(approval.review_ref, str) or not approval.review_ref.strip()):
            return denied('adult_review_required')
        if approval.catalog_revision != snapshot['revision']:
            return denied('terms_review_due')
        if (approval.issued_at.utcoffset() is None or approval.expires_at.utcoffset() is None
                or not approval.issued_at <= current < approval.expires_at
                or not timedelta(0) < approval.expires_at - approval.issued_at <= timedelta(hours=24)):
            return denied('approval_expired')
    except Exception:
        return denied('eligibility_unavailable')
    return {'allowed': True, 'reason': 'adult_setup_only',
            'expires_at': approval.expires_at.isoformat()}


def request_setup_decision(request, provider, *, actor, workspace, tenant='local'):
    """Only an in-process host resolver can supply a reviewed approval.

    Resolver accepts server-authenticated scope, not Request/body/query/headers.
    Default composition intentionally has no resolver and denies new setup.
    """
    try:
        resolver = getattr(request.app.state, 'connector_setup_approval', None)
        approval = resolver(actor=actor, tenant=tenant, provider=provider, workspace=str(Path(workspace).absolute())) if callable(resolver) else None
    except Exception:
        return {'allowed': False, 'reason': 'eligibility_unavailable'}
    return setup_decision(provider, approval, actor=actor, workspace=workspace, tenant=tenant)
