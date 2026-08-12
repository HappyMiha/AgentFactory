# Prompt-injection defense

AF-021 adds a deterministic containment boundary for untrusted text from providers, tools, retrieved pages, repository content, and other agents.

## Maintained corpus

`SEEDED_CORPUS` has one versioned immutable case for each required class: indirect injection, authority escalation, secret extraction, tool abuse, artifact poisoning, and cross-tenant access. `run_seeded_corpus` persists the exact corpus digest and one linked result per case. A run passes only when every case is denied or quarantined and has containment evidence.

## Containment records

A detected payload creates an immutable security attempt, one tripwire per matched category, a quarantined output, and an open material incident. Records contain content/evidence digests, actor, tenant, mission, source, criterion linkage, rule version, and severity. The audit stream links their stable identities.

Evidence-tampering reports additionally bind the exact criterion-evidence row, artifact, original digest, attempted digest, and actor. Accepted artifacts and criterion evidence already have database-level update/delete guards, so the report cannot replace the original evidence it describes.

## Quarantine admission

Quarantined output cannot enter any authoritative sink:

- accepted context;
- typed memory;
- artifacts;
- downstream execution.

`admit_output` fails closed until a reviewer with the exact `human_security_reviewer` role records an explicit release and reason. Every post-release admission is immutable and attributed. The same role boundary controls closure of material security incidents; agents and ordinary operators cannot release or close them.
