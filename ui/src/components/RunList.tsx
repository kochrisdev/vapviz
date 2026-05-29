import { useEffect } from "react";
import { GitCompare, X } from "lucide-react";
import type { NodeStatus, RunSummary } from "../types/events";
import { useRunStore } from "../store/runStore";

const STATUS_DOT: Record<NodeStatus, string> = {
  pending: "bg-slate-400",
  running: "bg-amber-400 animate-pulse",
  success: "bg-green-400",
  error:   "bg-red-400",
};

function fmt(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString();
}

function fmtCost(usd: number): string {
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 0.01)   return `$${usd.toFixed(6)}`;
  return `$${usd.toFixed(4)}`;
}

interface Props {
  onSelect: (runId: string) => void;
}

export function RunList({ onSelect }: Props) {
  const runs          = useRunStore((s) => s.runs);
  const selectedRunId = useRunStore((s) => s.selectedRunId);
  const compareRunId  = useRunStore((s) => s.compareRunId);
  const setRuns       = useRunStore((s) => s.setRuns);
  const setCompareRun = useRunStore((s) => s.setCompareRun);

  useEffect(() => {
    const load = () =>
      fetch("/runs")
        .then((r) => r.json())
        .then((data: RunSummary[]) => setRuns(data))
        .catch(() => {});
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, [setRuns]);

  return (
    <div className="flex flex-col h-full bg-slate-900 border-r border-slate-700">
      <div className="px-4 py-3 text-xs text-slate-400 uppercase tracking-wider border-b border-slate-700 font-semibold">
        Runs
      </div>
      <div className="flex-1 overflow-y-auto">
        {runs.map((run) => {
          const isSelected  = run.run_id === selectedRunId;
          const isCompare   = run.run_id === compareRunId;
          const canCompare  = !isSelected && selectedRunId !== null;

          return (
            <div
              key={run.run_id}
              className={`group relative border-b border-slate-800 transition-colors ${
                isSelected
                  ? "bg-slate-800 border-l-2 border-l-indigo-500"
                  : isCompare
                  ? "bg-slate-800/60 border-l-2 border-l-amber-500"
                  : "hover:bg-slate-800/50"
              }`}
            >
              <button
                onClick={() => onSelect(run.run_id)}
                className="w-full text-left px-4 py-3 pr-10"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`h-2 w-2 rounded-full shrink-0 ${STATUS_DOT[run.status]}`} />
                  <span className="text-sm font-medium text-slate-200 truncate">{run.label}</span>
                </div>
                <div className="text-xs text-slate-500 flex gap-3 flex-wrap">
                  <span>{fmt(run.started_at)}</span>
                  <span>{run.node_count} nodes</span>
                  <span>{run.event_count} events</span>
                  {run.total_cost_usd != null && (
                    <span className="text-purple-400 font-medium">
                      {fmtCost(run.total_cost_usd)}
                    </span>
                  )}
                </div>
              </button>

              {/* Compare button — visible on hover (or when this run is the compare target) */}
              {canCompare && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setCompareRun(isCompare ? null : run.run_id);
                  }}
                  title={isCompare ? "Cancel comparison" : "Compare with selected run"}
                  className={`absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded transition-colors ${
                    isCompare
                      ? "text-amber-400 hover:text-amber-200 opacity-100"
                      : "text-slate-600 hover:text-slate-300 opacity-0 group-hover:opacity-100"
                  }`}
                >
                  {isCompare ? <X size={14} /> : <GitCompare size={14} />}
                </button>
              )}
            </div>
          );
        })}
        {runs.length === 0 && (
          <div className="px-4 py-8 text-slate-500 text-sm text-center">
            No runs yet. Start an agent to see traces here.
          </div>
        )}
      </div>

      {/* Comparison mode banner */}
      {compareRunId && selectedRunId && (
        <div className="px-3 py-2 border-t border-amber-900/50 bg-amber-950/30 text-xs text-amber-300 flex items-center gap-2">
          <GitCompare size={12} />
          Comparison mode active
        </div>
      )}
    </div>
  );
}
