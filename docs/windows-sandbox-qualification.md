# Windows sandbox backend: probe findings

`platform_sandbox_backend()` still returns `UnavailableSandboxBackend` on Windows, so
writable execution remains disabled. This document records what an AppContainer and
job-object candidate actually enforced on one host. It is capability evidence for the
C-PILOT Windows decision, **not** a qualified backend and not a release gate.

Reproduce with `python scripts/windows_appcontainer_probe.py --report <path>`. The
probe writes a machine-independent report; the committed run is in
[`docs/evidence/windows-appcontainer-probe.json`](evidence/windows-appcontainer-probe.json).

## Candidate mechanism

Two separate primitives, each covering what the other does not:

- **AppContainer** supplies the resource boundary. The child starts through
  `CreateProcessW` with `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` and **zero**
  capabilities, so it reaches only objects whose ACL names its container SID. Denying
  network needs no rule: without `internetClient` the container has no route out.
- **A job object** with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` supplies process-tree
  containment. The child is created suspended, assigned to the job, then resumed, so no
  descendant can escape the job before it applies.

Write roots receive an inheritable `(OI)(CI)(M)` ACE for the container SID for the
lifetime of one execution; the interpreter or tool tree receives `(RX)`. Both grants are
removed afterwards.

## What the probe observed

Host: Windows 10 build 19045, unelevated session, Python 3.11. Thirteen checks, all
matching their expected outcome.

| Check | Expectation | Observed |
|---|---|---|
| C1 write into the worktree | allowed | allowed |
| C2 write outside the worktree | denied | `Access is denied.` |
| C3 write into a declared temp path | allowed | allowed |
| C4 read a private file outside the roots | denied | `Access is denied.` |
| C5 list the user profile | denied | `Access is denied.` |
| C6 outbound HTTPS | denied | connection failed |
| C7 write through a junction pointing outside | denied | `Access is denied.` |
| C8 write into the container's own package temp | allowed by design | allowed |
| C9 closing the job handle | tree terminated | tree terminated |
| C10 exceeding the execution timeout | tree terminated | tree terminated |
| C11 tool staged inside a sandbox-owned directory | allowed | allowed |
| C12 tool under the user profile with no ACE | denied | denied |
| C13 controlling process force-killed | tree terminated | tree terminated |

C7 matters because the ACL is evaluated on the junction's target, not on the path used
to reach it, so a reparse point inside a writable root does not widen the boundary.

## Constraints this candidate imposes

- **`LOCALAPPDATA` must survive environment scrubbing.** AppContainer profile
  redirection resolves through it; without it `CreateProcessW` fails with
  `ERROR_ENVVAR_NOT_FOUND` before the process exists. Every other profile variable
  stayed removable.
- **Tools must be staged into a directory the sandbox owns** (C11). A tool left under
  `%USERPROFILE%` is unreachable (C12), and making it reachable would mean writing
  container ACEs across the user's profile directories. An explicitly provisioned tool
  directory keeps the grant narrow and reviewable; silently widening profile
  permissions is not an acceptable substitute.
- **The container's own package directory stays writable** (C8). `%LOCALAPPDATA%\
  Packages\<container>\AC` is created by the OS and is outside the declared write roots,
  so teardown evidence must account for it rather than assume the worktree is the only
  place the child could have written.
- Granting an ACE on a directory does not reach files that already exist inside it;
  the grant has to be applied recursively.

## Outstanding before this can be qualified

The probe exercised the boundary, not the product path. Still unproven: the
`SandboxBackend` integration itself, the validator and Hermes/Codex routes over that
integration, concurrent executions sharing one container name, cleanup after an
interrupted grant, and behaviour on Windows builds other than the one above. Until
those carry their own evidence, the Windows profile stays **not-qualified** and
`UnavailableSandboxBackend` remains correct. WSL2 and Windows Sandbox remain separate
possible profiles; neither is a substitute for the Windows path.
