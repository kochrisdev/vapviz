---
name: pixel-art-set
description: >
  Create or extend the vapviz Theater "cozy office" pixel-art set — characters,
  furniture, buildings, tiles, props. Use whenever generating, cleaning, packing,
  or adding pixel-art assets for the Theater / office-floor views, or when wiring
  new art into the canvas renderer. Enforces one consistent style + CC0-clean
  licensing across sessions.
---

# vapviz pixel-art set — style guide & workflow

The Theater/office views use ONE coherent cozy-office pixel set. This skill is the
single source of truth for how that art is made so it stays consistent no matter
when we work on it. **Read this fully before producing or importing any sprite.**

## Style spec (do not drift)

- **Theme:** cozy / stylized office (warm, inviting — NOT corporate-sterile, NOT
  fantasy/medieval). Reference vibe: Stardew/cozy-RPG interiors.
- **Perspective:** **true top-down / bird's-eye** ("high top-down" in PixelLab terms —
  matches the pixtuoid + reference photos). **Locked 2026-06-29** (was "low top-down ¾";
  Nick rebuilt the Theater bird's-eye). Consistent top-left light source.
- **Grid:** 32×32 px base tile. Characters = 32×32 frame, figure ~24–26 px tall.
  Multi-tile objects are whole multiples of 32 (a desk = 32×32 or 64×32).
- **Animation:** characters need **4-direction walk** (down/up/left/right), ~4
  frames each, + a 1-frame idle per direction. Frame order documented in the
  manifest. Tool/desk activity is shown by the renderer (glow/bubble), not extra
  character frames.
- **Outline:** bold 1 px **single-color** dark outline in warm near-black `#241a14`
  (recolor PixelLab's pure-black outline to this in post). The bold single outline is
  what gives the chunky/retro-cute personality — NOT a soft selective outline.
- **Personality recipe (LOCKED, confirmed 2026-06-28 — Nick chose "chunky" over
  "polished"):** characters are **chibi** (big head), deliberately chunky, NOT
  smooth/realistic. PixelLab params: `proportions={"type":"preset","name":"chibi"}`,
  `size=32`, `outline="single color black outline"`, `detail="low detail"`,
  `shading="basic shading"`, `view="high top-down"`, `n_directions=4`. Furniture/props
  match: low detail, basic shading, single outline, same **high-top-down** view.
  (Updated 2026-06-29 from "low top-down" to "high top-down" — see Perspective above.)
- **Palette:** limited (~28–36 colors), warm. Woods/creams for floors+furniture,
  soft greens for plants, muted walls. Keep it cohesive — new assets must reuse
  existing palette entries, not introduce new hues casually. Maintain the palette
  in `ui/src/assets/theater/palette.gpl` (or `.hex`).
- **State accent colors** (for desk glow / status cues / dialogue dots) mirror the
  app design tokens so Theater matches the rest of the UI:
  LLM = `--kind-llm` (purple), tool = `--kind-tool` (teal/green),
  running = `--status-running` (amber), success = `--status-success` (green),
  error = `--status-error` (red). The renderer reads these CSS vars at runtime;
  bake them into the *art* only when unavoidable.
- **Output:** PNG, transparent background, no anti-aliasing. Rendered with
  `image-rendering: pixelated`.

## Licensing (hard rule — this is an OSS repo)

Every asset must be **CC0 or owned by us**. Allowed sources:
- **PixelLab MCP** output → we CC0-dedicate it (we generated it).
- **Code-authored** (PIL/canvas) → ours.
- **Verified CC0 packs** (Kenney; Ninja Adventure is CC0 too) — only if truly CC0.
NEVER add "free, no-redistribution" art (PIPOYA, LimeZu, bitglow, CraftPix) or
CC-BY-SA (LPC) without explicit sign-off. Record provenance for EVERY asset in
`ui/src/assets/theater/ASSETS.md` (name · source · license · date).

## Production workflow (the "mix" route)

1. **Hero art via PixelLab MCP** (characters + walk, key furniture/buildings):
   generate with prompts that state the style spec above (top-down ¾, 32px, warm
   cozy, 1px `#241a14` outline, transparent bg). Use its 4-direction + walk-anim
   tools for characters.
2. **Simple props/signs via code** (PIL in `.venv`, or canvas): grid-aligned to
   32px, palette-matched.
3. **Post-process EVERY asset** (script it; keep the script in `scratch/`):
   nearest-neighbor grid-snap → quantize to the set palette → trim transparent
   margins → pack into a sheet → update the manifest.
4. **Manifest:** `ui/src/assets/theater/manifest.json` maps logical names →
   `{sheet, x, y, w, h, frames?}` so the canvas renderer never hard-codes coords.
5. **Consistency check** before committing an asset: same perspective? on 32-grid?
   palette-only colors? `#241a14` outline? provenance recorded? If any "no", fix.

## Asset layout
```
ui/src/assets/theater/
  characters/   sheets + per-character walk frames
  furniture/    desks, bookshelves, printer, plants, lamps…
  buildings/    floor-view room exteriors
  tiles/        floor / wall / walkway tiles
  manifest.json
  palette.hex
  ASSETS.md     provenance + licenses (CC0 proof)
```

## Verifying art (no Playwright needed)
Render a check page headlessly with system Chrome:
`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new
--disable-gpu --screenshot=out.png --force-device-scale-factor=2 file://…`,
then Read the PNG. PIL + numpy are in `.venv` for cropping/quantizing.

## Related
UI/colors/theming → use the **vapviz-design** skill. Engine/data mapping (which
node → which station) lives in the Theater renderer, not here — this skill is art only.
