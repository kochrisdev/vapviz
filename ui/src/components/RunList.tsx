import { useEffect } from "react";
import type { NodeStatus, RunSummary } from "../types/events";
import { useRunStore } from "../store/runStore";

const STATUS_DOT: Record<NodeStatus, string> = {
  pending: "bg-slate-400",
  running: "bg-amber-400 animate-pulse",
  success: "bg-green-400",
  error: "bg-red-400",
};

function fmt(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString();
}

interface Props {
  onSelect: (runId: string) => void;
}

export function RunList({ onSelect }: Props) {
  const runs = useRunStore((s) => s.runs);
  const selectedRunId = useRunStore((s) => s.selectedRunId);
  const setRuns = useRunStore((s) => s.setRuns);

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
        {runs.map((run) => (
          <button
            key={run.run_id}
            onClick={() => onSelect(run.run_id)}
            className={`w-full text-left px-4 py-3 border-b border-slate-800 hover:bg-slate-800 transition-colors ${
              selectedRunId === run.run_id ? "bg-slate-800 border-l-2 border-l-indigo-500" : ""
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className={`h-2 w-2 rounded-full shrink-0 ${STATUS_DOT[run.status]}`} />
              <span className="text-sm font-medium text-slate-200 truncate">{run.label}</span>
            </div>
            <div className="text-xs text-slate-500 flex gap-3">
              <span>{fmt(run.started_at)}</span>
              <span>{run.node_count} nodes</span>
              <span>{run.event_count} events</span>
            </div>
          </button>
        ))}
        {runs.length === 0 && (
          <div className="px-4 py-8 text-slate-500 text-sm text-center">
            No runs yet. Start an agent to see traces here.
          </div>
        )}
      </div>
    </div>
  );
}
