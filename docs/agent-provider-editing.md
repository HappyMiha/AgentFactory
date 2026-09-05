# Edit an agent's provider and model

In **Agents, providers & reviewer routing**, choose a compatible provider and edit
the model identity. The fields keep your unsaved draft, focus and text selection
while the dashboard refreshes. Recent work, enabled status and reviewer activity
continue to update beside them.

- **Save changes** opens the existing confirmation dialog. A successful response
  shows “Changes saved.” Changes apply to future assignments.
- **Cancel changes** discards your draft and displays the latest known server
  version. It does not send an update.
- Cancelling the confirmation dialog keeps your draft. A failed save also keeps
  it and shows an error beside the fields.

If the server's provider or model changes while you edit, saving pauses and the
card offers two choices:

- **Use server version** discards your draft and displays the server values.
- **Keep my draft** acknowledges the newer server version but keeps your values.
  You must still press Save changes and confirm the replacement.

The UI checks the server values again after confirmation, before sending the
update. A change observed there also stops the save and offers the same choices.
If a provider disappears, its selected value remains visible as unavailable;
the server still validates compatibility. If the agent disappears, the card
keeps your draft and disables saving.

Drafts exist in the current browser page only. Reloading or closing the page
discards them. This task does not introduce browser storage for model settings.
The final preflight read detects observed conflicts; it is not an atomic server
compare-and-swap. A change between that read and the existing update endpoint
still needs server-side revision enforcement in a separate contract change.
After an uncertain transport failure, refresh and reconcile the server values
before deliberately retrying.

## Verification

```bash
python -m pip install playwright
python -m playwright install chromium
python -m unittest discover -s tests -p test_agent_drafts.py -v
```

The tests use real Chromium with the production editor, refresh and native dialog
functions and intercepted HTTP responses. One test waits through three actual
five-second refresh cycles and verifies field identity, provider selection,
model text, focus, caret and changing status. Other cases cover conflict choices,
Save/Cancel, a server change during confirmation, failed saves, missing agents or
providers, untouched forms, out-of-order refresh responses and slow six-second
responses under the standard five-second poll.
Only a newer completed snapshot or a save barrier supersedes an older response;
a newer pending request cannot starve live updates. The existing dialog
and specification-preview suites remain regression checks. These tests do not
invoke an AI provider or certify a generated game.
