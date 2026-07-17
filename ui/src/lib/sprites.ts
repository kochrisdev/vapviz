/**
 * Art-as-data sprite engine for the Theater office (UI-ROADMAP Phase 3 art rebuild).
 *
 * A sprite is hand-authored TEXT: a palette (single-char key → color spec) plus a
 * char-grid (one key per pixel, every row exactly `w` cells). The rasterizer turns a
 * grid into an offscreen canvas via ImageData; the renderer blits it with
 * integer-scale nearest-neighbor. Recolorable palette keys (skin/hair/shirt/pants)
 * resolve per agent from an FNV-1a-hashed colorway, so ONE authored worker becomes
 * many visually distinct coworkers.
 *
 * Provenance: hand-authored, owned art (zero AI, zero third-party packs). Authored
 * by Nick + Claude in `scratch/sprite-proto/proto.html` (layout/art locked
 * 2026-07-01), ported verbatim here 2026-07-02.
 *
 * The warm fixed hexes below ARE the art — they are sprite data, not UI theme
 * colors, and deliberately don't re-theme (the room is a diorama). UI chrome
 * around the canvas uses the design tokens instead.
 */

export interface Sprite {
  w: number;
  h: number;
  rows: string[];
}

export type ColorGroup = "skin" | "hair" | "shirt" | "pants";
type PaletteSpec = string | null | { group: ColorGroup; shade?: number };

export const PALETTE: Record<string, PaletteSpec> = {
  ".": null,
  "#": "#241a14", // outline (warm near-black, fixed)
  e: "#241a14", // eye
  b: "#3b2a1c", // shoe (fixed dark leather)
  w: "#f6f1e6", // white highlight
  // recolorable identity groups — each base key resolved from the agent colorway
  s: { group: "skin" },
  k: { group: "skin", shade: 0.2 }, // skin shadow
  h: { group: "hair" },
  g: { group: "hair", shade: 0.28 }, // hair shadow
  t: { group: "shirt" },
  T: { group: "shirt", shade: 0.22 }, // shirt shadow
  p: { group: "pants" },
  P: { group: "pants", shade: 0.26 }, // pants shadow
};

/** Row builder: guarantees every row is exactly `w` cells (a ragged row corrupts the raster). */
function rowmaker(w: number) {
  return (...segs: [string, number][]): string => {
    let s = "";
    for (const [c, n] of segs) s += c.repeat(n);
    if (s.length !== w) throw new Error(`sprite row width ${s.length}≠${w}: "${s}"`);
    return s;
  };
}

/* ── the 12×16 worker, facing down ─────────────────────────────────────── */
const R = rowmaker(12);
// head + torso (rows 0–11), shared by every frame
const TORSO: string[] = [
  R([".", 4], ["h", 4], [".", 4]), // 0 hair crown
  R([".", 2], ["#", 1], ["h", 6], ["#", 1], [".", 2]), // 1
  R([".", 1], ["#", 1], ["h", 8], ["#", 1], [".", 1]), // 2
  R([".", 1], ["#", 1], ["g", 1], ["s", 6], ["g", 1], ["#", 1], [".", 1]), // 3 forehead (hair sides)
  R([".", 1], ["#", 1], ["g", 1], ["s", 1], ["e", 1], ["s", 2], ["e", 1], ["s", 1], ["g", 1], ["#", 1], [".", 1]), // 4 eyes
  R([".", 1], ["#", 1], ["g", 1], ["s", 6], ["g", 1], ["#", 1], [".", 1]), // 5 cheeks
  R([".", 2], ["#", 1], ["k", 1], ["s", 4], ["k", 1], ["#", 1], [".", 2]), // 6 chin (skin shadow sides)
  R([".", 1], ["#", 1], ["t", 8], ["#", 1], [".", 1]), // 7 shoulders
  R([".", 1], ["#", 1], ["t", 3], ["T", 2], ["t", 3], ["#", 1], [".", 1]), // 8 torso (center seam shade)
  R([".", 1], ["#", 1], ["t", 3], ["T", 2], ["t", 3], ["#", 1], [".", 1]), // 9
  R([".", 1], ["#", 1], ["s", 1], ["t", 6], ["s", 1], ["#", 1], [".", 1]), // 10 hands at sides
  R([".", 2], ["#", 1], ["t", 1], ["T", 4], ["t", 1], ["#", 1], [".", 2]), // 11 waist
];
// leg frames (rows 12–15). A step shows a sole under the *forward* foot (and a
// 1px bob, applied at draw time) so motion is clearly visible at this size.
const LEGS: Record<string, string[]> = {
  mid: [
    R([".", 2], ["#", 1], ["p", 6], ["#", 1], [".", 2]),
    R([".", 2], ["#", 1], ["p", 2], ["#", 2], ["p", 2], ["#", 1], [".", 2]), // ## crease between legs
    R([".", 2], ["#", 1], ["b", 2], [".", 2], ["b", 2], ["#", 1], [".", 2]),
    R([".", 12]),
  ],
  left: [
    R([".", 2], ["#", 1], ["p", 6], ["#", 1], [".", 2]),
    R([".", 2], ["#", 1], ["p", 2], ["#", 2], ["p", 2], ["#", 1], [".", 2]),
    R([".", 2], ["#", 1], ["b", 2], [".", 2], ["b", 2], ["#", 1], [".", 2]),
    R([".", 3], ["b", 2], [".", 7]), // sole under left foot
  ],
  right: [
    R([".", 2], ["#", 1], ["p", 6], ["#", 1], [".", 2]),
    R([".", 2], ["#", 1], ["p", 2], ["#", 2], ["p", 2], ["#", 1], [".", 2]),
    R([".", 2], ["#", 1], ["b", 2], [".", 2], ["b", 2], ["#", 1], [".", 2]),
    R([".", 7], ["b", 2], [".", 3]), // sole under right foot
  ],
};
function workerFrame(legkey: string): Sprite {
  return { w: 12, h: 16, rows: [...TORSO, ...LEGS[legkey]] };
}
/** The 4-frame walk cycle (contact / step-L / contact / step-R). Frame 0 doubles as idle. */
export const WALK: Sprite[] = ["mid", "left", "mid", "right"].map(workerFrame);
/** Per-frame 1px body lift on each step. */
export const WALK_BOB = [0, -1, 0, -1];

/* ── per-agent recolor: FNV-1a hash → deterministic colorway ───────────── */
const SKIN = ["#f0c8a0", "#e3ad84", "#c88a5b", "#9c6a42", "#73492c"];
const HAIR = ["#2a2320", "#5a3a22", "#caa12a", "#8b2e2e", "#3a6ea5", "#7a3fa0", "#d9763a", "#e7e3da"];
const SHIRT = ["#5b8def", "#3fbf9b", "#e0894a", "#d05b7a", "#7a64d0", "#4aa6c8", "#86b94a", "#c8536b"];
const PANTS = ["#39414f", "#5a4632", "#2b3550", "#43352a", "#4b5563"];

export function fnv(s: string): number {
  let h = 0x811c9dc5 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
  }
  return h >>> 0;
}
const pick = (h: number, shift: number, arr: string[]) => arr[(h >>> shift) % arr.length];
export function hex2rgb(x: string): [number, number, number] {
  return [parseInt(x.slice(1, 3), 16), parseInt(x.slice(3, 5), 16), parseInt(x.slice(5, 7), 16)];
}
function darken(rgb: [number, number, number], t: number): [number, number, number] {
  return [Math.round(rgb[0] * (1 - t)), Math.round(rgb[1] * (1 - t)), Math.round(rgb[2] * (1 - t))];
}

export type Colorway = Record<ColorGroup, [number, number, number]>;

/** Deterministic identity colors for an agent/run id — same id, same coworker. */
export function colorway(id: string): Colorway {
  const h = fnv(id || "agent");
  return {
    skin: hex2rgb(pick(h, 0, SKIN)),
    hair: hex2rgb(pick(h, 5, HAIR)),
    shirt: hex2rgb(pick(h, 11, SHIRT)),
    pants: hex2rgb(pick(h, 17, PANTS)),
  };
}

/** Resolve a palette key → [r,g,b,a] under a colorway (null → transparent). */
export function resolve(key: string, cw: Colorway): [number, number, number, number] | null {
  const spec = PALETTE[key];
  if (spec === null || spec === undefined) return null;
  if (typeof spec === "string") {
    const [r, g, b] = hex2rgb(spec);
    return [r, g, b, 255];
  }
  const base = cw[spec.group];
  const rgb = spec.shade ? darken(base, spec.shade) : base;
  return [rgb[0], rgb[1], rgb[2], 255];
}

/* ── rasterizer: char grid → offscreen canvas (native px, unscaled) ────── */
export function rasterize(sprite: Sprite, cw: Colorway): HTMLCanvasElement {
  const { w, h, rows } = sprite;
  const cv = document.createElement("canvas");
  cv.width = w;
  cv.height = h;
  const ctx = cv.getContext("2d")!;
  const img = ctx.createImageData(w, h);
  for (let y = 0; y < h; y++) {
    const line = rows[y] || "";
    for (let x = 0; x < w; x++) {
      const px = resolve(line[x], cw);
      if (!px) continue;
      const i = (y * w + x) * 4;
      img.data[i] = px[0];
      img.data[i + 1] = px[1];
      img.data[i + 2] = px[2];
      img.data[i + 3] = px[3];
    }
  }
  ctx.putImageData(img, 0, 0);
  return cv;
}

/** Integer-scale nearest-neighbor blit, with optional horizontal flip. */
export function blit(
  dst: CanvasRenderingContext2D,
  src: HTMLCanvasElement,
  dx: number,
  dy: number,
  scale: number,
  flip = false,
): void {
  dst.imageSmoothingEnabled = false;
  if (flip) {
    dst.save();
    dst.translate(dx + src.width * scale, dy);
    dst.scale(-1, 1);
    dst.drawImage(src, 0, 0, src.width * scale, src.height * scale);
    dst.restore();
  } else {
    dst.drawImage(src, dx, dy, src.width * scale, src.height * scale);
  }
}
