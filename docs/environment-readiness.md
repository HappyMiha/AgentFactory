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
software, start services or download a model. Ordinary checks never invoke inference. A discovered
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

The bundled Ollama production collector supports `local:qwen2.5-coder:7b` and
`local:qwen2.5-coder:14b`, one selected model per route, with `ollama` as the only
approved provider. Selected roles must belong to the five autonomous planning
roles, Environment Bootstrap, or Developer. The effective workspace provider
configuration must match the bundled profile exactly. Custom overrides, other
models/providers/roles, and unknown services remain blocked. The optional service
`selected-local-model-runtime` is qualified by the same actual daemon checks.
A Git/Python route can use `tools: ["git", "python"]`, `services: []`; this does
not certify an engine or game build.

On the execution host, with its existing approved mission and database, run:

```bash
python scripts/check_environment.py --database /path/to/state.db --mission-id 123 --run-live
```

The packaged equivalent is `python -m agent_factory.environment_model_probe` with
the same arguments. `--run-live` explicitly authorizes seven API and seven CLI
synthetic local inference requests. Both use the fixed `127.0.0.1:11434` daemon;
remote/custom `OLLAMA_HOST`, proxies and redirects are rejected. The collector
reuses Core042's reviewed producer, now in `local_role_qualification.py`; the
original `scripts/qualify_provider_roles.py` command remains available. Each API
request has a 96-token output limit, each request a maximum 60-second timeout,
CLI output is capped at 16,384 combined characters and its JSON at 1,024
characters. A shared 240-second budget prevents additional requests after expiry.
CLI has no hard token limit. No downloads or service starts occur. Requests contain
only synthetic role contracts, never mission source. Mission authority, policy,
role/model bindings, pause/stop fences and the provider profile are revalidated
before every new request. An in-flight request remains bounded by its timeout.

A successful report includes a versioned immutable qualification record with the
current approval/plan/epoch binding, provider profile digest, installed model
digest, start/finish times and all seven role results. Only the collector's own
fresh return value is accepted; there is no uploaded/stdout/Bus receipt input.
Before use, the gate checks the current mission authority and reads the local
model inventory again, without inference. Model replacement/removal, provider
configuration changes, expiry, or loss of authority invalidate the receipt.
A failed fresh run supersedes prior success and exposes only a sanitized error
class. Inspect the report through the normal UI/API after the command. The normal
**Run actual-state checks** action still runs without inference and therefore
produces an unqualified model result; it does not silently reuse an earlier
canary. Rerun the explicit command to obtain a new live qualification.

This qualifies only the selected local role-contract route and its readiness
transition. It does not prove end-to-end planning accuracy, code quality, game
playability, hosted deployment, or owner product acceptance.

Tests execute real local Git/Python/filesystem checks and Chromium UI interactions.
Their injected model observations and browser responses are explicitly synthetic.
They test the gate and orchestration contract, not actual model qualification,
engine builds, game playability, a minor pilot or owner product acceptance.

For the opt-in actual local integration check, set
`AGENTFACTORY_LIVE_ENVIRONMENT_TESTS=1` and run
`python -m unittest tests.test_environment_model_probe.LiveEnvironmentRouteTests`.
It creates an isolated Git/Python route and a synthetic planning/approval fixture,
then uses the real installed 7b model (all fourteen inference requests), durable
receipt verification and DEVELOPMENT transition. It does not inject model probes.
The normal suite skips this test; an installed Ollama daemon/model is required.
Reported evidence omits workspace paths and does not certify planning or a game.
