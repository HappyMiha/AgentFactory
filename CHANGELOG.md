# Changelog

All notable changes to Agent Factory are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Guarded Antigravity CLI adapter with native Windows and Unix executable discovery, plan mode, OS sandboxing, and a replaceable implementation worker.
- Immutable approval snapshots that bind each provider gate to the full work item, agent definition, provider catalog, and execution policy.

### Changed

- Provider launch now falls through to the next reviewed executable only when process creation fails before a provider starts, including Windows access-denied aliases.
- Provider stdout and stderr are drained through a hard combined limit; overflowing processes are terminated and audited.
- The test matrix now covers Python 3.11 and 3.12 on Windows, Ubuntu, and macOS.

### Planned

- Native HTTP provider interface.
- Per-stage live execution approval orchestration.
- Streaming output limits and value-aware secret redaction.
- PostgreSQL storage adapter.
- Hosted control interface.

## [0.1.0] - 2026-08-02

### Added

- Project-neutral work items, agent roles, provider definitions, artifacts, and approval gates.
- Deterministic offline provider for safe demonstrations and CI.
- Guarded CLI adapters for Codex, Claude, Gemini, and Ollama.
- Health-only OpenClaw integration with execution disabled by default.
- Dependency-aware workflows with typed verdict and acceptance-evidence contracts.
- SQLite migrations, WAL mode, online backups, integrity checks, and interrupted-attempt reconciliation.
- One-use human approval gates for real provider calls.
- Separate final acceptance decisions for completed workflows.
- GitHub dry-run planning, mutation allowlists, plan hashing, idempotency, and durable reports.
- Cross-platform process-group supervision and bounded execution.
- Windows, Ubuntu, and macOS CI plus wheel and Docker build checks.
