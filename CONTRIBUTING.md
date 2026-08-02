# Contributing to Agent Factory

Thank you for helping build a dependable, provider-neutral orchestration layer.

## Ground rules

- Keep the core project-neutral. Customer names, private requirement documents, and domain-specific workflows belong in downstream configuration.
- Preserve the human approval boundary. Provider output must never approve itself or silently authorize an external mutation.
- Default to simulation and dry-run behavior.
- Treat provider output, imported backlog data, repository content, and CLI output as untrusted.
- Add tests for success, denial, replay, timeout, malformed input, and interrupted execution paths.
- Do not include credentials, personal data, local absolute paths, generated databases, or provider auth profiles.

## Development setup

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e .
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

### macOS or Linux

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

## Before opening a pull request

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
python -m pip install build
python -m build
docker build -t agent-factory:check .
```

Also verify that a clean wheel installation works from a directory outside the repository.

## Change expectations

### Provider adapters

A provider change needs:

- a fixed executable resolution strategy;
- immutable arguments for non-interactive, least-authority operation;
- a role allowlist;
- a hard timeout and output limit;
- an explicit prompt transport;
- health, missing-executable, denial, timeout, and cleanup tests;
- documentation of authentication ownership and side effects.

Do not enable a provider that can silently execute tools, change files, contact people, or mutate external systems.

### Workflows

Workflow stages need a unique ID, dependencies, an agent, an artifact name, acceptance criteria, and allowed verdicts. Tests must cover cycles, missing dependencies, invalid order, blocking verdicts, and missing evidence.

### GitHub operations

New mutation types must be narrowly allowlisted. Add tests proving that destructive or unrelated state changes remain blocked, approved plans cannot be replayed, and successful partial results stay idempotent.

### Storage

Never rewrite a released migration. Add a new migration and prove upgrade compatibility from the previous schema. State transitions and their audit event must commit atomically.

## Pull request checklist

- [ ] The change is focused and project-neutral.
- [ ] Tests cover the new behavior and its denial paths.
- [ ] Documentation and examples match the actual CLI.
- [ ] No credentials, personal data, absolute home paths, or runtime databases are included.
- [ ] Approval, audit, and dry-run guarantees remain intact.
- [ ] The wheel and Docker image build successfully when relevant.

No contribution license has been selected yet. Discuss contribution terms with the repository owner before submitting material intended for incorporation.
