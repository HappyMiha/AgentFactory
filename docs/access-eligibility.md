# Access for a young game author (AF-GC-025)

A 12-year-old can keep an idea and use the ready-made offline template without
an AI account. `/access-guide`, linked from **Доступ до AI**, provides these two
working actions, a synthetic age-path selector (12, 13–15, 16–17, adult, unknown),
an adult setup checklist, and dated official connector sources. Downloading an
idea is a browser-local UTF-8 text file, not a server-side draft or AI generation.
The three-star template is a small fixed interaction, not an engine qualification
or a game generated from the idea. After the page loads, both work offline.

The age selector is informational. It sends no age request, does not persist in
cookies/browser storage, and never grants eligibility. There is no DOB, ID,
school, address, child name, guardian document upload, or automatic account
creation. Closing/navigating away clears the form; the downloaded file remains
on the user's device until deleted. There is no telemetry, external resource
load, model call, purchase, publication, or key transfer in the guide. Clicking an
explicit source link navigates to that provider with no referrer. The existing
home-page local draft/intake flow is also available; its own persistence applies.

## Reviewed connector information

`defaults/connector-eligibility.json` is the shipped snapshot, checked on
**2026-09-06**. It covers every shipped CLI plus the deterministic fallback and
the two distinct API key routes. Each external connector has actual official
source URLs and a check date. The record separates consumer account restrictions
from developer API obligations; it is not a universal legal opinion or approval
of a deployment in any jurisdiction. In particular:

- Codex's [authentication documentation](https://learn.chatgpt.com/docs/auth)
  establishes distinct ChatGPT and API account/data policies, not a verified
  consumer minimum age for this review. Consumer eligibility remains unknown and
  no login is offered. API safeguards are separately recorded from
  [OpenAI's under-18 guidance](https://developers.openai.com/api/docs/guides/safety-checks/under-18-api-guidance).
- [Claude consumer terms](https://www.anthropic.com/legal/consumer-terms) and
  [Anthropic's organizational minor guidance](https://support.claude.com/en/articles/9307344-responsible-use-of-anthropic-s-models-guidelines-for-organizations-serving-minors)
  address different account/product uses. An adult's personal account is not a
  qualified child-facing API application.
- The [Gemini CLI route documentation](https://geminicli.com/docs/resources/tos-privacy/)
  is read together with the newer [consumer account deprecation](https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals).
  [Developer API age restrictions](https://ai.google.dev/gemini-api/terms) prohibit
  using that route in applications directed at or likely accessed by minors.
  A parent's Developer API key is not a workaround. Vertex and Enterprise require
  their own contract review; this snapshot does not qualify either.
- [Antigravity's FAQ](https://antigravity.google/docs/faq) and
  [terms](https://antigravity.google/terms) include age and third-party access
  restrictions. No login is offered and no adapter execution is enabled here.
- [Ollama's terms](https://ollama.com/terms) and
  [privacy policy](https://ollama.com/privacy) have inconsistent child-related
  wording. This is not resolved by selecting the least restrictive sentence.
  Local software/model licensing and the real local-AI path remain AF-GC-027–031.
- [OpenClaw](https://openclaw.ai/) stays health-only; connected provider/channel
  terms still need review. No independently verified child account route is claimed.
- [Firecrawl terms](https://www.firecrawl.dev/terms-of-service) and
  [privacy policy](https://www.firecrawl.dev/privacy-policy) are both considered;
  a conditional provider permission does not establish our own child deployment.

The JSON contains concise summaries of these sources. Its `review_due` is
**2026-10-06**: a product choice of at most 30 days, not a provider guarantee.
Future-dated, stale, malformed or unavailable snapshots deny new key setup.
Review earlier if terms or integration behavior changes. Updating the snapshot
changes its SHA-256 revision, invalidating prior setup approvals. Merely advancing
the date without checking the official sources is not a review. Unknown connector
IDs and additional routes stay unavailable pending a reviewed catalogue change.

## Trusted adult setup boundary

`credential_web.install_routes` composes the separate read-only guide installer;
no changes to central `web.py` are required. The default app intentionally has no
trusted eligibility resolver, so **new credential entry is disabled even for a
local operations owner**. Existing stored access can still be listed and revoked.
This is a deliberate tightening of the old key-entry UI. No existing credential,
workspace, claim, or provider execution gate is rewritten or migrated.

A separately reviewed host integration can set
`app.state.connector_setup_approval` to a synchronous in-process resolver. It is
called with the authenticated `actor`, fixed `local` tenant, specific `provider`
and canonical absolute `workspace` from the app. The resolver must bind this
supplied workspace exactly, including Windows long-path normalization; it must
not reconstruct it from a TEMP alias or browser input. It must resolve current independent verification and
revocation from host authority and return an `AdultSetupApproval` or `None`.
Never populate it from body/query/header values, a browser age, guardian checkbox,
local role alone, a copied Cloud identity, or the possession of an API key.
There is no HTTP endpoint to create this approval and no sample production
approval supplied by the application.

The immutable value binds that exact actor/tenant/provider/workspace, a nonempty
jurisdiction and private review reference, current catalogue digest, aware issue
and expiry times with at most 24 hours validity, verified account/data reviews,
`age_band=adult`, and `purpose=adult_self_use`. It is not a signed transport token:
the in-process host is the trust boundary. A dictionary, missing context, another
actor/workspace/provider, minor/unknown age, guardian purpose, stale digest,
future/expired/naive timestamps or failing resolver is denied. Every GET/POST
re-resolves current authority; approvals are not cached by the service. Private
context is not returned to the browser, stored in this module, or logged.
Only public decision codes and an expiry deadline are returned. The UI closes
and clears key entry at expiry or failed refresh. Superseded refresh responses
are discarded, including those pending when a POST denies eligibility; an old
response cannot reopen entry after a newer denial. The server rechecks before
reading a secret-bearing body and again for the selected route before storage.
The existing body bound, authentication/origin/scope/confirmation checks and
secret response firewall remain in force. Revocation racing an already executing
trusted storage operation is not transactional cancellation of that operation.

This narrow approval permits **adult key storage only**, on the already supported
Windows store; it does not permit inference, spend, a minor route, or account
sharing. Operators must separately establish account eligibility under the exact
current contract and jurisdiction and explain actual transmission, retention,
deletion, and budget to the adult before issuing approval. Test fixtures simulate
that context and cannot be used as evidence that a real adult or account passed
verification. AF-GC-009 and hosted identity/admission integrations must supply
reviewed real authority rather than turn the age selector into an access grant.

## Adult involvement and the current minor boundary

The guide explains the sequence: review the exact country/age/provider path with
a responsible adult; verify adult authority and required consent; review data
handling; approve a bounded budget and the data to send before any separate
execution. Provider-owned authentication and billing belong to the qualified
adult/organization. Do not hand a child that person's credentials. Nothing in
this change processes minor personal data through a cloud provider or claims a
verified guardian process, age-assurance service, zero-retention configuration,
or approved child-facing deployment.

Cloud AF-CLD-021's trusted identity and approved-route policy remain separate.
No Core loopback principal or catalogue entry becomes a Cloud tenant principal.
Unknown/underage Cloud access remains blocked. A future minor route requires its
own jurisdiction, consent/revocation, safeguards, retention and budget evidence
and product acceptance. Real local inference remains explicitly AF-GC-027–031.
The independent fallback is available while those prerequisites are unmet.

## Verification

Service and production-app tests exercise substituted and expired contexts,
strict boolean reviews, absent authority, stale/failed catalogue, authorization
before body reading, selected-provider recheck, revocation and preserved delete.
Chromium covers 12, 13–15, 16–17 and adult synthetic examples at 390px, no age
requests or browser persistence, actual network-disabled demo/download, hidden
key entry, forged HTTP age input, expiry and revoked setup with working delete.
These are synthetic UX/security checks, not a study involving real children or
legal acceptance of a hosted pilot. Provider pages were reviewed manually; tests
do not scrape terms, log in, invoke providers, or assert future terms are unchanged.
