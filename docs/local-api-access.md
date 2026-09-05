# Local API access

The Local Control Center is a single-operator service on this computer. Every
`/api` route, including health, diagnostics, schema, reads, uploads and mutations,
passes the same access boundary before request validation or storage access.
Domain approval, independent-review, role and execution-fence checks still apply.
This does not introduce a remotely deployable multi-user identity service.

## Operator policy

Configure the service process before starting `agent-factory web`:

| Environment setting | Default and meaning |
| --- | --- |
| `AGENT_FACTORY_API_TOKEN` | Empty: local-open mode. A nonempty credential requires bearer authentication or a browser session for every API route. |
| `AGENT_FACTORY_API_ACTOR` | `Founder`, the server-bound operator identity. Request JSON cannot choose another actor. |
| `AGENT_FACTORY_API_ROLE` | `operations_owner`, the role allowed on control-action commands. Other supported values: `mission_owner`, `security_reviewer`. |
| `AGENT_FACTORY_API_SCOPES` | `read,write,approve,control`. Set a comma-separated nonempty subset to restrict this operator. |
| `AGENT_FACTORY_API_TENANTS` | `*`, all local control-action tenant ledgers; or a comma-separated nonempty allowlist. This is not tenant isolation for the entire workspace. |
| `AGENT_FACTORY_SESSION_TTL_SECONDS` | `900`, an absolute browser-session lifetime between 1 and 3600 seconds; activity does not extend it. |

Use a randomly generated high-entropy token and keep it in the operator's process
configuration. Never put it in a URL, command history, shared task record or bug
report. The server does not return the configured token to the browser. This
change does not configure a credential on the developer's own running services.

Local-open mode preserves the existing explicit local operator workflow; it is
not authenticated user access. Host and Origin checks and command confirmation
still apply. Once a running app has required a credential, removing that credential
fails closed instead of silently opening the API. A deliberate switch to
local-open mode requires restarting with an empty token configuration.

## Browser flow

Open the usual loopback address. When authentication is required, the page shows
**Local access**. Enter the configured token and choose **Sign in**. The form posts
only to the same local origin, clears the password field, and uses no localStorage
or sessionStorage. The server issues a fresh random HttpOnly, SameSite=Strict
cookie; only a hash of its identifier is retained in process memory. On HTTPS the
cookie is also Secure. Plain HTTP remains supported only on loopback.

**Access & sign out** opens the session page, where **Sign out** immediately
revokes this session. Copying the old cookie cannot restore it. Expiry also stops
API reads and mutations; use the same link to sign in again. An expired dashboard
may show its last snapshot and a failed refresh until sign-in. Existing work is
not cancelled by signing out, and existing domain permissions are not expanded.

Sessions are process-local: restart invalidates them. Credential rotation or any
actor/role/scope/tenant/lifetime change invalidates existing sessions. A static
bearer credential remains valid until rotated or removed; it has no independent
TTL. A bad explicit Authorization header cannot fall back to an ambient cookie.
The in-memory session count is bounded. This is one process, not a distributed
session database or credential management system.

API clients send `Authorization: Bearer <operator-token>`. Browser clients use the
HttpOnly session. Both get the same server policy and required command scopes.
The login/logout endpoints at `/auth/session` require the explicit
`X-Agent-Factory-Session: true` header for mutation. They never accept actor,
role or scope claims from client input. `/login` and the generic assets are public
local shells; they contain no private workspace state or embedded credential.

## Origin, scope and confirmation

Only Host `localhost`, `127.0.0.1` or `[::1]` with an optional valid port is accepted.
An Origin header must exactly match that scheme, host and effective port. Foreign,
opaque, malformed and duplicate authority headers are denied. CLI requests may
omit Origin. Forwarded headers do not grant authority. Keep the service bound to
loopback; do not expose it through a public proxy.

| API operation | Required scope | Additional gate |
| --- | --- | --- |
| Every GET/HEAD/OPTIONS, including schema and health | `read` | Control-action reads also require the requested tenant in server policy. |
| Founder decisions and artifact-review POST | `approve` | Existing explicit confirmation and domain decision checks; Founder identity must match server policy. |
| `/api/control/actions` POST | `control` | Actor, role and tenant must match server policy; the domain role must allow the action; explicit confirmation is required. |
| All other mutations, including future API routes | `write` | Existing endpoint confirmation and domain checks. File upload is explicit input submission and has no separate confirmation dialog. |

The boundary applies by API path and method, so new routes do not accidentally
become public. Session routes are a separate explicit login/logout flow and cannot
mutate domain data. Confirmation is still the body `confirmed: true` plus
`X-Agent-Factory-Confirm: true` on confirmed domain commands. Credentials alone
cannot skip it. Authorization does not claim that arbitrary clients are human;
the application preserves its explicit confirmation and persisted approval gates.

Private responses use `Cache-Control: no-store`; shells also prevent framing and
send no-referrer/nosniff headers. The access layer returns generic 401/403 errors
without credentials. Invalid live policy returns 503. Secrets must not be included
in ordinary domain payloads or downstream provider artifacts.

## Verification

`test_http_auth` enumerates all actual API routes and methods for missing/wrong
credentials before any storage creation. It checks separate read/write/approve/
control scopes, actor and tenant mismatches, Origin/Host denials, expiry, logout
replay, rotation, restart, malformed login and retained confirmation gates.
`test_http_auth_browser` uses real Chromium and an actual ephemeral loopback HTTP
server to check login, HttpOnly storage, supported navigation, logout, bad tokens
and session expiry. Existing HTTP tests use an explicit loopback fixture host.

The tests use synthetic credentials and disposable databases. They do not qualify
a public deployment, OS credential store, distributed session service or game.
Detailed security reproduction material belongs in the repository's private
security review, not the public task registry.
