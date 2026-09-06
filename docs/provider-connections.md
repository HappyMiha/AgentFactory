# Choose a cloud connection (AF-GC-009 component)

The **Доступ до AI** page now starts with **Що у вас уже є?**. Its dated catalogue
distinguishes a chat product, a provider API key and login in the official CLI.
Choosing an item only displays guidance. An explicitly chosen API option can move
focus to the existing key form when the current account/age policy and supported
OS credential store permit it. The form still requires its separate confirmation.

The catalogue is `provider-connections-2026-09-06`, reviewed on 6 September 2026,
with review due on 6 October 2026. It does not inspect the current account, quota,
model access, network or coding/review capability. All these checks are returned
as `not_run`; `execution_ready` is false and qualified capabilities are empty.
Saving a credential does not turn those checks into success.

The current official sources were opened and reviewed:

- [OpenAI API quickstart](https://developers.openai.com/api/docs/quickstart): create
  an API key in the provider dashboard. The integration retains its existing OS
  credential store rather than adopting an example plaintext configuration file.
- [OpenAI/Codex authentication](https://learn.chatgpt.com/docs/auth): official CLI
  browser login, optional device-code login and separate API-key billing. ChatGPT
  sign-in/plan credits do not become general API credentials or API credit here.
- [Claude API authentication](https://platform.claude.com/docs/en/manage-claude/authentication):
  provider-console API key creation and expiry. The initial guidance asks for a key
  scoped to the required workspace; multi-workspace header selection and federation
  are not implemented by this wizard.
- [Claude Code authentication](https://code.claude.com/docs/en/authentication):
  official tool login and the distinction between subscription and Console/API
  authentication. The active account and configured credential source determine
  billing; a saved chat login is not imported by AgentFactory.

The official CLI instructions are guidance only. This component does not run a
login command, launch a browser callback receiver, import cookies/session files,
handle a device code, or claim that a CLI is supported by this connection wizard.
Other independently configured Core runtime profiles keep their existing behavior.
Other products are explicitly unverified; no new subscriptions or model defaults
are recommended. Account eligibility remains the separately reviewed Core025
policy, and actual capability remains the Core009 qualification contract.

The existing owner-scoped `GET /api/credential-connections` adds `catalog` to its
response. It still requires the existing local authentication/tenant boundary.
There is no new write endpoint or change to credential storage, broker scopes,
provider execution, budget approval or the trusted qualifier. API-key save and
disconnect retain their existing server-side checks.

Catalogue expiry disables its guided selection; it does not revoke credentials
or become a substitute authority for key management. Existing keys can still be
listed/disconnected and the existing separately policy-gated key form remains.
The browser checks catalogue time both while rendering and at selection, preserves
refresh generation guards, clears secrets when switching a product, and removes
old guidance/actions on failed refresh. It stores no product choice or secret in
browser storage and makes no provider request on selection.

Tests cover catalogue freshness and product distinctions, HTTP denial/unchanged
authorization, real Chromium selection without saving, 390px layout, lost access
and catalogue expiry. They use synthetic credential stores and do not certify
native Windows credential storage or real provider login/canaries. Full AF-GC-009
still requires trusted current-connection/evaluator integration, classified actual
connection failures and accepted cloud coding plus independent review evidence.
