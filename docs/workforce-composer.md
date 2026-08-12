# Workforce Composer

AF-012 turns mission role needs into immutable, justified role pools. Each `RolePoolRequirement` names an exact AF-010 role version and qualification role, required capabilities, pool and AF-011 routing strategies, minimum and maximum replicas, arbitration rule, independence constraints, provider-diversity constraints, and bounded candidates.

Supported pool strategies are `singleton`, `fixed`, `elastic`, and `strengthened`. A strengthened pool requires at least two primary replicas and cannot use single-agent arbitration. Supported arbitration rules are `single`, `majority`, `unanimous`, `ranked_choice`, and `human_decision`.

## Composition

The composer snapshots current qualification identity, validity, lifecycle, capabilities, provider, model, capacity, and estimated cost for every candidate. AF-011 provides the deterministic eligible order and fallback chain. The composer then searches across all pools together so one locally attractive choice cannot silently oversubscribe a shared agent, combine incompatible AF-010 duties, or exceed the total mission budget.

A `ready` result includes required roles, strategies, replica bounds, arbitration, primary and fallback assignments, qualification evidence, applied exception reviews, cost, and remaining budget. A `blocked` result has no dispatchable primary workforce and exposes typed gaps for missing capability, independence, provider diversity, capacity, or budget.

## Human-reviewed exceptions

Model-independence and provider-diversity constraints remain fail-closed. A named human mission owner or human reviewer may record an immutable approved or rejected exception with a rationale. Only an approved review bound to the same mission, role pool, and exact constraint can be applied by a later composition. Unreviewed, rejected, unrelated, or machine-authored exceptions cannot weaken the workforce.
