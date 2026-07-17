---
name: vapviz-design
description: >
  UI/UX + visual design system for the vapviz web app (ui/src). Use for any
  front-end change — new components, restyling, colors, theming, layout,
  accessibility — so the app stays one coherent, accessible, theme-aware product.
  Complements the artifact-design skill (general visual craft); this one encodes
  vapviz's specific tokens, identity, and rules.
---

# vapviz design system

vapviz is a self-hostable tracer/visualizer for AI agent pipelines — a local-first
cousin of LangSmith/Langfuse. Audience spans engineers AND non-technical viewers
(PM, ops). The UI must be **legible first, characterful second.**

## Use the tokens — never hardcode colors

All color lives in semantic, theme-aware CSS variables in `ui/src/index.css`
(`:root` = dark default, `html.light` = light — scoped to `html` on purpose:
ReactFlow v12 puts its own `light`/`dark` colorMode class on its container, and a
bare `.light` selector would let it hijack the tokens inside the graph). Values are
space-separated RGB channels; Tailwind maps them via `rgb(var(--x) / <alpha>)` (see
`ui/tailwind.config.ts`). Inline/canvas code reads them through `lib/cssColor.ts`.

- **Surfaces:** `--bg --surface --surface-hover --surface-inset`
- **Borders:** `--border --border-strong`
- **Text:** `--content --content-muted --content-faint --content-on-accent`
- **Accent:** `--accent --accent-hover`
- **Node kinds:** `--kind-agent --kind-step --kind-tool --kind-llm`
- **Status:** `--status-pending --status-running --status-success --status-error`
- **Pixel-step shadow ink:** `--shadow` (used only by the Tailwind shadow scale)

Rules:
- Add a token (with BOTH light + dark values) rather than a one-off literal.
- Anything that renders color — including the ReactFlow graph — must read tokens so it
  re-themes. Never commit a raw hex in a component.
- **One deliberate exemption (Nick, locked 2026-07-01):** the Theater's sprite-office
  diorama is a fixed warm palette that does NOT re-theme. Those hexes live as art data in
  `ui/src/lib/sprites.ts` / `ui/src/lib/officeArt.ts` (incl. the canvas-chrome `CHROME`
  set), governed by the **pixel-art-set** skill — components themselves still hold no raw
  hexes, and the UI chrome around the canvas themes normally.

## Identity — the app lives in the office's world (Nick, 2026-07-15)

The whole app wears the pixel-office look, *including its palette and all its
type* (the 2026-07-14 "pixel chrome / sans data" hybrid lasted one day — Nick
wanted full consistency, in the spirit of pixtuoid.dev but with plain
backgrounds, never imagery):

- **Palette is diorama-derived.** The theme tokens in `index.css` are taken
  from the sprite office's own hexes (`officeArt.ts`): dark = the office after
  hours (`#241a14` outline-ink surfaces, cream `#f3ead9` text, amber accent),
  light = the office by day (`#f6f1e6`/`#e7d8bf` creams, wood borders, deep
  amber accent). New tokens must stay in this warm family so chrome and the
  Theater/Building scenes read as one world. Kind/status hues stay as-is
  (semantic, cross-theme).
- **All type is pixel-family** (self-hosted @fontsource, OFL): **Silkscreen**
  display via `.px-display`/`.px-brand`/`font-display` (headings, tabs, badges,
  section labels); **Pixelify Sans** body — the global `body` font, all reading
  text; **VT323** for code-shaped text (`pre/code/kbd/.font-mono`, sized up
  ~1.16em in `index.css` because it draws small). Never introduce a non-pixel
  face; if a size renders illegibly, bump the size, don't switch family.
- **Form is pixel.** Square corners and hard-offset shadows come from the
  Tailwind `borderRadius`/`boxShadow` scale overrides in `ui/tailwind.config.ts`
  (do NOT re-add per-component radii/soft shadows). Faint checkerboard ground,
  pixel scrollbars, square focus rings — `index.css`.
- **Backgrounds stay simple** — subtle tile at most; no photos/illustrations
  behind content (explicit Nick rule, 2026-07-15).
- **Motion stays instant-or-subtle** — pixel UIs snap; no soft blurs, no big
  eased transitions in chrome.

There is **no Simple/Technical mode** (removed 2026-07-14): one adaptive UI,
with depth behind progressive disclosure (e.g. the detail panel's "Show
technical details" expander). Don't reintroduce audience gating.

**Legibility still wins every trade-off** — pixel faces were chosen for
readability (Pixelify Sans body, upsized VT323 mono); if a view reads badly at
its size, fix the size/contrast within the pixel system.

## Accessibility (required)

- **WCAG AA** contrast for text/surfaces in BOTH themes.
- **Colorblind-safe:** never signal state by color alone — always pair with an icon
  or shape (status icons already exist on nodes; keep that pattern). Red/green is
  never the only differentiator.
- Visible keyboard focus; respect `prefers-reduced-motion` (the Theater already
  gates its walk/idle animations on it — keep that for any new motion).

## Layout & type

- Spacing via flex/grid `gap`, not stacked margins. Wide content (tables, graph,
  code, logs) scrolls inside its own `overflow-x:auto` container — the page body
  never scrolls sideways.
- `font-variant-numeric: tabular-nums` for aligned numbers (costs, tokens, durations).
- Match the surrounding components' density, naming, and idiom when adding UI.

## Copy

Write from the user's side of the screen. Name things by what people recognize
(a "model call", not "llm_call event"); humanize labels (strip `agent/`/`llm/`
prefixes — see `formatLabel`). Costs use the project's `formatCost` (sub-cent runs
stay comparable). Active voice; errors say what happened + how to fix.

## Dual-logic reminder (not design, but easy to forget)

Event→graph reduction and the event schema are implemented twice (Python
`store.py` ↔ TS `runStore.ts`; `events.py` ↔ `types/events.ts`) and cost-reduce is
dual too. Changing an event type / node kind / cost logic means editing BOTH sides.
The Theater/Floor art (theater/sprites/officeArt/officeScene/OfficeStage) is UI-only and NOT part of that rule.

## Related
Pixel-art asset creation → the **pixel-art-set** skill. General visual craft →
the **artifact-design** skill.
