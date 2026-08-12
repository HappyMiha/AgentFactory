# CI troubleshooting

The repository CI workflow is `.github/workflows/ci.yml`. Validate the same checks locally before investigating GitHub status:

```powershell
$env:PYTHONPATH = "src"
python -m compileall -q src tests
python -W error::ResourceWarning -m unittest discover -s tests
python -c "import json; json.load(open('examples/development-backlog.json', encoding='utf-8'))"
```

If a GitHub run shows every job failing within a few seconds with no steps, inspect the run annotations with `gh run view <run-id> --verbose`. “The job was not started because recent account payments have failed or your spending limit needs to be increased” is an account billing/runners problem, not a repository test failure. Resolve it in GitHub Settings → Billing & plans and rerun the workflow.

Action major versions are intentionally pinned to supported tags (`checkout@v4`, `setup-python@v5`, and `upload-artifact@v4`). A started job with a failing step should be reproduced locally from that step’s command; a job that never starts cannot be fixed by changing application code.
