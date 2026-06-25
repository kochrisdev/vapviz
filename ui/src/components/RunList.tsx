import { useEffect, useState } from "react";
import { BarChart3, Drama, GitCompare, Moon, Search, Sun, Tag, Trash2, X } from "lucide-react";
import type { NodeStatus, RunSummary } from "../types/events";
import { useRunStore } from "../store/runStore";
import { runSubtitle } from "../lib/summary";
import { useTheme } from "../lib/theme";

const STATUS_DOT: Record<NodeStatus, { token: string; pulse?: boolean }> = {
  pending: { token: "--status-pending" },
  running: { token: "--status-running", pulse: true },
  success: { token: "--status-success" },
  error: { token: "--status-error" },
};

function fmt(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString();
}

interface Props {
  onSelect: (runId: string | null) => void;
}

export function RunList({ onSelect }: Props) {
  const runs = useRunStore((s) => s.runs);
  const selectedRunId = useRunStore((s) => s.selectedRunId);
  const compareRunId = useRunStore((s) => s.compareRunId);
  const setRuns = useRunStore((s) => s.setRuns);
  const setCompareRun = useRunStore((s) => s.setCompareRun);
  const view = useRunStore((s) => s.view);
  const setView = useRunStore((s) => s.setView);
  const { theme, toggle } = useTheme();

  const [search, setSearch] = useState("");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  // run_ids matching a content search, or null when no search is active
  const [matchIds, setMatchIds] = useState<Set<string> | null>(null);

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

  // Content search — query the backend (searches labels + node inputs/outputs), debounced.
  useEffect(() => {
    const q = search.trim();
    if (!q) {
      setMatchIds(null);
      return;
    }
    const handle = setTimeout(() => {
      fetch(`/search?q=${encodeURIComponent(q)}`)
        .then((r) => r.json())
        .then((data: RunSummary[]) => setMatchIds(new Set(data.map((r) => r.run_id))))
        .catch(() => setMatchIds(new Set()));
    }, 250);
    return () => clearTimeout(handle);
  }, [search]);

  const handleDelete = async (run: RunSummary, e: React.MouseEvent) => {
    e.stopPropagation();
    await fetch(`/runs/${run.run_id}`, { method: "DELETE" }).catch(() => {});
    const next = runs.filter((r) => r.run_id !== run.run_id);
    setRuns(next);
    if (selectedRunId === run.run_id) onSelect(null);
    if (compareRunId === run.run_id) setCompareRun(null);
  };

  const filtered = runs.filter((r) => {
    if (matchIds !== null && !matchIds.has(r.run_id)) return false;
    if (tagFilter !== null && !r.tags.includes(tagFilter)) return false;
    return true;
  });

  return (
    <div className="flex flex-col h-full bg-surface border-r border-border">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <span className="text-xs text-content-muted uppercase tracking-wider font-semibold">Runs</span>
        <div className="flex items-center gap-2">
          {runs.length > 0 && (
            <span className="text-[10px] bg-surface-hover text-content-muted px-1.5 py-0.5 rounded-full min-w-[20px] text-center">
              {runs.length}
            </span>
          )}
          <button
            onClick={toggle}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            className="p-1 rounded text-content-faint hover:text-content transition-colors"
          >
            {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
          </button>
          <button
            onClick={() => setView(view === "floor" ? "runs" : "floor")}
            title="Live floor — all agents working"
            className={`p-1 rounded transition-colors ${
              view === "floor" ? "text-accent bg-accent/10" : "text-content-faint hover:text-content"
            }`}
          >
            <Drama size={14} />
          </button>
          <button
            onClick={() => setView(view === "dashboard" ? "runs" : "dashboard")}
            title="Analytics dashboard"
            className={`p-1 rounded transition-colors ${
              view === "dashboard" ? "text-accent bg-accent/10" : "text-content-faint hover:text-content"
            }`}
          >
            <BarChart3 size={14} />
          </button>
        </div>
      </div>

      {/* Search — searches run labels and node inputs/outputs */}
      {runs.length > 0 && (
        <div className="px-3 py-2 border-b border-border shrink-0 space-y-2">
          <div className="flex items-center gap-2 bg-surface-inset rounded px-2 py-1.5">
            <Search size={11} className="text-content-faint shrink-0" />
            <input
              type="text"
              placeholder="Search runs & contents…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-transparent text-xs text-content placeholder-content-faint outline-none w-full"
            />
            {search && (
              <button onClick={() => setSearch("")} className="text-content-faint hover:text-content shrink-0">
                <X size={10} />
              </button>
            )}
          </div>
          {tagFilter !== null && (
            <button
              onClick={() => setTagFilter(null)}
              className="flex items-center gap-1 text-[10px] bg-accent/15 text-accent border border-accent/30 px-2 py-0.5 rounded-full hover:bg-accent/25"
            >
              <Tag size={9} /> {tagFilter} <X size={9} />
            </button>
          )}
        </div>
      )}

      {/* Run list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.map((run) => {
          const isSelected = run.run_id === selectedRunId;
          const isCompare = run.run_id === compareRunId;
          const canCompare = !isSelected && selectedRunId !== null;
          const dot = STATUS_DOT[run.status];

          return (
            <div
              key={run.run_id}
              className={`group relative border-b border-border/60 transition-colors ${
                isSelected
                  ? "bg-surface-hover border-l-2 border-l-accent"
                  : isCompare
                  ? "bg-surface-hover/60 border-l-2 border-l-status-running"
                  : "hover:bg-surface-hover/60"
              }`}
            >
              <button onClick={() => onSelect(run.run_id)} className="w-full text-left px-4 py-3 pr-16">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`h-2 w-2 rounded-full shrink-0 ${dot.pulse ? "animate-pulse" : ""}`}
                    style={{ background: `rgb(var(${dot.token}))` }}
                  />
                  <span className="text-sm font-medium text-content truncate">{run.label}</span>
                </div>
                {/* Plain-language subtitle — rich summary from the backend,
                    falling back to a count-based line for unsummarized runs. */}
                <div className="text-xs text-content-muted line-clamp-2">
                  {run.summary || runSubtitle(run)}
                </div>
                <div className="text-[11px] text-content-faint mt-0.5">{fmt(run.started_at)}</div>
                {run.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {run.tags.map((t) => (
                      <span
                        key={t}
                        role="button"
                        tabIndex={0}
                        onClick={(e) => {
                          e.stopPropagation();
                          setTagFilter(t);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.stopPropagation();
                            setTagFilter(t);
                          }
                        }}
                        className={`text-[9px] px-1.5 py-0.5 rounded-full border cursor-pointer transition-colors ${
                          tagFilter === t
                            ? "bg-accent/25 text-accent border-accent/40"
                            : "bg-surface-hover text-content-faint border-border hover:text-accent hover:border-accent/40"
                        }`}
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </button>

              {/* Action buttons — revealed on hover */}
              <div className="absolute right-2 top-3 flex items-center gap-0.5">
                {canCompare && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setCompareRun(isCompare ? null : run.run_id);
                    }}
                    title={isCompare ? "Cancel comparison" : "Compare with selected run"}
                    className={`p-1.5 rounded transition-colors ${
                      isCompare
                        ? "text-status-running opacity-100"
                        : "text-content-faint hover:text-content opacity-0 group-hover:opacity-100"
                    }`}
                  >
                    {isCompare ? <X size={13} /> : <GitCompare size={13} />}
                  </button>
                )}
                <button
                  onClick={(e) => handleDelete(run, e)}
                  title="Delete run"
                  className="p-1.5 rounded text-content-faint hover:text-status-error opacity-0 group-hover:opacity-100 transition-colors"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          );
        })}

        {filtered.length === 0 && (
          <div className="px-4 py-8 text-content-faint text-sm text-center leading-relaxed whitespace-pre-line">
            {runs.length === 0
              ? "No runs yet.\nStart an agent to see traces here."
              : tagFilter !== null
              ? `No runs tagged "${tagFilter}".`
              : `No runs matching "${search}".`}
          </div>
        )}
      </div>

      {/* Comparison mode banner */}
      {compareRunId && selectedRunId && (
        <div className="px-3 py-2 border-t border-status-running/40 bg-status-running/10 text-xs text-status-running flex items-center gap-2 shrink-0">
          <GitCompare size={12} />
          Comparison mode active
        </div>
      )}
    </div>
  );
}
