# Qualification suite

AF-032 provides `QualificationService`, a deterministic release gate for declared availability, p95 latency, durability, and security thresholds plus capacity of at least 10 active runs, 25 runnable tasks, and 100 registered agents. Every run stores suite/profile version, Python/platform/profile metadata, thresholds, input load, all criterion results, and raw evidence in an immutable record.

Accessibility, tenant isolation, and backup/restore are explicit required checks. Missing (`None`) or false evidence fails the gate; `require_pass` raises before release. CI can supply measured NFR and load values while preserving the same criterion schema. Human product and operations owners approve any documented SLO exception.
