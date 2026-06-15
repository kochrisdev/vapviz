import { useEffect, useState } from "react";
import { BarChart3, GitCompare, Search, Trash2, X } from "lucide-react";
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

function fmtDur(started: number, ended: number | null): string | null {
  if (!ended) return null;
  const ms = (ended - started) * 1000;
  return ms < 1000 ? `${ms.toFixed(0)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

interface Props {
  onSelect: (runId: string | null) => void;
}

export function RunList({ onSelect }: Props) {
  const runs          = useRunStore((s) => s.runs);
  const selectedRunId = useRunStore((s) => s.selectedRunId);
  const compareRunId  = useRunStore((s) => s.compareRunId);
  const setRuns       = useRunStore((s) => s.setRuns);
  const setCompareRun = useRunStore((s) => s.setCompareRun);
  const view          = useRunStore((s) => s.view);
  const setView       = useRunStore((s) => s.setView);
  const [search, setSearch] = useState("");

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

  const handleDelete = async (run: RunSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    await fetch(`/runs/${run.run_id}`, { method: "DELETE" }).catch(() => {});
    const next = runs.filter((r) => r.run_id !== run.run_id);
    setRuns(next);
    if (selectedRunId === run.run_id) onSelect(null);
    if (compareRunId  === run.run_id) setCompareRun(null);
  };

  const filtered = search
    ? runs.filter((r) => r.label.toLowerCase().includes(search.toLowerCase()))
    : runs;

  return (
    <div className="flex flex-col h-full bg-slate-900 border-r border-slate-700">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 shrink-0">
        <span className="text-xs text-slate-400 uppercase tracking-wider font-semibold">Runs</span>
        <div className="flex items-center gap-2">
          {runs.length > 0 && (
            <span className="text-[10px] bg-slate-700 text-slate-400 px-1.5 py-0.5 rounded-full min-w-[20px] text-center">
              {runs.length}
            </span>
          )}
          <button
            onClick={() => setView(view === "dashboard" ? "runs" : "dashboard")}
            title="Analytics dashboard"
            className={`p-1 rounded transition-colors ${
              view === "dashboard"
                ? "text-indigo-400 bg-indigo-500/10"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <BarChart3 size={14} />
          </button>
        </div>
      </div>

      {/* Search — only shown once there are enough runs to need it */}
      {runs.length > 3 && (
        <div className="px-3 py-2 border-b border-slate-800 shrink-0">
          <div className="flex items-center gap-2 bg-slate-800 rounded px-2 py-1.5">
            <Search size={11} className="text-slate-500 shrink-0" />
            <input
              type="text"
              placeholder="Filter runs…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-transparent text-xs text-slate-300 placeholder-slate-600 outline-none w-full"
            />
            {search && (
              <button onClick={() => setSearch("")} className="text-slate-500 hover:text-slate-300 shrink-0">
                <X size={10} />
              </button>
            )}
          </div>
        </div>
      )}

      {/* Run list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.map((run) => {
          const isSelected = run.run_id === selectedRunId;
          const isCompare  = run.run_id === compareRunId;
          const canCompare = !isSelected && selectedRunId !== null;
          const dur        = fmtDur(run.started_at, run.ended_at);

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
                className="w-full text-left px-4 py-3 pr-16"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`h-2 w-2 rounded-full shrink-0 ${STATUS_DOT[run.status]}`} />
                  <span className="text-sm font-medium text-slate-200 truncate">{run.label}</span>
                </div>
                <div className="text-xs text-slate-500 flex gap-2.5 flex-wrap">
                  <span>{fmt(run.started_at)}</span>
                  {dur && <span className="text-slate-400 font-medium">{dur}</span>}
                  <span>{run.node_count} nodes</span>
                  {run.total_cost_usd != null && (
                    <span className="text-purple-400 font-medium">{fmtCost(run.total_cost_usd)}</span>
                  )}
                </div>
              </button>

              {/* Action buttons — revealed on hover */}
              <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
                {canCompare && (
                  <button
                    onClick={(e) => { e.stopPropagation(); setCompareRun(isCompare ? null : run.run_id); }}
                    title={isCompare ? "Cancel comparison" : "Compare with selected run"}
                    className={`p-1.5 rounded transition-colors ${
                      isCompare
                        ? "text-amber-400 hover:text-amber-200 opacity-100"
                        : "text-slate-600 hover:text-slate-300 opacity-0 group-hover:opacity-100"
                    }`}
                  >
                    {isCompare ? <X size={13} /> : <GitCompare size={13} />}
                  </button>
                )}
                <button
                  onClick={(e) => handleDelete(run, e)}
                  title="Delete run"
                  className="p-1.5 rounded text-slate-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-colors"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          );
        })}

        {filtered.length === 0 && (
          <div className="px-4 py-8 text-slate-500 text-sm text-center leading-relaxed">
            {runs.length === 0
              ? "No runs yet.\nStart an agent to see traces here."
              : `No runs matching "${search}".`}
          </div>
        )}
      </div>

      {/* Comparison mode banner */}
      {compareRunId && selectedRunId && (
        <div className="px-3 py-2 border-t border-amber-900/50 bg-amber-950/30 text-xs text-amber-300 flex items-center gap-2 shrink-0">
          <GitCompare size={12} />
          Comparison mode active
        </div>
      )}
    </div>
  );
}
