/**
 * Phase 4d — the floor ENVIRONMENT art (UI-ROADMAP §4-L): what turns a Building
 * floor from CSS chrome into an actual place. One canvas per floor draws, from
 * measured DOM rects: corridor floor tiles, wall runs with door openings around
 * every room, a runner rug + ceiling lights down the Walk Way, props (plants,
 * water cooler, notice board, wall art, clock), the Door/Stairs alcove, and the
 * east-wall windows. The LOCKED 12×16 room dioramas render ABOVE this canvas,
 * untouched — the environment is drawn around them.
 *
 * Provenance: hand-authored, owned art (zero AI, zero third-party packs) —
 * Nick + Claude, 2026-07-12. Same warm palette + 1px `#241a14` outline family
 * as `officeArt.ts` / `loungeArt.ts` (new hues introduced: the cool-cream
 * corridor stone, so rooms' wood floors read distinct through their doors).
 * Fixed hexes here are sprite data, not theme colors — the environment is a
 * diorama and deliberately doesn't re-theme.
 */
import { blit } from "./sprites";
import { plantCanvas, waterCoolerCanvas, clockCanvas, windowCanvas } from "./officeArt";
import { doorCanvas, stairsCanvas } from "./loungeArt";

/** CSS px per native art px (matches the walk overlay's sprite scale). */
export const FS = 2;

const OUT = "#241a14";

/* corridor + wall palette (cool cream stone vs the rooms' warm wood) */
const STONE_A = "#d3c9b4";
const STONE_B = "#cbc0a8";
const STONE_SPECK = "#bfb299";
const STONE_SEAM = "#b5a88e";
const VACANT = "#b7ab93";
const VACANT_D = "#a89c84";
const WALL = "#e7d8bf";
const WALL_SHADE = "#d8c6a6";
const THRESH = "#a06c3a"; // door threshold wood
const THRESH_H = "#bd8a55";

type Cv = HTMLCanvasElement & { ctx: CanvasRenderingContext2D };
function newCv(w: number, h: number): Cv {
  const cv = document.createElement("canvas") as Cv;
  cv.width = w;
  cv.height = h;
  cv.ctx = cv.getContext("2d")!;
  cv.ctx.imageSmoothingEnabled = false;
  return cv;
}
function rect(c: Cv, x: number, y: number, w: number, h: number, col: string) {
  c.ctx.fillStyle = col;
  c.ctx.fillRect(x, y, w, h);
}
function box(c: Cv, x: number, y: number, w: number, h: number, fill: string) {
  rect(c, x, y, w, h, OUT);
  rect(c, x + 1, y + 1, w - 2, h - 2, fill);
}

/* ── tiles (16×16 native) ────────────────────────────────────────────────── */
const TILE = 16;

// corridor stone — subtle checker + speckle, seam lines on the tile edges
function corridorTile(alt: boolean): Cv {
  const c = newCv(TILE, TILE);
  rect(c, 0, 0, TILE, TILE, alt ? STONE_B : STONE_A);
  rect(c, 0, 15, TILE, 1, STONE_SEAM);
  rect(c, 15, 0, 1, TILE, STONE_SEAM);
  const s = alt ? 3 : 0;
  rect(c, (5 + s) % TILE, (9 + s) % TILE, 1, 1, STONE_SPECK);
  rect(c, (11 + s) % TILE, (3 + s) % TILE, 1, 1, STONE_SPECK);
  return c;
}
// vacant-office floor — dimmer, dustier stone (an unlet room)
function vacantTile(alt: boolean): Cv {
  const c = newCv(TILE, TILE);
  rect(c, 0, 0, TILE, TILE, alt ? VACANT_D : VACANT);
  rect(c, 0, 15, TILE, 1, "#9c9078");
  rect(c, 15, 0, 1, TILE, "#9c9078");
  return c;
}

/* ── props ───────────────────────────────────────────────────────────────── */
// cork notice board — 22×13 (wood frame, pinned notes)
function noticeBoardCanvas(): Cv {
  const c = newCv(22, 13);
  box(c, 0, 0, 22, 13, "#74502f"); // frame
  rect(c, 2, 2, 18, 9, "#caa874"); // cork
  rect(c, 2, 2, 18, 1, "#b8945e"); // cork top shade
  // pinned notes (each with a 1px pin dot)
  const notes: [number, number, number, number, string][] = [
    [3, 3, 5, 4, "#f1ead8"],
    [10, 4, 4, 5, "#c8e2f0"],
    [16, 3, 3, 4, "#f0d5a8"],
    [5, 8, 4, 2, "#d7ecd0"],
  ];
  for (const [x, y, w, h, col] of notes) {
    rect(c, x, y, w, h, col);
    rect(c, x + Math.floor(w / 2), y, 1, 1, "#c8536b");
  }
  return c;
}
// framed wall art — 14×12, two motifs (hills / abstract)
export function wallArtCanvas(motif: 0 | 1): Cv {
  const c = newCv(14, 12);
  box(c, 0, 0, 14, 12, "#74502f"); // frame
  rect(c, 2, 2, 10, 8, motif ? "#e8ddc8" : "#9fc6e0"); // canvas / sky
  if (motif) {
    // abstract: three color blocks
    rect(c, 3, 3, 4, 6, "#c8536b");
    rect(c, 7, 5, 3, 4, "#4aa6c8");
    rect(c, 9, 3, 2, 3, "#e0a35e");
  } else {
    // hills under a sky
    rect(c, 2, 7, 10, 3, "#4f9d52");
    rect(c, 2, 6, 4, 1, "#4f9d52");
    rect(c, 8, 6, 3, 1, "#3a7a3f");
    rect(c, 9, 3, 2, 2, "#f6f1e6"); // cloud
  }
  return c;
}
// ceiling light — 12×8, a hanging office fixture seen from above-front
function ceilingLightCanvas(): Cv {
  const c = newCv(12, 8);
  rect(c, 5, 0, 2, 2, "#4c545f"); // stem
  box(c, 1, 2, 10, 5, "#8a5a30"); // shade
  rect(c, 2, 6, 8, 1, "#f6f1e6"); // lit rim
  rect(c, 3, 7, 6, 1, "#ffe9b8"); // glow lip
  return c;
}

/* ── art cache (built once; blits scale at draw time) ────────────────────── */
interface EnvArt {
  stone: [Cv, Cv];
  vacant: [Cv, Cv];
  plant: HTMLCanvasElement;
  cooler: HTMLCanvasElement;
  clock: HTMLCanvasElement;
  win: HTMLCanvasElement;
  board: Cv;
  art0: Cv;
  art1: Cv;
  light: Cv;
  door: HTMLCanvasElement;
  stairs: HTMLCanvasElement;
}
let cache: EnvArt | null = null;
function envArt(): EnvArt {
  return (cache ??= {
    stone: [corridorTile(false), corridorTile(true)],
    vacant: [vacantTile(false), vacantTile(true)],
    plant: plantCanvas(),
    cooler: waterCoolerCanvas(),
    clock: clockCanvas(),
    win: windowCanvas(),
    board: noticeBoardCanvas(),
    art0: wallArtCanvas(0),
    art1: wallArtCanvas(1),
    light: ceilingLightCanvas(),
    door: doorCanvas(),
    stairs: stairsCanvas(),
  });
}

/* ── the floor-environment renderer ──────────────────────────────────────── */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface EnvRoom {
  rect: Rect;
  /** Door centre-x (CSS px) + which edge faces the Walk Way. */
  doorCx: number;
  doorSide: "top" | "bottom";
  occupied: boolean;
}

/** Everything drawFloorEnv needs, measured floor-local in CSS px. */
export interface EnvLayout {
  w: number;
  h: number;
  rooms: EnvRoom[];
  walk: Rect | null;
  door: Rect | null;
  stairs: Rect | null;
  /** East wall column (non-top floors). Top floor (lounge) passes null. */
  east: Rect | null;
}

const WALL_T = 8; // wall-run thickness, CSS px
const WALL_G = 5; // ring outset — half the 10px grid gap, so adjacent rooms share a wall
const DOOR_W = 34; // door opening width, CSS px

/** Tile-fill a CSS-px region with a 2-tile checker. */
function tileFill(
  ctx: CanvasRenderingContext2D,
  tiles: [Cv, Cv],
  r: Rect,
  k: number // dpr
) {
  const s = FS * k;
  const t = TILE * FS; // tile size in CSS px
  ctx.save();
  ctx.beginPath();
  ctx.rect(r.x * k, r.y * k, r.w * k, r.h * k);
  ctx.clip();
  const x0 = Math.floor(r.x / t), y0 = Math.floor(r.y / t);
  const x1 = Math.ceil((r.x + r.w) / t), y1 = Math.ceil((r.y + r.h) / t);
  for (let ty = y0; ty < y1; ty++)
    for (let tx = x0; tx < x1; tx++)
      blit(ctx, tiles[(tx + ty) & 1], tx * t * k, ty * t * k, s);
  ctx.restore();
}

/** A wall run: cream fill with a near-black outline on both long edges. */
function wallRect(ctx: CanvasRenderingContext2D, r: Rect, k: number) {
  const o = Math.max(1, Math.round(k)); // 1 CSS px outline
  ctx.fillStyle = OUT;
  ctx.fillRect(r.x * k, r.y * k, r.w * k, r.h * k);
  ctx.fillStyle = WALL;
  ctx.fillRect(r.x * k + o, r.y * k + o, r.w * k - 2 * o, r.h * k - 2 * o);
  ctx.fillStyle = WALL_SHADE;
  ctx.fillRect(r.x * k + o, r.y * k + o, r.w * k - 2 * o, Math.min(2 * k, r.h * k - 2 * o));
}

/** The wall ring around one room, with a door opening on its corridor edge. */
function roomWalls(ctx: CanvasRenderingContext2D, room: EnvRoom, k: number) {
  const { rect: r, doorCx, doorSide } = room;
  const T = WALL_T;
  // the ring sits mostly OUTSIDE the room rect (outset = half the grid gap, so
  // two adjacent rooms' rings abut mid-gap and read as one shared wall); the
  // 3px that lies inside the rect is hidden under the room's diorama canvas
  const ox = r.x - WALL_G, oy = r.y - WALL_G, ow = r.w + 2 * WALL_G, oh = r.h + 2 * WALL_G;
  // top + bottom runs (the corridor edge gets a door gap)
  const runs: { rr: Rect; gap: boolean }[] = [
    { rr: { x: ox, y: oy, w: ow, h: T }, gap: doorSide === "top" },
    { rr: { x: ox, y: oy + oh - T, w: ow, h: T }, gap: doorSide === "bottom" },
  ];
  for (const { rr, gap } of runs) {
    if (!gap) {
      wallRect(ctx, rr, k);
      continue;
    }
    const gx0 = doorCx - DOOR_W / 2, gx1 = doorCx + DOOR_W / 2;
    wallRect(ctx, { x: rr.x, y: rr.y, w: Math.max(0, gx0 - rr.x), h: T }, k);
    wallRect(ctx, { x: gx1, y: rr.y, w: Math.max(0, rr.x + rr.w - gx1), h: T }, k);
    // threshold — warm wood strip bridging room floor and corridor stone
    ctx.fillStyle = OUT;
    ctx.fillRect(gx0 * k, rr.y * k, (gx1 - gx0) * k, T * k);
    ctx.fillStyle = THRESH;
    ctx.fillRect((gx0 + 1) * k, (rr.y + 1) * k, (gx1 - gx0 - 2) * k, (T - 2) * k);
    ctx.fillStyle = THRESH_H;
    ctx.fillRect((gx0 + 1) * k, (rr.y + 1) * k, (gx1 - gx0 - 2) * k, 1 * k);
    // door posts
    ctx.fillStyle = OUT;
    ctx.fillRect((gx0 - 1) * k, (rr.y - 1) * k, 3 * k, (T + 2) * k);
    ctx.fillRect((gx1 - 2) * k, (rr.y - 1) * k, 3 * k, (T + 2) * k);
  }
  // left + right runs
  wallRect(ctx, { x: ox, y: oy + T, w: T, h: oh - 2 * T }, k);
  wallRect(ctx, { x: ox + ow - T, y: oy + T, w: T, h: oh - 2 * T }, k);
}

/**
 * Draw one floor's environment into `ctx` (already sized to layout.w×layout.h
 * CSS px × dpr). Pure draw — measures nothing, owns no DOM.
 */
export function drawFloorEnv(ctx: CanvasRenderingContext2D, L: EnvLayout, dpr: number) {
  const a = envArt();
  const k = dpr;
  const s = FS * k;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, L.w * k, L.h * k);
  ctx.imageSmoothingEnabled = false;

  // 1 — corridor stone everywhere (rooms render on top and hide theirs)
  tileFill(ctx, a.stone, { x: 0, y: 0, w: L.w, h: L.h }, k);

  // 2 — vacant rooms: dim floor + a faint ring so the slot reads as an unlet office
  for (const room of L.rooms) if (!room.occupied) tileFill(ctx, a.vacant, room.rect, k);

  // 3 — the Walk Way: runner rug + ceiling lights
  if (L.walk) {
    const w = L.walk;
    const rugH = Math.min(22, w.h - 6);
    const rug: Rect = { x: w.x + 10, y: w.y + (w.h - rugH) / 2, w: w.w - 20, h: rugH };
    ctx.fillStyle = OUT;
    ctx.fillRect(rug.x * k, rug.y * k, rug.w * k, rug.h * k);
    ctx.fillStyle = "#c08a5a";
    ctx.fillRect((rug.x + 1) * k, (rug.y + 1) * k, (rug.w - 2) * k, (rug.h - 2) * k);
    ctx.fillStyle = "#d8b483";
    ctx.fillRect((rug.x + 3) * k, (rug.y + 3) * k, (rug.w - 6) * k, (rug.h - 6) * k);
    // rug end-stripes
    ctx.fillStyle = "#9c6a42";
    ctx.fillRect((rug.x + 5) * k, (rug.y + 1) * k, 2 * k, (rug.h - 2) * k);
    ctx.fillRect((rug.x + rug.w - 7) * k, (rug.y + 1) * k, 2 * k, (rug.h - 2) * k);
    // ceiling lights spaced down the corridor — the fixture hangs near the
    // corridor's top edge; a soft pool of light falls on the rug below it
    const n = Math.max(2, Math.round(w.w / 240));
    for (let i = 0; i < n; i++) {
      const cx = w.x + ((i + 1) * w.w) / (n + 1);
      const lw = a.light.width * FS;
      ctx.fillStyle = "rgba(255, 233, 184, .18)";
      ctx.beginPath();
      ctx.ellipse(cx * k, (w.y + w.h / 2 + 2) * k, 26 * k, 12 * k, 0, 0, 7);
      ctx.fill();
      blit(ctx, a.light, (cx - lw / 2) * k, (w.y - 2) * k, s);
    }
  }

  // 4 — room wall rings + door openings
  for (const room of L.rooms) roomWalls(ctx, room, k);

  // 5 — perimeter wall (drawn after rooms so corners join cleanly)
  wallRect(ctx, { x: 0, y: 0, w: L.w, h: WALL_T }, k);
  wallRect(ctx, { x: 0, y: L.h - WALL_T, w: L.w, h: WALL_T }, k);
  wallRect(ctx, { x: 0, y: 0, w: WALL_T, h: L.h }, k);
  wallRect(ctx, { x: L.w - WALL_T, y: 0, w: WALL_T, h: L.h }, k);

  // 6 — props on the corridor + walls. Standing props anchor their FEET to the
  // corridor's bottom edge; hung props anchor their TOP to the wall band above
  // the corridor (the top rooms' south wall) so nothing bleeds under a room
  // canvas. Mixed projection (front-view objects on a top-down floor) is the
  // set's established style — same as the room diorama's windows.
  if (L.walk) {
    const w = L.walk;
    const feetY = w.y + w.h + WALL_G; // corridor bottom (bottom rooms' wall top)
    const hangY = w.y - WALL_G - 6; // wall band above the corridor
    // plants at both corridor ends
    const pw = a.plant.width * FS, ph = a.plant.height * FS;
    blit(ctx, a.plant, (w.x + 4) * k, (feetY - ph) * k, s);
    blit(ctx, a.plant, (w.x + w.w - pw - 4) * k, (feetY - ph) * k, s);
    // water cooler near the right end (by the Door/Stairs column)
    const cw = a.cooler.width * FS, ch = a.cooler.height * FS;
    blit(ctx, a.cooler, (w.x + w.w - pw - cw - 12) * k, (feetY - ch) * k, s);
    // notice board + two framed pictures hung along the top wall band
    const bw = a.board.width * FS;
    blit(ctx, a.board, (w.x + w.w * 0.18 - bw / 2) * k, hangY * k, s);
    const aw = a.art0.width * FS;
    blit(ctx, a.art0, (w.x + w.w * 0.45 - aw / 2) * k, hangY * k, s);
    blit(ctx, a.art1, (w.x + w.w * 0.68 - aw / 2) * k, hangY * k, s);
    // wall clock between the framed pictures
    const kw = a.clock.width * FS;
    blit(ctx, a.clock, (w.x + w.w * 0.56 - kw / 2) * k, hangY * k, s);
  }

  // 7 — the Door / Stairs alcove (icons drawn on the corridor)
  const alcove = (r: Rect | null, icon: HTMLCanvasElement) => {
    if (!r) return;
    const sc = Math.min(FS, (r.h - 6) / icon.height, (r.w - 6) / icon.width) * k;
    const dw = icon.width * sc, dh = icon.height * sc;
    blit0(ctx, icon, r.x * k + (r.w * k - dw) / 2, r.y * k + (r.h * k - dh) / 2, sc);
  };
  alcove(L.door, a.door);
  alcove(L.stairs, a.stairs);

  // 8 — east wall windows (non-top floors; the top floor's east side is the lounge DOM)
  if (L.east) {
    const e = L.east;
    wallRect(ctx, e, k);
    const ww = a.win.width * FS, wh = a.win.height * FS;
    // 2×2 window grid on the facade (capped — it's a wall, not a greenhouse)
    const rows = Math.min(2, Math.max(1, Math.floor(e.h / (wh * 3))));
    const cols = e.w > ww * 2 + 30 ? 2 : 1;
    for (let r = 0; r < rows; r++)
      for (let c = 0; c < cols; c++) {
        const wx = e.x + ((c + 1) * e.w) / (cols + 1) - ww / 2;
        const wy = e.y + ((r + 1) * e.h) / (rows + 1) - wh / 2;
        blit(ctx, a.win, wx * k, wy * k, s);
      }
  }
}

/** blit() wants integer-ish scaled draws; alcove icons may scale fractionally
 *  to fit their cell, still nearest-neighbor. */
function blit0(
  dst: CanvasRenderingContext2D,
  src: HTMLCanvasElement,
  dx: number,
  dy: number,
  scale: number
) {
  dst.imageSmoothingEnabled = false;
  dst.drawImage(src, dx, dy, src.width * scale, src.height * scale);
}
