import { useEffect, useRef } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { Activity } from "lucide-react";
import { AgentGraph } from "./components/AgentGraph";
import { Dashboard } from "./components/Dashboard";
import { EventTimeline } from "./components/EventTimeline";
import { ExportMenu } from "./components/ExportMenu";
import { NodeDetail } from "./components/NodeDetail";
import { RunComparison } from "./components/RunComparison";
import { RunList } from "./components/RunList";
import { useRunStream } from "./hooks/useRunStream";
import { useRunStore } from "./store/runStore";

function RunViewer() {
  const selectedRunId  = useRunStore((s) => s.selectedRunId);
  const compareRunId   = useRunStore((s) => s.compareRunId);
  const runStates      = useRunStore((s) => s.runStates);
  const selectedNodeId = useRunStore((s) => s.selectedNodeId);
  const runs           = useRunStore((s) => s.runs);
  const view           = useRunStore((s) => s.view);
  const selectRun      = useRunStore((s) => s.selectRun);
  const selectNode     = useRunStore((s) => s.selectNode);
  const setCompareRun  = useRunStore((s) => s.setCompareRun);

  useRunStream(selectedRunId);

  const state        = selectedRunId ? runStates[selectedRunId] : null;
  const selectedNode = state?.nodes.find((n) => n.id === selectedNodeId) ?? null;

  // Ref passed to ExportMenu for PNG capture
  const graphRef = useRef<HTMLDivElement>(null);

  // Labels for comparison header
  const labelA = runs.find((r) => r.run_id === selectedRunId)?.label ?? selectedRunId ?? "";
  const labelB = runs.find((r) => r.run_id === compareRunId)?.label  ?? compareRunId  ?? "";

  // Escape key: close node detail panel
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") selectNode(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectNode]);

  return (
    <div className="flex h-screen bg-slate-950 text-white overflow-hidden">
      {/* Sidebar — run list */}
      <div className="w-64 shrink-0 flex flex-col">
        <RunList onSelect={selectRun} />
      </div>

      {/* Main area */}
      {view === "dashboard" ? (
        /* ── Analytics dashboard ───────────────────────────────── */
        <Dashboard />
      ) : compareRunId && selectedRunId ? (
        /* ── Comparison mode ───────────────────────────────────── */
        <RunComparison
          runIdA={selectedRunId}
          runIdB={compareRunId}
          labelA={labelA}
          labelB={labelB}
          onClose={() => setCompareRun(null)}
        />
      ) : state ? (
        /* ── Normal run view ───────────────────────────────────── */
        <>
          {/* Graph column */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Header bar */}
            <div className="flex items-center gap-3 px-4 py-2 border-b border-slate-700 bg-slate-900 shrink-0">
              <span className="font-semibold text-slate-100 truncate">{state.label}</span>
              <StatusBadge status={state.status} />
              {state.started_at && state.ended_at && (
                <span className="text-xs text-slate-400 font-mono tabular-nums">
                  {((state.ended_at - state.started_at) * 1000).toFixed(0)} ms
                </span>
              )}
              <div className="ml-auto">
                <ExportMenu
                  runId={selectedRunId!}
                  label={state.label}
                  graphContainerRef={graphRef}
                />
              </div>
            </div>

            <div className="flex flex-1 min-h-0">
              {/* Graph canvas */}
              <div className="flex-1 min-w-0" ref={graphRef}>
                <ReactFlowProvider>
                  <AgentGraph graphNodes={state.nodes} graphEdges={state.edges} />
                </ReactFlowProvider>
              </div>

              {/* Timeline panel */}
              <div className="w-64 shrink-0 border-l border-slate-700">
                <EventTimeline events={state.events} startedAt={state.started_at ?? 0} />
              </div>
            </div>
          </div>

          {/* Node detail panel */}
          {selectedNode && (
            <div className="w-72 shrink-0">
              <NodeDetail node={selectedNode} />
            </div>
          )}
        </>
      ) : (
        /* ── Empty state ───────────────────────────────────────── */
        <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-8">
          <div className="h-14 w-14 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
            <Activity size={26} className="text-indigo-400" />
          </div>
          <div>
            <p className="text-slate-300 font-medium mb-1">No run selected</p>
            <p className="text-slate-500 text-sm leading-relaxed max-w-xs">
              Pick a run from the sidebar, or start an agent with{" "}
              <code className="bg-slate-800 text-slate-300 px-1 py-0.5 rounded text-xs">
                python examples/simple_demo.py
              </code>{" "}
              to see a live trace.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "running"
      ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
      : status === "success"
      ? "bg-green-500/20 text-green-300 border border-green-500/30"
      : status === "error"
      ? "bg-red-500/20 text-red-300 border border-red-500/30"
      : "bg-slate-500/20 text-slate-300 border border-slate-500/30";
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${cls}`}>
      {status}
    </span>
  );
}

export default RunViewer;
