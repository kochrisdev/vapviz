import { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { Activity, BookOpen, History, Network, ScrollText } from "lucide-react";
import { AgentGraph } from "./components/AgentGraph";
import { Dashboard } from "./components/Dashboard";
import { LogsView } from "./components/LogsView";
import { ExportMenu } from "./components/ExportMenu";
import { NodeDetail } from "./components/NodeDetail";
import { ReplayBar } from "./components/ReplayBar";
import { RunComparison } from "./components/RunComparison";
import { ModeToggle } from "./components/ModeToggle";
import { RunList } from "./components/RunList";
import { StatusBadge } from "./components/StatusBadge";
import { StoryView } from "./components/StoryView";
import { TagEditor } from "./components/TagEditor";
import { buildGraphAt } from "./lib/replay";
import { useRunStream } from "./hooks/useRunStream";
import { useRunStore } from "./store/runStore";

type RunTab = "story" | "graph" | "logs";

function RunViewer() {
  const selectedRunId = useRunStore((s) => s.selectedRunId);
  const compareRunId = useRunStore((s) => s.compareRunId);
  const runStates = useRunStore((s) => s.runStates);
  const selectedNodeId = useRunStore((s) => s.selectedNodeId);
  const runs = useRunStore((s) => s.runs);
  const view = useRunStore((s) => s.view);
  const mode = useRunStore((s) => s.mode);
  const selectRun = useRunStore((s) => s.selectRun);
  const selectNode = useRunStore((s) => s.selectNode);
  const setCompareRun = useRunStore((s) => s.setCompareRun);

  const technical = mode === "technical";

  const streamStatus = useRunStream(selectedRunId);

  const state = selectedRunId ? runStates[selectedRunId] : null;
  const selectedNode = state?.nodes.find((n) => n.id === selectedNodeId) ?? null;

  // Per-run tab — Story is the default legible view.
  const [tab, setTab] = useState<RunTab>("story");
  // Graph "Simplified" hides framework-internal nodes (default on).
  const [graphSimplified, setGraphSimplified] = useState(true);

  // Replay / time-travel: null = live view; a number = events applied so far.
  const [replayIndex, setReplayIndex] = useState<number | null>(null);
  const [replayPlaying, setReplayPlaying] = useState(false);

  // Reset tab + replay when the selected run changes.
  useEffect(() => {
    setTab("story");
    setReplayIndex(null);
    setReplayPlaying(false);
  }, [selectedRunId]);

  // The graph to render: live nodes/edges, or a partial graph during replay.
  const replayGraph = useMemo(
    () => (state && replayIndex !== null ? buildGraphAt(state.events, replayIndex) : null),
    [state, replayIndex]
  );
  const shownNodes = replayGraph ? replayGraph.nodes : state?.nodes ?? [];
  const shownEdges = replayGraph ? replayGraph.edges : state?.edges ?? [];

  // Ref passed to ExportMenu for PNG capture
  const graphRef = useRef<HTMLDivElement>(null);

  // Labels for comparison header
  const labelA = runs.find((r) => r.run_id === selectedRunId)?.label ?? selectedRunId ?? "";
  const labelB = runs.find((r) => r.run_id === compareRunId)?.label ?? compareRunId ?? "";

  // Escape key: close node detail panel
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") selectNode(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [selectNode]);

  return (
    <div className="flex h-screen bg-bg text-content overflow-hidden">
      {/* Sidebar — global mode switch + run list */}
      <div className="w-64 shrink-0 flex flex-col">
        <ModeToggle />
        <RunList onSelect={selectRun} />
      </div>

      {/* Main area */}
      {view === "dashboard" ? (
        <Dashboard />
      ) : compareRunId && selectedRunId ? (
        <RunComparison
          runIdA={selectedRunId}
          runIdB={compareRunId}
          labelA={labelA}
          labelB={labelB}
          onClose={() => setCompareRun(null)}
        />
      ) : state ? (
        <>
          {/* Run column */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Header bar */}
            <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-surface shrink-0">
              <span className="font-semibold text-content truncate">{state.label}</span>
              <StatusBadge status={state.status} />
              {streamStatus === "reconnecting" && (
                <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-medium bg-status-running/15 text-status-running border border-status-running/30 animate-pulse">
                  reconnecting…
                </span>
              )}

              {/* Tabs + technical controls — Technical mode only */}
              {technical && (
                <>
                  <div className="flex items-center gap-1 bg-surface-inset rounded-lg p-1">
                    <TabButton active={tab === "story"} onClick={() => setTab("story")} icon={BookOpen}>
                      Story
                    </TabButton>
                    <TabButton active={tab === "graph"} onClick={() => setTab("graph")} icon={Network}>
                      Graph
                    </TabButton>
                    <TabButton active={tab === "logs"} onClick={() => setTab("logs")} icon={ScrollText}>
                      Logs
                    </TabButton>
                  </div>

                  <div className="border-l border-border pl-3">
                    <TagEditor
                      runId={selectedRunId!}
                      tags={runs.find((r) => r.run_id === selectedRunId)?.tags ?? []}
                    />
                  </div>
                  <div className="ml-auto flex items-center gap-2">
                    {tab === "graph" && (
                      <>
                        {/* Simplified | Detailed toggle */}
                        <div className="flex items-center gap-0.5 bg-surface-inset rounded-lg p-0.5">
                          <button
                            onClick={() => setGraphSimplified(true)}
                            className={`text-xs font-medium px-2 py-1 rounded-md transition-colors ${
                              graphSimplified ? "bg-surface text-content shadow-sm" : "text-content-faint hover:text-content"
                            }`}
                            title="Hide framework-internal nodes"
                          >
                            Simplified
                          </button>
                          <button
                            onClick={() => setGraphSimplified(false)}
                            className={`text-xs font-medium px-2 py-1 rounded-md transition-colors ${
                              !graphSimplified ? "bg-surface text-content shadow-sm" : "text-content-faint hover:text-content"
                            }`}
                            title="Show every node"
                          >
                            Detailed
                          </button>
                        </div>
                        <button
                          onClick={() => setReplayIndex(replayIndex === null ? state.events.length : null)}
                          title="Replay this run event by event"
                          className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded transition-colors ${
                            replayIndex !== null
                              ? "bg-accent/15 text-accent"
                              : "text-content-faint hover:text-content hover:bg-surface-hover"
                          }`}
                        >
                          <History size={13} /> Replay
                        </button>
                      </>
                    )}
                    <ExportMenu runId={selectedRunId!} label={state.label} graphContainerRef={graphRef} />
                  </div>
                </>
              )}
            </div>

            {/* Body — Simple mode is narrative-only; Technical unlocks tabs */}
            {!technical || tab === "story" ? (
              <StoryView state={state} />
            ) : tab === "logs" ? (
              <LogsView events={state.events} startedAt={state.started_at ?? 0} />
            ) : (
              <div className="flex-1 min-w-0 flex flex-col min-h-0">
                <div className="flex-1 min-h-0" ref={graphRef}>
                  <ReactFlowProvider>
                    <AgentGraph graphNodes={shownNodes} graphEdges={shownEdges} simplified={graphSimplified} />
                  </ReactFlowProvider>
                </div>
                {replayIndex !== null && (
                  <ReplayBar
                    events={state.events}
                    startedAt={state.started_at ?? 0}
                    index={replayIndex}
                    setIndex={setReplayIndex}
                    playing={replayPlaying}
                    setPlaying={setReplayPlaying}
                    onExit={() => {
                      setReplayIndex(null);
                      setReplayPlaying(false);
                    }}
                  />
                )}
              </div>
            )}
          </div>

          {/* Node detail panel */}
          {selectedNode && (
            <div className="w-72 shrink-0">
              <NodeDetail node={selectedNode} technical={technical} />
            </div>
          )}
        </>
      ) : (
        /* ── Empty state ───────────────────────────────────────── */
        <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-8">
          <div className="h-14 w-14 rounded-2xl bg-accent/10 border border-accent/20 flex items-center justify-center">
            <Activity size={26} className="text-accent" />
          </div>
          <div>
            <p className="text-content font-medium mb-1">No run selected</p>
            <p className="text-content-faint text-sm leading-relaxed max-w-xs">
              Pick a run from the sidebar, or start an agent with{" "}
              <code className="bg-surface-inset text-content-muted px-1 py-0.5 rounded text-xs">
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

function TabButton({
  active,
  onClick,
  icon: Icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof BookOpen;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 text-sm font-semibold px-3 py-1.5 rounded-md transition-colors ${
        active
          ? "bg-accent text-content-on-accent shadow-sm"
          : "text-content-muted hover:text-content hover:bg-surface-hover"
      }`}
    >
      <Icon size={15} /> {children}
    </button>
  );
}

export default RunViewer;
