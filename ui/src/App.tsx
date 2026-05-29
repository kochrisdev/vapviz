import { useRef } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { AgentGraph } from "./components/AgentGraph";
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
  const selectRun      = useRunStore((s) => s.selectRun);
  const setCompareRun  = useRunStore((s) => s.setCompareRun);

  useRunStream(selectedRunId);

  const state        = selectedRunId ? runStates[selectedRunId] : null;
  const selectedNode = state?.nodes.find((n) => n.id === selectedNodeId) ?? null;

  // Ref passed to ExportMenu for PNG capture
  const graphRef = useRef<HTMLDivElement>(null);

  // Labels for comparison header
  const labelA = runs.find((r) => r.run_id === selectedRunId)?.label ?? selectedRunId ?? "";
  const labelB = runs.find((r) => r.run_id === compareRunId)?.label ?? compareRunId ?? "";

  return (
    <div className="flex h-screen bg-slate-950 text-white overflow-hidden">
      {/* Sidebar — run list */}
      <div className="w-64 shrink-0 flex flex-col">
        <RunList onSelect={selectRun} />
      </div>

      {/* Main area */}
      {compareRunId && selectedRunId ? (
        /* ── Comparison mode ─────────────────────────────────────── */
        <RunComparison
          runIdA={selectedRunId}
          runIdB={compareRunId}
          labelA={labelA}
          labelB={labelB}
          onClose={() => setCompareRun(null)}
        />
      ) : state ? (
        /* ── Normal run view ─────────────────────────────────────── */
        <>
          {/* Graph column */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Header */}
            <div className="flex items-center gap-3 px-4 py-2 border-b border-slate-700 bg-slate-900 shrink-0">
              <span className="font-semibold text-slate-100">{state.label}</span>
              <StatusBadge status={state.status} />
              {state.started_at && state.ended_at && (
                <span className="text-xs text-slate-400">
                  {((state.ended_at - state.started_at) * 1000).toFixed(0)} ms total
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
        /* ── Empty state ─────────────────────────────────────────── */
        <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
          Select a run from the sidebar
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "running"
      ? "bg-amber-500/20 text-amber-300"
      : status === "success"
      ? "bg-green-500/20 text-green-300"
      : status === "error"
      ? "bg-red-500/20 text-red-300"
      : "bg-slate-500/20 text-slate-300";
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>{status}</span>
  );
}

export default RunViewer;
