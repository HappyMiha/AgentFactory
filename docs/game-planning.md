# Local manual game planning (AF-GC-008)

After saving an idea into Core on the home page, open **Відкрити чернетку плану гри** in preparation. The planning page keeps the original specification visible and separately edits genre, engine, platform, controls, success/failure, visual direction, the first complete loop, assumptions, deferred ambition and cost/budget unknowns. Three unanswered questions appear at a time. A populated field is not proof that its assumption is correct.

The three templates (platformer, top-down collector and tile puzzle) are explicitly manual suggestions. Selecting a genre does not silently overwrite fields: the separate template button replaces form fields. Users can edit every field before saving. A large multiplayer vision remains intact in its original source while the proposed local first milestone and deferred capabilities stay separate. `examples/game-planning-fixtures.json` contains four reviewable synthetic examples, including that oversized case.

Saving requires the authenticated mission owner, local tenant access, the existing HTTP write scope, a boolean confirmation and the confirmation header. It creates one immutable HUMAN backlog revision with five executable-shaped draft tasks: scene, input, rules, verification and local exported-build checks. Each has dependencies, source/version/digest and field references, game-specific criteria, validation, required components/infrastructure, expected artifacts and definition of done. These tasks are proposed work, not scheduled work. A form edit updates the task preview only after an explicit save.

## Authority and concurrency

`GamePlanning` is a facade over `AutonomousMissionIntakeService` and `BacklogRevisionService`. Original source content is never rewritten by the facade. The existing revision snapshot `source.game_planning` holds fields, source binding, policy and save command ID; it is digest-bound immutable metadata, not a second source table or mutable plan store. Every explicit save may create another revision, including restoring previously used fields. A UUID command replays its exact request without duplicating a revision; reusing it with different content is rejected by the existing command authority.

The existing SQLite writer transaction covers owner, mission draft phase, current source digest, expected latest revision and immutable revision creation. A stale editor receives 409. A source update through the existing intake authority marks the displayed old binding stale and requires reviewing fields against the new source before saving. Previous revisions remain available read-only; the latest 50 revision links are shown, and the owner API can retrieve an older revision by ID. A latest revision belonging to another planning workflow is rejected rather than replaced. No storage schema or worker runtime changes are introduced.

The browser keeps unsaved text on errors and retries an ambiguous save with the same command. Navigation to another revision is blocked while local edits remain; save them or copy them before reloading. Original source previews stop at 12,000 characters with an explicit notice; the complete immutable source remains in Core. Browser rendering uses text nodes, not source HTML. Request bodies are bounded at 80,000 bytes and each field at 1,500 characters. API errors do not echo submitted source or fields.

## Acceptance boundary and future bridge

There is no model call, accepted AI plan, budget reservation, source extraction claim, automatic blueprint creation, backlog activation, approval, execution grant or publication here. Execution costs remain unknown until separate qualification and approval; no synthetic token/currency estimate is presented. The existing intake/blueprint readiness and approval workflow remains authoritative. This facade does not bypass its workforce/readiness gates.

Cloud AF-CLD-007 GameBrief versions and AF-CLD-008 scope proposals remain their current authorities. Core does not import their stores or copy their scope estimator. A future explicit bridge must bind the selected Cloud brief/version and scope proposal to a Core source and reviewed revision, preserve original ambition and record provenance/idempotency. Live cloud planning remains gated by Core AF-GC-018; this PR does not implement that bridge.

## Validation

Service tests cover restart, source immutability and updates, immutable history/reverts, exact command replay, competing writers, owner isolation, draft-only admission and another planning workflow. The four fixtures exercise genre-specific task contracts and preserve oversized ambition. HTTP tests use the default Core app and real authentication/origin/scope policy. Chromium tests use a synthetic mission and cover explicit save, reload, history, hostile source text, mobile layout and conflicting tabs. These tests do not qualify an engine build, model, hosted cloud planner or playable game.
