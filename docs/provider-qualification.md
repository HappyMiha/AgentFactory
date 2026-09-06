# Purpose-bound cloud capability evidence (AF-GC-009 component)

This first component gives Core and future Cloud consumers one contract for
cloud coding and independent review qualifications. It reuses Core's existing
immutable `worker_qualifications`, lifecycle, routing and workforce records.
There is no new database, migration, HTTP endpoint or Cloud qualification store.
The connection wizard and real provider qualification remain unfinished.

## Current local connection scope

`ProviderConnectionScopeResolver` connects the qualification reader to the
existing `CredentialConnections` metadata store. Trusted host configuration
supplies immutable `ProviderConnectionBinding` records for each worker, role and
purpose, including actor, tenant, connection reference, provider, requested model
and configuration digest. No HTTP route accepts these records or installs this
resolver automatically. Changing host configuration requires a new resolver;
bindings are copied and duplicate keys are rejected.

`scope(worker_id=..., role=..., purpose=...)` reads a local active connection and
returns a scope snapshot for a separately trusted evaluator. It does not read the
secret or establish a qualification. `resolve(...)` supplies the current scope to
the existing Core qualification service; `revalidate(receipt)` checks the current
binding and connection before revalidating the exact immutable Core receipt.
Missing or pending connections, another actor/tenant, provider mismatch, local
disconnect, reconnect and configuration changes fail closed. Core's existing
latest-record, expiry, identity and worker-lifecycle checks still apply.

The opaque connection generation derives from the canonical local metadata
database location and the connection UUID. Every connect creates a fresh UUID;
revoked references never reactivate. Restart at the same database preserves the
generation, while moving/copying the database or reconnecting invalidates earlier
scopes. This is a local metadata generation, not a provider account generation or
a secret fingerprint. Out-of-band database rollback, provider-side key rotation,
deleted OS credentials, expired subscriptions, quota and model access still need
the trusted host's actual credential/provider evaluation and revocation policy.

Connection metadata reads and Core qualification reads are serialized with local
disconnect through the existing metadata SQLite writer transaction. A read
already in progress may finish before disconnect returns; later reads reject.
The resolver performs no network calls or credential execution inside that
transaction. Its return value is a snapshot, not a lease: consumers must resolve
or revalidate again at their fallback, retry and admission boundaries. Do not
cache it as proof of continuing access, nor invoke connection operations from
inside `current_metadata(...)`; they need their own transaction. Actual execution
still goes through the existing mission policy and `CredentialConnections.execute`
broker, which independently serializes local disconnect with admission.

This component does not change Core routing automatically, run a canary, issue
account authority or bind a producer artifact. A host/Cloud consumer must install
the trusted resolver explicitly and retain Core's canonical-model independence
checks. Direct calls to the lower-level qualification service still require a
trusted current scope; browser-provided scopes remain invalid authority.

`test_provider_connection_scope` uses real local SQLite files with synthetic
credentials and evaluator records to verify generation, restart, cross-owner
denial, disconnect/reconnect, config changes, copied databases, receipt replacement,
lifecycle, expiry and a concurrent disconnect. It also confirms that active
metadata alone creates no qualification and that the resolver never reads secrets.
These tests are not live provider or native credential-store qualification.

## Trusted host boundary

### Arithmetic smoke evaluator

`ProviderCanaryEvaluator` joins the accepted observation transport to a small,
versioned deterministic grading suite: `arithmetic-expression-smoke.v1`. It asks
for an expression summing integers from 1 through n for n in 0..100 and compares
nine fixed cases with independently computed expected integers. The requested
prompt, provider observation, candidate digest and grading evidence remain
distinct. A correct result says only that this particular arithmetic smoke test
passed. It does not establish general coding skill, independent review, a
producer/reviewer pair or game readiness. This class never calls a qualification
writer or returns the purpose-specific qualification check set.

The host supplies the actual matching worker assignment/fencing token, its
mission context and a fresh empty worktree through the existing `SandboxPolicy`
and `SandboxManager`. The transport and sandbox must share Core storage. The
evaluator checks current lease ownership, bounded canonical policy and the empty
worktree before asking the provider, before grading and after grading. The
transport's separate atomic account/policy/budget authorizer remains mandatory;
the host must bind that mission authorization to this assignment. Observations
are rechecked against the current connection before a passing report. A report
is historical evidence, never a lease or execution permission.

Only the existing Linux Bubblewrap backend is supported by this initial profile.
Windows and other unsupported backends deny before a provider request; they do
not silently use an unenforced test backend. Merely finding Bubblewrap does not
prove a grading run succeeded: the actual sandbox result must succeed without
timeout, output overflow, changed files or loss of process containment.

Generated text is **not executed as Python**. Both the parent and fixed isolated
runner parse only a 256-byte ASCII expression. The grammar permits `n`, integer
constants up to 1000, parentheses, unary plus/minus and `+ - * // %`. Imports,
calls, attributes, loops, comprehensions, powers, shifts, other names and all
non-integer constants are rejected. AST size is at most 32 nodes and depth 8;
intermediate absolute values are at most 1,000,000. One multiplication can
temporarily reach at most 10^12 (40 bits) before rejection. There is no recursion
or allocation construct under candidate control beyond those fixed bounds.

The trusted runner uses Python `-I -S`, sets a 64 MiB address-space limit and a
one-second CPU limit before parsing, and interprets the validated arithmetic AST
without `eval`, `exec` or compilation of candidate text. Existing sandbox policy
adds at most five seconds of execution time and at most 2048 captured characters;
existing process cleanup can take additional bounded joins. The smoke worktree
must stay empty. The existing Bubblewrap profile exposes host paths read-only;
this is not host-read isolation and must never be used here for unrestricted
generated code. The tiny fixed interpreter gives candidate data no file, network,
import or process operation.

Frozen evidence contains bounded status/reason, suite version, provider-observed
identity and request/observation/candidate/grader/sandbox hashes, without candidate
source or filesystem paths. Every result retains `execution_eligible: false` and
empty `qualified_capabilities`, including success. Existing worker qualifications
are not renewed, replaced or invalidated. A future full evaluator still needs
actual account authority, stronger capability suites, independent-model evidence
and a reviewed lifecycle/qualification publication contract.

Tests use synthetic model responses and credentials with actual SQLite leases,
broker evidence and Linux Bubblewrap grading. They cover a correct expression,
a known wrong control, forbidden syntax/resource growth, late lease expiry and
disconnect, nonempty/out-of-scope worktrees and Windows denial. Linux execution
tests are explicitly skipped on other systems; those skips are not sandbox or
model acceptance. No live provider account or spend was used during development.

### Bounded observation transport prerequisite

`ProviderCanaryTransport` can make one credential-backed OpenAI Responses request
for a separately trusted evaluator. It uses the existing current-connection
resolver and credential broker. The initial route is OpenAI API only; there is
no default model, HTTP/UI endpoint, automatic account discovery or qualification
writer. Anthropic/CLI transports and the coding/review canary suite remain open.

Host composition must provide `authorize`, a trusted callable that checks current
mission/account policy and atomically reserves budget for each exact request
digest. It receives the connection scope, mission, operation and fixed call/token/
deadline bounds. Only an exact `True` admits the call. The callback runs inside
the existing connection admission immediately before network execution; absent,
false or failed authorization sends nothing. A callback that always returns true
is a test fixture, not a production authority. Repeated `observe` calls each need
fresh authorization; this transport does not implement a mission budget ledger.

Only a host-selected canary prompt up to 4096 UTF-8 bytes is accepted. The fixed
HTTPS endpoint is `api.openai.com/v1/responses`, with verified TLS, no environment
proxy discovery, redirects, retries, tools, streaming or requested response
storage. Each call requests at most 512 output tokens. A spawned child bounds
network work to 15 seconds after startup, followed by at most two seconds of
termination/kill joins. Response reads stop at 64 KiB plus one overflow byte;
accepted generated text is limited to 2048 UTF-8 bytes. The parent never runs
generated text. Host scripts must follow Python's normal spawn/main-guard rules.
The secret crosses only the private child IPC; it is not placed in command-line
arguments, environment variables or files. A synchronous admitted call can finish
before local disconnect; the existing metadata writer lock is held during it.

Timeout/cancellation does not prove the provider cancelled work or charged
nothing. Host budget approval must cover that uncertainty; there is no automatic
retry. The bounded reason `quota_or_rate_limit` deliberately does not infer the
cause of an HTTP 429. Other failures expose only bounded reason codes, never raw
provider bodies. Unknown/incomplete/refused/tool responses cannot supply an
observation. Identity comes from the completed provider response envelope, not a
requested alias or model-generated text; canonical mapping remains separately
trusted and is not learned here.

The frozen observation contains in-process text for the future evaluator, the
current scope, observed identity, a digest and optional immutable token usage.
Broker evidence retains only identity, validated counts and hashes, not
prompts/generated text; credential echoes are rejected.
Handles are revoked on every exit. Success creates no qualification and does not
invalidate or renew an earlier qualification: the future evaluator must fence
stale worker evidence, run its actual purpose-specific suite and publish through
the existing Core writer. This observation alone cannot establish coding,
independent review, model quality, quota headroom or game execution permission.

API contract sources reviewed 2026-09-06: [text generation](https://developers.openai.com/api/docs/guides/text)
and [Responses creation](https://developers.openai.com/api/reference/resources/responses/methods/create).
The tests use synthetic HTTPS envelopes and credentials, actual spawned child
termination and real SQLite/broker records. No provider account, live budget or
actual model capability was qualified by these tests.

#### Provider-reported token metadata

For the OpenAI Responses route, `CanaryObservation.usage` is either a frozen
`CanaryTokenUsage` or `None` (unknown). The three aggregate envelope fields
`usage.input_tokens`, `usage.output_tokens` and `usage.total_tokens` must all be
nonnegative integers, excluding booleans, fractions and numeric strings. Each
must be at most `2**53 - 1`, and the total must equal input plus output. This is
an exact JSON interoperability bound, not a provider quota or spending limit.
Valid counts above the requested output cap are retained without truncation.

These fields follow the [OpenAI Responses schema](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
(checked 2026-09-06). Cached/reasoning breakdowns are not added to aggregate
counts. This component does not retain or validate those breakdowns; it cannot
price them. Other metadata is discarded, and Chat Completions field names such
as `prompt_tokens`/`completion_tokens` are not substituted for this route.
Generated text never supplies usage.

Missing, null, partial, inconsistent or malformed aggregate counts remain
unknown; the otherwise valid text observation can still reach the evaluator.
An explicit valid all-zero tuple is distinct from unknown and still does not
prove that a request incurred no charge. Errors, incomplete responses and lost
responses retain the existing denial/uncertainty behavior. No usage is inferred
from text length, request limits, timeouts or a failed response.

Validated usage is checked again after child IPC and included in both the
observation digest and the existing broker evidence. Changing usage changes
that digest; it does not change the pre-call request digest. Without valid
usage, the optional wire/evidence field is omitted, preserving legacy hashes;
the original five-argument observation constructor defaults to unknown. No
database migration or automatic reservation, usage ingestion, settlement,
release, USD estimate, account grant or qualification is introduced. A future
trusted host must handle missing usage and actual billing uncertainty explicitly.

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
