# Local Control Center accessibility checklist

AF-043 qualifies the loopback MVP against this keyboard and screen-reader baseline. The automated checks run in the normal unit-test matrix; the short manual pass is repeated when layout or control semantics change.

## Automated baseline

- The document declares its language, has a unique title, a skip link, one main landmark, labelled primary navigation, and semantic sections.
- Every input, select, and textarea is nested in or referenced by a label; icon-only controls are not used.
- Dialogs have programmatic names, status changes use polite live regions, and loading/detail workspaces announce updates without stealing focus.
- All actions use native links, buttons, forms, details, or dialog controls. There is no positive `tabindex` and no click-only non-interactive element.
- `:focus-visible` styling, reduced-motion handling, and responsive breakpoints are present.
- Primary text (`#f3f7fb`) and secondary text (`#91a2b8`) meet WCAG AA contrast against the dark page and panel surfaces.

## Manual keyboard and screen-reader pass

1. Press `Tab` from the address bar. The “Skip to dashboard” link becomes visible and moves focus to the main content when activated.
2. Traverse navigation, refresh, backlog filters/import, work-item actions, agent controls, audit filters, settings, GitHub preview, and Founder inbox using `Tab`/`Shift+Tab`; activate with `Enter` or `Space`.
3. Open each confirmation, run-detail, and Founder dialog. Focus remains within the native modal, every control has an announced name, and `Escape` closes the modal without executing a command.
4. Confirm that connection errors, successful commands, empty results, and refreshed evidence are announced through the status/live regions.
5. At 320 CSS pixels, verify there is no page-level horizontal scroll and controls remain reachable. At 200% zoom, verify labels and evidence do not overlap.
6. Enable reduced motion and confirm pulse/scroll animations stop. Verify visible keyboard focus on links, buttons, inputs, selects, textareas, and summary controls.
7. With a screen reader, follow the critical path: choose a work item, inspect the ordered run, read independent reviewer identity and exclusions, open the Founder packet, read unresolved findings, and cancel without mutation.

The MVP uses native browser dialog focus management. A future custom focus implementation must add dedicated focus-trap and focus-return tests before replacing it.
