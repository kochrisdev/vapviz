import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Coffee, Drama, Pause, Play, Siren, Square, X, type LucideIcon } from "lucide-react";
import type { GraphNode, NodeStatus, RunSummary } from "../types/events";
import { controlUiState, type ControlAction, type ControlDesired } from "../lib/runControl";
import { OfficeStage } from "./OfficeStage";
import { LoungeStage } from "./LoungeStage";
import { FloorEnv } from "./FloorEnv";
import { useRunStore } from "../store/runStore";
import { formatCost } from "../lib/format";
import {
  WalkEngine,
  type Pt,
  type Lane,
  type LifeSpec,
} from "../lib/walkOverlay";
import {
  buildBuilding,
  pruneDismissed,
  type AppRoom,
  type Building,
} from "../lib/building";

/**
 * Office Building view (UI-ROADMAP §4-J, Phase 4b) — the *visual* building.
 * The Floor is re-keyed from run instances to APPS: app = room, agent = desk.
 *
 * Each floor is a 2×3 room grid around a central Walk Way, with a Door
 * (top-right) / Stairs (bottom-right) column and, on the top floor's right, a
 * shared Lounge (solid east wall + windows below it). A failed app's home room
 * stays put and turns red while its agents "gather" in the lounge; clears on
 * re-run or manual Dismiss. When the top floor fills, the earliest app descends
 * a floor (lib/building.ts owns the placement algorithm).
 *
 * Live by polling the existing endpoints (no backend change): `/runs` for the
 * roster, `/runs/{id}/graph` for each visible room's nodes.
 */

const POLL_MS = 1500;
const DISMISS_KEY = "vapviz.dismissed"; // failed run_ids cleared from the lounge

function loadDismissed(): Set<string> {
  try {
    const raw = window.localStorage.getItem(DISMISS_KEY);
    const arr: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function saveDismissed(ids: Set<string>) {
  try {
    window.localStorage.setItem(DISMISS_KEY, JSON.stringify([...ids]));
  } catch {
    /* storage full/blocked — dismissals stay session-only */
  }
}

const DOT: Record<NodeStatus, string> = {
  running: "bg-status-running animate-pulse",
  success: "bg-status-success",
  error: "bg-status-error",
  pending: "bg-status-pending",
  stopped: "bg-status-stopped",
};

const CTL_ICON: Record<ControlAction, LucideIcon> = { pause: Pause, resume: Play, stop: Square };
const CTL_LABEL: Record<ControlAction, string> = { pause: "Pause", resume: "Resume", stop: "Stop" };

/** A floor room: an app's home. Renders its current run's office diorama, plus
 *  (for a running app) hover-revealed pause/resume/stop controls — the same
 *  cooperative control as the Theater bar, without leaving the floor view. */
function RoomTile({
  slot,
  room,
  nodes,
  onOpen,
  control,
  onControl,
}: {
  slot: number;
  room: AppRoom;
  nodes: GraphNode[];
  onOpen: () => void;
  control?: { desired: string; acked: string; waiting_for_input?: boolean };
  onControl?: (action: ControlAction) => void;
}) {
  const side = slot < 3 ? "bottom" : "top";
  const needsInput = room.status === "running" && !!control?.waiting_for_input;
  // Reuse the Theater bar's pure state machine so the buttons + pausing…/stopping…
  // disabling behave identically here (message-inject stays Theater-only).
  const ctl =
    room.status === "running" && onControl
      ? controlUiState(
          (control?.desired ?? "running") as ControlDesired,
          (control?.acked ?? "running") as ControlDesired,
          "running",
        )
      : null;
  return (
    <div
      className={`vt-room group relative ${room.status === "error" ? "vt-room--error" : ""}`}
      data-appkey={room.appKey}
      style={{ gridArea: `r${slot}` }}
    >
      <button onClick={onOpen} title="Open this app's current run in Theater" className="w-full text-left">
        <div className="vt-room-stage">
          <OfficeStage nodes={nodes} compact />
        </div>
      </button>
      {/* Run control (§ ride-along B): sibling of the open-in-Theater button (not
          nested — valid HTML), on top, revealed on hover/focus of the room. */}
      {ctl && (
        <div
          className="absolute top-1 right-1 z-10 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
          role="group"
          aria-label={`Control ${room.label}`}
        >
          {ctl.buttons.map(({ action, disabled }) => {
            const Icon = CTL_ICON[action];
            return (
              <button
                key={action}
                onClick={() => onControl!(action)}
                disabled={disabled}
                title={`${CTL_LABEL[action]} ${room.label}`}
                aria-label={`${CTL_LABEL[action]} ${room.label}`}
                className={`grid place-items-center w-[18px] h-[18px] border-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                  action === "stop"
                    ? "border-status-error/50 text-status-error bg-surface-inset/90 hover:bg-status-error/20"
                    : "border-border-strong text-content bg-surface-inset/90 hover:bg-surface-hover"
                }`}
              >
                <Icon size={11} />
              </button>
            );
          })}
        </div>
      )}
      {/* Needs-input nudge (Layer 2b): the agent is blocked in ask()/take_input().
          Always visible (not hover-gated) — it's a call to act; click through to
          Theater to answer in the chat panel. */}
      {needsInput && (
        <button
          onClick={onOpen}
          title={`${room.label} is waiting for your input — open in Theater to reply`}
          aria-label={`${room.label} needs your input`}
          className="absolute top-1 left-1 z-10 flex items-center gap-1 px-1.5 py-0.5 border-2 border-status-running bg-surface-inset/90 text-status-running px-display text-[8px] animate-pulse"
        >
          💬 needs input
        </button>
      )}
      {/* Door on the Walk-Way-facing edge (§4-K): where floor-life walkers step
          out. Top-row rooms open downward, bottom-row rooms upward. Its rect is
          the walker's spawn/return anchor (captured as roomdoor:<appKey>); the
          visible opening is drawn by the FloorEnv canvas (§4-L). */}
      <span
        className={`vt-room-door vt-room-door--${side}`}
        data-roomdoor={room.appKey}
        aria-hidden="true"
      />
      {/* Nameplate (§4-L): signage on the corridor wall beside the door — art-
          styled plate, crisp DOM text (app names are arbitrary strings). */}
      <span className={`vt-plate vt-plate--${side}`}>
        <span className={`vt-led ${DOT[room.status]}`} />
        <span className="vt-plate-name">{room.label}</span>
        {room.runCount > 1 && <span className="vt-plate-n">×{room.runCount}</span>}
      </span>
    </div>
  );
}

/** A failed app waiting in the lounge — inspect (click) or dismiss. */
function LoungeCard({
  room,
  onOpen,
  onDismiss,
}: {
  room: AppRoom;
  onOpen: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="vt-lounge-card" data-lounge={room.appKey}>
      <button onClick={onOpen} title="Inspect the failed run" className="vt-lounge-open">
        <Siren size={11} className="text-status-error shrink-0" />
        <span className="text-[11px] font-semibold text-content truncate">{room.label}</span>
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDismiss();
        }}
        title="Dismiss — clears this failure until the app runs again"
        className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-full border border-status-error/40 text-status-error hover:bg-status-error/15 transition-colors shrink-0"
      >
        <X size={8} /> Dismiss
      </button>
    </div>
  );
}

type LocalRect = { x: number; y: number; w: number; h: number };

/** Building-local rects of every room (by appKey) + per-floor door/stairs/walkway
 *  + the lounge — captured before/after an update to drive the walk overlay. */
function snapshot(el: HTMLElement): Map<string, LocalRect> {
  const m = new Map<string, LocalRect>();
  const b = el.getBoundingClientRect();
  const put = (key: string, r: DOMRect) =>
    m.set(key, { x: r.left - b.left, y: r.top - b.top, w: r.width, h: r.height });
  el.querySelectorAll<HTMLElement>("[data-appkey]").forEach((e) =>
    put(`room:${e.dataset.appkey}`, e.getBoundingClientRect())
  );
  el.querySelectorAll<HTMLElement>("[data-roomdoor]").forEach((e) =>
    put(`roomdoor:${e.dataset.roomdoor}`, e.getBoundingClientRect())
  );
  el.querySelectorAll<HTMLElement>("[data-floor]").forEach((f) => {
    const fi = f.dataset.floor;
    const q = (sel: string, key: string) => {
      const c = f.querySelector(sel);
      if (c) put(key, c.getBoundingClientRect());
    };
    q(".vt-door", `door:${fi}`);
    q(".vt-stairs", `stairs:${fi}`);
    q(".vt-walkway", `walk:${fi}`);
  });
  const lounge = el.querySelector(".vt-lounge");
  if (lounge) put("lounge", lounge.getBoundingClientRect());
  return m;
}

const rectCenter = (r: LocalRect): Pt => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 });

/** appKey → floor index, for diffing placements between ticks. */
function floorOf(b: Building): Map<string, number> {
  const m = new Map<string, number>();
  b.floors.forEach((f) => f.rooms.forEach((r) => r && m.set(r.appKey, f.index)));
  return m;
}

/** Spawn overlay walkers for the transitions between `oldB` and `newB`: an app
 *  that descended a floor (vanish-at-stairs / reappear-at-door), and an app that
 *  just failed (its home room stays put; one coworker walks up to the lounge).
 *  Returns the appKeys given a walker, so the FLIP fallback skips them. */
function spawnTransitions(
  oldB: Building,
  newB: Building,
  first: Map<string, LocalRect>, // pre-render rects (old positions)
  now: Map<string, LocalRect>, // post-render rects (new positions)
  engine: WalkEngine
): Set<string> {
  const animated = new Set<string>();
  const oldPos = floorOf(oldB);
  const newPos = floorOf(newB);
  const oldLounge = new Set(oldB.lounge.map((r) => r.appKey));

  // descents — old room → walkway → stairs (VANISH) → door below → walkway → new room
  for (const [app, nf] of newPos) {
    const of = oldPos.get(app);
    if (of === undefined || nf <= of) continue;
    const start = first.get(`room:${app}`);
    const stairs = now.get(`stairs:${of}`);
    const walkFrom = now.get(`walk:${of}`);
    const door = now.get(`door:${nf}`);
    const walkTo = now.get(`walk:${nf}`);
    const end = now.get(`room:${app}`);
    if (!start || !stairs || !walkFrom || !door || !walkTo || !end) continue;
    const s = rectCenter(start);
    const st = rectCenter(stairs);
    const dr = rectCenter(door);
    const e = rectCenter(end);
    const yFrom = rectCenter(walkFrom).y;
    const yTo = rectCenter(walkTo).y;
    engine.spawn(
      app,
      [
        s,
        { x: s.x, y: yFrom },
        { x: st.x, y: yFrom },
        st, // enter the stairs…
        dr, // …and reappear at the door below — segment 3 (stairs→door) is hidden
        { x: dr.x, y: yTo },
        { x: e.x, y: yTo },
        e,
      ],
      3
    );
    animated.add(app);
  }

  // failures — the room stays put (red); one coworker walks up to the lounge
  for (const room of newB.lounge) {
    if (oldLounge.has(room.appKey)) continue;
    const start = now.get(`room:${room.appKey}`);
    const lounge = now.get("lounge");
    if (!start || !lounge) continue;
    const s = rectCenter(start);
    const l = rectCenter(lounge);
    const floor = newPos.get(room.appKey);
    const walk = floor !== undefined ? now.get(`walk:${floor}`) : undefined;
    const yWalk = walk ? rectCenter(walk).y : s.y;
    engine.spawn(room.appKey, [s, { x: s.x, y: yWalk }, { x: l.x, y: yWalk }, l], -1);
    animated.add(room.appKey);
  }
  return animated;
}

/** Derive the floor-life inputs (§4-K, honest-only since §4-L) from the current
 *  Building + fresh rects: one honest walker per RUNNING room. A room's door +
 *  its floor's Walk Way must both be measured. */
function floorLife(b: Building, rects: Map<string, LocalRect>): LifeSpec[] {
  const busy: LifeSpec[] = [];
  for (const floor of b.floors) {
    const walk = rects.get(`walk:${floor.index}`);
    if (!walk) continue;
    const floorId = `f${floor.index}`;
    const lane: Lane = { y: walk.y + walk.h / 2, x0: walk.x, x1: walk.x + walk.w };
    for (const r of floor.rooms) {
      if (!r || r.status !== "running") continue;
      const d = rects.get(`roomdoor:${r.appKey}`);
      if (d) busy.push({ key: r.appKey, floorId, door: rectCenter(d), lane });
    }
  }
  return busy;
}

export function BuildingView() {
  const selectRun = useRunStore((s) => s.selectRun);
  const [building, setBuilding] = useState<Building | null>(null);
  const [nodesByRun, setNodesByRun] = useState<Record<string, GraphNode[]>>({});
  const [controlByRun, setControlByRun] = useState<
    Record<string, { desired: string; acked: string; waiting_for_input?: boolean }>
  >({});
  const [costToday, setCostToday] = useState(0);
  const [loaded, setLoaded] = useState(false);

  const prevRef = useRef<Building | null>(null); // room stickiness across ticks
  const dismissedRef = useRef<Set<string>>(loadDismissed());
  const lastRunsRef = useRef<RunSummary[]>([]);

  // Walk overlay (§4-J) + FLIP fallback. Right before a building update we
  // capture (First) the building-local rects + the old Building; after the
  // re-render the walk engine animates descents (room → Walk Way → Stairs,
  // vanish, Door below → room) and failures (room → lounge). Rooms the overlay
  // didn't animate fall back to the FLIP glide; reduced motion snaps everything.
  const bodyRef = useRef<HTMLDivElement>(null);
  const buildingElRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<WalkEngine | null>(null);
  const firstRects = useRef<Map<string, DOMRect>>(new Map());
  const firstSnap = useRef<Map<string, LocalRect> | null>(null);
  const animPrev = useRef<Building | null>(null);

  const captureRects = () => {
    const rects = new Map<string, DOMRect>();
    bodyRef.current
      ?.querySelectorAll<HTMLElement>("[data-appkey]")
      .forEach((el) => rects.set(el.dataset.appkey!, el.getBoundingClientRect()));
    firstRects.current = rects;
    firstSnap.current = buildingElRef.current ? snapshot(buildingElRef.current) : null;
    animPrev.current = prevRef.current;
  };

  // Engine lifecycle: create once the building box exists; keep the overlay
  // canvas sized to it (floors grow/shrink) and track reduced-motion live.
  // useLayoutEffect (not useEffect) so the engine exists before the poll-driven
  // animation layout effect below runs on the first building commit — else
  // floor life would be skipped until the next poll. On unmount, clearAll()
  // stops the rAF loop (residents keep it alive, so it won't self-terminate).
  useLayoutEffect(() => {
    const el = buildingElRef.current;
    const cv = overlayRef.current;
    if (!el || !cv) return;
    const engine = (engineRef.current ??= new WalkEngine(cv));
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const applyMotion = () => engine.setReduced(mq.matches);
    applyMotion();
    mq.addEventListener("change", applyMotion);
    const ro = new ResizeObserver(() =>
      engine.resize(el.clientWidth, el.clientHeight, window.devicePixelRatio || 1)
    );
    ro.observe(el);
    return () => {
      ro.disconnect();
      mq.removeEventListener("change", applyMotion);
      engine.clearAll();
    };
  }, [building === null]);

  useLayoutEffect(() => {
    const first = firstRects.current;
    const firstLocal = firstSnap.current;
    const oldB = animPrev.current;
    firstRects.current = new Map();
    firstSnap.current = null;
    animPrev.current = null;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return; // snap
    // walkers for descents + failures, plus the persistent floor-life layer
    let animated = new Set<string>();
    const engine = engineRef.current;
    const el = buildingElRef.current;
    if (engine && el && building) {
      const now = snapshot(el);
      if (oldB && firstLocal) animated = spawnTransitions(oldB, building, firstLocal, now, engine);
      engine.reconcileFloorLife(floorLife(building, now));
    }
    // FLIP glide for any moved room the overlay didn't take
    if (!first.size) return;
    bodyRef.current?.querySelectorAll<HTMLElement>("[data-appkey]").forEach((roomEl) => {
      const key = roomEl.dataset.appkey!;
      if (animated.has(key)) return;
      const prev = first.get(key);
      if (!prev) return;
      const next = roomEl.getBoundingClientRect();
      const dx = prev.left - next.left;
      const dy = prev.top - next.top;
      if (dx || dy)
        roomEl.animate(
          [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "translate(0, 0)" }],
          { duration: 450, easing: "cubic-bezier(0.25, 0.1, 0.25, 1)" }
        );
    });
  }, [building]);

  useEffect(() => {
    let alive = true;
    let pruned = false;
    const cache = new Map<string, GraphNode[]>(); // finished-run graphs don't change

    async function tick() {
      try {
        const runs: RunSummary[] = await fetch("/runs").then((r) => r.json());
        lastRunsRef.current = runs;

        // prune-on-load: drop dismissals whose run left the roster (bounded list)
        if (!pruned) {
          dismissedRef.current = pruneDismissed(dismissedRef.current, runs);
          saveDismissed(dismissedRef.current);
          pruned = true;
        }

        const next = buildBuilding(runs, prevRef.current, dismissedRef.current);

        const visible = [
          ...next.lounge,
          ...next.floors.flatMap((f) => f.rooms.filter((r): r is AppRoom => r !== null)),
        ];
        const graphs: Record<string, GraphNode[]> = {};
        const controls: Record<string, { desired: string; acked: string; waiting_for_input?: boolean }> = {};
        await Promise.all(
          visible.map(async (room) => {
            const id = room.currentRunId;
            if (room.status !== "running" && cache.has(id)) {
              graphs[id] = cache.get(id)!;
              return; // finished run: cached graph, no live control to poll
            }
            try {
              const g = await fetch(`/runs/${id}/graph`).then((r) => r.json());
              graphs[id] = g.nodes as GraphNode[];
              if (room.status !== "running") cache.set(id, graphs[id]);
            } catch {
              graphs[id] = cache.get(id) ?? [];
            }
            // Control latch — only for a live (running) room; powers the tile's
            // hover pause/stop controls + the "needs input" nudge badge (L2b).
            if (room.status === "running") {
              try {
                const c = await fetch(`/runs/${id}/control`).then((r) => r.json());
                controls[id] = {
                  desired: c.desired,
                  acked: c.acked,
                  waiting_for_input: !!c.waiting_for_input,
                };
              } catch {
                /* transient — the tile falls back to defaults (Pause/Stop) */
              }
            }
          })
        );

        if (alive) {
          captureRects();
          prevRef.current = next;
          setBuilding(next);
          setNodesByRun(graphs);
          setControlByRun(controls);
          setCostToday(runs.reduce((s, r) => s + (r.total_cost_usd ?? 0), 0));
          setLoaded(true);
        }
      } catch {
        /* transient — keep the last good building */
      }
    }

    tick();
    const t = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const dismiss = (room: AppRoom) => {
    dismissedRef.current = new Set([...dismissedRef.current, room.currentRunId]);
    saveDismissed(dismissedRef.current);
    const next = buildBuilding(lastRunsRef.current, prevRef.current, dismissedRef.current);
    captureRects();
    prevRef.current = next;
    setBuilding(next);
  };

  // Pause/resume/stop a running app's room from the floor (ride-along B). Same
  // cooperative endpoint as the Theater bar; optimistic, then the poll reconciles.
  const sendRoomControl = async (runId: string, action: ControlAction) => {
    const optimistic: ControlDesired =
      action === "pause" ? "paused" : action === "resume" ? "running" : "stopped";
    setControlByRun((p) => ({
      ...p,
      [runId]: { desired: optimistic, acked: p[runId]?.acked ?? "running" },
    }));
    try {
      await fetch(`/runs/${runId}/control`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
    } catch {
      /* transient — the next poll reconciles */
    }
  };

  const floors = building?.floors ?? [];
  const lounge = building?.lounge ?? [];
  const active = floors
    .flatMap((f) => f.rooms)
    .filter((r) => r?.status === "running").length;
  const isEmpty = lounge.length === 0 && floors.every((f) => f.rooms.every((r) => r === null));
  const costStr = formatCost(costToday);

  return (
    <div className="flex-1 min-w-0 flex flex-col min-h-0">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-surface shrink-0">
        <Drama size={16} className="text-accent" />
        <span className="font-semibold text-content">Office building</span>
        <span className="text-xs text-content-muted">
          {active > 0 ? `${active} app${active > 1 ? "s" : ""} working now` : "watching for activity"}
        </span>
        {lounge.length > 0 && (
          <span className="flex items-center gap-1 text-xs text-status-error">
            <Siren size={12} />
            {lounge.length} in the lounge
          </span>
        )}
      </div>

      <div ref={bodyRef} className="vt-yard flex-1 min-h-0 overflow-auto">
        {building && (
          <div className="vt-building" ref={buildingElRef}>
            <canvas ref={overlayRef} className="vt-walk-overlay sprite" aria-hidden="true" />
            <div className="vt-roof">
              <span className="vt-sign">VAPVIZ</span>
            </div>

            {/* Floors, top-down; the tag counts down like a real building */}
            {floors.map((floor) => (
              <div className="vt-floor" data-floor={floor.index} key={floor.index}>
                {/* The environment canvas (§4-L): corridor tiles, walls + door
                    openings, props — drawn under the rooms from measured rects. */}
                <FloorEnv
                  sig={`${floor.rooms.map((r) => (r ? r.appKey : "·")).join("|")}#${floor.index === 0 ? "L" : "E"}`}
                />
                <div className="vt-floor-tag">{floors.length - floor.index}F</div>

                {floor.rooms.map((room, i) =>
                  room ? (
                    <RoomTile
                      key={room.appKey}
                      slot={i}
                      room={room}
                      nodes={nodesByRun[room.currentRunId] ?? []}
                      onOpen={() => selectRun(room.currentRunId, "theater")}
                      control={controlByRun[room.currentRunId]}
                      onControl={(action) => sendRoomControl(room.currentRunId, action)}
                    />
                  ) : (
                    <div
                      key={`empty-${floor.index}-${i}`}
                      className="vt-room vt-room--empty"
                      data-doorside={i < 3 ? "bottom" : "top"}
                      style={{ gridArea: `r${i}` }}
                    >
                      <div className="vt-room-stage" />
                    </div>
                  )
                )}

                {/* Walk Way / Door / Stairs — layout anchors; visuals live on
                    the FloorEnv canvas (corridor rug + lights, alcove icons). */}
                <div className="vt-walkway" />
                <div className="vt-door" role="img" aria-label="Door" />
                <div className="vt-stairs" role="img" aria-label="Stairs" />

                {/* East column: the shared lounge on the top floor, solid wall below. */}
                {floor.index === 0 ? (
                  <div className="vt-lounge">
                    <div className="vt-lounge-head">
                      <Coffee size={11} /> Lounge
                    </div>
                    <LoungeStage apps={lounge.map((r) => ({ id: r.appKey, label: r.label }))} />
                    {lounge.length > 0 && (
                      <div className="vt-lounge-cards">
                        {lounge.map((room) => (
                          <LoungeCard
                            key={room.appKey}
                            room={room}
                            onOpen={() => selectRun(room.currentRunId)}
                            onDismiss={() => dismiss(room)}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  /* anchor only — the wall + windows are drawn by FloorEnv */
                  <div className="vt-eastwall" />
                )}
              </div>
            ))}

            {/* Lobby — building base + live directory board (also empty-state home) */}
            <div className="vt-lobby">
              {loaded && isEmpty ? (
                <div className="vt-directory">
                  <b>VAPVIZ</b>
                  <span className="vt-dir-sep">·</span>
                  <span>No runs yet — start an agent and its app gets a room here.</span>
                </div>
              ) : (
                <div className="vt-directory">
                  <b>VAPVIZ</b>
                  <span className="vt-dir-sep">·</span>
                  <span>
                    <b>{active}</b> app{active === 1 ? "" : "s"} working
                  </span>
                  <span className="vt-dir-sep">·</span>
                  <span>
                    <b>{lounge.length}</b> in the lounge
                  </span>
                  {costStr && (
                    <>
                      <span className="vt-dir-sep">·</span>
                      <span>
                        <b>{costStr}</b> today
                      </span>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
