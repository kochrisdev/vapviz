---
name: pixel-art-set
description: >
  Author or extend the vapviz Theater "cozy office" pixel art — characters,
  furniture, props, room tiles. The art is hand-authored DATA (palette + char-grid
  sprites), rasterized to canvas and recolored per run — NOT PNGs, NOT AI-generated,
  NOT a third-party pack. Use whenever creating, editing, or wiring a sprite into
  the Theater / office-floor renderer. Enforces one coherent style + zero-license art.
---

# vapviz pixel-art set — style guide & workflow

The Theater/office views use ONE coherent cozy-office pixel set, authored as **art-as-data**:
each sprite is a small **text grid of palette keys** plus a palette, rasterized to the canvas
by our own renderer and **recolored per run**. This is the pixtuoid model. This skill is the
single source of truth for how that art is made so it stays consistent no matter when we work
on it. **Read this fully before authoring or editing any sprite.**

> **Direction locked 2026-06-30 (supersedes the old PixelLab/Kenney/PNG approach).** We retired
> PixelLab MCP, the Kenney packs, the PIL "chunkify" pipeline, baked AI/Gemini backgrounds, and
> the 32px/48px PNG-sheet assumptions. The reference implementation is the prototype in
> `scratch/sprite-proto/` (`proto.html` + its sprite data). Nothing about the *event/graph model*
> or the scene/choreography logic (`theater.ts`) changes — only the bottom art-source layer.

## The art-as-data model (the core of this skill)

A sprite is **two things**, both authored by hand as text:

1. **A palette** — a map from a single-char **key** → a color. Example keys: `.`=transparent,
   `o`=outline, `k`=skin, `h`=hair, `s`=shirt, `p`=pants, `a`=accent.
2. **A grid** — rows of palette keys, one char per pixel. Every row MUST have the **same cell
   count** (the sprite's pixel width). Animation = a list of grids (frames) + per-frame ms.

```
# 12×16 worker, frame 0 (illustrative)
palette: { ".":transparent, "o":#241a14, "k":skin, "h":hair, "s":shirt, "p":pants }
....hhhh....
...hooooh...
...okkkko...
...okkkko...
...ohkkho...        ← each row is exactly 12 chars
....oooo....
...ssssss...
..ssssssss..
...s.ss.s...
...pp..pp...
...pp..pp...
...oo..oo...
```

- **Characters are 12×16 px** (taller than pixtuoid's 8×12 — Nick's call). Figure fills most of
  the box. Room and furniture are **sized to the sprites**, not to a fixed big grid.
- **Recolor is the point.** Some palette keys are flagged **per-run recolorable** (skin / hair /
  shirt / accent). A run id is hashed → a deterministic palette → one authored sprite becomes
  many visually distinct coworkers. **This requires every recolorable key to have its own
  UNIQUE RGB in the base art** — if two regions share a color, recolor can't separate them.
- **The rasterizer** (in the renderer, not here): parse grid → write pixels into an offscreen
  `ImageData` → integer-scale ×3/×4 **nearest-neighbor** → draw to canvas with
  `image-rendering: pixelated`. No anti-aliasing, ever.

## Style spec (do not drift)

- **Theme:** cozy / stylized office (warm, inviting — NOT corporate-sterile, NOT fantasy/medieval).
  Reference vibe: Stardew / cozy-RPG interiors.
- **Perspective:** **true top-down / bird's-eye.** Consistent top-left light source.
- **Characters:** 12×16 px. Chunky/cute reads, not smooth/realistic. A **4-frame walk** for the
  facing direction (contact / step-L / contact / step-R) + an idle frame; other directions are
  authored or mirrored as needed. Tool/desk activity is shown by the renderer (glow + speech
  bubble), not by extra character frames.
- **Outline:** bold 1 px **single-color** dark outline in warm near-black `#241a14`. The bold
  single outline is what gives the chunky/retro-cute personality — NOT a soft selective outline.
- **Palette:** limited, warm, cohesive (~24–36 colors). Woods/creams for floors+furniture, soft
  greens for plants, muted walls. New assets reuse existing palette entries — don't introduce new
  hues casually. **Every recolorable key gets a unique RGB** (see recolor, above).
- **State accent colors** (desk glow / status cues / dialogue) mirror the app design tokens so the
  Theater matches the rest of the UI — the renderer reads these CSS vars at runtime; bake them
  into the *art* only when unavoidable. (Note: the current prototype uses one calm blue-white
  "active" halo rather than per-kind colors — the label + bubble carry the meaning.)

## Licensing (the rule that now dissolves)

Hand-authored pixel grids are **OWNED art**: zero AI, zero third-party license. That is the whole
reason we adopted this model. **No AI-generated OR AI-edited pixels ever ship** (the copyright/ToS
gray area that blocked every prior approach). If a CC0 source is ever genuinely needed, it must be
verifiably CC0 — but the default and strongly-preferred path is to **author it ourselves**. Record
provenance for every asset (author · date · "hand-authored, owned").

## Authoring workflow (the iterate loop)

1. **Author / edit the sprite text** (palette + grid). Keep rows at a constant cell count.
2. **Render a check page** headlessly and **Read the PNG** (see Verifying, below).
3. **Self-critique** against the checklist below; edit; repeat. Silhouette + color identity first,
   pixel-level polish last.
4. **Wire it in** only once it reads well: add it to the sprite registry the renderer loads, and
   to the room layout / station map (layout logic lives in the renderer, not here).

## beautify-decoration lessons (from pixtuoid — apply these)

- **"Silhouette + color identity over pixel-level polish."** A piece reads by its shape and its
  distinct colors long before fine detail. Spend effort there.
- **Every row identical cell count** — verify mechanically (e.g. an `awk '{print length}'` /
  script pass over the grid) before rendering. A ragged row corrupts the whole rasterize.
- **Recolorable keys need UNIQUE RGB** — recolor targets a specific color; shared colors bleed.
- **≥ ~5 display-cells per readable element** — anything smaller is mush at 12×16.
- **Identity pitfalls → fixes:** transparent bodies → solid fills; monochrome rows → distinct base
  colors; symmetric H-frames that look static → asymmetric details; muddy adjacency → space the
  colors out.
- **Self-critique checklist before showing Nick:** Stranger-ID (could a stranger name what this
  is?) · visually differs from neighbors (not a sub-pixel difference) · correct width/footprint ·
  colors distinct · recolor keys unique · renders clean (no stray pixels, no ragged rows).

## Asset layout

- **Production (source of truth since 2026-07-02):** `ui/src/lib/sprites.ts` (the 12×16 worker +
  recolor palette + rasterizer) and `ui/src/lib/officeArt.ts` (furniture, tiles, canvas-chrome
  `CHROME` set, and the **room layout locked by Nick 2026-07-01** — don't rearrange/restyle
  without a new sign-off). Rendered by `ui/src/components/OfficeStage.tsx` (Theater tab).
  Author/edit sprites HERE. Provenance is recorded in `ui/src/lib/ASSETS.md`
  (author · date · owned) — update it with every asset change.
- **Prototype (historical reference only):** `scratch/sprite-proto/` (`proto.html`, final renders
  `pose10.png`/`live10.png`) — gitignored, this clone only; no longer the source of truth.

## Verifying art (no Playwright needed)

Render a check page headlessly with system Chrome, then Read the PNG:
`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu
--screenshot=out.png --force-device-scale-factor=2 file://…`. PIL + numpy are in `.venv` if you
need to crop/inspect a region.

## Related
UI / colors / theming → use the **vapviz-design** skill. Engine + data mapping (which node → which
station, walk choreography, recolor hashing) lives in the Theater renderer / `theater.ts`, not
here — **this skill is art only.**
