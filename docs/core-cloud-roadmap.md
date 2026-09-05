# Core and Cloud roadmap

Planning revision: 2026-09-05. This update changes documents only. All new product work remains proposed.

Core will provide reusable, controlled AI execution. Cloud will turn that foundation into a simple game creation service. Keep one implementation owner for each capability and verify the product against a pinned Core version.

## Delivery order

| Stage | Core contribution | Cloud result | Evidence needed |
| --- | --- | --- | --- |
| M0: agree the boundaries | Review the actual runtime, stable interfaces, task ownership, and known regressions | Clear product scope, Game Brief model, Creator/Operator views, age and rights requirements | Reviewed contracts and a capability map; no deployment claim |
| M1: prove the game loop | Fix the required model identity, review, worker, setup, sandbox, and version gaps; qualify optional Godot packs | Three small games with browser Play, Windows/source export, feedback, v2, restore, and a private licensed remix | Real engine and graphical tests, independent review, clean-machine use, owner playtest |
| M2: qualify private hosting | Stable worker, credential, usage, state, cancellation, and recovery contracts | Accounts, isolated workers, protected artifacts, budget controls, and a hosted Creator Portal | Cross-tenant and failure tests, measured server capacity, restore drill, approved pilot |
| M3: open the creation loop | Authorized snapshots, immutable build identity, and auditable operations | Discover → Play → Remix → Create → Publish → Play | Rights and moderation checks, exact-release delivery, abuse handling, meaningful usage measurements |
| M4: add commerce | Scoped connectors and reliable usage evidence | Eligible sellers, licenses, purchases, refunds, entitlements, and payouts | Reconciled payment ledger and accepted commercial rules; pricing remains a hypothesis |
| M5: qualify more targets | Optional engine/target packs and conformance checks | Explicit support for selected Unity, Unreal, mobile, or PC-store routes | Evidence for every offered matrix row; unavailable consoles or targets stay blocked |
| M6: accept the supported service | Versioned templates, public integration contracts, and local/hybrid qualification | Reliable operation for a declared product scope | Security, recovery, compatibility, support, and measured economics; optional factory commerce and non-game work stay separate |

These are capability gates, not promised dates. Independent design can proceed in parallel. Do not delay the first Godot proof for later payment or engine work. Do not expose a hosted service before the required security and account controls are verified.

## First Core work to refine

1. Reproduce and resolve the current test and integration gaps, keeping the offline demo working: AF-GC-001–006, 039, 041, 042.
2. Qualify model connections, resources, and setup: AF-GC-009–015. A stored Ready state must follow actual probes. A browser alone cannot install software on a creator's PC.
3. Complete the smallest safe Godot route: AF-GC-016–024 and the relevant worker requirements in AF-AMM. Prove a real integrated source change and the exact playable artifact.
4. Accept the creator journey through the Cloud integration. Keep upstream component evidence distinct from AF-GC-026 and AF-CLD-020 product acceptance.
5. Add local/hybrid and other engine routes only when their own capability and resource tests pass.

This is a refinement sequence, not a replacement dependency graph. The canonical AF-GC manifest keeps its stable IDs and internal dependencies. Mixed historical requirements retain one traceable owner in the [ownership map](core-cloud-backlog.md).

## What does not change

The repository URL, Apache-2.0 license, existing source, historical requirement IDs, and offline demonstration remain in place. Optional game packs must not introduce engine-specific rules into the neutral scheduler. Cloud must not copy or bypass Core's authority over a run.

The [Cloud roadmap](https://github.com/HappyMiha/AgentFactory-Cloud/blob/main/docs/roadmap.md) owns the detailed M0–M6 product plan. Its [backlog](https://github.com/HappyMiha/AgentFactory-Cloud/blob/main/docs/backlog.md) contains 67 proposed tasks and seven epics. The [boundary document](core-cloud-boundaries.md) explains how the two repositories work together.
