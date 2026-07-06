import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Drama, Siren, X } from "lucide-react";
import type { GraphNode, NodeStatus, RunSummary } from "../types/events";
import { OfficeStage } from "./OfficeStage";
import { useRunStore } from "../store/runStore";
import {
  buildBuilding,
  pruneDismissed,
  type AppRoom,
  type Building,
} from "../lib/building";

/**
 * Office Building view (UI-ROADMAP §4-I, Phase 4a) — the Floor re-keyed from
 * run instances to APPS: app = room, agent = desk. Floors hold 6 rooms; when
 * the top floor is full the earliest app descends a floor (lib/building.ts
 * owns the placement algorithm). Apps whose current run failed are pulled
 * into the red incident hall at the top — inspect (click) or dismiss.
 *
 * Live by polling the existing endpoints (no backend change): `/runs` for the
 * roster, `/runs/{id}/graph` for each visible room's nodes.
 */

const POLL_MS = 1500;
const DISMISS_KEY = "vapviz.dismissed"; // failed run_ids cleared from the hall

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
};

interface RoomTileProps {
  room: AppRoom;
  nodes: GraphNode[];
  hall?: boolean;
  onOpen: () => void;
  onDismiss?: () => void;
}

function RoomTile({ room, nodes, hall, onOpen, onDismiss }: RoomTileProps) {
  return (
    <div className={`vt-room ${hall ? "vt-room--hall" : ""} group relative`} data-appkey={room.appKey}>
      <button
        onClick={onOpen}
        title={hall ? "Inspect the failed run" : "Open this app's current run"}
        className="w-full text-left"
      >
        <div className="flex items-center gap-2 px-1 pb-1">
          <span className={`w-2 h-2 rounded-full shrink-0 ${DOT[room.status]}`} />
          <span className="text-xs font-semibold text-content-muted truncate">{room.label}</span>
          {room.runCount > 1 && (
            <span className="text-[10px] text-content-faint shrink-0 tabular-nums">
              ×{room.runCount}
            </span>
          )}
        </div>
        <div className="vt-room-stage">
          <OfficeStage nodes={nodes} compact />
        </div>
      </button>
      {hall && onDismiss && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDismiss();
          }}
          title="Dismiss — clears this failure until the app runs again"
          className="absolute right-2 top-1 flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border border-status-error/40 text-status-error bg-surface/70 hover:bg-status-error/15 transition-colors"
        >
          <X size={9} /> Dismiss
        </button>
      )}
    </div>
  );
}

export function BuildingView() {
  const selectRun = useRunStore((s) => s.selectRun);
  const [building, setBuilding] = useState<Building | null>(null);
  const [nodesByRun, setNodesByRun] = useState<Record<string, GraphNode[]>>({});
  const [loaded, setLoaded] = useState(false);

  const prevRef = useRef<Building | null>(null); // room stickiness across ticks
  const dismissedRef = useRef<Set<string>>(loadDismissed());
  const lastRunsRef = useRef<RunSummary[]>([]);

  // FLIP glide: capture each room's rect (First) right before a building
  // update, then animate from the delta (Invert→Play) after the re-render, so
  // a descending room glides to its new floor instead of teleporting.
  const bodyRef = useRef<HTMLDivElement>(null);
  const firstRects = useRef<Map<string, DOMRect>>(new Map());

  const captureRects = () => {
    const rects = new Map<string, DOMRect>();
    bodyRef.current
      ?.querySelectorAll<HTMLElement>("[data-appkey]")
      .forEach((el) => rects.set(el.dataset.appkey!, el.getBoundingClientRect()));
    firstRects.current = rects;
  };

  useLayoutEffect(() => {
    const first = firstRects.current;
    firstRects.current = new Map();
    if (!first.size || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    bodyRef.current?.querySelectorAll<HTMLElement>("[data-appkey]").forEach((el) => {
      const prev = first.get(el.dataset.appkey!);
      if (!prev) return;
      const next = el.getBoundingClientRect();
      const dx = prev.left - next.left;
      const dy = prev.top - next.top;
      if (dx || dy)
        el.animate(
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
          ...next.incidentHall,
          ...next.floors.flatMap((f) => f.rooms.filter((r): r is AppRoom => r !== null)),
        ];
        const graphs: Record<string, GraphNode[]> = {};
        await Promise.all(
          visible.map(async (room) => {
            const id = room.currentRunId;
            if (room.status !== "running" && cache.has(id)) {
              graphs[id] = cache.get(id)!;
              return;
            }
            try {
              const g = await fetch(`/runs/${id}/graph`).then((r) => r.json());
              graphs[id] = g.nodes as GraphNode[];
              if (room.status !== "running") cache.set(id, graphs[id]);
            } catch {
              graphs[id] = cache.get(id) ?? [];
            }
          })
        );

        if (alive) {
          captureRects();
          prevRef.current = next;
          setBuilding(next);
          setNodesByRun(graphs);
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

  const floors = building?.floors ?? [];
  const hall = building?.incidentHall ?? [];
  const active = floors
    .flatMap((f) => f.rooms)
    .filter((r) => r?.status === "running").length;
  const isEmpty = hall.length === 0 && floors.every((f) => f.rooms.every((r) => r === null));

  return (
    <div className="flex-1 min-w-0 flex flex-col min-h-0">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-surface shrink-0">
        <Drama size={16} className="text-accent" />
        <span className="font-semibold text-content">Office building</span>
        <span className="text-xs text-content-muted">
          {active > 0 ? `${active} app${active > 1 ? "s" : ""} working now` : "watching for activity"}
        </span>
        {hall.length > 0 && (
          <span className="flex items-center gap-1 text-xs text-status-error">
            <Siren size={12} />
            {hall.length} incident{hall.length > 1 ? "s" : ""}
          </span>
        )}
      </div>

      <div className="vt-floor flex-1 min-h-0 overflow-auto">
        {loaded && isEmpty ? (
          <div className="h-full grid place-items-center text-content-faint text-sm">
            No runs yet — start an agent and its app will get a room here.
          </div>
        ) : (
          <div className="vt-building">
            {/* Incident hall — top of the building, extra (never one of the 6 slots) */}
            {hall.length > 0 && (
              <div className="vt-hall">
                <div className="flex items-center gap-1.5 px-1 pb-2 text-[11px] font-semibold uppercase tracking-wider text-status-error">
                  <Siren size={11} /> Incident hall
                </div>
                <div className="flex flex-wrap gap-3">
                  {hall.map((room) => (
                    <RoomTile
                      key={room.appKey}
                      room={room}
                      nodes={nodesByRun[room.currentRunId] ?? []}
                      hall
                      onOpen={() => selectRun(room.currentRunId)}
                      onDismiss={() => dismiss(room)}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Floors, top-down; the tag counts down like a real building */}
            {floors.map((floor) => (
              <div className="vt-floor-row" key={floor.index}>
                <div className="vt-floor-tag">{floors.length - floor.index}F</div>
                {floor.rooms.map((room, i) =>
                  room ? (
                    <RoomTile
                      key={room.appKey}
                      room={room}
                      nodes={nodesByRun[room.currentRunId] ?? []}
                      onOpen={() => selectRun(room.currentRunId)}
                    />
                  ) : (
                    <div key={`empty-${floor.index}-${i}`} className="vt-room vt-room--empty">
                      <div className="vt-room-stage" />
                    </div>
                  )
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
