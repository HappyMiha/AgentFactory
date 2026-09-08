# Lokvetia Core visual identity

Lokvetia is the family brand. **Lokvetia Core** is its local AI agent orchestration product, formerly AgentFactory. **Lokiravia**, formerly AgentFactory Cloud, is the separate creative product and is endorsed as **Lokiravia by Lokvetia**. Core's game-related tools remain part of Lokvetia Core; their presence does not turn Core into Lokiravia.

The identity expresses precision, clear responsibility, and a calm working environment. The open geometric L represents a deliberate path; the separate square shares its grid. Neither shape communicates a live system status or an approval.

## Canonical assets

| Asset | Repository path | Served path |
| --- | --- | --- |
| Mark and SVG favicon | [`src/agent_factory/static/brand-mark.svg`](../../src/agent_factory/static/brand-mark.svg) | `/assets/brand-mark.svg` |
| Full wordmark | [`src/agent_factory/static/brand-wordmark.svg`](../../src/agent_factory/static/brand-wordmark.svg) | `/assets/brand-wordmark.svg` |
| Application identity styles | [`src/agent_factory/static/brand.css`](../../src/agent_factory/static/brand.css) | `/assets/brand.css` |

The mark has a `64 × 64` viewBox. The wordmark has a `360 × 80` viewBox and includes “Lokvetia Core” with “HUMAN AUTHORITY. AGENT CAPABILITY.” The SVG files contain native geometry and local text; they make no external font or image requests.

## Color

| Role | Color | Use |
| --- | --- | --- |
| Deep ink | `#102C35` | Light-screen text and mark background |
| Core teal | `#176B5C` | Primary buttons and links on light screens |
| Mint | `#6FE1C7` | The L inside the mark |
| Paper | `#F3F7F6` | Light application background |
| Muted ink | `#50666B` | Supporting copy on light screens |
| Light border | `#D5E1DF` | Dividers and card outlines |
| Night | `#0B1B22` | Dark application background |
| Dark surface | `#12272F` | Dark panels and review cards |
| Dark text | `#EDF6F3` | Main text on dark screens |
| Dark accent | `#80DCC1` | Links and accents on dark screens |
| Dark muted text | `#A2B8B4` | Supporting copy on dark screens |
| Focus, light / dark | `#A66216` / `#F0C778` | Keyboard focus outline |

Use the specified dark teal for text on light backgrounds. The mark's bright mint is a graphic accent, not a substitute for accessible body text. Existing warning, failure, and approval states retain their meanings; communicate states with words as well as color.

## Typography and composition

Application text uses `Segoe UI Variable Text`, then `Segoe UI`, then the system sans-serif. Headings use the same family with restrained negative tracking. No hosted fonts are required. The standalone wordmark uses `Segoe UI` with an Arial/sans-serif fallback; its text remains searchable in the SVG.

Keep the mark square and scale proportionally. Allow clear space of at least one quarter of the mark's width around a standalone mark. Use it at 24 CSS pixels or larger in normal content; the favicon may be smaller. Application headers currently use 36–40 pixels.

The standalone wordmark is intended for a light background. Use it near its 360-pixel native width when the small tagline must be readable. In narrow headers or dark interfaces, use the mark beside live HTML product text, as the application does. Do not compress the full lockup, stretch the mark, add effects, or recolor individual shapes. A light panel is appropriate when placing the full wordmark on a dark presentation.

## Accessibility and implementation

A mark next to visible “Lokvetia Core” text is decorative and uses an empty `alt`. A standalone image needs an accessible name of “Lokvetia Core.” Avoid duplicating that name in adjacent image and link labels. Keyboard focus uses a visible outline, and motion respects `prefers-reduced-motion`.

The shared CSS is loaded after page styles and is scoped with `brand-core` and, on the existing dark pages, `brand-dark`. Page classes keep layout changes local. Preserve existing DOM IDs, hidden states, form contracts, and approval controls when changing presentation.

The brand domain is `lokvetia.com`. A domain link is a brand reference; it does not certify that a hosted Core service is available there. These assets define the project's visual identity and make no claim of trademark registration. Technical compatibility and rollout decisions are documented in [the migration guide](migration.md).
