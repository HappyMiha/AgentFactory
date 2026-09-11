# Asset provenance, safe import and hardware budgets

Three questions about an imported file are kept apart, because the answers are
independent:

1. **May this file be used at all?** Type is decided by content, and archives
   are inspected before anything is written.
2. **Do we have the rights to ship it?** Source, licence and attribution, or an
   explicit `unknown` marker.
3. **Will it fit the machine?** Per-asset, per-image, per-audio and total
   budgets tied to a target hardware profile.

Requirement trace: `AF-GC-035`. Core owns generic provenance and safe import;
game-specific asset rules stay in the game pack, and release, remix and
marketplace rights decisions stay in Lokiravia.

## Rights

An asset with unknown rights is **not blocked from local work** — it can be
imported, edited and built into an internal build. What it blocks is every
operation that needs rights: `export`, `share`, `publish`, `sell`.

| Licence | Redistribute | Commercial | Attribution required |
|---|---|---|---|
| `CC0-1.0`, `owned` | yes | yes | no |
| `CC-BY-4.0`, `CC-BY-SA-4.0`, `OFL-1.1`, `MIT`, `Apache-2.0` | yes | yes | yes |
| `licensed-noncommercial` | yes | no | yes |
| `licensed-internal` | no | no | yes |
| `unknown` | no | no | — |

A licence that requires attribution with none recorded is refused with that
reason, not silently allowed. One unknown asset blocks the whole project's
export until its licence is recorded; `rights_check` names exactly which assets
block it and why.

## Safe import

- **Type comes from content.** A file named `sprite.png` that holds a `MZ` or
  ELF header is refused as executable content; a PNG named `.jpg` is reported as
  a mismatch rather than quietly accepted. Nothing is ever handed to a plugin.
- **Archives are inspected, not extracted.** `inspect_archive` refuses path
  traversal (`../`), absolute and drive-letter paths, backslash separators,
  symbolic links, non-regular members, duplicate names, member counts over the
  limit, expanded sizes over the limit, and compression ratios that look like a
  decompression bomb. It writes nothing at all.
- **Measurements are real or absent.** PNG, GIF and JPEG dimensions and WAV
  duration are read from the headers. For formats this module cannot measure,
  the record says `measured: false` instead of guessing.

## Budgets

| Profile | Per asset | Total | Image pixels | Audio |
|---|---|---|---|---|
| `baseline-pc` | 32 MB | 512 MB | 4096×4096 | 600 s |
| `low-end-laptop` | 8 MB | 128 MB | 2048×2048 | 300 s |
| `handheld` | 4 MB | 64 MB | 1024×1024 | 180 s |

An asset over a per-asset, pixel or audio budget is refused with the measured
number in the reason. An import that would take the project over the total
budget is refused at apply time.

## Preview and rollback

Import is plan-then-apply, like the game pack. A file you changed in the project
after it was imported becomes a `conflict`: the apply is refused unless a named
approver names that exact file. Every replaced file is copied into
`.lokvetia/asset-backups/<backup id>/` first, so `rollback` restores the previous
bytes and removes assets the import added. `.lokvetia/assets.json` records each
asset's digest, size, kind, format, measurement and provenance.

```bash
lokvetia assets inspect --archive ./downloads/pack.zip
lokvetia assets add --path ./my-game --file ./hero.png --name art/hero.png \
    --licence CC-BY-4.0 --source "https://example.com/hero" --attribution "A. Artist"
lokvetia assets add --path ./my-game --file ./hero.png --name art/hero.png \
    --licence CC-BY-4.0 --source "https://example.com/hero" --attribution "A. Artist" --confirm
lokvetia assets rights --path ./my-game --operation export
lokvetia assets list --path ./my-game
```

`inspect` and `rights` exit `3` when the answer is no, so a delivery loop can
gate on the exit code.

## What this does not do

It does not scan for malware, validate that a licence claim is true, or prove
that an asset performs well on a given GPU. It records what was claimed, refuses
what is structurally unsafe, and measures what it can actually read.
