# 72-hour soak

AF-033 defines the versioned mixed-mission workload and provider/worker/process/network/queue/storage/host fault schedule. `SoakService` records a run only with a declared duration of at least 72 hours, immutable resource evidence, and continuity evidence proving accepted state, artifacts, audit, and authorized external operations were preserved without duplicates.

The documented steady-state bounds are 2,048 MB memory, 10,240 MB storage, queue depth 1,000, zero orphaned leases, and 100 temporary environments. CI can replay the same evidence schema with measured values; any missing or over-bound value fails the gate.
