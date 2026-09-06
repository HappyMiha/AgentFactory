# Local hardware inventory

AF-GC-011 collects the technical facts needed before choosing a model and game
engine. It does not install software, call AI models, approve a plan, or qualify
a machine for a particular workload.

## Creator flow

Open the PC page and choose **Перевірити ПК** (Check this PC). Opening the page
does not start a scan. The report shows its timestamp, operating system and
architecture, processor, available and total RAM, detected graphics devices,
available memory information, free workspace-volume disk space, and detected
runtimes or engines.

Unknown values remain unknown. In particular, failure to inspect a GPU does not
mean zero VRAM, and an undetected engine is not proof that it is absent. The
page explains that cloud AI remains an alternative; it does not claim that an
account is connected or that a cloud workload has been qualified.

The current Windows collector uses the native RAM API and a fixed CPU registry
field. NVIDIA memory comes from the fixed local driver tool; the Windows GPU
fallback reads names only. It does not trust the limited `AdapterRAM` field.
Linux reads bounded kernel CPU/RAM and DRM information. GPU type and shared
memory remain unknown when those probes cannot establish them. Other operating
systems return the available basic facts and explicit unsupported metrics.

Software detection checks at most 32 local PATH entries and a bounded set of
standard installation directories. It rejects network, relative and reparse
locations; Linux also rejects unknown or network mount types. Installed software
behind a skipped path can therefore remain undetected. Only the running Python
version is reported; other programs are not executed to obtain their versions.
Fixed GPU probes have a three-second deadline and 32 KiB output cap each, with
bounded child cleanup and no output-reader threads. No broad process or disk scan
is used. The disk observation refers to the workspace volume supplied by the host.

The report stays in the local process and the browser page. It is not written
to the project database or sent to a provider. An explicit download saves a
JSON copy in the user's chosen browser download location. Reloading clears the
page report. A failed rescan keeps the previous timestamped report visible.
The inventory does not request personal file contents, serial numbers or a
list of running third-party processes.

## Integration contract

```python
from agent_factory.web import create_app
from agent_factory.hardware_web import install_routes

app = create_app(workspace, database)
install_routes(app, workspace)
```

Install once, before application startup. The installer requires Core's existing
local access object and HTTP boundary; a bare FastAPI app is rejected. It adds
`GET /hardware` and `POST /api/hardware/scan` with an empty JSON object. The
workspace comes from trusted application composition, never from a request.
Extra body fields or query parameters are rejected. Static assets use Core's
existing `/assets` mount and are included by the package's static-file rule.

The scan inherits Core authentication, loopback host/origin checks, and the
existing `write` scope requirement for POST requests. An unauthenticated page
request displays the supported sign-in page. Responses have `Cache-Control:
no-store`. The scan runs outside the HTTP event loop. One scan per process may
run at once, across all workspaces; another caller receives HTTP 409 and can
retry after it finishes. This lock does not coordinate separate OS processes.
Unexpected failures return a generic HTTP 503 without raw driver error text.

Core010 owns the call in the default `create_app` and the main settings link.
This component's browser tests exercise the same installer on the production
base application. Until that composition is reviewed and merged, the default
application does not expose the PC page and AF-GC-011 remains incomplete.

## Evidence and limits

The collector uses schema version 1, bytes for memory/disk values, a UTC
observation timestamp, and explicit unknown reasons. Detection and measured
free memory are a snapshot, not a promise that a later build or model will fit.
Shared GPU memory must not be added to dedicated VRAM as if it were equivalent.
Driver-reported GPU memory and operating-system RAM have separate meanings.

Unit fixtures cover missing metrics and CPU-only, integrated/discrete graphics,
and low-disk cases. HTTP tests exercise the actual access boundary, rejected
parameters, redacted errors and concurrent requests. Chromium tests exercise
the page through real loopback HTTP. A separate actual host report is required
alongside these fixtures; test fixtures alone do not qualify a host profile.
Engine recommendations and model qualification remain later tasks.

For a standalone report, using the installed package or a checkout on PYTHONPATH:

```console
python -m agent_factory.hardware_inventory --workspace .
```

The Windows observation on 6 September 2026 detected a Ryzen 9 3900X with 24
logical processors, about 31.9 GiB total RAM and a GTX 1070 with 8 GiB dedicated
memory. It also found an Unreal Editor executable in the search scope. This was
presence/inventory evidence only: Unreal was not launched, and no model or game
build was qualified. Free memory and disk space change between observations.
