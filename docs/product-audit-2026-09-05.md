# Product audit summary

Audit date: 2026-09-05. Runtime baseline: `03bb23b8f58e64f1fc0e4a14ecb4ff1fe27ec32d`. The earlier audit and AF-GC plan were published in `43a26cad86f08b18eae13595d99ef621c61f799d`. This English planning revision does not change or repair runtime code.

**Conclusion:** Core is a useful orchestration foundation. The repository does not yet prove the intended beginner journey from a plain game idea through guided setup to a playable, editable game. A working consumer Cloud product has not been established by this audit.

## Evidence and limits

The audit ran 409 tests on Windows with Python 3.11: 408 passed and one Docker durability test was skipped. A source distribution, wheel, clean-environment CLI demo, and 13 targeted backlog/roadmap checks also passed during the earlier audit. Those results cover the tested environment and component paths; they do not prove real model or engine integration. The recorded CI baseline also had platform-dependent failures.

| Finding | Evidence type | Product impact | Existing requirement |
| --- | --- | --- | --- |
| Bootstrap can record a ready phase without installing or probing the required tools | Source review and focused checks | A creator can see readiness before the machine is ready | AF-GC-002, 013–015 |
| The configured model can differ from the model actually invoked | Source and runtime-path review | Model choice, cost estimates, and review separation may be misleading | AF-GC-006, 041 |
| Some planning roles are rejected by provider role restrictions | Source and focused checks | Local planning can stop before useful work starts | AF-GC-042 |
| A live child route can assign one effective producer to multiple stages | Source review | Independent review is not established by different role names | AF-GC-041 |
| A plain paragraph can lose its meaning in the deterministic intake path | Reproduction | A beginner's original idea is not reliably carried into the plan | AF-GC-005 |
| Background UI refresh can replace an unsaved model draft | Browser reproduction | The user loses an edit while trying to configure the system | AF-GC-004 |
| Confirmation state may be reused after cancellation | Source-only concern; browser confirmation not completed | A destructive confirmation flow needs a targeted regression check | AF-GC-003 |
| Application access controls are not consistent across the reviewed API surface | Focused authorization checks | Hosted exposure needs verified, consistent account boundaries | AF-GC-039; Cloud AF-CLD-021 |
| Coding-worker foundations exist, but the complete production route to an accepted game commit is not demonstrated | Source-path review | An agent response is not proof of a changed, integrated game project | AF-GC-019; AF-AMM worker integration |
| No qualified Godot/Unity creator path, real hardware setup wizard, or complete Play/feedback flow was found | Repository and UI review | Engine and consumer features remain planned work | AF-GC-007–040, applied by phase |

The current Local Control Center is an operator interface. It needs a separate Creator experience with plain-language status, one next action, preserved drafts, visible budget, and access to the last working game. Usability for children aged 12+ is a testable product goal, not an observed result.

## How to use this audit

Keep generic fixes in Core and accept the game experience in Cloud against a pinned upstream version. Use the [42-task upstream plan](../examples/game-creator-backlog.json), the [ownership map](core-cloud-backlog.md), and the [Core/Cloud roadmap](core-cloud-roadmap.md). Do not reopen every historical component task or assume every earlier Ready label describes production behavior.

The [full Ukrainian audit](product-audit-2026-09-05.uk.md) contains the detailed observations, evidence boundaries, and original priorities. The user reports an available server, but no server access, capacity test, deployment, or hosted game acceptance was performed for this planning revision.
