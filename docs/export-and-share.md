# Exporting a game, and sharing it as a separate act

Exporting and publishing are two different decisions. Core packages a verified
version for a supported target and stops there. Publication has its own preview,
its own named approver and its own call — a development authorisation never
grants it, and a cancelled share performs no external action at all.

Requirement trace: `AF-GC-037`. Core owns the generic packaging and the
publication gate; which audience may see a release stays a Lokiravia decision.

## Targets

| Target | Platform | Offered |
|---|---|---|
| `linux-x86_64` | Linux | yes |
| `windows-x86_64` | Windows | yes |
| `portable-zip` | Any desktop | yes |
| `web` | Browser | no — needs its own engine template and qualification run |
| `ios` | iOS | no — needs an Apple developer account and a signed build |
| `console` | Console | no — needs a platform partner agreement and a qualified toolchain |

An unsupported target is explained **before** anything is built, not after a
failed attempt.

## What the check refuses

`preflight` runs before packaging and refuses, with the reason:

- the recorded build artifact is missing, or its bytes no longer match the
  verified version;
- an asset without export rights (the verdict names the asset);
- a secret in any file that would ship — private key blocks, AWS and GitHub and
  Slack tokens, bearer tokens, and `api_key`/`secret`/`password`/`token`
  assignments — including inside the compiled game file;
- a local home path (`/home/<name>/`, `/Users/<name>/`, `C:\Users\<name>\`).

Findings are reported with the matched value **masked**, so the log of a refusal
is not itself a leak. `.git`, `.lokvetia`, `.env`, databases, keys, logs and
`export_presets.cfg` (which holds local output paths) are excluded from packages
by default; `--exclude` adds more.

## What the package contains

```
lokvetia-bundle.json   version digest, source commit, engine, checksums, file list
LAUNCH.md              what this is, how to run it, the game file's SHA-256
ATTRIBUTIONS.md        the credits the assets require, or a plain statement that none do
game/<artifact>        the built game
source/...             the project files this build came from
```

The manifest records `published: false`. Packaging never sets it otherwise.

## Sharing

`prepare` returns a preview that performs nothing and states what is still
required: a named human approver, an explicit publish decision, and a connected
publisher. Then:

- **cancel** → outcome `cancelled`, `external_state_changed: false`, and the
  record says the cancellation happened before any external call;
- **approve without an approver name** → refused, nothing published;
- **approve with no publisher connected** → refused, and the reason says nothing
  was published (the default: Core has no publisher);
- **approve with a package whose checksum differs from the reviewed one** →
  refused; an approved preview cannot carry a different file;
- **approve, with rights blocked** → refused, naming the assets.

Only an approved decision on the reviewed package, with an approver and a
connected publisher, calls that publisher — exactly once.

```bash
lokvetia export targets
lokvetia export preflight --project my-game --path ./my-game --target linux-x86_64
lokvetia export build --project my-game --path ./my-game --target linux-x86_64 \
    --output ./dist/collector-linux.zip --name "Collector Starter"

lokvetia export share --bundle ./dist/collector-linux.zip \
    --destination https://example.com/games --visibility unlisted
lokvetia export share --bundle ./dist/collector-linux.zip \
    --destination https://example.com/games --visibility unlisted --cancel --actor "your-name"
```

`preflight` and `share` exit `3` when the answer is no.

## What this does not do

It does not publish anywhere by itself, decide who may see a release, or prove a
package runs on a clean machine. Running the export on a clean machine is still
a required acceptance step for `AF-GC-037` and is not recorded here.
