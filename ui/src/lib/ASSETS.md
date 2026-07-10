# Theater art provenance

All Theater/office pixel art is **art-as-data**: hand-authored palette + char-grid
sprites (`sprites.ts`) and hand-authored procedural pixel-rect furniture
(`officeArt.ts`), rasterized to canvas at runtime. There are no image files, no
AI-generated or AI-edited pixels, and no third-party art packs — the art is code
in this directory and is **owned outright**.

| Asset | Where | Author · date | License |
|---|---|---|---|
| 12×16 worker (4-frame walk) + recolor palette | `sprites.ts` | Nick + Claude, 2026-06-30 → 07-01 (prototype), ported 2026-07-02 | owned, hand-authored |
| Room tiles, furniture set, locked office layout | `officeArt.ts` | Nick + Claude, 2026-06-30 → 07-01 (prototype), ported 2026-07-02 | owned, hand-authored |
| Lounge (break-room) diorama: floor/wall tiles, counter+sink, coffee machine, snack vending machine, mini fridge, water cooler, round table + stools, plants, poster; + Door / Stairs descent-column icons | `loungeArt.ts` | Nick + Claude, 2026-07-07 (Phase 4b) | owned, hand-authored |

(The interim SVG pixel characters — `avatar.ts`, Claude 2026-06 — were retired 2026-07-03
when the Live Floor moved to the sprite office; both views now use the art above.)

**Phase 4c — floor life / room doors (2026-07-09):** added **no new art**. The
floor-life walkers (`walkOverlay.ts` `reconcileFloorLife`) reuse the existing 12×16
`WALK` sprite above, recolored per app; the room **door** is theme-aware **CSS chrome**
(`.vt-room-door`, via `vapviz-design` — not pixel art), so the LOCKED 12×16 room
diorama is untouched.

Reference prototype (final approved renders `pose10.png` / `live10.png`):
`scratch/sprite-proto/` (local, gitignored). Room layout **locked by Nick
2026-07-01** — do not rearrange or restyle without a new sign-off. Authoring
rules live in the `pixel-art-set` skill.
