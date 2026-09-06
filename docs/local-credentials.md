# Local AI credentials (AF-GC-010)

Open **Settings and details → AI access** from My games. Choose OpenAI or
Anthropic, enter the API key in the dedicated password field, explicitly consent,
and save. The form clears the field after submission, including failure. Saved
means stored locally; it does not validate the provider account, select a model,
approve a mission, authorize charges, or start inference. Cloud connection and
budget wizards remain separate tasks.

## Storage and authority

Windows is the supported persistent backend for this change. Generic entries use
Windows Credential Manager in the current Windows user context with local-machine
persistence, not roaming. Only newly allocated `AgentFactory/<namespace>/<id>`
entries are written/read/deleted. The namespace binds the resolved metadata path;
no enumeration or modification of unrelated Windows credentials occurs.
The [Microsoft credential structure reference](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw)
describes persistence for subsequent logon sessions of the same user on this PC.
The adapter uses [CredWriteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew),
[CredReadW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw)
and [CredDeleteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-creddeletew).
Linux/macOS fail closed: there is no plaintext-file or memory-only fallback
presented as persistent OS protection. Synthetic in-memory stores are test seams.

The workspace stores only a random reference, owner, tenant, fixed provider,
lifecycle and timestamps in `.agent-factory/credential-connections.db`. No key,
key prefix, key suffix, or value-derived digest is stored. Moving/copying that
metadata to another OS account or workspace does not copy the credential.
Protect the local workspace and OS account: this is not a security boundary
against another process running as the same Windows user.

A durable pending reference is committed before the OS write. If the process
stops during saving, the pending record remains visible but cannot authorize
use. Remove the incomplete connection and re-enter the key. On a lost HTTP
response, refresh the list before retrying to avoid duplicate connections.
At most 32 active/pending connections per owner are admitted.

`CredentialConnections.execute` is a trusted host composition interface, **not**
an HTTP operation. The caller supplies current mission-approved operations to
the existing `CredentialBroker`. A saved reference supplies no mission approval.
The broker still binds tenant/mission/tool/operation, rejects scope expansion,
blocks key material in prompt/arguments (including JSON-escaped keys/values),
and sanitizes executor results and error evidence. A temporary environment map
is passed only to the synchronous approved executor; the global environment
is never modified. The temporary broker lease is revoked on completion/failure.
The provider transport must use that approved environment/header seam and must
not log raw inputs. This task does not add an unapproved provider invocation
route or a second scheduler.

## Disconnect, failures and restart

Disconnect requires the operations-owner role, local tenant access, write and
control scopes, and explicit confirmation. The local HTTP boundary checks
loopback origin and authentication before route processing. Read-only credentials
or another actor cannot manage these references. Mutation bodies are bounded;
validation and backend failures return fixed codes without reflecting input.
There is no API to fetch the secret. Replies carry `Cache-Control: no-store`.

Disconnect serializes with admission across local processes. A currently running
synchronous call may finish before disconnect succeeds. The metadata fence is
committed before OS deletion; if deletion fails, new use remains blocked and the
UI offers retry. A busy metadata lock returns failure after five seconds; refresh
and retry, rather than assuming the operation succeeded. Restart never revives a
revoked or pending reference. OS access failure denies use without a fallback.

Local disconnect does not invalidate copied keys or revoke the provider account.
Revoke/delete or rotate the key in the provider account separately. Do that also
if the key was pasted into another application or a shared document.

## Secret handling and evidence

Use only the dedicated entry step. Do not paste keys into prompts, briefs,
backlogs, support bundles or screenshots. Clear the field before taking a
screenshot. The page has no reveal button and writes no key to localStorage,
sessionStorage, URL, DOM text or API result. It does transmit the entered value
to the authenticated loopback endpoint; browser developer/network recorders can
observe that request, so do not record or export its body.

Qualification searches synthetic canaries in generated SQLite files, SQL export,
broker evidence, API/error responses, application log capture and browser DOM /
storage. A saved credential is accessed in a fresh Python process, then revoked
and denied in another fresh process using the actual Windows store. Native API
buffers are zeroed before release where supported; Python/browser strings cannot
be reliably erased from process memory. No raw memory dump, debugger recording,
third-party logger inside a trusted executor, or OS crash dump is certified as a
safe support artifact. Sanitized application error results can be exported;
never attach memory dumps or request captures containing an entered key.

Run focused qualification:

```text
python -m unittest tests.test_os_credentials tests.test_credential_connections tests.test_credential_web tests.test_credential_browser tests.test_credentials tests.test_http_auth
```

Native tests use unique synthetic entries and delete their own references.
Chromium tests exercise the production HTTP composition with a synthetic store;
separate native tests qualify actual persistence and broker use across processes.
No real provider key, paid request or game acceptance is used as evidence.

Core010 owns `web.py` and home settings composition. Core011 owns independent
hardware inventory modules; its reviewed `install_routes(app, workspace)` will
be composed here after upstream integration. Hardware default-app acceptance is
pending until that composition is reviewed; no unfinished hardware link is shown.
