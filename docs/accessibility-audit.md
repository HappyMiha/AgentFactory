# Accessibility judged on the rendered page

Reading the markup tells you what the author wrote. It does not tell you whether
the text is legible on the colour behind it, whether a control is big enough to
hit, whether focus is visible, or whether the page still fits at 320 CSS pixels.
So the browser collects what it actually rendered, and the rules judge that.

Requirement trace: `AF-GC-024`, which asks explicitly for the *dynamic*
interface, keyboard use and understandable errors — "not just HTML strings".

## Collection and judgement are separate

`accessibility.COLLECTOR_SCRIPT` runs in the page and returns a snapshot:
computed colours and font sizes, laid-out boxes, accessible names, focus rules
that apply, headings and landmarks that are visible, live regions, the tab order
and the document width. `accessibility.audit` judges that snapshot.

The rules are therefore testable without a browser (`test_accessibility_rules`,
34 cases), and any collector producing the same shape is judged identically.

## What is checked

| Criterion | Rule |
|---|---|
| 1.3.1 Info and Relationships | one visible `h1`, a `main` landmark |
| 1.4.3 Contrast (Minimum) | 4.5:1, or 3:1 for text ≥ 18.66px or bold ≥ 14px |
| 1.4.4 Resize Text | no horizontal scroll at a 200%-zoom viewport |
| 1.4.10 Reflow | no horizontal scroll at 320 CSS px |
| 2.4.1 Bypass Blocks | a skip link where there is navigation to skip, and it comes first |
| 2.4.2 Page Titled | the page has a title |
| 2.4.3 Focus Order | no repeated stop in the tab order |
| 2.4.7 Focus Visible | a focus rule applies to every focusable control |
| 2.5.8 Target Size (Minimum) | 24×24 CSS px, excepting inline links in a sentence |
| 3.1.1 Language of Page | `lang` is set, and is Ukrainian or English |
| 4.1.2 Name, Role, Value | every visible, enabled control has an accessible name |
| 4.1.3 Status Messages | a status region announces itself |

Contrast uses the WCAG relative-luminance formula; the unit tests pin the known
values (white on black is 21:1, `#777` on white is 4.48:1, which fails).

## Running it

```bash
python -m unittest tests.test_accessibility_rules      # rules only, no browser
python -m unittest tests.test_accessibility_browser    # real Chromium
```

The browser suite starts the Local Control Center on a loopback port, opens
`/`, `/settings`, `/hardware` and `/login` at three viewports — 320×720,
1280×800, and 640×400 (which is how a 1280×800 laptop lays out at 200% zoom) —
and fails on any `problem`. It also walks the settings page from the keyboard,
checks that the first stop is the skip link, and checks that the consequence
dialog takes focus and gives it back on Escape. It skips itself when Playwright
is not installed.

## What this run found and fixed

The first run was not clean. Every control under 24px tall failed target size —
nav links, footer links, the skip link, checkboxes, and every button on the
settings page — so `brand.css` now declares the minimum once, for every page.
The settings page overflowed a 320px screen three times over: an auto grid
column sized to its content, a history table with no scroll container of its
own, and long unbreakable identifiers such as
`godot_pack.ADDITIONAL_ENGINE_VERSIONS` painting past the edge. The generated
settings controls had no accessible name at all — a visible heading above an
input is not associated with it — so each one now carries its own label. Status
paragraphs on the login and identity pages were not announced.

Two findings were the checker's own fault and are worth recording. Focus
visibility cannot be measured by calling `focus()`, because `:focus-visible`
deliberately ignores programmatic focus; the collector now asks the stylesheet
whether a focus rule applies. And a naive walk of CSS rules missed every rule,
because CSS nesting gave plain style rules an empty `cssRules` list that the
walk treated as a group to descend into.

## What is still open

`AF-GC-024` also requires the main journey to be localised in Ukrainian **and**
English, with errors that explain cause and action. The interface is Ukrainian
only; the language rule accepts both and flags anything else, but no
localisation layer exists yet. A manual screen-reader walkthrough is also part
of the card's acceptance and has not been done — an automated check cannot
replace someone listening to the page.
