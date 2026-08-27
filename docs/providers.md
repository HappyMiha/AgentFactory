# Providers

Providers are replaceable execution backends. Agent roles and workflows refer to stable provider IDs, while executable paths, arguments, timeouts, and role allowlists live in reviewed configuration.

## Shipped providers

| ID | Adapter | Default posture | Primary uses |
|---|---|---|---|
| `deterministic` | Built-in | Offline simulation | CI, demonstrations, workflow contract development. |
| `codex` | Codex CLI | Read-only sandbox | Implementation and validation artifacts. |
| `claude` | Claude Code | Plan mode | Policy review, planning, implementation proposals, validation. |
| `gemini` | Gemini CLI | Plan mode | Independent planning, implementation proposals, validation. |
| `antigravity` | Antigravity CLI | Plan mode plus OS sandbox | Non-interactive implementation proposals, planning, and independent review. |
| `ollama` | Ollama CLI | Local model, no tools | Private local artifacts and economical review. |
| `openclaw` | OpenClaw CLI | Health-only | Version discovery; execution is intentionally disabled. |
| `firecrawl` | Firecrawl CLI | Read-only, gated, five-credit ceiling | Public web search, scraping, and source-backed research artifacts. |

Running `agent-factory providers status` is read-only. A healthy executable does not imply authenticated access or permission to execute.

## Common execution contract

Every enabled CLI provider uses:

- an allowlisted executable and fixed argument vector;
- `shell=false`;
- a reviewed prompt transport;
- an agent-role allowlist;
- a maximum timeout;
- a retained-output limit;
- a workspace-scoped current directory;
- a one-use approval scoped to provider, agent, and work item;
- process-tree termination on timeout;
- persisted attempt metadata and artifact digest.

Provider output is untrusted and cannot grant final approval.

## Codex

Official documentation: [Codex CLI](https://developers.openai.com/codex/cli/).

The official page provides platform-specific installation options. On macOS and Linux, its standalone installer is:

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

Run `codex` once and complete an available sign-in method, then verify:

```bash
codex --version
agent-factory providers status
```

The shipped command contract is:

```text
codex exec --sandbox read-only --skip-git-repo-check --color never -
```

The prompt travels over standard input. Windows native candidates are checked before a potentially blocked execution alias, preventing a common `WinError 5` launcher failure.

## Claude Code

Official documentation: [Set up Claude Code](https://docs.anthropic.com/en/docs/claude-code/getting-started).

With a supported Node.js installation:

```bash
npm install -g @anthropic-ai/claude-code
claude doctor
claude
```

On Windows PowerShell, use `npm.cmd` when script execution policy blocks `npm.ps1`:

```powershell
npm.cmd install -g @anthropic-ai/claude-code
& "$env:APPDATA\npm\claude.cmd" doctor
```

The shipped command contract is:

```text
claude -p --output-format text --permission-mode plan --disable-slash-commands
```

Authentication remains in Claude Code's own profile. The generic provider command above stays plan-only. AF-050's separately qualified writable profile is documented in [Claude Code implementation worker](claude-code-worker.md); it is available only through the fenced `claude-cli` Worker Runtime and cannot be selected by planning roles.

## Gemini CLI

Official Google guide: [Gemini CLI hands-on](https://codelabs.developers.google.com/gemini-cli-hands-on).

With Node.js 20 or newer:

```bash
npm install -g @google/gemini-cli
gemini
gemini --version
```

Windows PowerShell alternative:

```powershell
npm.cmd install -g @google/gemini-cli
& "$env:APPDATA\npm\gemini.cmd" --version
& "$env:APPDATA\npm\gemini.cmd"
```

Complete interactive authentication once. The factory then uses the non-interactive plan contract:

```text
gemini --prompt "" --output-format text --approval-mode plan
```

The actual task prompt travels over standard input.

## Antigravity CLI

Official Google documentation:

- [Install the Antigravity CLI](https://antigravity.google/docs/cli/install)
- [Get started with the Antigravity CLI](https://antigravity.google/docs/cli/getting-started)
- [Understand plan mode](https://antigravity.google/docs/cli/modes)

Windows PowerShell installation:

```powershell
irm https://antigravity.google/cli/install.ps1 | iex
# Open a new PowerShell window after installation.
agy --version
agy
```

If the new terminal has not picked up `PATH`, the official installer uses a per-user native executable that can be launched without a PowerShell script shim:

```powershell
$Agy = "$env:LOCALAPPDATA\agy\bin\agy.exe"
& $Agy --version
& $Agy
```

macOS or Linux installation:

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
agy --version
agy
```

On the first interactive launch, Antigravity attempts to use its operating-system secure-keyring session and otherwise starts Google's browser sign-in flow. Complete authentication outside Agent Factory. On a remote terminal, follow the URL-and-code flow shown by Antigravity, but never copy its URL, code, tokens, account details, or authentication output into work items, logs, Issues, or artifacts. Use `/logout` in the interactive CLI when the session must be removed.

The shipped contract, verified against Antigravity CLI 1.1.9, is equivalent to:

```text
agy --output-format text --mode plan --sandbox --disable-slash-commands --print "<task prompt>"
```

These controls are complementary: `--mode plan` limits the agent to plan-oriented, read-only tooling, while `--sandbox` enables operating-system terminal restrictions. `--print` makes the call non-interactive, and slash-command expansion is disabled.

Antigravity currently requires `prompt_transport: argument`. Agent Factory excludes the appended prompt from its own command metadata, but the task prompt is still part of the child-process command line and may be visible to local process inspection and operating-system diagnostics. Treat prompts as non-secret work-item content. Do not put credentials, private authentication material, or unnecessary sensitive data in them. Revalidate the fixed flags and a bounded live canary before adopting a newer CLI release.

After authentication and `providers status`, use the same one-use gate as every real provider:

```bash
agent-factory providers request antigravity --agent coding-worker-antigravity --task-id 1
agent-factory providers approve 1 --note "One bounded advisory artifact"
agent-factory providers invoke 1
```

## Ollama

Official downloads and documentation:

- [Download Ollama](https://ollama.com/download)
- [Ollama documentation](https://docs.ollama.com/)

Install Ollama, start its local service, and pull the configured model:

```bash
ollama pull qwen2.5-coder:7b
ollama list
ollama --version
```

The shipped command contract is:

```text
ollama run qwen2.5-coder:7b --think=false --nowordwrap
```

Ollama is the simplest real-provider smoke test because it needs no external provider account after the model is downloaded. Model quality and resource use depend on the host.

## OpenClaw

Official installation guide: [Install OpenClaw](https://docs.openclaw.ai/install).

The adapter runs only a version health probe. `allow_execution` is false, the role allowlist is empty, and no agent may invoke it. Enabling execution requires a dedicated no-tools profile and negative integration tests proving that it cannot use filesystem, shell, network, messaging, or gateway tools.

Do not point the factory at a general-purpose profile.

## Firecrawl

Official references: [Firecrawl CLI](https://docs.firecrawl.dev/sdks/cli) and [Firecrawl API v2](https://docs.firecrawl.dev/api-reference/v2-introduction).

Firecrawl is assigned to the dedicated `Web Researcher` role. The shipped agent has only `search_web`, `scrape_web`, and `create_artifact` permissions. It cannot read the project, propose code, review another agent, issue policy verdicts, merge, or close work.

Install and authenticate the CLI in its own user profile. Browser authentication avoids placing a key in shell history:

```powershell
npm.cmd install -g firecrawl-cli@latest
firecrawl config --browser
firecrawl view-config
agent-factory providers status
```

For non-interactive provisioning, pass the API key to Firecrawl's setup command directly and never save it in repository files:

```powershell
npx -y firecrawl-cli@latest init --all --yes --api-key <FIRECRAWL_API_KEY>
```

The reviewed execution contract is:

```text
firecrawl agent --wait --json --max-credits 5 <provider-prompt>
```

The prompt is a process argument because the Firecrawl agent command has no stdin prompt mode. Agent Factory excludes prompt contents from retained command metadata, but local process inspection can see them during execution. Never put credentials or private project data in a Firecrawl task.

Every call still requires a gate scoped to the exact provider, agent, and work item:

```bash
agent-factory providers request firecrawl --agent web-researcher-firecrawl --task-id 1
agent-factory providers approve 1 --note "Bounded public-web research; maximum five credits"
agent-factory providers invoke 1
```

Retrieved pages are untrusted input. The role instructions require source URLs and forbid forms, target-site authentication, access-control bypass, and browser actions with external side effects. Firecrawl authentication remains in Firecrawl's own profile and is not passed through Agent Factory's subprocess environment.

## Review provider status

```bash
agent-factory providers status
```

Interpret results as follows:

- `healthy: true`: the allowlisted executable answered its version probe;
- `healthy: false`: no candidate was found, the probe timed out, or the launcher failed;
- health-only: version inspection is available, but execution remains blocked;
- authenticated access: not guaranteed by a health result.

## One-use provider execution

```bash
agent-factory providers request codex --agent coding-worker-codex --task-id 1
agent-factory providers gates
agent-factory providers approve 1 --note "Reviewed provider, role, task, and scope"
agent-factory providers invoke 1
```

To deny a pending request:

```bash
agent-factory providers reject 1 --note "Scope is too broad"
```

An invocation cannot reuse a gate. If it fails, request and review another gate.

## Override provider configuration

Copy packaged defaults into a private or repository-controlled config directory:

```bash
mkdir config
cp src/agent_factory/defaults/*.json config/
export AGENT_FACTORY_CONFIG_DIR="$PWD/config"
```

Example CLI definition:

```json
{
  "id": "local-reviewer",
  "type": "cli",
  "enabled": true,
  "executable": "reviewer",
  "executable_candidates": [],
  "args": ["--non-interactive", "--read-only"],
  "version_args": ["--version"],
  "prompt_transport": "stdin",
  "allow_execution": false,
  "allowed_roles": ["Validation Reviewer"],
  "max_timeout": 120,
  "max_output_chars": 50000
}
```

Start with `allow_execution: false`. Verify the exact installed version and every switch, add denial and timeout tests, then enable it through reviewed configuration.

Supported prompt transports are `stdin`, `argument`, and temporary `file`. Prefer standard input. Arguments may expose prompt content to process listings; files create cleanup and access-control obligations.

## Authentication and secrets

Use each CLI's own profile or operating-system keyring. The provider subprocess environment removes variables whose names suggest tokens, secrets, passwords, credentials, API keys, or authentication material.

Consequences:

- do not configure provider API keys in `.env`;
- do not put credentials in provider arguments;
- do not include authentication output in artifacts or Issues;
- do not mount broad credential directories into Docker;
- re-authenticate the provider interactively outside Agent Factory when needed.

Successful stdout and failure diagnostics can enter retained execution results and artifacts. Sensitive environment-variable names are filtered, but comprehensive value-aware redaction of provider output is not implemented. Review artifacts before publishing or attaching them to external systems.

## Future HTTP providers

DeepSeek, OpenRouter, Mistral, Groq, Together AI, Fireworks AI, and direct vendor APIs are not native providers in version 0.1. A proper implementation needs an HTTP provider class with endpoint and model allowlists, secret retrieval, timeouts, response-size limits, retry policy, rate-limit handling, cost metadata, structured-output validation, and tests.

A generic shell wrapper can technically expose such a service as a CLI, but that wrapper becomes part of the trusted execution boundary and must satisfy the same fixed-command and approval contract.

## Troubleshooting

### Provider is missing

Run the provider's own `--version` command in the same terminal. Confirm its installation directory is on `PATH`, or add a fixed executable candidate in reviewed configuration.

### Windows reports access denied

An application execution alias may resolve even though it cannot be launched by a subprocess. Configure the provider's stable native executable before the alias. The shipped Codex definition already includes native candidates.

### Provider times out

Reduce task scope before increasing the timeout. A timed-out attempt consumes its gate. Confirm the process tree was terminated in the recorded metadata, then request a new gate.

### Provider returns prose during a workflow

Workflow stages require JSON containing `verdict`, `criteria_evidence`, and `summary`. A valid provider connection can still fail the stage contract when it returns unstructured text.
