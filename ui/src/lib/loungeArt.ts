/**
 * The shared Lounge diorama — the break room where a failed app's agents gather
 * (UI-ROADMAP §4-J, Phase 4b). Same art-as-data model, palette, and 1px
 * `#241a14` outline as the locked office room (officeArt.ts): furniture is drawn
 * as clean pixel rects at NATIVE px and integer-scaled at blit time. This room
 * is NOT the locked 12×16 office diorama — it is a new, portrait break room
 * sized to the building's top-right lounge column.
 *
 * Also here: the small Door / Stairs pixel icons for the descent column frames.
 *
 * Provenance: hand-authored, owned art (zero AI, zero third-party packs) —
 * Nick + Claude, 2026-07-07. Fixed warm hexes here are sprite data, not theme
 * colors (the lounge is a diorama and deliberately doesn't re-theme); the UI
 * chrome around the canvas themes normally. See ui/src/lib/ASSETS.md.
 */
import { blit } from "./sprites";

export const LTILE = 16;
export const LCOLS = 6;
export const LROWS = 10;
/** Lounge size in native px (portrait — fills the top-floor east column). */
export const LW = LCOLS * LTILE; // 96
export const LH = LROWS * LTILE; // 160

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
/** 1px outline around a filled box (matches officeArt's `box`). */
function box(c: Cv, x: number, y: number, w: number, h: number, fill: string) {
  rect(c, x, y, w, h, OUT);
  rect(c, x + 1, y + 1, w - 2, h - 2, fill);
}

/* ── floor / wall tiles — warmer, "off-duty" break-room wood + tile wall ─── */
function floorTile(seed: number): Cv {
  const c = newCv(LTILE, LTILE);
  rect(c, 0, 0, LTILE, LTILE, "#c69256"); // lighter, homier wood than the office
  rect(c, 0, seed % 2 ? 6 : 12, LTILE, 1, "#b5813f");
  c.ctx.fillStyle = "#cf9d63";
  for (let i = 0; i < 3; i++) c.ctx.fillRect((seed * 4 + i * 5) % LTILE, (i * 6 + seed) % LTILE, 1, 1);
  rect(c, 0, 15, LTILE, 1, "#a9732f");
  return c;
}
function wallTile(): Cv {
  const c = newCv(LTILE, LTILE);
  rect(c, 0, 0, LTILE, LTILE, "#dccfe0"); // cool lilac-grey break-room wall
  rect(c, 0, 0, LTILE, 1, "#cabdd0");
  // subtle tile grid
  rect(c, 0, 8, LTILE, 1, "#cfc1d4");
  rect(c, 8, 0, 1, LTILE, "#cfc1d4");
  return c;
}
function baseboardTile(): Cv {
  const c = newCv(LTILE, LTILE);
  rect(c, 0, 0, LTILE, LTILE, "#dccfe0");
  rect(c, 0, 11, LTILE, 3, "#b7a2be");
  rect(c, 0, 14, LTILE, 2, "#a9732f");
  return c;
}

/* ── break-room furniture (native px) ───────────────────────────────────── */

// kitchen counter with a sink + faucet (top wall) — 56×15
function counterCanvas(): Cv {
  const c = newCv(56, 15);
  box(c, 0, 2, 56, 12, "#a06c3a"); // counter body (dark wood)
  rect(c, 1, 3, 54, 1, "#c08a5a"); // front-edge highlight
  // cabinet seams
  rect(c, 18, 4, 1, 9, "#74502f");
  rect(c, 38, 4, 1, 9, "#74502f");
  rect(c, 9, 9, 4, 1, "#74502f"); // little handles
  rect(c, 27, 9, 4, 1, "#74502f");
  rect(c, 45, 9, 4, 1, "#74502f");
  // stainless sink basin inset (right of centre)
  box(c, 40, 3, 12, 8, "#9aa3ad");
  rect(c, 41, 4, 10, 6, "#c1c9d0");
  rect(c, 42, 5, 8, 4, "#aab3bb"); // basin
  rect(c, 45, 1, 1, 4, "#7d8690"); // faucet neck
  rect(c, 45, 1, 4, 1, "#7d8690"); // faucet spout
  return c;
}

// countertop coffee machine — 13×15
function coffeeCanvas(): Cv {
  const c = newCv(13, 15);
  box(c, 1, 0, 11, 14, "#3a3550"); // dark machine body
  rect(c, 2, 1, 9, 3, "#514a6e"); // water tank (top, lighter)
  rect(c, 3, 2, 3, 1, "#8fc4e6"); // water level
  rect(c, 4, 6, 5, 1, "#241a14"); // group head
  rect(c, 6, 7, 1, 3, "#241a14"); // spout
  box(c, 4, 10, 5, 4, "#f1ead8"); // cup
  rect(c, 5, 11, 3, 1, "#6b4a2a"); // coffee in cup
  rect(c, 9, 2, 1, 1, "#e0894a"); // amber power light
  rect(c, 9, 4, 1, 1, "#4f9d52"); // green ready light
  return c;
}

// snack vending machine — 20×32
function vendingCanvas(): Cv {
  const c = newCv(20, 32);
  box(c, 0, 0, 20, 32, "#4aa6c8"); // teal-blue cabinet
  rect(c, 1, 1, 18, 1, "#74c6e2"); // top highlight
  // glass front
  box(c, 2, 3, 12, 24, "#1c2530");
  const snacks = ["#c8536b", "#e0a35e", "#4f9d52", "#f1ead8", "#7a64d0", "#e0894a"];
  for (let r = 0; r < 4; r++)
    for (let col = 0; col < 3; col++) {
      rect(c, 4 + col * 3, 5 + r * 5, 2, 3, snacks[(r * 3 + col) % snacks.length]);
    }
  rect(c, 3, 4, 10, 1, "#3a4550"); // shelf glints
  rect(c, 3, 14, 10, 1, "#3a4550");
  rect(c, 3, 24, 10, 1, "#3a4550");
  // control column (right)
  box(c, 15, 4, 4, 10, "#2f3a44");
  rect(c, 16, 5, 2, 1, "#e0894a");
  rect(c, 16, 7, 2, 1, "#4f9d52");
  rect(c, 16, 9, 2, 1, "#f1ead8"); // buttons
  // dispenser tray
  box(c, 3, 28, 14, 3, "#1c2530");
  return c;
}

// water cooler — 12×22 (break-room re-author; bubble animates live)
function coolerCanvas(): Cv {
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

// mini fridge — 15×22
function fridgeCanvas(): Cv {
  const c = newCv(15, 22);
  box(c, 1, 0, 13, 22, "#cdd6dd");
  rect(c, 2, 1, 11, 20, "#dde5eb");
  rect(c, 1, 10, 13, 1, "#9aa3ad"); // door split
  rect(c, 10, 3, 1, 4, "#7d8690");
  rect(c, 10, 12, 1, 5, "#7d8690"); // handles
  rect(c, 3, 3, 3, 2, "#e0894a"); // a magnet / sticky note
  return c;
}

// round break table + 4 stool cushions (top-down) — 34×34
function tableCanvas(): Cv {
  const c = newCv(34, 34);
  const STOOL = "#c8536b", STOOLd = "#a23f55";
  // four stools around the table
  ([[13, 0], [13, 27], [0, 13], [27, 13]] as const).forEach(([x, y]) => {
    box(c, x, y, 7, 7, STOOL);
    rect(c, x + 1, y + 1, 5, 2, "#d97a92");
    rect(c, x + 1, y + 5, 5, 1, STOOLd);
  });
  // round tabletop (crisp pixel disc)
  const cx = 17, cy = 17, R2 = 10 * 10;
  for (let y = 0; y < 34; y++)
    for (let x = 0; x < 34; x++) {
      const dx = x - cx, dy = y - cy, d = dx * dx + dy * dy;
      if (d <= R2) rect(c, x, y, 1, 1, d >= (10 * 10 - 20) ? OUT : "#b07a45");
    }
  rect(c, 12, 13, 10, 1, "#c69256"); // top highlight
  rect(c, 12, 21, 10, 1, "#9c6636"); // shade
  box(c, 14, 14, 6, 6, "#4f9d52"); // little potted centrepiece
  rect(c, 15, 13, 3, 2, "#e0894a");
  return c;
}

// potted plant — 14×18 (break-room re-author, taller leaf spread)
function plantCanvas(): Cv {
  const c = newCv(14, 18);
  box(c, 4, 12, 6, 5, "#caa874");
  rect(c, 3, 11, 8, 2, "#9c6636"); // pot
  const G = "#4f9d52", g = "#3a7a3f";
  (
    [
      [5, 1, 4, 4, G], [3, 3, 3, 5, g], [8, 3, 3, 5, g],
      [4, 6, 6, 4, G], [2, 7, 3, 3, G], [9, 7, 3, 3, G], [6, 0, 2, 3, g],
    ] as const
  ).forEach(([x, y, w, h, col]) => box(c, x, y, w, h, col));
  return c;
}

// framed "BREAK" poster on the wall — 22×12
function posterCanvas(): Cv {
  const c = newCv(22, 12);
  box(c, 0, 0, 22, 12, "#74502f"); // frame
  rect(c, 2, 2, 18, 8, "#f1ead8"); // paper
  rect(c, 4, 4, 14, 2, "#e0894a"); // a warm sunrise band
  rect(c, 4, 7, 10, 1, "#4aa6c8");
  rect(c, 4, 9, 6, 1, "#4f9d52"); // little "text" lines
  return c;
}

/* ── the descent-column icons (Door / Stairs), drawn as their own canvases ─ */

// door icon — 20×26 (a warm wooden door, ajar highlight + knob)
export function doorCanvas(): Cv {
  const c = newCv(20, 26);
  box(c, 1, 0, 18, 26, "#8a5a30"); // door slab
  box(c, 3, 2, 14, 22, "#a06c3a"); // inner panel
  rect(c, 4, 3, 12, 1, "#bd8a55"); // panel highlight
  rect(c, 3, 12, 14, 1, "#74502f"); // mid rail
  rect(c, 4, 4, 12, 7, "#8a5a30"); // upper recess
  rect(c, 4, 14, 12, 8, "#8a5a30"); // lower recess
  rect(c, 14, 12, 2, 2, "#e0a35e"); // brass knob
  return c;
}

// stairs icon — 20×26 (top-down flight descending, treads receding)
export function stairsCanvas(): Cv {
  const c = newCv(20, 26);
  box(c, 1, 0, 18, 26, "#8a5a30"); // stairwell frame
  // treads — lighter at the top (near), darker going down (far)
  const shades = ["#caa874", "#bd8a55", "#a06c3a", "#8a5a30", "#74502f", "#5a3a22"];
  for (let i = 0; i < 6; i++) {
    const y = 2 + i * 4;
    rect(c, 3, y, 14, 4, shades[i]);
    rect(c, 3, y + 3, 14, 1, "#3a2516"); // step nosing (shadow line)
  }
  // down-arrow to read "descend"
  rect(c, 9, 8, 2, 8, "#241a14");
  rect(c, 7, 14, 6, 1, "#241a14");
  rect(c, 8, 15, 4, 1, "#241a14");
  rect(c, 9, 16, 2, 1, "#241a14");
  return c;
}

/* ── lounge layout (native px; cx = blit centre-x, top = top edge) ───────── */
export const LDECOR = {
  counter: { cx: 30, top: 17 },
  coffee: { cx: 9, top: 18 },
  vending: { cx: 84, top: 16 },
  fridge: { cx: 8, top: 60 },
  cooler: { cx: 88, top: 62 },
  poster: { cx: 44, top: 40 },
  table: { cx: 44, top: 92 },
  plantL: { cx: 9, top: 132 },
  plantR: { cx: 87, top: 132 },
} as const;

/** Where an idling agent stands (feet point, native px) + which prop it uses.
 *  Step 5 assigns waiting agents to distinct spots so each does something
 *  different. Ordered by preference; wraps if there are more agents than spots. */
export interface IdleSpot {
  x: number;
  y: number;
  activity: "coffee" | "vending" | "cooler" | "table" | "plant" | "wander";
}
export const IDLE_SPOTS: IdleSpot[] = [
  { x: 20, y: 40, activity: "coffee" },
  { x: 74, y: 42, activity: "vending" },
  { x: 78, y: 84, activity: "cooler" },
  { x: 32, y: 110, activity: "table" },
  { x: 56, y: 110, activity: "table" },
  { x: 18, y: 124, activity: "plant" },
  { x: 44, y: 74, activity: "wander" },
  { x: 66, y: 118, activity: "wander" },
];

export function blitC(ctx: CanvasRenderingContext2D, cv: HTMLCanvasElement, cx: number, top: number, scale: number) {
  blit(ctx, cv, Math.round((cx - cv.width / 2) * scale), Math.round(top * scale), scale);
}

interface LoungeArt {
  wall: Cv;
  base: Cv;
  floors: Cv[];
  counter: Cv;
  coffee: Cv;
  vending: Cv;
  fridge: Cv;
  cooler: Cv;
  poster: Cv;
  table: Cv;
  plant: Cv;
}
let art: LoungeArt | null = null;
function loungeArt(): LoungeArt {
  return (art ??= {
    wall: wallTile(),
    base: baseboardTile(),
    floors: [0, 1, 2, 3, 4].map(floorTile),
    counter: counterCanvas(),
    coffee: coffeeCanvas(),
    vending: vendingCanvas(),
    fridge: fridgeCanvas(),
    cooler: coolerCanvas(),
    poster: posterCanvas(),
    table: tableCanvas(),
    plant: plantCanvas(),
  });
}

/** Bake the static lounge (tiles + wall + all break-room furniture) at `scale`. */
export function bakeLounge(scale: number): HTMLCanvasElement {
  const a = loungeArt();
  const g = document.createElement("canvas");
  g.width = LW * scale;
  g.height = LH * scale;
  const ctx = g.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;

  for (let r = 0; r < LROWS; r++)
    for (let cI = 0; cI < LCOLS; cI++) {
      const tile = r === 0 ? a.wall : r === 1 ? a.base : a.floors[(r * LCOLS + cI) * 7 % 5];
      blit(ctx, tile, cI * LTILE * scale, r * LTILE * scale, scale);
    }

  blitC(ctx, a.counter, LDECOR.counter.cx, LDECOR.counter.top, scale);
  blitC(ctx, a.coffee, LDECOR.coffee.cx, LDECOR.coffee.top, scale);
  blitC(ctx, a.vending, LDECOR.vending.cx, LDECOR.vending.top, scale);
  blitC(ctx, a.fridge, LDECOR.fridge.cx, LDECOR.fridge.top, scale);
  blitC(ctx, a.poster, LDECOR.poster.cx, LDECOR.poster.top, scale);
  blitC(ctx, a.cooler, LDECOR.cooler.cx, LDECOR.cooler.top, scale);
  blitC(ctx, a.table, LDECOR.table.cx, LDECOR.table.top, scale);
  blitC(ctx, a.plant, LDECOR.plantL.cx, LDECOR.plantL.top, scale);
  blitC(ctx, a.plant, LDECOR.plantR.cx, LDECOR.plantR.top, scale);
  return g;
}

/** Live lounge fx over the baked ground: the coffee machine's ready light
 *  blinks and the water-cooler bubble rises. Skipped under reduced motion. */
export function drawLoungeAnim(ctx: CanvasRenderingContext2D, t: number, scale: number) {
  // coffee ready-light blink (coffee local x9,y4 → machine cx - w/2 + x)
  const on = Math.floor(t * 2) % 2 === 0;
  const lx = LDECOR.coffee.cx - 6 + 9, ly = LDECOR.coffee.top + 4;
  ctx.fillStyle = on ? "#4f9d52" : "#2f5f38";
  ctx.fillRect(lx * scale, ly * scale, scale, scale);
  // cooler bubble rising (cooler width 12 → half 6; water rows 1–7)
  const bx = LDECOR.cooler.cx - 6 + 5, by = LDECOR.cooler.top + 7 - ((t * 6) % 6);
  ctx.fillStyle = "#f6f1e6";
  ctx.fillRect(Math.round(bx * scale), Math.round(by * scale), scale, scale);
}

/** Per-agent idle-activity fx (§4-J: "each waiting agent does something
 *  different") — tiny procedural pixel effects near the worker/prop, same
 *  style as drawLoungeAnim. `phase` desyncs agents sharing an activity.
 *  Native lounge px; the caller passes the worker's feet point. */
export function drawIdleFx(
  ctx: CanvasRenderingContext2D,
  spot: IdleSpot,
  feet: Pt2,
  t: number,
  scale: number,
  phase: number
) {
  const tt = t + phase;
  const px = (x: number, y: number, col: string, w = 1, h = 1) => {
    ctx.fillStyle = col;
    ctx.fillRect(Math.round(x * scale), Math.round(y * scale), w * scale, h * scale);
  };
  switch (spot.activity) {
    case "coffee": {
      // steam curling up from the machine's cup (cup ≈ machine cx, top+11)
      const mx = LDECOR.coffee.cx, my = LDECOR.coffee.top + 10;
      const rise = (tt * 3) % 4;
      ctx.globalAlpha = 0.8 - rise * 0.18;
      px(mx + (Math.floor(tt * 3) % 2 ? 0 : 1), my - rise, "#f6f1e6");
      ctx.globalAlpha = 1;
      break;
    }
    case "vending": {
      // a snack drops into the tray every few seconds, then the tray glints
      const cyc = (tt * 0.5) % 1;
      const vx = LDECOR.vending.cx, vTop = LDECOR.vending.top;
      if (cyc < 0.3) px(vx - 4, vTop + 6 + cyc * 70, "#e0a35e", 2, 2); // falling snack
      else if (cyc < 0.5) px(vx - 4, vTop + 29, "#e0a35e", 2, 2); // resting in the tray
      break;
    }
    case "cooler": {
      // sipping: a little cup in hand, raised every few seconds
      const sip = (tt * 0.6) % 1 < 0.25 ? -3 : 0;
      px(feet.x + 6, feet.y - 7 + sip, "#f6f1e6", 2, 2);
      px(feet.x + 6, feet.y - 5 + sip, "#4aa6c8", 2, 1); // water line
      break;
    }
    case "table": {
      // lunch on the table edge in front of the seat: plate + food, and a
      // rising bite crumb now and then
      const towardCentre = feet.x < LDECOR.table.cx ? 5 : -7;
      px(feet.x + towardCentre, feet.y - 2, "#f1ead8", 4, 2); // plate
      px(feet.x + towardCentre + 1, feet.y - 3, "#e0894a", 2, 1); // sandwich
      if ((tt * 0.8) % 1 < 0.15) px(feet.x + towardCentre + 2, feet.y - 5, "#e0894a");
      break;
    }
    case "plant": {
      // watering: a tin in hand + droplets falling toward the plant
      const tin = feet.x < 48 ? -4 : 10; // tin on the plant side
      px(feet.x + tin, feet.y - 8, "#9aa3ad", 3, 2); // watering tin
      const drop = (tt * 2.5) % 3;
      ctx.globalAlpha = 0.9;
      px(feet.x + tin + (tin < 0 ? -1 : 3), feet.y - 6 + drop, "#8fc4e6");
      ctx.globalAlpha = 1;
      break;
    }
    case "wander":
      break; // the pacing itself is the activity
  }
}
interface Pt2 {
  x: number;
  y: number;
}
