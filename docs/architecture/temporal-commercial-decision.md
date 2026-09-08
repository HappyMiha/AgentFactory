# Temporal in a commercial Lokvetia Core

Date: 6 September 2026. Status: architecture recommendation for review. This document changes no runtime, dependency, deployment or service subscription.

## Recommendation

Keep Temporal for durable development and hosted job workflows. Keep Lokvetia Core's task ownership, permissions, budgets, worker admission and release decisions in Core. Use the existing local mode where a durable service is unnecessary. Do not write a replacement workflow engine simply because Cloud will be a commercial product.

For the proposed Unreal path, Temporal can coordinate long build, test, approval and recovery steps. It should not become a dependency of the first shipped game or schedule NPC movement and every frame. Gameplay AI needs its own asynchronous, game-owned decisions, memory and save/load boundary. A future always-on world service may evaluate durable jobs separately.

## What the repository uses today

The reviewed source baseline is Core commit `765bea67f0164a71b24a8e5d042cd4d90c3e7101`.

| Evidence | Current behavior |
| --- | --- |
| [Package metadata](../../pyproject.toml) | `temporalio==1.31.0` is a required Python dependency. The package exposes `agent-factory-temporal-worker`. It is not currently an optional installation extra. |
| [Settings](../../src/agent_factory/orchestration/temporal/settings.py) | `TEMPORAL_ENABLED` defaults to false. The configured endpoint defaults to localhost. Runtime use is optional even though the SDK is installed. |
| [Application dispatch](../../src/agent_factory/application.py) | Enabled dispatch starts a Temporal workflow; disabled dispatch retains the synchronous path. An enabled but unavailable service must report failure, not silently change the durability promise. |
| [Workflows](../../src/agent_factory/orchestration/temporal/workflows.py) and [activities](../../src/agent_factory/orchestration/temporal/activities.py) | Delivery and autonomous missions use signals, child workflows, retries, history compatibility and continue-as-new boundaries. Activities call existing Core services. This is a substantial integration, not an unused package. |
| [Core operation journal](../../src/agent_factory/durable_workflow.py) and [worker admission](../worker-admission.md) | Core retains domain records, scoped approvals, mutation reconciliation and worker capacity. Temporal does not replace these authorities. |
| [Development stack](../../infra/temporal/docker-compose.yml) | Self-hosted server/admin tools default to 1.31.2, PostgreSQL to 16.14 and UI to 2.53.0. Ports are loopback-bound. This is a development profile, not a qualified public service. |
| [Client connection](../../src/agent_factory/orchestration/temporal/client.py) | The current helper passes the address and namespace to `Client.connect`; it does not configure TLS or an API key. A managed or secured hosted profile needs explicit connection support and tests. |
| [Existing tests](../../tests/test_temporal_workflows.py), [configuration tests](../../tests/test_temporal_config.py) and [Docker durability test](../../tests/test_temporal_docker_durability.py) | Replay, recovery and configuration have executable tests. The Docker test is opt-in; its presence does not prove a current production deployment. |

At reviewed Cloud commit `9f61c179177090696f3cb564e5021fe5df8cecd5`, Temporal is an upstream integration target in the Cloud plan. There is no direct Temporal SDK import in Cloud application source. Cloud's dependency on Core can still bring the SDK into its installation. Neither fact establishes a running hosted Temporal service.

## Commercial use and cost

The inspected [Temporal Server 1.31.2 license](https://github.com/temporalio/temporal/blob/v1.31.2/LICENSE) and [Python SDK 1.31.0 license](https://github.com/temporalio/sdk-python/blob/1.31.0/LICENSE) are MIT. They permit commercial use, modification and distribution, including integration into proprietary products, subject to their notice conditions. They do not require Lokiravia's application source to become public. Preserve the copyright and license notices when distributing covered software.

That finding applies to these components. Keep an inventory of the exact shipped dependencies, container images and notices; their transitive components, trademarks and any hosted service agreement need their own treatment. Core remains Apache-2.0 and Cloud's own license choice remains separate.

| Option | What Lokvetia Core pays for | Decision |
| --- | --- | --- |
| Self-hosted open-source Temporal | Machines, database, backups, upgrades, monitoring and operator time; no MIT software license fee | Suitable candidate for a qualified private deployment. Account for operations rather than calling the whole service free. |
| Temporal Cloud | Managed service usage and plan charges, plus our own application workers | Optional later operating choice. It is not required to use the SDK or self-hosted server. No subscription is created by this review. |
| A replacement built by our team | Design, implementation, failure recovery, migration and permanent maintenance | Do not start now. No demonstrated product constraint justifies this cost. |

Temporal documents both [self-hosting](https://docs.temporal.io/self-hosted-guide) and a separately priced [managed service](https://temporal.io/pricing). Check actual terms and usage before choosing a paid profile; prices and promotions are not an architecture dependency.

## Why replacing it is a separate engineering project

Temporal reconstructs workflow state from a durable event history after a worker fails. Activities can be retried, so our external effects still need idempotency and reconciliation. A timeout is not proof that a remote build or model request stopped. [Event history](https://docs.temporal.io/encyclopedia/event-history), [Activity idempotency](https://docs.temporal.io/activity-definition#idempotency).

Lokvetia Core already has a domain journal. That is useful business authority, but it does not by itself replace distributed timers, signals, task delivery, child workflow recovery, history replay and compatible worker upgrades. Moving these responsibilities into a new engine would require preserving existing mission histories, pause/stop semantics, unknown operations and all external-effect boundaries. A queue plus retry loop would not establish equivalent behavior.

An alternative should be considered only after a measured problem: unacceptable operating cost, an unsupported deployment requirement, a material licensing change in a selected version, or a workload that cannot meet its limits. Compare alternatives with the same crash/replay/cancellation tests and an explicit migration plan. Reusing MIT-licensed code is possible subject to its terms; maintaining a fork still leaves us responsible for its distributed-system behavior.

## Product boundaries and next work

1. **Keep the current integration.** Document the selected local or durable execution mode. Hide infrastructure setup behind an operator flow; a creator should see progress, the next action and the latest accepted game.
2. **Qualify a hosted profile under Cloud AF-CLD-025 and AF-CLD-033.** Reuse Core's versioned workflow boundary. Measure restart recovery, database restore, worker replacement, upgrade/replay compatibility and tenant isolation. Review service authentication, encrypted transport and payload retention before exposing a deployment. The existing loopback Compose defaults do not qualify this profile. See Temporal's [production checklist](https://docs.temporal.io/self-hosted-guide/production-checklist).
3. **Keep domain ownership in Core.** Temporal history is operational history, not the sole permanent record of accepted builds, rights, budgets or task ownership. Continue using small IDs and summaries; keep secrets and large assets outside workflow payloads.
4. **Keep the first player package independent.** Do not bundle Temporal Server, development workers or creator credentials into the Unreal game. Its declared local model or gameplay service is a separate dependency, with offline fallback and per-session limits.
5. **Evaluate lighter installation only when needed.** Moving the Python SDK to an optional extra could reduce a minimal local install. That is a future packaging change requiring import, CLI, wheel and both execution-mode tests; `TEMPORAL_ENABLED=false` alone does not remove the installed dependency.

The [original integration analysis](temporal-integration-analysis.md) and [worker versioning guide](../development/temporal-worker-versioning.md) retain their implementation detail. This review adds the commercial product decision and Unreal/gameplay boundary; it does not claim new performance measurements or production acceptance.
