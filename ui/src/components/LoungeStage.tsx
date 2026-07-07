import { useEffect, useRef } from "react";
import { WALK, WALK_BOB, colorway, rasterize, blit } from "../lib/sprites";
import { CHROME } from "../lib/officeArt";
import {
  LW, LH, IDLE_SPOTS, bakeLounge, drawLoungeAnim, drawIdleFx, type IdleSpot,
} from "../lib/loungeArt";

/**
 * LoungeStage — the shared break-room diorama (loungeArt.ts) rendered on a
 * canvas, with one recolored 12×16 worker per waiting app at a distinct
 * break-room spot, each doing something different (§4-J): making coffee, at
 * the vending machine, sipping at the cooler, eating lunch, watering a plant,
 * or pacing. Pure presentation of already-derived data; not part of the
 * dual-logic rule.
 *
 * Motion (activity fx, the pacing walk, a 1px idle sway) is gated on
 * `prefers-reduced-motion`: when set, the loop stops and the room is painted
 * once, statically.
 */

const MAX_SCALE = 8;
const PACE_RANGE = 11; // wanderers pace ±px around their spot
const PACE_SPEED = 0.22; // pace cycles per second

export interface LoungeApp {
  id: string; // recolor key (appKey) — stable coworker per app
  label: string;
}

interface Placed {
  id: string;
  frames: HTMLCanvasElement[];
  spot: IdleSpot;
  x: number; // sprite top-left (native px)
  y: number;
  phase: number; // desyncs sway/fx between agents
}

interface StageState {
  apps: LoungeApp[];
  placed: Placed[];
  scale: number;
  dpr: number;
  ground: HTMLCanvasElement | null;
  groundScale: number;
  reduced: boolean;
  onscreen: boolean;
}

// The poll hands us a fresh array every tick — cache rasterized frames per app
// id so unchanged casts don't re-rasterize (bounded; lounges are small).
const frameCache = new Map<string, HTMLCanvasElement[]>();
function framesFor(id: string): HTMLCanvasElement[] {
  let f = frameCache.get(id);
  if (!f) {
    if (frameCache.size > 64) frameCache.clear();
    f = WALK.map((s) => rasterize(s, colorway(id)));
    frameCache.set(id, f);
  }
  return f;
}

function place(apps: LoungeApp[]): Placed[] {
  return apps.map((a, i) => {
    const spot = IDLE_SPOTS[i % IDLE_SPOTS.length];
    return {
      id: a.id,
      frames: framesFor(a.id),
      spot,
      x: spot.x - 6, // sprite is 12 wide → left edge from centre
      y: spot.y - 16, // feet at spot → top edge
      phase: i * 1.7,
    };
  });
}

/** Triangle wave in [-1, 1] — drives the wander pacing. */
function tri(t: number): number {
  const f = t % 1;
  return f < 0.5 ? f * 4 - 1 : 3 - f * 4;
}

function paint(s: StageState, canvas: HTMLCanvasElement | null, t: number) {
  if (!canvas || !s.ground || !s.scale) return;
  const ctx = canvas.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(s.ground, 0, 0);
  if (!s.reduced) drawLoungeAnim(ctx, t, s.scale);
  // back-to-front by y so nearer agents overlap farther ones
  for (const p of [...s.placed].sort((a, b) => a.y - b.y)) {
    const wander = p.spot.activity === "wander" && !s.reduced;
    const sway = tri((t + p.phase) * PACE_SPEED);
    const x = wander ? p.x + sway * PACE_RANGE : p.x;
    const bob = s.reduced ? 0 : WALK_BOB[Math.floor(t * 2 + p.phase) % WALK_BOB.length] || 0;
    const frame = wander
      ? p.frames[Math.floor(t * 1000 / 150) % 4] // pacing → walk cycle
      : p.frames[0];
    const dx = Math.round(x * s.scale), dy = Math.round((p.y + bob) * s.scale);
    // soft shadow
    ctx.globalAlpha = 0.18;
    ctx.fillStyle = CHROME.shadow;
    ctx.beginPath();
    ctx.ellipse(dx + 6 * s.scale, dy + 16 * s.scale, 6 * s.scale, 2.2 * s.scale, 0, 0, 7);
    ctx.fill();
    ctx.globalAlpha = 1;
    blit(ctx, frame, dx, dy, s.scale, wander && sway < 0);
    if (!s.reduced)
      drawIdleFx(ctx, p.spot, { x: p.spot.x - 6, y: p.spot.y }, t, s.scale, p.phase);
  }
}

export function LoungeStage({ apps }: { apps: LoungeApp[] }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const st = useRef<StageState>({
    apps,
    placed: place(apps),
    scale: 0,
    dpr: 0,
    ground: null,
    groundScale: 0,
    reduced: false,
    onscreen: true,
  });

  useEffect(() => {
    const s = st.current, wrap = wrapRef.current, canvas = canvasRef.current;
    if (!wrap || !canvas) return;

    let raf = 0, t0: number | null = null;
    const tick = (ts: number) => {
      if (t0 === null) t0 = ts;
      paint(s, canvas, (ts - t0) / 1000);
      raf = requestAnimationFrame(tick);
    };
    const stopLoop = () => { if (raf) cancelAnimationFrame(raf); raf = 0; };
    const startLoop = () => { if (!raf) raf = requestAnimationFrame(tick); };
    const updateLoop = () => {
      if (s.reduced || !s.onscreen) { stopLoop(); paint(s, canvas, 0); }
      else startLoop();
    };

    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const applyMotion = () => { s.reduced = mq.matches; updateLoop(); };
    mq.addEventListener("change", applyMotion);
    const io = new IntersectionObserver(([e]) => { s.onscreen = e.isIntersecting; updateLoop(); });
    io.observe(wrap);

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = wrap.clientWidth, h = wrap.clientHeight;
      if (!w || !h) return;
      const scale = Math.max(1, Math.min(Math.floor((w * dpr) / LW), Math.floor((h * dpr) / LH), MAX_SCALE));
      if (scale === s.scale && dpr === s.dpr) return;
      s.scale = scale;
      s.dpr = dpr;
      canvas.width = LW * scale;
      canvas.height = LH * scale;
      canvas.style.width = `${(LW * scale) / dpr}px`;
      canvas.style.height = `${(LH * scale) / dpr}px`;
      if (scale !== s.groundScale) { s.ground = bakeLounge(scale); s.groundScale = scale; }
      paint(s, canvas, 0);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    resize();
    applyMotion();

    return () => {
      stopLoop();
      ro.disconnect();
      io.disconnect();
      mq.removeEventListener("change", applyMotion);
    };
  }, []);

  // Cast changes: re-place the standing workers and repaint if the loop is
  // idle. The poll rebuilds `apps` each tick — key on ids to skip no-ops.
  const castKey = apps.map((a) => a.id).join("|");
  useEffect(() => {
    const s = st.current;
    s.apps = apps;
    s.placed = place(apps);
    if (s.reduced || !s.onscreen) paint(s, canvasRef.current, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [castKey]);

  return (
    <div ref={wrapRef} className="vt-lounge-stage">
      <canvas ref={canvasRef} className="sprite" role="img" aria-label="Break room" />
    </div>
  );
}
