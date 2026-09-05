# Readiness for an approved development route

AF-GC-002 separates control-plane health, executable discovery, and permission to
enter autonomous DEVELOPMENT. The monitor being healthy is not evidence that a
selected engine, service or model can build a game. Executable discovery now says
`installed`, not `ready`.

## Bind requirements to the approved plan

Commit `agentfactory.environment.json` in the repository before approving the
mission's base Git revision. For example, a selected Godot route may require:

```json
{
  "schema_version": 1,
  "profile": "autonomous-local-default",
  "tools": ["git", "python", "godot"],
  "services": ["selected-local-model-runtime"]
}
```

The profile name must equal the mission's approved local tool profile. The file is
read from the approved epoch's base commit, with a 64 KiB limit, exact fields and
no duplicate keys. Editing the working copy cannot weaken approved requirements.
Missing or invalid requirements block entry; an empty workspace does not silently
become a generic Python route. Correcting requirements needs a new approved
revision/epoch, not an unreviewed change to a running plan.

Tools and services are explicitly selected. Model requirements come from the
approved role/model manifest and allowed provider IDs, not every installed or
configured provider. An unrelated broken provider cannot block this route. The
operator and plan reviewer remain responsible for selecting the complete engine,
toolchain and service requirements; Core does not infer them from prose.

## Actual checks and current evidence

The built-in verifiers run fixed read-only Git, Python, Node and Godot version
commands, and test read/write/rename using only a private temporary directory in
the approved workspace. They never run commands supplied by a plan, install
software, start services, download a model or invoke inference. A discovered
executable whose probe fails remains installed but unqualified. Unknown selected
tools/services/models produce blockers with a next action.

Each observation separates installed, authenticated, qualified, execution mode,
actual identity and next action. Authentication is not applicable to the built-in
local version/workspace probes; their permission check is satisfied by the actual
local operation. A model observation must name the exact approved model and one
of its allowed providers. Simulation, unknown mode, missing identity, wrong model,
probe exceptions and malformed observations cannot grant readiness.

Migration 73 adds immutable reports. Every report binds the approval digest,
backlog revision/digest, epoch/base commit, workspace/branch, selected profile,
role/model manifest and policy digest. Reports expire five minutes after checks
start. A future, expired, corrupted or differently bound report cannot be reused.
The latest failure supersedes an older success. A repeat check executes actual
probes again and retains the earlier result. A new process reads the same durable
report; a response timeout is not assumed to mean a failed or successful check.

`AutonomousCodingDeliveryService.enter_development` requires a current complete
live report before advancing any environment phase. Existing authority, policy,
version and fence checks remain required. The Temporal activity runs the first
check if no report exists. After a readiness failure, the patched workflow checks
for a fresh durable report every 30 seconds; these retries do not execute new
probes or create repeated receipts. The explicit check action produces a new
report. A successful current report allows the original approved workflow to
continue, while its normal pause/stop and authorization boundaries still apply.
Other configuration errors retain their existing operator-attention behavior.

## Inspect and rerun

Open **System monitor → Check an approved development route**, choose an approved
mission, and inspect its checks. **Run actual-state checks** is explicit; the
background dashboard refresh never invokes probes. The UI distinguishes installed,
authenticated, qualified and live/simulation/unknown observations, removes a
positive status when evidence expires, and clears it when a request fails.

The loopback API uses the existing uniform authentication/scope boundary:

- `GET /api/environment/missions` lists approved missions with offset/limit pagination.
- `GET /api/autonomous-missions/{mission_id}/environment` reads current evidence.
- `POST /api/autonomous-missions/{mission_id}/environment/check` runs checks.

The API accepts no commands, uploaded reports, model-generated proof or readiness
flags. A check endpoint never starts development or supplies human approval.

## Trusted verifier integration and limits

`EnvironmentReadiness(..., probes=...)`, the web app's `environment_probes` argument,
and `AgentFactoryActivities(autonomous_environment_probes=...)` are trusted
in-process composition seams. Adapters are keyed by an exact requirement such as
`service:selected-local-model-runtime` or `model:Developer`. They receive the
selected requirement and return a bounded `Observation`. Adapters must verify
actual current state, exact identity, permission and qualification, enforce their
own bounded I/O, and sanitize diagnostics. Register only operator-reviewed code;
this mapping is not accepted from HTTP requests or generated project files.

No production model/service verifier is shipped in this change. In their absence,
the default autonomous route correctly remains blocked. Core042's seven-role
Ollama smoke JSON Lines are not a trusted persisted qualification receipt: they
lack a versioned receipt/expiry and mission binding. Neither those lines nor a Bus
message are promoted to READY. A reviewed receipt/verifier integration is required
before a real model route can qualify; this guard must not be weakened to make a
demonstration pass.

Tests execute real local Git/Python/filesystem checks and Chromium UI interactions.
Their injected model observations and browser responses are explicitly synthetic.
They test the gate and orchestration contract, not actual model qualification,
engine builds, game playability, a minor pilot or owner product acceptance.
