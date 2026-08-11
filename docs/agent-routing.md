# Evaluation-aware agent routing

AF-011 routes an AF-010 role/version requirement without trusting a caller's qualification claim. For every candidate it reloads the latest immutable qualification, validity window, lifecycle state, provider binding and capabilities, then combines those facts with enabled/health, model independence, quality, risk, cost, latency, load and canary evidence.

The supported deterministic strategies are `pinned`, `best-qualified`, `cost-aware`, `latency-aware`, `diversity`, `canary`, `tournament`, and `fallback`. Stable agent IDs break every tie. Each immutable decision stores the exact request and candidate snapshots, eligible and excluded lists with reasons, rationale, selected agent, and ordered fallback chain. Reusing a decision key returns the same result only for the exact same request.

Failed, expired, quarantined, offline, provider-mismatched or capability-incompatible qualifications cannot route. Independent decisions also exclude the producer model. The existing `ReviewerRouter` remains unchanged and continues its deterministic least-used, model-aware round robin for independent review stages.
