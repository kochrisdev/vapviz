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
(`:root` = dark default, `.light` on `<html>` = light). Values are space-separated
RGB channels; Tailwind maps them via `rgb(var(--x) / <alpha>)` (see
`ui/tailwind.config.ts`). Inline/canvas code reads them through `lib/cssColor.ts`.

- **Surfaces:** `--bg --surface --surface-hover --surface-inset`
- **Borders:** `--border --border-strong`
- **Text:** `--content --content-muted --content-faint --content-on-accent`
- **Accent:** `--accent --accent-hover`
- **Node kinds:** `--kind-agent --kind-step --kind-tool --kind-llm`
- **Status:** `--status-pending --status-running --status-success --status-error`

Rules:
- Add a token (with BOTH light + dark values) rather than a one-off literal.
- Anything that renders color — including the ReactFlow graph — must read tokens so it
  re-themes. Never commit a raw hex in a component.
- **One deliberate exemption (Nick, locked 2026-07-01):** the Theater's sprite-office
  diorama is a fixed warm palette that does NOT re-theme. Those hexes live as art data in
  `ui/src/lib/sprites.ts` / `ui/src/lib/officeArt.ts` (incl. the canvas-chrome `CHROME`
  set), governed by the **pixel-art-set** skill — components themselves still hold no raw
  hexes, and the UI chrome around the canvas themes normally.

## Identity & where personality goes

- **Cozy/warm identity** ties the app to the Theater's office aesthetic — but
  **the data views (Story / Graph / Logs / Dashboard) stay clean and professional.**
  Playfulness (pixel art, dialogue, animation) lives in the **Theater / office-floor**
  views, not the data views. This boundary is deliberate: engineers evaluating the
  tool must not read it as un-serious.

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
The Theater art (avatar/theater/AgentStage) is UI-only and NOT part of that rule.

## Related
Pixel-art asset creation → the **pixel-art-set** skill. General visual craft →
the **artifact-design** skill.
