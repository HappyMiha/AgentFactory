# Security Policy

Agent Factory launches third-party AI CLIs and can prepare changes for external systems. Its approval and execution boundaries therefore deserve the same care as a deployment tool.

## Supported versions

| Version | Security updates |
|---|---|
| `0.1.x` | Yes, while the project remains in alpha |
| Older versions | No |

## Reporting a vulnerability

Report vulnerabilities privately through the repository's **Security** tab using a GitHub Security Advisory. Do not open a public Issue for a suspected vulnerability and do not include real credentials, personal data, or exploit output from systems you do not own.

Include, when possible:

- affected version or commit;
- operating system and Python version;
- provider and execution mode;
- minimal reproduction with synthetic data;
- expected and observed security boundary;
- impact and any known workaround.

Maintainers will acknowledge and triage reports on a best-effort basis. Public disclosure should wait until a fix or coordinated mitigation is available.

## Security model

The implemented controls include:

- one-use approval gates scoped to provider, agent, and work item;
- a separate final human decision for workflow completion;
- fixed provider executables and argument vectors;
- `shell=false` subprocess creation;
- provider and agent-role allowlists;
- bounded prompts, timeouts, and retained output;
- targeted process-tree cleanup;
- immutable GitHub mutation plans with SHA-256 digests;
- dry-run GitHub behavior by default;
- allowlisted GitHub operations and idempotency keys;
- durable attempt, artifact, decision, and event records.

## Important alpha limitations

- Provider output is untrusted and may contain prompt injection or sensitive text.
- Environment filtering is name-based; comprehensive value-aware redaction is not complete.
- Output is truncated for persistence, but streaming memory limits are not complete.
- Local database administrators can alter SQLite files; the audit stream is not cryptographically tamper-evident.
- Windows process cleanup does not yet use a Job Object.
- Provider CLIs maintain their own authentication state outside Agent Factory.
- The Docker image is designed for deterministic simulation and does not bundle external providers.

## Safe deployment guidance

- Run under a dedicated, unprivileged operating-system account.
- Point `AGENT_FACTORY_WORKSPACE` only at repositories the operator intends agents to inspect.
- Keep configuration and the SQLite database readable only by the operator.
- Use provider profiles with the least authority available.
- Review provider CLI updates before changing an allowlisted version or argument contract.
- Keep simulation as the default in CI and demonstrations.
- Back up state before schema upgrades.
- Never mount a Docker socket, SSH agent, cloud credential directory, or broad home directory into the container.

## Out of scope

Reports about model quality, hallucination, provider availability, provider billing, or an upstream CLI without an Agent Factory boundary bypass should be sent to that provider. A model response that is merely incorrect is not itself a security vulnerability.

## Local HTTP access

All local API routes share the [operator access policy](docs/local-api-access.md).
Configured bearer credentials and short-lived HttpOnly browser sessions carry
server-bound identity and scopes; Host/Origin checks and domain confirmation
remain required. Logout, expiry, restart and credential/policy rotation invalidate
sessions. An empty initial credential means documented local-open mode, not
authenticated multi-user access. This loopback service is not a public deployment.
