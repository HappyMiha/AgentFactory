# Tool Registry, Gateway, and connectors

AF-018 normalizes native, CLI, HTTP, and MCP tools behind one Control Plane boundary. Every immutable semantic-version descriptor declares object input and output schemas, explicit side effects, risk tier, required capabilities, bounded timeout, and required evidence outputs.

Dynamic connector discovery records all announced tool names but authorizes only the intersection of mission, role, and policy allowlists. An announced or even registered tool outside any one allowlist remains non-invocable. The gateway additionally requires a healthy matching connector, declared capabilities, schema-valid arguments and output, and complete evidence fields. Every supported invocation stores request and evidence digests plus a succeeded or failed outcome.

Connector manifests are immutable versions. Instances record install, successful or failed health checks, disable, upgrade, and removal as separate lifecycle events and audit records. An upgrade returns to installed/awaiting-health state. Removed connectors cannot be revived. Registration or scope expansion of a mutation-capable production connector requires an attributable human approval before its version exists.
