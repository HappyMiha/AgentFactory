# Unity: a setup recipe, and a build whose verdict is not the exit code

Unity is not Godot. The Editor is installed through a Hub, modules are added per
platform, and the account, licence and EULA steps belong to Unity's own flow
between the person and Unity. So this is a recipe plus an adapter, not an
automation of someone else's agreement.

Requirement trace: `AF-GC-032` (setup) and `AF-GC-033` (pack, tests, build
adapter). Unity must not block the Godot route, and it does not: nothing here
changes the Godot path.

## What is pinned

| Editor | Series | Modules |
|---|---|---|
| `6000.0.23f1` (default) | 6000.0 LTS | windows-il2cpp, mac-mono, linux-il2cpp |
| `2022.3.45f1` | 2022.3 LTS | windows-il2cpp, mac-mono, linux-il2cpp |

Unity Hub 3.8.0 or newer. Build targets map to the module that builds them, and
each records which host platforms can build it — `iOS` needs macOS, `Android`
needs the SDK, NDK and JDK modules together.

## The licence step is yours

```
Open Unity Hub and sign in with your own Unity account.
In Preferences, Licenses, choose Add and follow Unity's own activation flow.
Accept Unity's terms in that flow; they are an agreement between you and Unity,
  not something this tool can accept for you.
Come back and re-run the readiness check; setup resumes from where it stopped.
```

There is no field, argument or file anywhere in this module for a Unity account,
password, serial or activation token, and a test walks every dataclass to prove
it. There is no `activate()`. The adapter takes a licence *probe* — something
that reports what Unity Hub says — and with no probe the answer is "not active",
never an optimistic default.

## What the status tells you

Every gap becomes its own action, each marked as the person's: install or
upgrade the Hub, install the pinned Editor, add the platform module, activate
the licence, free disk space. Other Editor versions are reported and explicitly
**not** removed — Unity supports several side by side. A target this machine
cannot build (iOS on Windows) is `blocked` rather than merely pending.

A project's own requirement is read from text files only: `ProjectVersion.txt`
for the Editor version, `packages-lock.json` for a dependency digest. A
same-series mismatch says the Hub can open it; a cross-series mismatch warns
that opening it upgrades the project and is **not reversible in place**, so copy
it first.

## Running the editor

Fixed argument vectors, `-batchmode -nographics -logFile -`, a hard timeout, and
a bounded log:

| Operation | Adds |
|---|---|
| import / compile | `-quit -projectPath P` |
| EditMode tests | `-runTests -testPlatform EditMode -testResults R` |
| PlayMode tests | `-runTests -testPlatform PlayMode -testResults R` |
| build | `-quit -buildTarget T -executeMethod M` |

`-runTests` is never combined with `-quit`; the editor exits on its own.

**Unity exits 0 on real failures**, so the log decides too. A run fails on
`error CS…`, `Compilation failed`, `Build completed with a result of 'Failed'`,
a licence message, another editor holding the project, unresolved packages, an
aborted batchmode, or a missing asset — whatever the exit code says. Tests are
read from the results file: a missing results file is a failure, not a pass, and
failing tests fail the run even when the log is clean.

Nothing starts at all while the licence is inactive, because a batch run without
a licence produces a confusing log rather than an honest error.

## The build record

Editor version, the project's own editor version, the packages-lock digest,
build target, source commit, artifact path, SHA-256 and size, and every run with
its command digest. `evidence_gap` always carries `graphical_playtest`, and
carries `play_mode_runtime` too when PlayMode did not pass — a headless batch run
is not someone playing the game.

`promotable` restates the same build in the playable ledger's neutral shape, so
a Unity build promotes through exactly the same gate as a Godot one: the editor
version is the engine version, the packages lock identifies the dependency
state, and the build target plays the part of an export preset.

```bash
lokvetia unity catalogue
lokvetia unity project --path ./MyGame
lokvetia unity health --executable "/path/to/Unity" --licence active
```

`unity project` and `unity health` exit `3` when the answer is not clean.

## What is not here

- **No reference Unity project.** `AF-GC-033` wants one with gameplay, controls
  and win/lose, and a reproducible package lock. Generating a valid Unity project
  without an editor is not something this change can verify, so it ships the
  recipe and the adapter and leaves the reference project to be made in a real
  editor.
- **No installation probing.** The catalogue and status describe and judge; they
  do not inspect your machine. The licence state comes from you.
- **Nothing was run against a real Unity Editor.** The adapter is qualified
  against a stand-in CLI only. `AF-GC-032`'s clean-VM activation handoff evidence
  and `AF-GC-033`'s healthy and broken project runs are the acceptance work, and
  both items stay open.
