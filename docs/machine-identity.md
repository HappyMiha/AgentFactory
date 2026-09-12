# Whose hardware is this?

The demo at test.lokvetia.com reported the container's CPU where a person
expected their own. Nothing in the report was false; the report simply never
said which machine it described, and a reader supplied the wrong answer.

Requirement trace: `F8` of the AI-studio statement and the honest-reports half
of `AF-ST-701`.

## One rule, in one place

`describe_this_machine()` decides, and every hardware report carries the answer:

1. **A declaration wins.** The deployment sets `LOKVETIA_MACHINE_KIND`
   (`this_pc`, `web_container` or `cloud_worker`) and optionally
   `LOKVETIA_MACHINE_NAME`. Whoever deploys knows; guessing is for when nobody
   said. The hosted test deployment now declares itself a `web_container`.
2. **Container markers mean a container.** `/.dockerenv`,
   `/run/.containerenv`, or a container cgroup.
3. **Otherwise it is the computer Core is installed on** — which is the truth
   for a local install.

Every answer carries *how* it was reached, because a guess and a declaration
are not the same evidence and the reader is entitled to know which they have.

## What a report now says

```json
"machine": {
  "kind": "web_container",
  "label": "the site's web container: test.lokvetia.com",
  "basis": "Declared this way by the deployment.",
  "is_the_users_computer": false,
  "caveat": "These are the numbers of the site's web container, not of your PC."
}
```

The caveat is printed on the hardware page next to the report, and it travels
with the downloaded JSON — a saved report that loses whose machine it described
is worth nothing later.

## What it deliberately does not do

- **No host name.** A hardware report omits host names and paths on purpose;
  the signature would be a fine place to smuggle one back in, so only a name
  the deployment declared is ever shown, and a test asserts the default is
  empty.
- **No claim of trust.** The signature says which machine produced the report
  as far as this process can tell. It is not a cryptographic attestation, and
  a process that lies about `LOKVETIA_MACHINE_KIND` is not caught here.
- **No routing.** Deciding which machine *may* run something is
  [`studio_workers`](studio-setup.md); this only names the one that did.
