# AgentFactory Core and Cloud

Status: proposed plan. This document defines ownership and integration. It does not claim that a product, hosted service, game builder, marketplace, or deployment is complete.

There are exactly two projects:

| Project | Purpose | Source of truth |
|---|---|---|
| AgentFactory Core | Open-source software for planning and running controlled AI work, locally or on managed workers. | This repository: `HappyMiha/AgentFactory`. |
| AgentFactory Cloud | A commercial creator and player product built on Core: discover a game, play it, remix it with AI, create a version, and publish it. | The product specification, roadmap, and `AF-CLD-*` backlog in [HappyMiha/AgentFactory-Cloud](https://github.com/HappyMiha/AgentFactory-Cloud). |

Game creation is the first domain pack on Core. “Games”, “Game Studio”, and “Marketplace” describe capabilities inside these two projects. They are not additional repositories or independent control systems.

## The product promise

The main Cloud loop is **Play → Remix → Create → Publish → Play**. A creator can also start with a new idea. AI work produces a real source project and versioned builds. The creator can play a working version, request changes, and export the material they have the right to export.

The first proof is a small Godot 2D game. A private demonstration uses the creator's own game or a sample with explicit remix permission. Public discovery, remixing another creator's release, and public publication require the later account, rights, moderation, and release gates. A private preview must never be presented as a public release.

Core remains useful outside games. Its task, provider, policy, tool, artifact, and workflow models must not require a game engine. Game rules and engine commands belong to optional packs. Supporting another type of project is a future qualification exercise, not a claim that every domain already works.

## What each repository owns

| Area | Core owns | Cloud owns |
|---|---|---|
| Planning | Source preservation, task graphs, role contracts, model selection, versioned plans and revisions. | Creator questions, Game Brief screens, first-playable scope, and product choices. |
| AI execution | Provider and worker interfaces, effective model identity, scoped tool access, cancellation, recovery, and usage evidence. | Managed provider accounts, customer quotas, service capacity, product presets, and customer-facing costs. |
| Game creation | Optional Game Studio roles and engine packs: Planner, Coding Agent, Game Builder, Tester, Debugger, and runtime checks. | The creator journey, visible team, progress, play feedback, and product acceptance of those packs. |
| Engines | Versioned engine/target interfaces and qualified Godot, then other optional adapters. | Which engine/target combinations are offered, their limits, and their customer experience. |
| Local setup | Hardware discovery, tool probes, approved installation operations, local runner and resource contracts. | Setup instructions and consent where a local or hybrid product route is offered. |
| State | Authoritative task, run, approval, lease, artifact, evidence, and audit records. | Users, organizations, profiles, project membership, game pages, listings, orders, and customer support state. |
| Fork and versions | Neutral project snapshots, immutable parent references, safe workspace creation, and recovery. | Creator remix settings, license and asset checks, attribution, discovery, and derivative-release rules. |
| Publishing | Generic artifact and protected-operation contracts. | Private/unlisted/public release states, moderation, delivery, discovery, and explicit Publish actions. |
| Money | Measured provider usage and execution limits. | Subscription/credit policy, payment integration, sales, entitlements, fees, refunds, revenue ledger, and payouts. |
| Operations | Reusable deployment and diagnostic contracts, compatibility tests, and Core recovery evidence. | Hosting, capacity, backups, support, incident response, and evidence for the managed service. |

Generic fixes stay upstream in Core. Cloud must not copy the Core scheduler, credential broker, acceptance logic, or database tables to create another authority. Product data may reference Core identifiers; it must not directly edit Core storage to advance a run or bypass an approval.

An engine pack may live in the Core repository while remaining an optional package. That is a packaging boundary, not a reason to create another repository. No source files are being moved as part of this planning change.

## The existing foundation and its limits

The repository contains provider adapters, worker lifecycle contracts, managed worktrees, task revisions, evidence, policy, and pack lifecycle code. These are useful foundations. The [September product audit](product-audit-2026-09-05.md) records the tested limits of the current game-creation path.

The current pack manifest identifies a pack, version, Core compatibility interval, permissions, dependencies, migrations, evaluations, and signature. The software-engineering reference pack still names internal Python services. The small `SDKClient` is a transport contract, not evidence of a complete supported external product SDK. Existing web routes primarily expose operator and work-item operations.

Before Cloud depends on a capability, the teams must define and qualify a public integration contract. Internal class names, shared SQLite access, or a “Ready” label are insufficient. The existing API authorization findings must be resolved and verified before the service is exposed to other users.

The present HMAC pack-signing mechanism is a trusted-installation foundation. It must not be described as a completed public publisher-signing ecosystem. Third-party pack publication needs its own trust, compatibility, permission, revocation, and qualification decisions.

## Contracts between Core and Cloud

These are required contract subjects, not claims about endpoints that already exist.

| Contract | Required content and behavior |
|---|---|
| Capability and compatibility | Core/pack versions, supported operations, engine/toolchain identity, qualification evidence, and explicit unsupported states. |
| Project and fork | Project/source identity, exact snapshot digest, authorized input scope, immutable parent identity, and a new workspace without changing the parent. |
| Plan and revision | Original intent, task dependencies, expected artifacts, acceptance criteria, actor, version, and approved scope. |
| Execute and control | Actor/project/run/attempt scope, provider and model, tool permissions, limits, idempotency, pause/stop behavior, and recovery receipt. |
| Worker registration | Execution location, qualified capabilities, capacity, lease and fencing identity, heartbeat, drain, replacement, and stale-worker rejection. |
| Build and evidence | Source digest, pack and toolchain versions, commands, deterministic results, runtime evidence, artifact digests, and failures or skipped checks. |
| Events and progress | Versioned events, correlation IDs, ordering/deduplication rules, bounded payloads, and recovery when the live stream is unavailable. |
| Usage | Estimated, reserved, observed, and reconciled usage. Provider costs must remain distinct from customer credit prices and marketplace revenue. |
| Export and import | Source/build manifest, dependencies, checksums, attribution, permitted assets, and no credentials or unrelated project data. |
| Upgrade and recovery | Supported version pairs, active-run compatibility, checkpoint restoration, data ownership, and a tested rollback route. |

Cloud owns the decision that a creator may remix, publish, or sell. Core enforces the scoped operation it receives and verifies its inputs. A Cloud entitlement must not become unrestricted filesystem, network, or provider authority.

Use one versioned application boundary first. Separate repositories do not require a separate service for every box in a diagram. Extract services only when a measured isolation, deployment, scaling, or ownership need justifies them.

## Managed workers and local runners

The first hosted route uses managed workers and managed outbound provider requests. A customer should not need a cloud-provider developer account merely to use an offered managed plan. Bring-your-own-key and local/hybrid routes are separate supported choices with their own eligibility, credential, privacy, and qualification requirements.

Cloud manages customer permission and budget. Core dispatches only the authorized work. Build workers receive a limited workspace and artifact access; they must not receive the service's broad provider, storage, or administrative credentials.

A local runner is a distinct execution location. Its registration, scope, approved paths, data transfer, stop behavior, and reconnect recovery must be visible. A request may not silently move from local inference to a remote model. Local-only qualification must demonstrate the promised network behavior rather than relying on a provider's name.

Do not promise that retries can never produce a second provider charge. Internal usage records must be idempotent. Provider-side idempotency should be used when supported; an uncertain remote result needs reconciliation before a potentially chargeable retry.

## The reported server and deployment boundaries

The owner reports that a server is available. Its capacity, configuration, access, backups, and suitability for untrusted game builds have not been verified by that statement. There is no established evidence here of a deployed game-generation, sandbox, build, object-storage, or CDN path.

The hosted-worker work in `AF-CLD-024` must begin with a read-only inventory and a written gap report: OS, CPU/RAM/GPU, available storage, virtualization/isolation support, network and service boundaries, toolchain requirements, access roles, backup state, and available build capacity. Sensitive server details stay out of public documentation. Installation or deployment is a later, separately authorized action.

Three trust zones are required even if the first qualified deployment uses one physical host:

| Zone | Allowed purpose | Boundary to prove |
|---|---|---|
| Control | Accounts, authorization, scheduling, credentials, and authoritative records. | Generated code cannot access control credentials or change accepted state. |
| Agent/build | Disposable workspaces, bounded tools, engine builds and tests. | CPU/RAM/disk/time/process/egress limits, no other customer's files, and no host-administration access. |
| Play/delivery | Serve approved static game artifacts and scoped private previews. | Separate origin and browser policy from the creator/admin application; no execution in the control process. |

New artifacts enter quarantine. Scans, rights checks, engine/runtime evidence, and the applicable release decision determine which artifacts may be previewed or published. A signed URL is an access mechanism; it does not make a build trustworthy. Private previews must remain private and revocable. Public pages must pin a published release digest, not a mutable working directory.

Capacity limits, fair queues, cleanup, worker loss, storage growth, and a fresh restore of both records and artifacts must be measured before a hosted cohort is admitted. One available server is not proof of any particular concurrency or service-level target.

## Remix rights and creator control

Remix starts from an authorized source snapshot. A playable game or public URL alone does not grant access to its source or permission to make a derivative. No task authorizes extracting unavailable source from someone else's game.

The Cloud decision must check the release's remix setting, source license, each included asset's rights, required attribution, and any conflicts. Unknown or incompatible rights block the affected operation and explain what must change. Core then creates a new project/workspace from the exact permitted snapshot and preserves its parent reference.

Later changes cannot silently replace the parent snapshot or remove attribution. A creator's withdrawal, account removal, takedown, and existing derivative must have explicit policy. Those decisions are not solved by deleting lineage or rewriting history. Revenue sharing or royalties between original creators and remixers are not assumed; they require explicit product terms and user agreement.

## Young users and commercial features

The intended creator experience includes users aged 12 and above. Account eligibility, privacy defaults, appropriate adult involvement, reporting, and permitted AI access must be designed before a pilot admits minors. Seller onboarding is too late to introduce those controls.

Creator access and commercial eligibility are separate. Purchases, sales, tax/payment-provider processes, and payouts require their own supported flow. Sensitive identity and payment processing should use qualified providers with minimal data retained by the product.

The proposed 10–30% marketplace fee, CHF 15/39/99 plans, and separate AI credits are business hypotheses. They are not launched prices, provider-cost estimates, verified margins, or promises about creator earnings. Their later acceptance must cover unit economics, transparent terms, refunds, and reconciliation. An internal AI usage ledger is not a customer payment or payout ledger.

## How this plan is accepted

The planning deliverable is complete when ownership, contracts, phase gates, evidence requirements, and cross-repository references are consistent. It does not require implementing the proposed services now.

Implementation readiness will require separate proof: Core contract tests, consumer integration tests against a pinned Core version, real engine builds and play sessions, negative rights and tenant tests, and operational qualification. See [Core and Cloud backlog ownership](core-cloud-backlog.md) for stable IDs and the acceptance bridge.
