# Purpose-bound cloud capability evidence (AF-GC-009 component)

This first component gives Core and future Cloud consumers one contract for
cloud coding and independent review qualifications. It reuses Core's existing
immutable `worker_qualifications`, lifecycle, routing and workforce records.
There is no new database, migration, HTTP endpoint or Cloud qualification store.
The connection wizard and real provider qualification remain unfinished.

## Trusted host boundary

`ProviderQualificationService` accepts evidence only from a trusted host
evaluator. It does not authenticate that evaluator, run its canary, inspect an
account, verify a provider signature or establish execution permission. Do not
expose `record`, the underlying storage writer, model mappings or an evaluator
checkbox as browser input. A document with hashes and true checks is not proof
of a real canary. No production evaluator or model mapping is installed here.

The host must first establish current actor/tenant/account access and actual
provider-observed identity, run a bounded canary using the separately authorized
credential/execution path, and retain its private evidence. Only opaque identity
references, version identifiers, bounded checks and artifact/observation digests
enter this contract. Credentials, prompts, generated source and raw provider
error bodies do not belong in these identifiers or Core qualification evidence.

`QualificationScope` binds actor, tenant, opaque connection reference and its
generation, provider, requested model, configuration digest and purpose. A
current trusted connection resolver must provide that scope when consuming the
receipt. Changing an account, configuration or access generation invalidates the
old scope. On disconnect, also fence the worker through the existing lifecycle
or append a failed qualification before allowing more consumption. This service
does not discover credential-store revocation by itself.

The allowed purposes are `coding` and `review`, yielding `cloud_coding` and
`independent_review` respectively. Coding evidence requires a bounded workspace,
a produced candidate and successful candidate tests. Review evidence requires a
bounded workspace, detection of a known defect and acceptance of a clean control.
The host evaluator must actually establish those results with a versioned suite;
the service validates their contract, not their truth. A JSON role-contract smoke
has neither purpose's evidence and cannot grant either capability. Generic health
dimensions other than this quality result remain unknown; this does not invent
measured latency, availability, safety or cost.

## Identity and immutable evidence

`CanonicalModels` is an explicit trusted mapping from `(provider, observed model)`
to a canonical underlying model identity. Requested aliases never populate it.
Different providers/resellers exposing the same model must map to the same
canonical identity. Ambiguous, unobservable, auto-routed or unsupported identities
remain unqualified. Existing adapter metadata named `effective_model` is not by
itself provider observation: the host must inspect its provenance. The host must
review mapping updates; no mappings are learned from model-generated text.

`record(...)` appends a normal immutable worker qualification with schema
`core.provider-qualification.v1`, the exact scope, observed and canonical model,
mapping digest, suite version, private artifact/observation digests, required
checks and issued/expiry times. Its lifetime is 1 second to 24 hours. Failed
checks append failure, so earlier successful rows cannot silently win. Invalid
requests/unknown observations are rejected without creating a new row; hosts
must use existing lifecycle revocation when a connection becomes unusable.

`resolve(worker_id=..., role=..., scope=...)` returns a frozen
`QualificationReceipt` only for the latest qualification of that worker, the
matching role/provider/scope, active lifecycle, current database validity,
current mapping, valid evidence digest and current bounded evidence lifetime.
`revalidate(receipt)` also checks the exact qualification ID and all receipt
fields. Fabricating a different canonical identity inside a receipt cannot
change the stored evidence. A later failed row, quarantine, expiry or changed
trusted scope prevents reuse. The existing one-latest-qualification-per-worker
rule remains: do not assume one logical worker simultaneously holds independent
coding and review qualifications.

## Routing and workforce consumption

Construct `AgentRouter(storage, qualification_service=service)` or
`WorkforceComposer(storage, qualification_service=service)` for this profile.
They must share the same Core storage object. Once configured, omitting purpose
scopes fails closed instead of falling back to the historical caller-labelled
profile. Existing constructors without the service keep their prior behavior;
that historical behavior is not cloud capability or independence qualification.

For routing, supply `qualification_scopes` keyed by every candidate's worker ID.
Candidate provider and requested-model label must match the trusted scope. All
candidates share actor, tenant and purpose. Review routing additionally needs a
current coding `producer_receipt` for the same actor/tenant. The trusted caller
must bind it to the actual producer's execution/artifact record; choosing an
unrelated producer receipt is not evidence of that relationship. This component
does not create that execution record or authorize a review job.

Every eligible review candidate, including every fallback, must have a different
canonical model from the producer. The requested alias and the older
`producer_model` display field cannot waive this check. A missing or forged
producer receipt fails. Each eligible snapshot stores the observed/canonical
identity and exact qualification evidence digest. Replaying a routing key
revalidates its qualifications; changed eligibility requires a new decision key,
not resurrection of an old fallback chain.

For workforce pools, set `qualification_scopes` to worker/scope pairs and, for
review, `producer_receipt`. Replica independence uses canonical identities.
Human diversity/replica exceptions cannot make a conflicting producer eligible.
Replaying a composition checks the current purpose-bound snapshots against the
stored ones. Historical profiles retain their existing serialized request shape.

Receipts and stored routing/workforce objects are snapshots, not leases. Before
dispatch or fallback, resolve the current connection scope, revalidate evidence
and bind the exact qualification into the existing atomic worker admission and
execution approval boundary. Holding an old Python object does not preserve its
authority. Real Cloud/runtime composition still needs that separately reviewed
integration; this component supplies no execution, spending or launch permission.

## Validation and remaining acceptance

Tests use synthetic trusted-host mappings, observations and checks with real
SQLite immutability/restart behavior. They cover all scope dimensions, observed
versus requested identities, schema/purpose failures, expiry, latest-row and
lifecycle revocation, forged receipts, same-model reseller aliases, producer
scope, fallback/replay invalidation, workforce independence and legacy request
compatibility. They do not call a provider or certify coding/model quality.

Whole AF-GC-009 remains incomplete until the supported login/device/key wizard,
trusted host issuers/current connection resolvers, actual producer bindings and
authorized disposable-account canaries establish at least one cloud coding and
independent review route. Auth, quota, model access, capability and network errors
still need actual route-specific classification. Cloud must consume the accepted
Core contract and cannot mint its own substitute authority.
