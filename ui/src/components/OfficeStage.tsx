import { useEffect, useMemo, useRef } from "react";
import type { GraphNode } from "../types/events";
import { buildScene, type AvatarState } from "../lib/theater";
import { callsByAgent, stationForCall, fallbackStation, lineFor, errorLineFor } from "../lib/officeScene";
import { WALK, WALK_BOB, colorway, rasterize, blit } from "../lib/sprites";
import {
  RW, RH, STATION_DEFS, homeSpots, bakeGround, drawDecorAnim, CHROME,
  type HomeSpot, type StationName,
} from "../lib/officeArt";

/**
 * OfficeStage — the sprite Theater room (art rebuild of Phase 3's stage).
 *
 * Renders the LOCKED cozy-office diorama (officeArt.ts) on a canvas and walks
 * one recolored 12×16 worker (sprites.ts) per cast agent through it. What each
 * agent is doing comes from `buildScene` (unchanged); WHICH desk a tool call
 * maps to comes from `officeScene.stationForCall`. Driven purely by props, so
 * it animates equally for live SSE updates and scrubbed replay.
 *
 * Walking uses adaptive px/s: every trip takes ~WALK_S seconds regardless of
 * distance, so an agent reaches its desk before any call longer than that
 * completes. `prefers-reduced-motion` is tracked live: when set, the animation
 * loop stops entirely — agents appear at their targets and the room repaints
 * only when the data or size changes.
 *
 * `compact` renders the same room for the Floor's small tiled run-zones:
 * station label chips and speech bubbles are dropped (unreadable at zone
 * scale), name tags keep a legible floor via the chrome unit `u`, and the
 * glow / walk / ✓ ! cues carry the activity signal.
 */

const WALK_S = 0.55; // seconds per trip → adaptive speed
const FONT = "ui-monospace,SFMono-Regular,Menlo,monospace";
const MAX_SCALE = 8;
const COMPACT_TAG_UNIT = 3.2; // compact chrome-unit floor (× dpr → ~9 CSS-px name tags)

interface Goal {
  name: string;
  state: AvatarState;
  target: { x: number; y: number };
  home: { x: number; y: number };
  /** Station the agent is at/heading to, null = home desk. */
  station: StationName | null;
  /** Speech-bubble line, shown once arrived (null = no bubble). */
  say: string | null;
}
interface Goals {
  agents: Goal[];
  byName: Map<string, Goal>;
  hot: Set<StationName>;
  homes: HomeSpot[];
  /** Screen-reader description of the whole scene (the canvas is opaque to AT). */
  label: string;
}

interface Worker {
  x: number;
  y: number;
  facingLeft: boolean;
  speed: number; // native px/s, set per trip
  target: { x: number; y: number };
  frames: HTMLCanvasElement[];
}

function stationDef(name: StationName) {
  return STATION_DEFS.find((s) => s.label === name)!;
}

/** Pure: scene + per-agent calls → where everyone should stand and what they say. */
function computeGoals(nodes: GraphNode[]): Goals {
  const scene = buildScene(nodes);
  const calls = callsByAgent(nodes);
  const homes = homeSpots(scene.agents.length);
  const hot = new Set<StationName>();

  // First pass: resolve each agent's station (or home).
  const raw = scene.agents.map((a, i) => {
    const c = calls.get(a.name) ?? { runningLlm: null, runningTool: null, recent: null };
    let station: StationName | null = null;
    if (a.at === "llm") {
      station = "LLM";
      if (c.runningLlm) hot.add("LLM"); // glow only while a model call is running
    } else if (a.at === "tool") {
      // Prefer the RUNNING tool call (kind-matched to buildScene's `at`), fall
      // back to the most recent tool call for linger, then to a hash spread.
      const call = c.runningTool ?? (c.recent?.kind === "tool" ? c.recent : null);
      station = call ? stationForCall(call) : fallbackStation(a.name);
      if (c.runningTool) hot.add(station);
    }
    const say = station
      ? lineFor(a.name, station)
      : a.state === "thinking"
        ? lineFor(a.name, "LLM") // active but not at a desk yet — still show life
        : a.state === "error"
          ? errorLineFor(a.name)
          : null;
    const spot = homes[Math.min(i, homes.length - 1)];
    const home = { x: spot.x, y: spot.y - 6 };
    return { a, station, say, home };
  });

  // Second pass: place, fanning out agents that share a station.
  const atStation = new Map<StationName, number[]>();
  raw.forEach((r, idx) => {
    if (r.station) (atStation.get(r.station) ?? atStation.set(r.station, []).get(r.station)!).push(idx);
  });
  const agents: Goal[] = raw.map((r, idx) => {
    let target = r.home;
    if (r.station) {
      const def = stationDef(r.station);
      const peers = atStation.get(r.station)!;
      const k = peers.indexOf(idx);
      target = { x: def.sx + (k - (peers.length - 1) / 2) * 14, y: def.sy };
    }
    return { name: r.a.name, state: r.a.state, target, home: r.home, station: r.station, say: r.say };
  });

  const label = agents.length
    ? `Office view — ${agents.map((g) => `${g.name}: ${g.say ?? g.state}${g.station ? ` at ${g.station}` : ""}`).join("; ")}`
    : "Office view — no agents yet";
  return { agents, byName: new Map(agents.map((g) => [g.name, g])), hot, homes, label };
}

/* ── canvas text/fx helpers (all sized off `scale` so every zoom is crisp) ── */

// measureText runs per worker per frame across every stage instance — cache
// widths by font+text (both come from a small, stable set per session).
const textW = new Map<string, number>();
function measure(ctx: CanvasRenderingContext2D, text: string, font: string): number {
  const key = font + "|" + text;
  let w = textW.get(key);
  if (w === undefined) {
    if (textW.size > 512) textW.clear();
    ctx.font = font;
    w = ctx.measureText(text).width;
    textW.set(key, w);
  }
  return w;
}

function labelChip(ctx: CanvasRenderingContext2D, text: string, cx: number, yTop: number, hot: boolean, scale: number) {
  const f = `600 ${2.5 * scale}px ${FONT}`;
  ctx.font = f;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const tw = measure(ctx, text, f), x = cx * scale, y = yTop * scale;
  ctx.fillStyle = hot ? CHROME.chipHotBg : CHROME.chipBg;
  ctx.fillRect(x - tw / 2 - 1.25 * scale, y, tw + 2.5 * scale, 4 * scale);
  ctx.fillStyle = hot ? CHROME.chipHotText : CHROME.chipText;
  ctx.fillText(text, x, y + 0.75 * scale);
}
// small, simple activity glow (calm blue-white)
function glow(ctx: CanvasRenderingContext2D, cx: number, cy: number, scale: number) {
  const x = cx * scale, y = cy * scale, r = 11 * scale;
  const g = ctx.createRadialGradient(x, y, 0, x, y, r);
  g.addColorStop(0, CHROME.glowIn);
  g.addColorStop(1, CHROME.glowOut);
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, 7);
  ctx.fill();
}
function drawWorker(
  ctx: CanvasRenderingContext2D,
  w: Worker,
  goal: Goal | undefined,
  name: string,
  frameIdx: number,
  scale: number,
  u: number, // chrome unit: = scale full-size, floored in compact so text stays legible
  showSay: boolean,
) {
  const cv = w.frames[frameIdx];
  const bob = WALK_BOB[frameIdx] || 0;
  const dx = Math.round(w.x * scale), dy = Math.round((w.y + bob) * scale);
  // soft shadow
  ctx.globalAlpha = 0.18;
  ctx.fillStyle = CHROME.shadow;
  ctx.beginPath();
  ctx.ellipse(dx + 6 * scale, dy + 16 * scale, 7 * scale, 2.4 * scale, 0, 0, 7);
  ctx.fill();
  ctx.globalAlpha = 1;
  const top = dy - 2 * scale; // sprite top edge in canvas px
  blit(ctx, cv, dx, top, scale, w.facingLeft);
  // name tag — anchored just above the head; state carried as a text mark
  // (✓ done / ! error), never by color alone
  const tag = goal?.state === "done" ? `${name} ✓` : goal?.state === "error" ? `${name} !` : name;
  const tagFont = `600 ${2.75 * u}px ${FONT}`;
  ctx.font = tagFont;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const tw = measure(ctx, tag, tagFont), cx = dx + 6 * scale, tagY = top - 4.25 * u;
  ctx.fillStyle = CHROME.tagBg;
  ctx.fillRect(cx - tw / 2 - u, tagY, tw + 2 * u, 3.75 * u);
  ctx.fillStyle = CHROME.tagText;
  ctx.fillText(tag, cx, tagY + 0.75 * u);
  // speech bubble once arrived — short, fun, informative
  const arrived = w.x === w.target.x && w.y === w.target.y;
  const say = arrived && showSay ? goal?.say : null;
  if (say) {
    const sayFont = `600 ${2.5 * u}px ${FONT}`;
    ctx.font = sayFont;
    const sw = measure(ctx, say, sayFont) + 3 * u, by = tagY - 5.25 * u, bx = cx - sw / 2;
    ctx.fillStyle = CHROME.bubbleBg;
    ctx.fillRect(bx, by, sw, 4.25 * u);
    ctx.beginPath();
    ctx.moveTo(cx - 0.75 * u, by + 4.25 * u);
    ctx.lineTo(cx + 0.75 * u, by + 4.25 * u);
    ctx.lineTo(cx, by + 5.25 * u);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = CHROME.bubbleText;
    ctx.fillText(say, cx, by + u);
  }
}

/** Everything the render loop needs, kept in one mutable ref (no stale closures). */
interface StageState {
  goals: Goals;
  scale: number;
  dpr: number;
  ground: HTMLCanvasElement | null;
  groundKey: string;
  workers: Map<string, Worker>;
  spriteCache: Map<string, HTMLCanvasElement[]>;
  reduced: boolean;
  compact: boolean;
  /** False while the stage is scrolled out of view — the rAF loop pauses. */
  onscreen: boolean;
}

/** Full frame paint at time `t` (seconds) / `ts` (ms, drives the leg cycle). */
function paintStage(s: StageState, canvas: HTMLCanvasElement | null, ts: number, t: number) {
  if (!canvas || !s.ground || !s.scale) return;
  const ctx = canvas.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(s.ground, 0, 0);
  if (!s.reduced) drawDecorAnim(ctx, t, s.scale);
  for (const name of s.goals.hot) {
    const def = stationDef(name);
    glow(ctx, def.sx, def.sy - 2, s.scale);
  }
  // station labels (hot ones highlighted) on top of the glow — full size only;
  // at zone scale they'd be noise, and the furniture already reads
  if (!s.compact) {
    for (const def of STATION_DEFS) {
      labelChip(ctx, def.label, def.fcx, def.lbl ?? Math.max(3, def.ftop - 13), s.goals.hot.has(def.label), s.scale);
    }
  }
  // compact keeps name tags legible by flooring the chrome unit
  const u = s.compact ? Math.max(s.scale, COMPACT_TAG_UNIT * s.dpr) : s.scale;
  const order = [...s.workers.entries()].sort((a, b) => a[1].y - b[1].y);
  for (const [name, w] of order) {
    const moving = w.x !== w.target.x || w.y !== w.target.y;
    drawWorker(ctx, w, s.goals.byName.get(name), name, moving && !s.reduced ? Math.floor(ts / 120) % 4 : 0, s.scale, u, !s.compact);
  }
}

/** Rebake the static ground if scale or the home-desk layout changed. */
function rebake(s: StageState) {
  const key = `${s.scale}|${s.goals.homes.map((h) => `${h.x},${h.y}`).join(";")}`;
  if (key !== s.groundKey && s.scale > 0) {
    s.ground = bakeGround(s.scale, s.goals.homes);
    s.groundKey = key;
  }
}

/** Spawn/remove/retarget workers to match goals; teleport when motion is reduced. */
function syncWorkers(s: StageState) {
  const names = new Set<string>();
  for (const g of s.goals.agents) {
    names.add(g.name);
    let w = s.workers.get(g.name);
    if (!w) {
      let frames = s.spriteCache.get(g.name);
      if (!frames) {
        frames = WALK.map((f) => rasterize(f, colorway(g.name)));
        s.spriteCache.set(g.name, frames);
      }
      w = { x: g.home.x, y: g.home.y, facingLeft: false, speed: 0, target: g.home, frames };
      s.workers.set(g.name, w);
    }
    if (g.target.x !== w.target.x || g.target.y !== w.target.y) {
      w.target = g.target;
      const d = Math.hypot(w.target.x - w.x, w.target.y - w.y);
      w.speed = Math.min(600, Math.max(30, d / WALK_S)); // adaptive px/s
    }
    if (s.reduced) {
      w.x = w.target.x;
      w.y = w.target.y;
    }
  }
  for (const name of [...s.workers.keys()]) if (!names.has(name)) s.workers.delete(name);
}

interface OfficeStageProps {
  nodes: GraphNode[];
  /** Small tiled rendering for the Floor's run-zones (fewer/smaller labels). */
  compact?: boolean;
}

export function OfficeStage({ nodes, compact = false }: OfficeStageProps) {
  const goals = useMemo(() => computeGoals(nodes), [nodes]);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const st = useRef<StageState>({
    goals,
    scale: 0,
    dpr: 0,
    ground: null,
    groundKey: "",
    workers: new Map(),
    spriteCache: new Map(),
    reduced: false,
    compact,
    onscreen: true,
  });

  // Mount: reduced-motion tracking, integer device-pixel sizing, the rAF loop.
  useEffect(() => {
    const s = st.current, wrap = wrapRef.current, canvas = canvasRef.current;
    if (!wrap || !canvas) return;

    let raf = 0, last: number | null = null, t0: number | null = null;
    const tick = (ts: number) => {
      if (t0 === null) t0 = ts;
      const dt = last === null ? 0 : Math.min((ts - last) / 1000, 0.1);
      last = ts;
      for (const w of st.current.workers.values()) {
        const dx = w.target.x - w.x, dy = w.target.y - w.y, d = Math.hypot(dx, dy);
        const step = w.speed * dt;
        if (d > step && d > 0.01) {
          w.x += (dx / d) * step;
          w.y += (dy / d) * step;
          if (Math.abs(dx) > 0.4) w.facingLeft = dx < 0;
        } else {
          w.x = w.target.x;
          w.y = w.target.y;
        }
      }
      paintStage(s, canvas, ts, (ts - t0) / 1000);
      raf = requestAnimationFrame(tick);
    };
    const stopLoop = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      last = null;
    };
    const startLoop = () => {
      if (!raf) raf = requestAnimationFrame(tick);
    };

    // The loop runs only when motion is allowed AND the stage is on screen
    // (offscreen Floor zones would otherwise keep repainting — browsers only
    // pause rAF for hidden *tabs*, not scrolled-out elements).
    const updateLoop = () => {
      if (s.reduced || !s.onscreen) {
        stopLoop();
        if (s.reduced) {
          syncWorkers(s); // teleport everyone to their targets
          paintStage(s, canvas, 0, 0);
        }
      } else {
        startLoop();
      }
    };
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const applyMotion = () => {
      s.reduced = mq.matches;
      updateLoop();
    };
    mq.addEventListener("change", applyMotion);
    const io = new IntersectionObserver(([entry]) => {
      s.onscreen = entry.isIntersecting;
      updateLoop();
    });
    io.observe(wrap);

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = wrap.clientWidth, h = wrap.clientHeight;
      if (!w || !h) return;
      const scale = Math.max(1, Math.min(Math.floor((w * dpr) / RW), Math.floor((h * dpr) / RH), MAX_SCALE));
      if (scale === s.scale && dpr === s.dpr) return;
      s.scale = scale;
      s.dpr = dpr;
      canvas.width = RW * scale;
      canvas.height = RH * scale;
      canvas.style.width = `${(RW * scale) / dpr}px`;
      canvas.style.height = `${(RH * scale) / dpr}px`;
      rebake(s);
      paintStage(s, canvas, 0, 0);
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

  // Data changes: install the new goals, keep the ground + cast in sync, and
  // repaint immediately when the loop isn't running (reduced motion).
  useEffect(() => {
    const s = st.current;
    s.goals = goals;
    s.compact = compact;
    rebake(s);
    syncWorkers(s);
    if (s.reduced) paintStage(s, canvasRef.current, 0, 0);
  }, [goals, compact]);

  return (
    <div ref={wrapRef} className={`office-stage${compact ? " office-stage--compact" : ""}`}>
      <canvas ref={canvasRef} className="sprite" role="img" aria-label={goals.label} />
      {goals.agents.length === 0 && <div className="vt-empty">No agents yet…</div>}
    </div>
  );
}
