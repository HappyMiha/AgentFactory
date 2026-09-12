# Two languages, or the catalogue is wrong

The product claims Ukrainian and English. A half-translated interface is worse
than an untranslated one, because it hides which half is missing. So every
message carries both languages, and the type refuses to exist without them.

```python
Message("Налаштування", "Settings")     # fine
Message("Налаштування", "")             # MissingTranslation
```

Requirement trace: the localisation half of `AF-GC-024`. The other half — the
accessibility of the rendered page — is [already checked](accessibility-audit.md).

## Where the text lives

`localisation.CATALOGUE` holds the shared interface strings. Setting labels,
help, consequences, section titles and every section finding are `Message`
objects declared next to the thing they describe, so a new setting cannot be
added in one language only.

Three tests defend this and are the reason it stays true:

- **every message carries every language** — a blank half fails;
- **the two languages actually differ** — a Ukrainian string copied into the
  English slot is not a translation, and only the product name is exempt;
- **every setting, section and finding** is checked the same way.

## Choosing the language

An explicit choice wins, then a remembered one, then what the browser asked
for, then Ukrainian:

| Source | How |
|---|---|
| explicit | `?lang=en` on the page or any settings API call |
| remembered | a cookie the page route sets when you choose |
| browser | `Accept-Language`, ranked by its own `q` values |
| default | Ukrainian |

A regional tag resolves to its language (`en-GB` → `en`); anything unsupported
falls back rather than half-applying.

## How a static page gets translated

`GET /api/i18n` returns the whole catalogue in the negotiated language. The page
carries `data-i18n="key"` on its text and `data-i18n-attr="aria-label:key"` on
its attributes, and fills them on load — including `<html lang>` and the tab
title, so a screen reader announces the right language and the accessibility
audit sees it.

Generated content goes through the same catalogue. A missing key renders as the
key itself, which is loud, rather than as silent Ukrainian, which is not.

## Errors reach the person in their language

An error a person must act on travels as a `LocalisedError` carrying its
`Message`; the request boundary renders it in the negotiated language, and
`str()` still gives Ukrainian so a log line reads. Refusals are phrased as cause
plus action:

> Ліміт часу на операцію: 2 менше за мінімум 10. Виберіть значення в межах.
> Time limit per operation: 2 is below the minimum 10. Choose a value in range.

## What is not translated yet

Only the settings area and the shared chrome. The creator journey, the operator
console and the hardware pages are still Ukrainian only; they carry no
`data-i18n` and are not served through the catalogue. `AF-GC-024` stays open
until they are, and until someone walks the journey with a screen reader in both
languages.
