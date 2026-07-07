/**
 * The walk-overlay engine (UI-ROADMAP §4-J, Phase 4b) — the meatiest 4b piece.
 *
 * A shell-layer sprite overlay that sits ABOVE the room canvases (room interiors
 * are the locked OfficeStage diorama, so cross-floor walkers can't live inside
 * them) and animates one recolored 12×16 worker per building transition:
 *
 *   • descent  — room → Walk Way → Stairs (VANISH) → Door of the floor below
 *                (reappear) → Walk Way → room. Nobody is ever drawn on the
 *                stairs (Nick's resource-saver: two flat walks + a vanish/appear).
 *   • failure  — room → Walk Way → up the descent column → the shared lounge.
 *
 * All coordinates are building-local CSS px (the canvas is a child of the
 * building box, so they're scroll-independent); the engine multiplies by dpr
 * for its backing store. Pure presentation of already-derived data — NOT part
 * of the dual-logic rule. Motion is gated by the caller: under reduced motion
 * nothing is spawned (the FLIP room glide is the fallback).
 */
import { WALK, colorway, rasterize, blit } from "./sprites";
import { CHROME } from "./officeArt";

export interface Pt {
  x: number;
  y: number;
}

const SPEED = 300; // CSS px/s along the path (~4s for a full descent, ~2s to the lounge)
const SPRITE_S = 2; // CSS scale of the 12×16 worker (×dpr for device px)
const LINGER_MS = 450; // hold at the destination before despawning
const FRAME_MS = 120; // walk-cycle frame duration

interface Walker {
  frames: HTMLCanvasElement[];
  path: Pt[];
  hideSeg: number; // sprite hidden while traversing this segment index (−1 = never)
  seg: number;
  segT: number; // 0..1 along the current segment
  facingLeft: boolean;
  linger: number; // ms remaining after arrival
}

function len(a: Pt, b: Pt): number {
  return Math.hypot(b.x - a.x, b.y - a.y) || 1e-4;
}

export class WalkEngine {
  private ctx: CanvasRenderingContext2D;
  private dpr = 1;
  private w = 0;
  private h = 0;
  private walkers: Walker[] = [];
  private cache = new Map<string, HTMLCanvasElement[]>();
  private raf = 0;
  private last = 0;
  private reduced = false;

  constructor(private canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext("2d")!;
  }

  setReduced(r: boolean) {
    this.reduced = r;
    if (r) this.clearAll();
  }

  /** Size the backing store to the building box (CSS px + dpr). */
  resize(w: number, h: number, dpr: number) {
    if (w === this.w && h === this.h && dpr === this.dpr) return;
    this.w = w;
    this.h = h;
    this.dpr = dpr;
    this.canvas.width = Math.max(1, Math.round(w * dpr));
    this.canvas.height = Math.max(1, Math.round(h * dpr));
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    // Resizing cleared the backing store. If walkers are mid-route the rAF loop
    // repaints on its own next frame (forcing a paint here would snap the walk
    // cycle to frame 0 — a stutter); only paint when idle, to stay cleared.
    if (!this.hasActive()) this.paint(0);
  }

  private framesFor(id: string): HTMLCanvasElement[] {
    let f = this.cache.get(id);
    if (!f) {
      f = WALK.map((s) => rasterize(s, colorway(id)));
      if (this.cache.size > 64) this.cache.clear();
      this.cache.set(id, f);
    }
    return f;
  }

  /** Spawn a walker along `path`; hide the sprite while crossing `hideSeg`
   *  (the stairs→door segment for descents; −1 for a continuous walk). */
  spawn(id: string, path: Pt[], hideSeg = -1) {
    if (this.reduced || path.length < 2) return;
    this.walkers.push({
      frames: this.framesFor(id),
      path,
      hideSeg,
      seg: 0,
      segT: 0,
      facingLeft: false,
      linger: LINGER_MS,
    });
    if (!this.raf) {
      this.last = 0;
      this.raf = requestAnimationFrame(this.tick);
    }
  }

  hasActive(): boolean {
    return this.walkers.length > 0;
  }

  clearAll() {
    this.walkers = [];
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.paint(0);
  }

  private advance(wkr: Walker, dt: number) {
    if (wkr.seg >= wkr.path.length - 1) {
      wkr.linger -= dt * 1000;
      return;
    }
    let remain = SPEED * dt;
    while (remain > 0 && wkr.seg < wkr.path.length - 1) {
      const a = wkr.path[wkr.seg];
      const b = wkr.path[wkr.seg + 1];
      const segLen = len(a, b);
      const step = Math.min(remain, segLen * (1 - wkr.segT));
      wkr.segT += step / segLen;
      if (Math.abs(b.x - a.x) > 1) wkr.facingLeft = b.x < a.x;
      remain -= step;
      if (wkr.segT >= 1 - 1e-6) {
        wkr.seg++;
        wkr.segT = 0;
      }
    }
  }

  private tick = (ts: number) => {
    const dt = this.last ? Math.min((ts - this.last) / 1000, 0.05) : 0;
    this.last = ts;
    for (const wkr of this.walkers) this.advance(wkr, dt);
    this.walkers = this.walkers.filter((w) => w.seg < w.path.length - 1 || w.linger > 0);
    this.paint(ts);
    if (this.walkers.length) this.raf = requestAnimationFrame(this.tick);
    else this.raf = 0;
  };

  private paint(ts: number) {
    const ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.imageSmoothingEnabled = false;
    const s = SPRITE_S * this.dpr;
    for (const wkr of this.walkers) {
      const seg = Math.min(wkr.seg, wkr.path.length - 2);
      if (seg === wkr.hideSeg) continue; // on the stairs → not drawn
      const a = wkr.path[seg];
      const b = wkr.path[seg + 1];
      const t = wkr.seg >= wkr.path.length - 1 ? 1 : wkr.segT;
      const x = a.x + (b.x - a.x) * t;
      const y = a.y + (b.y - a.y) * t;
      const moving = wkr.seg < wkr.path.length - 1;
      const frame = wkr.frames[moving ? Math.floor(ts / FRAME_MS) % 4 : 0];
      // Feet at path point (x,y) in device px. The sprite is 12×16 native drawn
      // at scale `s` (device px/native px), so displayed w=12·s, h=16·s: centre
      // it on x (−6·s) and hang it above the point (−16·s). Offsets must use the
      // DRAW scale, not the native half-size — else the walker floats off-path.
      const dx = Math.round(x * this.dpr - 6 * s);
      const dy = Math.round(y * this.dpr - 16 * s);
      // soft shadow at the feet
      ctx.globalAlpha = 0.16;
      ctx.fillStyle = CHROME.shadow;
      ctx.beginPath();
      ctx.ellipse(dx + 6 * s, dy + 16 * s, 6 * s, 2.2 * s, 0, 0, 7);
      ctx.fill();
      ctx.globalAlpha = 1;
      blit(ctx, frame, dx, dy, s, wkr.facingLeft);
    }
  }
}
