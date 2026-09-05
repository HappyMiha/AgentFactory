# Reproducing the CI checks

Task: `core:AF-GC-001`. The CI matrix runs Python 3.11 and 3.12 on
Ubuntu, Windows and macOS. A clean checkout needs Git and Python, not a
personal AI CLI installation or provider credentials.

## Automatic and manual runs

At the owner's request (`core:AF-TEAM-002`), the six Python matrix jobs run only
when someone explicitly starts the **CI** workflow with **Run workflow** in
GitHub Actions. They are skipped on pull requests and pushes to `main`.
Wheel and Docker checks still run automatically. The separate required
coordination policy and team tooling checks remain active, as do local
pre-push checks. This changes scheduling; it does not repair or hide old failures.

To request the matrix for a specific branch, use **Actions > CI > Run workflow**
and select that branch, or run `gh workflow run ci.yml --ref BRANCH`.
The manual run also includes wheel and Docker checks. Record its actual head
commit when using the result as evidence; a branch name can move afterward.
An automatic green run does not mean the six-platform Python matrix passed.

## Local checks

Install and run the same checks locally with the Python environment you selected:

```sh
python -m pip install -e ".[web,dev]"
python -m compileall -q src tests
python scripts/validate-game-creator-backlog.py
python -m unittest discover -s tests -v
agent-factory --help
agent-factory --workspace ./tmp/ci-demo demo
```

Use `python3` when that is the name of your interpreter. Temporal workflow
tests download and start the SDK's time-skipping test server; internet access
and permission to run its binary are required. Failure to start that server
is a test failure, not a reason to silently skip the tests.

## What the regressions verify

- Monitor tests use a disposable provider configuration. The healthy CLI is
  the current Python interpreter with `--version`; no AI provider is invoked.
  An enabled missing CLI and a failed version probe degrade the monitor.
  Disabling the unused missing CLI removes its blocker. Emergency stop remains
  a blocker even with healthy providers. Production defaults are unchanged.
- Cancellation tests start a real long-running child and cancel its Temporal
  workflow. The child must disappear within a bounded wait. POSIX uses signal
  zero; Windows uses a checked `tasklist.exe` call and exact CSV PID matching.
  Probe failures do not count as successful cancellation. Additional tests
  verify live/reaped children and both OS probe paths.
- Empty unittest suites fail local commit checks on both Python 3.11 (exit 0)
  and Python 3.12+ (exit 5). Neither result creates a passing attestation;
  import failures retain their actual diagnostic.

The workflow uploads `tests-<os>-python-<version>` artifacts even when tests
fail. Each contains verbose unittest output, including executed test count and
skip reasons, and the installed dependency versions. Test pipelines preserve
the Python exit status. For a manual matrix run, inspect all six results for
the exact head, plus the separate wheel and Docker jobs, before claiming full
matrix validation. Historical failures remain visible in GitHub.

## Packaging and Docker

The wheel job builds both distributions, installs the wheel in a fresh
environment outside the checkout, exercises CLI help and the deterministic
demo, and verifies packaged defaults. The Docker job validates Compose,
builds the simulation image, and runs CLI help and the deterministic demo.
Neither job runs a paid provider or deploys a service.

One existing test is explicitly opt-in: `TemporalDockerDurabilityTests` needs
`AGENTFACTORY_TEMPORAL_DOCKER_TESTS=1` and a dedicated running local Temporal
stack. It stops/restarts that stack and currently uses a Windows PowerShell
health script. It is skipped with a visible reason in the default matrix.
The Docker image smoke job does **not** establish persistent Temporal server
restart durability. Never enable this test against a shared or production
stack; its cross-platform stack orchestration remains a separate limitation.

Record actual counts, skipped reasons, commit IDs and CI run links in the PR.
A local Linux pass alone does not certify Windows, macOS or product acceptance.
