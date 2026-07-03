/**
 * The Theater office room — furniture, floor/wall tiles, and the LOCKED layout
 * (Nick, 2026-07-01). Ported verbatim from `scratch/sprite-proto/proto.html`
 * (final approved renders: pose10.png / live10.png). Do not rearrange the room
 * or restyle the art without a new sign-off.
 *
 * Provenance: hand-authored, owned art (zero AI, zero third-party packs) —
 * Nick + Claude, 2026-06-30 → 07-01. Furniture is drawn as clean pixel rects in
 * the same warm palette + 1px `#241a14` outline as the char-grid worker
 * (`sprites.ts`); converting these to char-grids is possible later, but the
 * rect form is the approved art. Fixed hexes here are sprite data, not theme
 * colors (the room is a diorama and deliberately doesn't re-theme).
 *
 * Everything is drawn at NATIVE room pixels (208×128, 16px tiles); the stage
 * component integer-scales at blit time.
 */
import { blit, hex2rgb } from "./sprites";

export const TILE = 16;
export const COLS = 13;
export const ROWS = 8;
/** Room size in native px. */
export const RW = COLS * TILE; // 208
export const RH = ROWS * TILE; // 128

const OUT = "#241a14";

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
/** 1px outline around a filled box. */
function box(c: Cv, x: number, y: number, w: number, h: number, fill: string) {
  rect(c, x, y, w, h, OUT);
  rect(c, x + 1, y + 1, w - 2, h - 2, fill);
}

/**
 * Canvas-chrome palette for the stage's overlays (label chips, name tags,
 * speech bubbles, glow) — part of the diorama's fixed warm art, kept here as
 * art data so the component itself holds no raw hexes.
 */
export const CHROME = {
  chipBg: "rgba(20,16,12,.82)",
  chipText: "#f3ead9",
  chipHotBg: "rgba(224,163,94,.95)",
  chipHotText: "#1a130c",
  tagBg: "rgba(20,16,12,.8)",
  tagText: "#efe7da",
  bubbleBg: "#f6f1e6",
  bubbleText: "#3a2c20",
  glowIn: "#dce8ffaa",
  glowOut: "#dce8ff00",
  shadow: "#000",
} as const;

/* ── floor / wall tiles (procedural, warm wood + cream wall) ───────────── */
function woodTile(seed: number): Cv {
  const c = newCv(TILE, TILE);
  rect(c, 0, 0, TILE, TILE, "#b07a45");
  rect(c, 0, seed % 2 ? 5 : 11, TILE, 1, "#a06c3a"); // plank seam
  c.ctx.fillStyle = "#bd8a55";
  for (let i = 0; i < 3; i++) c.ctx.fillRect((seed * 3 + i * 5) % TILE, (i * 5 + seed) % TILE, 1, 1); // grain
  rect(c, 0, 15, TILE, 1, "#9c6636");
  return c;
}
function wallTile(): Cv {
  const c = newCv(TILE, TILE);
  rect(c, 0, 0, TILE, TILE, "#e7d8bf");
  rect(c, 0, 0, TILE, 1, "#d8c6a6");
  return c;
}
function baseboardTile(): Cv {
  const c = newCv(TILE, TILE);
  rect(c, 0, 0, TILE, TILE, "#e7d8bf");
  rect(c, 0, 11, TILE, 3, "#caa874");
  rect(c, 0, 14, TILE, 2, "#9c6636"); // floor transition
  return c;
}

/* ── furniture ─────────────────────────────────────────────────────────── */
// desk with monitor (LLM station) — 34×22
function deskCanvas(): Cv {
  const c = newCv(34, 22);
  box(c, 2, 11, 30, 9, "#8a5a30"); // desk top
  rect(c, 3, 12, 28, 1, "#a86d3c"); // highlight
  rect(c, 4, 19, 2, 3, "#5a3a22");
  rect(c, 28, 19, 2, 3, "#5a3a22"); // legs
  // monitor
  box(c, 7, 2, 12, 8, "#2c2c34");
  rect(c, 9, 4, 8, 4, "#7fcfe6");
  rect(c, 9, 4, 8, 2, "#a6e3f2");
  rect(c, 12, 10, 2, 1, "#3a3a44");
  rect(c, 11, 11, 4, 1, "#454552"); // stand
  // notebook + mug
  box(c, 22, 5, 8, 5, "#f1ead8");
  rect(c, 23, 7, 6, 1, "#caa874");
  box(c, 21, 12, 4, 4, "#c8536b");
  rect(c, 25, 13, 1, 2, "#a23f55");
  return c;
}
// potted plant — 14×18
function plantCanvas(): Cv {
  const c = newCv(14, 18);
  box(c, 4, 12, 6, 5, "#caa874");
  rect(c, 3, 11, 8, 2, "#9c6636"); // pot
  const G = "#4f9d52", g = "#3a7a3f";
  ([[5, 2, 4, 3, G], [3, 4, 3, 4, g], [8, 4, 3, 4, g], [4, 6, 6, 4, G], [6, 1, 2, 3, g], [2, 7, 3, 3, G], [9, 7, 3, 3, G]] as const)
    .forEach(([x, y, w, h, col]) => box(c, x, y, w, h, col));
  return c;
}
// round rug — 50×30, muted warm
function rugCanvas(): Cv {
  const w = 50, h = 30, c = newCv(w, h);
  const img = c.ctx.createImageData(w, h);
  const bands: [number, string][] = [[0.28, "#e7d3ad"], [0.5, "#d8b483"], [0.74, "#c08a5a"], [0.92, "#9c6a42"], [1, OUT]];
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      const dx = (x - w / 2) / (w / 2), dy = (y - h / 2) / (h / 2), d = dx * dx + dy * dy;
      if (d > 1) continue;
      let col = OUT;
      for (const [r, cc] of bands) if (d <= r) { col = cc; break; }
      const [R0, G0, B0] = hex2rgb(col), i = (y * w + x) * 4;
      img.data[i] = R0; img.data[i + 1] = G0; img.data[i + 2] = B0; img.data[i + 3] = 255;
    }
  c.ctx.putImageData(img, 0, 0);
  return c;
}
// wall clock — 9×9, crisp pixel disc (no anti-aliased arc → sharp when scaled)
function clockCanvas(): Cv {
  const c = newCv(9, 9);
  for (let y = 0; y < 9; y++)
    for (let x = 0; x < 9; x++) {
      const dx = x - 4, dy = y - 4, d = dx * dx + dy * dy;
      if (d <= 16) rect(c, x, y, 1, 1, d >= 12 ? OUT : "#f1ead8"); // ring = outline, inside = face
    }
  rect(c, 4, 2, 1, 3, OUT);
  rect(c, 4, 4, 3, 1, OUT); // hour + minute hands
  return c;
}
// two-seat couch (top-down, facing UP toward the TV) — 36×20
function sofaCanvas(): Cv {
  const c = newCv(36, 20);
  const BODY = "#5a6b8a", SEAT = "#7d8fb0", SEATd = "#6f80a0", ARM = "#4f5e78", BACK = "#48566f";
  box(c, 0, 0, 36, 20, BODY); // outlined body
  rect(c, 3, 13, 30, 5, BACK);
  rect(c, 3, 13, 30, 1, "#3c4860"); // backrest (bottom, darker)
  rect(c, 1, 2, 5, 16, ARM);
  rect(c, 30, 2, 5, 16, ARM); // armrests
  rect(c, 1, 2, 5, 1, "#6b7a96");
  rect(c, 30, 2, 5, 1, "#6b7a96"); // arm highlights
  rect(c, 6, 3, 24, 11, SEAT);
  rect(c, 6, 3, 24, 1, "#90a0bd"); // seat + top highlight
  rect(c, 17, 3, 1, 11, SEATd);
  rect(c, 6, 12, 24, 1, SEATd); // cushion seam + crease
  box(c, 7, 5, 7, 7, "#c8536b");
  rect(c, 8, 6, 3, 2, "#d97a92"); // throw pillow (rose)
  box(c, 22, 5, 7, 7, "#e0a35e");
  rect(c, 23, 6, 3, 2, "#edbd86"); // throw pillow (amber)
  return c;
}
// filing cabinet / vault (DATA station) — 16×22
function cabinetCanvas(): Cv {
  const c = newCv(16, 22);
  box(c, 2, 0, 12, 22, "#8a5a30");
  for (let i = 0; i < 3; i++) {
    const y = 2 + i * 7;
    rect(c, 3, y, 10, 5, "#a06c3a");
    rect(c, 6, y + 2, 4, 1, "#3a2516");
  }
  return c;
}
// small home desk (per-agent base) — 26×16
function homeDeskCanvas(): Cv {
  const c = newCv(26, 16);
  box(c, 1, 6, 24, 9, "#8a5a30");
  rect(c, 2, 7, 22, 1, "#a86d3c");
  rect(c, 3, 14, 2, 2, "#5a3a22");
  rect(c, 21, 14, 2, 2, "#5a3a22");
  box(c, 4, 1, 9, 6, "#2c2c34");
  rect(c, 5, 2, 7, 3, "#7fcfe6"); // monitor
  box(c, 16, 3, 6, 4, "#f1ead8"); // papers
  return c;
}
// SEARCH — two bookshelves as one unit — 30×30
function doubleShelfCanvas(): Cv {
  const c = newCv(30, 30);
  box(c, 1, 0, 28, 30, "#74502f");
  rect(c, 2, 1, 26, 28, "#5a3a22");
  rect(c, 14, 1, 1, 28, "#3a2516");
  const books = ["#c8536b", "#4f9d52", "#e0a35e", "#4aa6c8", "#7a64d0", "#caa874"];
  for (let shelf = 0; shelf < 4; shelf++) {
    const sy = 2 + shelf * 7;
    for (let i = 0; i < 12; i++) {
      const bx = 3 + i * 2;
      if (bx >= 14 && bx < 15) continue;
      const bh = 4 + ((i + shelf) % 2);
      rect(c, bx, sy + 6 - bh, 2, bh, books[(i + shelf * 2) % books.length]);
    }
    rect(c, 2, sy + 6, 26, 1, "#3a2516");
  }
  return c;
}
// FETCH — two server racks as one unit — 26×28
function wideServerCanvas(): Cv {
  const c = newCv(26, 28);
  box(c, 1, 0, 24, 28, "#363c45");
  rect(c, 12, 1, 2, 26, "#2a2f37");
  for (let i = 0; i < 5; i++) {
    const y = 3 + i * 5;
    rect(c, 3, y, 8, 3, "#4c545f");
    rect(c, 15, y, 8, 3, "#4c545f");
    rect(c, 4, y + 1, 1, 1, i % 2 ? "#4f9d52" : "#e0a35e");
    rect(c, 16, y + 1, 1, 1, "#4aa6c8");
  }
  return c;
}
// PRINT — printer sitting on a table — 28×22
function printerTableCanvas(): Cv {
  const c = newCv(28, 22);
  box(c, 1, 11, 26, 8, "#8a5a30");
  rect(c, 2, 12, 24, 1, "#a86d3c"); // table
  rect(c, 3, 18, 2, 3, "#5a3a22");
  rect(c, 23, 18, 2, 3, "#5a3a22"); // legs
  box(c, 8, 3, 12, 8, "#9aa3ad");
  rect(c, 9, 1, 10, 3, "#f1ead8"); // printer + paper
  rect(c, 9, 8, 10, 2, "#2c2c34");
  rect(c, 10, 5, 2, 1, "#4f9d52"); // slot + LED
  return c;
}
// fridge (filler) — 16×26
function fridgeCanvas(): Cv {
  const c = newCv(16, 26);
  box(c, 2, 0, 12, 26, "#cdd6dd");
  rect(c, 3, 1, 10, 24, "#dde5eb");
  rect(c, 2, 11, 12, 1, "#9aa3ad"); // door split
  rect(c, 11, 3, 1, 5, "#7d8690");
  rect(c, 11, 14, 1, 6, "#7d8690"); // handles
  return c;
}
// dinner / break table + 4 chairs (top-down) — 40×30
function dinnerTableCanvas(): Cv {
  const c = newCv(40, 30);
  const SEAT = "#caa874", BACK = "#74502f", WOOD = "#a06c3a", WOODH = "#bd8a55", WOODD = "#74502f";
  // chairs — each = a seat cushion with a darker backrest bar on its OUTER edge
  box(c, 15, 0, 10, 7, SEAT);
  rect(c, 16, 1, 8, 2, BACK); // top chair
  box(c, 15, 23, 10, 7, SEAT);
  rect(c, 16, 27, 8, 2, BACK); // bottom chair
  box(c, 0, 11, 7, 10, SEAT);
  rect(c, 1, 12, 2, 8, BACK); // left chair
  box(c, 33, 11, 7, 10, SEAT);
  rect(c, 37, 12, 2, 8, BACK); // right chair
  // table top with wood grain
  box(c, 8, 6, 24, 18, WOOD);
  rect(c, 9, 7, 22, 1, WOODH);
  rect(c, 9, 22, 22, 1, WOODD);
  rect(c, 10, 12, 20, 1, WOODH);
  rect(c, 10, 18, 20, 1, WOODD);
  // four place settings + a small centrepiece
  ([[11, 9], [24, 9], [11, 16], [24, 16]] as const).forEach(([x, y]) => {
    box(c, x, y, 6, 5, "#f1ead8");
    rect(c, x + 1, y + 1, 4, 3, "#e7d8bf");
  });
  box(c, 18, 13, 4, 5, "#4f9d52");
  rect(c, 19, 12, 2, 2, "#e0894a"); // potted centrepiece
  return c;
}
// wall TV on a media console (filler + animated — screen overdrawn live) — 30×18
function tvCanvas(): Cv {
  const c = newCv(30, 18);
  box(c, 2, 12, 26, 5, "#74502f");
  rect(c, 3, 13, 24, 1, "#8a5a30"); // console
  box(c, 4, 0, 22, 12, "#1c1c22"); // TV bezel
  rect(c, 6, 2, 18, 8, "#2a3a4a"); // default screen
  rect(c, 14, 11, 2, 2, "#1c1c22"); // stand
  return c;
}
// water cooler (filler + animated — bubble rises live) — 12×22
function waterCoolerCanvas(): Cv {
  const c = newCv(12, 22);
  box(c, 2, 0, 8, 9, "#bcdcef");
  rect(c, 3, 1, 6, 7, "#8fc4e6"); // water bottle
  box(c, 1, 9, 10, 13, "#dde5eb");
  rect(c, 2, 10, 8, 11, "#cdd6dd"); // dispenser body
  rect(c, 3, 13, 6, 2, "#5a6b8a"); // spigot panel
  rect(c, 4, 16, 1, 1, "#3fbf9b");
  rect(c, 7, 16, 1, 1, "#c8536b"); // hot/cold taps
  return c;
}
// window on the back wall — 30×13 (outdoor view: a city skyline)
function windowCanvas(): Cv {
  const c = newCv(30, 13);
  box(c, 0, 0, 30, 13, "#74502f"); // frame
  rect(c, 2, 2, 26, 8, "#9fc6e0"); // daytime sky
  rect(c, 2, 2, 26, 2, "#b6d6ea"); // lighter sky near top
  const B = "#6f7f96", Bd = "#566578", win = "#cfe4f2";
  const blds: [number, number, number][] = [[2, 4, 5], [7, 5, 7], [13, 3, 4], [17, 6, 8], [24, 4, 6]];
  blds.forEach(([x, w, h], k) => rect(c, x, 10 - h, w, h, k % 2 ? Bd : B));
  ([[3, 8], [9, 5], [10, 8], [18, 5], [20, 8], [25, 7]] as const).forEach(([x, y]) => rect(c, x, y, 1, 1, win));
  rect(c, 2, 10, 26, 1, "#3a2516"); // ground/sill line
  rect(c, 14, 2, 1, 8, "#74502f");
  rect(c, 2, 6, 26, 1, "#74502f"); // mullions
  return c;
}

/* ── LOCKED room layout (native px; cx = blit centre-x, top = top edge) ── */
export type StationName = "LLM" | "SEARCH" | "FETCH" | "DATA" | "PRINT";

export interface StationDef {
  label: StationName;
  /** Furniture blit centre-x / top edge. */
  fcx: number;
  ftop: number;
  /** Stand point — where an avatar's feet go, clear of neighbouring furniture. */
  sx: number;
  sy: number;
  /** Optional explicit label-chip top (default sits above the furniture). */
  lbl?: number;
}

export const STATION_DEFS: StationDef[] = [
  { label: "LLM", fcx: 28, ftop: 22, sx: 28, sy: 50, lbl: 18 }, // label chip below the window
  { label: "SEARCH", fcx: 72, ftop: 6, sx: 72, sy: 42 },
  { label: "FETCH", fcx: 150, ftop: 8, sx: 150, sy: 42 },
  { label: "DATA", fcx: 192, ftop: 56, sx: 174, sy: 70 },
  { label: "PRINT", fcx: 184, ftop: 96, sx: 162, sy: 108 },
];

/** Locked home-desk row: 3 desks at [64,104,146], top 108 (name tags clear the couch). */
export const HOME_CX = [64, 104, 146];
export const HOME_TOP = 108;
/**
 * Overflow back row (additive, 2026-07-03 — the locked furniture is untouched):
 * open floor between the sofa (ends y66) and the front row, x-range clears the
 * dinner table (ends x58) and the PRINT table (starts x170).
 */
export const HOME_BACK_TOP = 84;

export interface HomeSpot {
  x: number;
  y: number;
}

/**
 * Home-desk centre-x positions for a cast of `n`. n≤3 uses the locked layout
 * (centred subset); larger casts space evenly across the same row (desks are
 * 26px wide, so ~6 fit before they start to crowd).
 */
export function homeCx(n: number): number[] {
  if (n <= 0) return [];
  if (n === 1) return [HOME_CX[1]];
  if (n === 2) return [HOME_CX[0] + 10, HOME_CX[2] - 10];
  if (n === 3) return [...HOME_CX];
  const left = 40, right = 168;
  return Array.from({ length: n }, (_, i) => Math.round(left + (i * (right - left)) / (n - 1)));
}

/**
 * Home-desk positions for a cast of `n`: up to 6 sit in the locked front row;
 * beyond that the overflow wraps into the back row so desks stop overlapping
 * (the front row physically fits ~6 26px desks).
 */
export function homeSpots(n: number): HomeSpot[] {
  if (n <= 6) return homeCx(n).map((x) => ({ x, y: HOME_TOP }));
  const back = n - 6, left = 72, right = 151;
  const backXs = back === 1
    ? [Math.round((left + right) / 2)]
    : Array.from({ length: back }, (_, i) => Math.round(left + (i * (right - left)) / (back - 1)));
  return [
    ...homeCx(6).map((x) => ({ x, y: HOME_TOP })),
    ...backXs.map((x) => ({ x, y: HOME_BACK_TOP })),
  ];
}

// decor placements. `tv` + `cooler` are re-addressed in drawDecorAnim.
export const DECOR = {
  winL: { cx: 32, top: 4 },
  winR: { cx: 176, top: 4 }, // symmetric windows (72px each side of centre)
  clock: { cx: RW / 2, top: 5 }, // centred clock
  tv: { cx: 111, top: 16 }, // TV against the wall, midway between SEARCH and FETCH
  rug: { cx: 111, top: 36 }, // rug between the TV and the couch
  sofa: { cx: 111, top: 46 }, // couch below the rug, facing UP toward the TV
  dinner: { cx: 38, top: 64 }, // dinner/break table — left + a bit up
  fridge: { cx: 24, top: 100 },
  cooler: { cx: 199, top: 24 },
  plant: { cx: 10, top: 70 },
} as const;

/** Blit a canvas by centre-x / top edge (native px) at `scale`. */
export function blitC(ctx: CanvasRenderingContext2D, cv: HTMLCanvasElement, cx: number, top: number, scale: number) {
  blit(ctx, cv, Math.round((cx - cv.width / 2) * scale), Math.round(top * scale), scale);
}

/**
 * All static art canvases, built ONCE on first bake (they're authored at
 * native resolution and scale-independent — blit scales at draw time), so
 * resizes and cast changes only re-composite, never re-rasterize.
 */
interface ArtCache {
  wall: Cv;
  base: Cv;
  woods: Cv[];
  win: Cv;
  clock: Cv;
  tv: Cv;
  rug: Cv;
  sofa: Cv;
  furn: Record<StationName, Cv>;
  dinner: Cv;
  fridge: Cv;
  cooler: Cv;
  plant: Cv;
  home: Cv;
}
let art: ArtCache | null = null;
function artCache(): ArtCache {
  return (art ??= {
    wall: wallTile(),
    base: baseboardTile(),
    woods: [0, 1, 2, 3, 4].map(woodTile), // wood seeds are taken % 5
    win: windowCanvas(),
    clock: clockCanvas(),
    tv: tvCanvas(),
    rug: rugCanvas(),
    sofa: sofaCanvas(),
    furn: {
      LLM: deskCanvas(),
      SEARCH: doubleShelfCanvas(),
      FETCH: wideServerCanvas(),
      DATA: cabinetCanvas(),
      PRINT: printerTableCanvas(),
    },
    dinner: dinnerTableCanvas(),
    fridge: fridgeCanvas(),
    cooler: waterCoolerCanvas(),
    plant: plantCanvas(),
    home: homeDeskCanvas(),
  });
}

/**
 * Bake the static room (tiles + walls + all furniture + `homes` home desks)
 * into an offscreen canvas at `scale`. Rebake only when scale or cast changes.
 */
export function bakeGround(scale: number, homes: HomeSpot[]): HTMLCanvasElement {
  const a = artCache();
  const ground = document.createElement("canvas");
  ground.width = RW * scale;
  ground.height = RH * scale;
  const g = ground.getContext("2d")!;
  g.imageSmoothingEnabled = false;

  for (let r = 0; r < ROWS; r++)
    for (let cI = 0; cI < COLS; cI++) {
      const tile = r === 0 ? a.wall : r === 1 ? a.base : a.woods[(r * COLS + cI) * 7 % 5];
      blit(g, tile, cI * TILE * scale, r * TILE * scale, scale);
    }

  blitC(g, a.win, DECOR.winL.cx, DECOR.winL.top, scale);
  blitC(g, a.win, DECOR.winR.cx, DECOR.winR.top, scale);
  blitC(g, a.clock, DECOR.clock.cx, DECOR.clock.top, scale);
  blitC(g, a.tv, DECOR.tv.cx, DECOR.tv.top, scale);
  blitC(g, a.rug, DECOR.rug.cx, DECOR.rug.top, scale);
  blitC(g, a.sofa, DECOR.sofa.cx, DECOR.sofa.top, scale);
  for (const s of STATION_DEFS) blitC(g, a.furn[s.label], s.fcx, s.ftop, scale);
  blitC(g, a.dinner, DECOR.dinner.cx, DECOR.dinner.top, scale);
  blitC(g, a.fridge, DECOR.fridge.cx, DECOR.fridge.top, scale);
  blitC(g, a.cooler, DECOR.cooler.cx, DECOR.cooler.top, scale);
  blitC(g, a.plant, DECOR.plant.cx, DECOR.plant.top, scale);
  for (const h of homes) blitC(g, a.home, h.x, h.y, scale);
  return ground;
}

/**
 * Live decor animation, drawn over the baked ground each frame: the TV screen
 * flickers through cool hues with a drifting scanline; the cooler bubbles.
 */
export function drawDecorAnim(ctx: CanvasRenderingContext2D, t: number, scale: number) {
  // TV screen — inside tvCanvas the screen rect is x6,y2,18×8 (tv width 30 → half 15)
  const tvX = DECOR.tv.cx - 15 + 6, tvY = DECOR.tv.top + 2;
  const hues = ["#2e5f8a", "#3a6ea5", "#4aa6c8", "#356596"];
  const ph = Math.floor(t * 2.5) % hues.length;
  ctx.fillStyle = hues[ph];
  ctx.fillRect(tvX * scale, tvY * scale, 18 * scale, 8 * scale);
  ctx.fillStyle = "rgba(255,255,255,.16)"; // scanline drifting down
  ctx.fillRect(tvX * scale, (tvY + (Math.floor(t * 8) % 8)) * scale, 18 * scale, scale);
  // water-cooler bubble rising inside the bottle (cooler width 12 → half 6;
  // water is local rows 1–7, so the cycle stays inside them and never lands
  // on the bottle's outline rows)
  const bx = DECOR.cooler.cx - 6 + 5, by = DECOR.cooler.top + 7 - ((t * 6) % 6);
  ctx.fillStyle = "#f6f1e6";
  ctx.fillRect(Math.round(bx * scale), Math.round(by * scale), scale, scale);
}
