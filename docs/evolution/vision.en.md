<a id="lokvetia--lokiravia-світ-що-памятає-платформа-що-вчиться"></a>
# Lokvetia / Lokiravia: a world that remembers, a platform that learns


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [vision.uk.md](vision.uk.md). Source SHA-256 (UTF-8/LF): `dec331e5c3202df3d8cc216e2c9c98cbf0a8fc783f58cc88fe35e10cb3072bcb`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](vision.uk.md).

Shared product concept · 2026-09-09 · documentation revision 1.

**Lokvetia Core should become better at creating, verifying and improving products, including itself. Lokiravia should let people create a world that responds to their actions with a history of its own.** The ambition is to turn an unexpected idea into a verified new capability, and an individual adventure into part of a world that others can experience.

This is a product direction, not a claim that RSI has been implemented or an MMO is ready. It extends the existing backlogs. The current work produces concepts, contracts and requirements only; implementation does not begin as part of it.

<a id="1-продуктова-обіцянка"></a>
## 1. The product promise

Imagine a town where you helped an unfamiliar craftsperson move a broken bell. Nobody assigned an epic quest. A week later, that bell led to a different way of convening the town council. Some residents are grateful; others are annoyed. Merchants have invented a service that did not exist before. Perhaps your action was necessary. Perhaps the town would have found a similar path without you. The game lets you investigate, rather than declaring you the centre of every event.

Alongside it is another story. Core repeatedly failed to assemble the right context for an engineering task. It did not simply remember to “try harder”. It retained the cause of failure, proposed a new way to select evidence, tested it on previously unseen tasks, rejected two attractive candidates and accepted the third. The next version now finds errors in subsequent candidates for **Core itself** at lower cost. People can see the evidence for this gain and where it does not apply.

These stories share memory, consequences, exploration and verification, but have different success criteria. The game should surprise people and matter to them. The platform should help people more reliably and demonstrate improvements to its own capabilities.

<a id="2-три-обєкти-еволюції-одна-інфраструктура"></a>
## 2. Three objects of evolution, one infrastructure

| Object | Audience | What changes | What “better” means |
| --- | --- | --- | --- |
| **Lokvetia Core** | Product creators, engineers, researchers, operators | UX, tools, planning, orchestration, skills, memory, code, experimental methods, evaluator candidates | More independently accepted outcomes at comparable cost; fewer regressions; methods that transfer to new tasks |
| **Lokiravia as a creator product** | People with game ideas, small-studio creators | Briefs, first-version selection, Play, feedback, versions, explanations, authoring tools | People turn their own ideas into real games and can change them meaningfully while retaining authorship |
| **The Lokiravia world / game pack** | Players, communities, world authors | State, relationships, institutions, events, knowledge; later, rules and new interaction types | Tangible, causally understandable consequences, different paths, surprise, humour and memory without pressure to keep playing |

AgentFactory / AgentFactory Cloud are the historical names of these two products. This concept does not rename compatible AF IDs, Python packages or technical identifiers.

<a id="3-для-кого-починаємо"></a>
## 3. Who we start with

**The first creator:** an individual or small team seeking a small, complete game with a distinctive idea. Their problem: a generated result impresses for a minute, but is difficult to verify, change, save and make personal. Lokiravia's job: “Help me create a world with character, where player decisions have consequences.”

**The first Core user:** an agent-product creator whose system repeats mistakes and who cannot distinguish real progress from a more expensive run. The job: “Help the system learn to work better on itself, while giving me understandable evidence and version control.”

**The first player:** someone who enjoys cooperation, experimentation and stories about unexpected uses for ordinary things. The initial format is a short single-player adventure involving cooperation with NPCs; depth of consequences matters more than map size. A relaxed pace and accessibility are part of the design. Human co-op is a separate later direction requiring verification of networking and shared permissions; it does not silently expand the current Godot MVP.

The first target is a small Godot 2D vertical slice aligned with the current creator roadmap. A large 3D/Unreal version, numerous worlds and communities of thousands belong to a later evidence horizon, not the hidden scope of the first version.

<a id="4-звідки-характер"></a>
## 4. Where its character comes from

From “corpus A” we take ways for humour to emerge: the mismatch between grand intentions and everyday needs, unexpected combinations of mechanics, friendship, ingenuity and amusing social costs. Humour should happen through actions and consequences. Generating more jokes does not ensure it.

From “corpus B” we take identity and futures shaped by choices, local interests, long causal chains and worlds changed by unusual interactions. Every analysed episode has a source locator; this project's concrete mechanics are our proposals, not a borrowed fictional system.

We do not carry over forced suffering, hidden administrator intervention against inventive players or manipulation through addiction. We use original worlds, characters and wording. EPUB files, full texts and substantial quotations do not enter Git.

From RSI research we take a harder promise: accumulate verified methodology as well as results. The world may change; the way the quality of a change is established may also evolve, through separate epochs, external anchors and comparisons.

<a id="5-сім-принципів-дизайну"></a>
## 5. Seven design principles

1. **The world responds for a reason.** Important events have traceable chains of causation. “Because the model decided so” is not a domain rule. A mechanism hidden from the player remains verifiable by the author.
2. **Open experimentation has costs and room to unfold.** New uses of objects depend on properties, context, resources and others' reactions. A player's words do not create unlimited authority.
3. **Significance is not the same as scale.** A small friendship can matter more than a global catastrophe. Ordinary, local and zero consequences make major ones credible.
4. **The world remembers unevenly.** Canonical fact, personal experience, rumour and belief are different things. A false rumour can have real consequences without changing what happened.
5. **Creativity does not suspend causality.** Authors can support a new interaction through a rule change in the next epoch. Past history is not rewritten retrospectively to suit a new plot.
6. **Improvement is demonstrated through external outcomes.** A new Core is evaluated on platform and consumer tasks; a new game on rule execution and human experience. These evaluations are not interchangeable.
7. **The system can stop and reconsider the question.** No effect, conflicting feedback, a regression or an obsolete objective may be the right endpoint for an iteration.

<a id="6-чим-rsi-має-відрізняти-продукт"></a>
## 6. How RSI should distinguish the product

A static generator starts each request with similar limitations. Our system accumulates verified methods, negative results and information about where they apply. Accumulation alone, however, is not recursive improvement.

We distinguish three claims:

- **Task improvement:** under a fixed protocol, G1 performs tasks better than G0.
- **Method improvement:** on new tasks, G1 selects, conducts and evaluates experiments better under an equal budget.
- **Frame improvement:** a proposed change of objective better serves new human needs while preserving required invariants. This remains an open research hypothesis involving human judgement.

The first independent demonstration is **Core-on-Core**, without depending on a finished living world. The second is a creator loop that makes game creation materially easier. The third is a playable living-world slice. They can be investigated in parallel, but success in one does not conceal failure in another.

<a id="7-що-побачить-користувач"></a>
## 7. What users will see

In Core: a change card showing the problem, before/after versions, improvements, regressions, costs, verification limits, the decision and a way back. A separate “evaluation method updated” notice compares old and new assessments. Authors should not have to read logs to understand the consequence.

In Lokiravia: the saved original idea, an understandable first adventure, Play for a specific version, change history, proposals informed by real feedback and consequence review. An author can say, “I want more unusual peaceful solutions, but keep the town's character,” and compare alternatives before accepting one.

In the game: new possibilities, rumours, relationships and traces of events. A personal chronicle shows only knowledge available to the character. The author's causal debugger sees complete events within its permissions. Players receive meaning and opportunities to act, rather than a technical panel of experiment IDs.

<a id="8-економіка-та-межі-росту"></a>
## 8. Economics and limits to growth

Core must be useful without Lokiravia. Self-improvement is evaluated through useful outcomes per unit of resource and reuse of methods. The creator product sells the ability to create and maintain personal games; research costs are shown separately from ordinary runs. Monetisation remains a hypothesis pending interviews and willingness-to-pay testing; this document invents no prices, TAM or revenue projections.

The pilot does not require an LLM call for every frame or every line of dialogue. The deterministic world operates on its own; models propose slower changes of intent, new affordances and research candidates. Proposals have time, resource and domain limits. Any claimed savings include generation, failures, verifiers, research, storage and human verification costs.

<a id="9-перша-послідовність-доказів"></a>
## 9. The first sequence of evidence

**E0 — the design can be falsified.** Repository facts, sources, reading limits, concrete contracts, verifiable criteria and an honest list of unknowns are available. This is the current documentation delivery.

**E1 — Core improves Core.** Baseline/challenger comparisons on independent platform tasks; a negative mutation is rejected; the accepted version persists; recovery is demonstrated. Success criteria are set before the run.

**E2 — the method improves the next method.** Several generations are evaluated on new tasks, controlling for budgets and memory effects, without regressions in consumer contracts. The hypothesis may fail.

**E3 — the world is worth a lived story.** A small, real single-player game: an unusual solution, a local consequence, a possible cascade, a failed grand strategy, save/load, an alternative causal branch and a human playtest. Multiplayer reconnect belongs to a later cooperative profile.

**E4 — stable world evolution.** A rule changes between epochs; an old save remains compatible; there is a chronicle, a faulty update can be stopped and human experience is reassessed. A new rule version is not automatically authorised for a public world.

**E5 — scale and new frames.** Larger worlds, long shared histories, Unreal and other targets, evaluator evolution and training-time research. Each direction needs its own evidence of value and quality.

The E stages complement existing `Ready / Playable / Exportable / Publishable / Sellable` and milestone gates; they do not replace them. A finished document does not mean E1–E5 have passed.

<a id="10-невизначеності-які-рухають-наступні-проходи"></a>
## 10. Uncertainties that guide subsequent passes

Do people stay in the world because of relationships and freedom to act, or only because of novelty? How much surprise remains fair? Does understanding complete causality matter to the author? Do Core's methods transfer between products? How can we identify a valuable change whose benefits appear a month later? What part of evolution justifies its own cost?

These questions lead to specific interviews, experiments and backlog items. The next iteration should reduce uncertainty or change a decision based on evidence. Increasing documentation volume is not an objective in itself.
