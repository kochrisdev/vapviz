import { useEffect, useState } from "react";
import { Drama } from "lucide-react";
import type { GraphNode, NodeStatus, RunSummary } from "../types/events";
import { OfficeStage } from "./OfficeStage";
import { useRunStore } from "../store/runStore";

/**
 * Global Floor view (UI-ROADMAP Phase 3) — the centralized monitor: one open
 * office floor where every active (and most-recent) run is a soft labeled
 * *zone*, each a compact sprite office (`OfficeStage`, the same engine as the
 * Theater) with its own desks and walking workers. You watch all your agents
 * working across the floor at once; click a zone to drill into that run's
 * full Theater.
 *
 * Live by polling the existing endpoints (no backend change): `/runs` for the
 * roster + status, `/runs/{id}/graph` for each run's nodes.
 */

const MAX_RUNS = 9;
const POLL_MS = 1500;

interface FloorRun {
  run: RunSummary;
  nodes: GraphNode[];
}

const DOT: Record<NodeStatus, string> = {
  running: "bg-status-running animate-pulse",
  success: "bg-status-success",
  error: "bg-status-error",
  pending: "bg-status-pending",
};

export function FloorView() {
  const selectRun = useRunStore((s) => s.selectRun);
  const [floor, setFloor] = useState<FloorRun[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    const cache = new Map<string, GraphNode[]>(); // finished-run graphs don't change

    async function tick() {
      try {
        const runs: RunSummary[] = await fetch("/runs").then((r) => r.json());
        const sorted = [...runs]
          .sort((a, b) => {
            const ar = a.status === "running" ? 1 : 0;
            const br = b.status === "running" ? 1 : 0;
            if (ar !== br) return br - ar; // running first
            return (b.started_at ?? 0) - (a.started_at ?? 0); // then newest
          })
          .slice(0, MAX_RUNS);

        const result: FloorRun[] = [];
        for (const run of sorted) {
          let nodes: GraphNode[] | undefined;
          if (run.status === "running" || !cache.has(run.run_id)) {
            try {
              const g = await fetch(`/runs/${run.run_id}/graph`).then((r) => r.json());
              nodes = g.nodes as GraphNode[];
              if (run.status !== "running") cache.set(run.run_id, nodes);
            } catch {
              nodes = cache.get(run.run_id);
            }
          } else {
            nodes = cache.get(run.run_id);
          }
          result.push({ run, nodes: nodes ?? [] });
        }
        if (alive) {
          setFloor(result);
          setLoaded(true);
        }
      } catch {
        /* transient — keep last good floor */
      }
    }

    tick();
    const t = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const active = floor.filter((f) => f.run.status === "running").length;

  return (
    <div className="flex-1 min-w-0 flex flex-col min-h-0">
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-surface shrink-0">
        <Drama size={16} className="text-accent" />
        <span className="font-semibold text-content">Live floor</span>
        <span className="text-xs text-content-muted">
          {active > 0 ? `${active} run${active > 1 ? "s" : ""} working now` : "watching for activity"}
        </span>
      </div>

      <div className="vt-floor flex-1 min-h-0 overflow-auto">
        {loaded && floor.length === 0 ? (
          <div className="h-full grid place-items-center text-content-faint text-sm">
            No runs yet — start an agent and its cast will appear here.
          </div>
        ) : (
          <div className="flex flex-wrap gap-5 content-start">
            {floor.map(({ run, nodes }) => (
              <button
                key={run.run_id}
                onClick={() => selectRun(run.run_id)}
                title="Open this run's Theater"
                className="vt-zone text-left"
              >
                <div className="flex items-center gap-2 px-1 pb-1">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${DOT[run.status]}`} />
                  <span className="text-xs font-semibold text-content-muted truncate max-w-[280px]">
                    {run.label}
                  </span>
                </div>
                <div className="vt-zone-stage">
                  <OfficeStage nodes={nodes} compact />
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
