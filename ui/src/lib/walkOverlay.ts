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

/** A floor's Walk-Way corridor in building-local CSS px: centre-line `y`, and
 *  the `[x0, x1]` span residents mill between. */
export interface Lane {
  y: number;
  x0: number;
  x1: number;
}

/** A running room that should have one honest floor-life walker out on the
 *  corridor: recolored by `key` (the app key), anchored to its `door` on
 *  `floorId`'s Walk-Way lane. */
export interface LifeSpec {
  key: string;
  floorId: string;
  door: Pt;
  lane: Lane;
}

const SPEED = 300; // CSS px/s along the path (~4s for a full descent, ~2s to the lounge)
const LIFE_SPEED = 130; // CSS px/s for the relaxed floor-life stroll
const SPRITE_S = 2; // CSS scale of the 12×16 worker (×dpr for device px)
const LINGER_MS = 450; // hold at the destination before despawning
const FRAME_MS = 120; // walk-cycle frame duration
const MILL_MARGIN = 14; // keep mill targets off the very ends of the lane

interface Walker {
  frames: HTMLCanvasElement[];
  path: Pt[];
  hideSeg: number; // sprite hidden while traversing this segment index (−1 = never)
  seg: number;
  segT: number; // 0..1 along the current segment
  facingLeft: boolean;
  linger: number; // ms remaining after arrival
}

/**
 * A persistent floor-life resident (§4-K; honest-only since §4-L — the ambient
 * idle-floor stroller was deleted with the environment redesign). One per
 * RUNNING room, alive as long as the room runs. State machine: `in` (door →
 * lane) → `mill` (drift between random lane points) → `out` (lane → back
 * through the door).
 */
interface Resident {
  key: string; // "h:<appKey>" — one per running room
  floorId: string; // owning floor (re-anchored if the running app descends)
  frames: HTMLCanvasElement[];
  door: Pt; // walkway-facing edge of the home room (updated by reconcile)
  lane: Lane;
  pos: Pt;
  target: Pt;
  phase: "in" | "mill" | "out";
  facingLeft: boolean;
  pauseMs: number; // remaining pause at a mill point (idle → frame 0)
  wanted: boolean; // reconcile clears this → the resident walks home and despawns
  yJit: number; // per-resident lane-band offset so they don't perfectly overlap
  done: boolean; // reached the door on the way out → filtered next tick
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
  private life: Resident[] = []; // persistent floor-life residents (§4-K)
  private jitN = 0; // spreads residents across the lane band
  private cache = new Map<string, HTMLCanvasElement[]>();
  private raf = 0;
  private last = 0;
  private reduced = false;

  constructor(private canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext("2d")!;
  }

  setReduced(r: boolean) {
    this.reduced = r;
    if (r) this.clearAll(); // no floor life / walkers under reduced motion
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
    return this.walkers.length > 0 || this.life.length > 0;
  }

  /** Stop everything: transient walkers AND persistent residents, and blank the
   *  canvas. Used on reduced-motion and on unmount teardown. */
  clearAll() {
    this.walkers = [];
    this.life = [];
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.paint(0);
  }

  /** Start the rAF loop if anything (transient walkers OR residents) is active. */
  private ensureLoop() {
    if (!this.raf && this.hasActive()) {
      this.last = 0;
      this.raf = requestAnimationFrame(this.tick);
    }
  }

  /**
   * Reconcile the persistent floor-life layer (§4-K, honest-only since §4-L)
   * against the current poll: one honest resident per running room, nothing
   * else — an empty floor has an empty corridor. Called each tick from
   * BuildingView after the fresh snapshot. No-op (and clears) under reduced motion.
   */
  reconcileFloorLife(busy: LifeSpec[]) {
    if (this.reduced) {
      if (this.life.length) this.life = [];
      return;
    }
    const busyByKey = new Map(busy.map((s) => [`h:${s.key}`, s]));

    // Re-anchor the residents whose room still runs; send the rest home.
    for (const r of this.life) {
      const s = busyByKey.get(r.key);
      if (!s) {
        r.wanted = false;
        continue;
      }
      r.wanted = true;
      if (s.floorId !== r.floorId) {
        // The room changed floors (a running app descended): re-emerge at the
        // new door rather than gliding diagonally across floors through walls.
        r.floorId = s.floorId;
        r.pos = { ...s.door };
        r.phase = "in";
        r.target = { x: s.door.x, y: s.lane.y + r.yJit };
      }
      r.door = s.door;
      r.lane = s.lane;
    }

    // Add one honest resident for each newly-running room.
    const have = new Set(this.life.map((r) => r.key));
    for (const s of busy) {
      const key = `h:${s.key}`;
      if (!have.has(key)) this.life.push(this.makeResident(key, s.key, s.door, s.lane, s.floorId));
    }

    this.ensureLoop();
  }

  private makeResident(key: string, colorId: string, door: Pt, lane: Lane, floorId: string): Resident {
    const yJit = ((this.jitN++ % 5) - 2) * 3; // −6..+6 across the corridor band
    return {
      key,
      floorId,
      frames: this.framesFor(colorId),
      door: { ...door },
      lane,
      pos: { ...door },
      target: { x: door.x, y: lane.y + yJit }, // step out onto the lane
      phase: "in",
      facingLeft: false,
      pauseMs: 0,
      wanted: true,
      yJit,
      done: false,
    };
  }

  private pickMill(r: Resident) {
    const lo = r.lane.x0 + MILL_MARGIN;
    const hi = r.lane.x1 - MILL_MARGIN;
    const x = hi > lo ? lo + Math.random() * (hi - lo) : (r.lane.x0 + r.lane.x1) / 2;
    r.target = { x, y: r.lane.y + r.yJit };
  }

  private advanceResident(r: Resident, dt: number) {
    if (r.pauseMs > 0) {
      r.pauseMs -= dt * 1000;
      return;
    }
    const dx = r.target.x - r.pos.x;
    const dy = r.target.y - r.pos.y;
    const dist = Math.hypot(dx, dy);
    if (Math.abs(dx) > 0.5) r.facingLeft = dx < 0;
    const step = LIFE_SPEED * dt;
    if (dist <= step || dist < 1e-3) {
      r.pos = { ...r.target };
      this.arriveResident(r);
    } else {
      r.pos.x += (dx / dist) * step;
      r.pos.y += (dy / dist) * step;
    }
  }

  private arriveResident(r: Resident) {
    if (r.phase === "in") {
      r.phase = "mill";
      this.pickMill(r);
    } else if (r.phase === "mill") {
      if (!r.wanted) {
        r.phase = "out";
        r.target = { x: r.door.x, y: r.lane.y + r.yJit }; // line up with the door
      } else {
        r.pauseMs = 400 + Math.random() * 800;
        this.pickMill(r);
      }
    } else {
      // "out": if the room started running again mid-exit, turn back to milling.
      if (r.wanted) {
        r.phase = "mill";
        this.pickMill(r);
        return;
      }
      // Otherwise reach the lane point in front of the door, then step inside.
      if (Math.abs(r.pos.y - r.door.y) > 1) {
        r.target = { x: r.door.x, y: r.door.y };
      } else {
        r.done = true;
      }
    }
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
    for (const r of this.life) this.advanceResident(r, dt);
    this.walkers = this.walkers.filter((w) => w.seg < w.path.length - 1 || w.linger > 0);
    this.life = this.life.filter((r) => !r.done);
    this.paint(ts);
    if (this.hasActive()) this.raf = requestAnimationFrame(this.tick);
    else this.raf = 0;
  };

  /** Draw one worker with its feet at building-local CSS point (x,y). The sprite
   *  is 12×16 native at draw scale `s` (device px/native px): centre it on x
   *  (−6·s) and hang it above the point (−16·s). Offsets use the DRAW scale, not
   *  the native half-size — else the sprite floats off its anchor. */
  private drawWorker(
    frames: HTMLCanvasElement[],
    x: number,
    y: number,
    facingLeft: boolean,
    moving: boolean,
    ts: number
  ) {
    const ctx = this.ctx;
    const s = SPRITE_S * this.dpr;
    const frame = frames[moving ? Math.floor(ts / FRAME_MS) % 4 : 0];
    const dx = Math.round(x * this.dpr - 6 * s);
    const dy = Math.round(y * this.dpr - 16 * s);
    ctx.globalAlpha = 0.16; // soft shadow at the feet
    ctx.fillStyle = CHROME.shadow;
    ctx.beginPath();
    ctx.ellipse(dx + 6 * s, dy + 16 * s, 6 * s, 2.2 * s, 0, 0, 7);
    ctx.fill();
    ctx.globalAlpha = 1;
    blit(ctx, frame, dx, dy, s, facingLeft);
  }

  private paint(ts: number) {
    const ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.imageSmoothingEnabled = false;
    // Persistent floor-life residents (under the transient walkers).
    for (const r of this.life) this.drawWorker(r.frames, r.pos.x, r.pos.y, r.facingLeft, r.pauseMs <= 0, ts);
    // Transient descent/failure walkers.
    for (const wkr of this.walkers) {
      const seg = Math.min(wkr.seg, wkr.path.length - 2);
      if (seg === wkr.hideSeg) continue; // on the stairs → not drawn
      const a = wkr.path[seg];
      const b = wkr.path[seg + 1];
      const t = wkr.seg >= wkr.path.length - 1 ? 1 : wkr.segT;
      const x = a.x + (b.x - a.x) * t;
      const y = a.y + (b.y - a.y) * t;
      const moving = wkr.seg < wkr.path.length - 1;
      this.drawWorker(wkr.frames, x, y, wkr.facingLeft, moving, ts);
    }
  }
}
