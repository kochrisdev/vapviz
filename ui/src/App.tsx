import { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { Activity, BookOpen, Drama, History, Network, ScrollText } from "lucide-react";
import { AgentGraph } from "./components/AgentGraph";
import { TheaterView } from "./components/TheaterView";
import { BuildingView } from "./components/BuildingView";
import { Dashboard } from "./components/Dashboard";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { LogsView } from "./components/LogsView";
import { ExportMenu } from "./components/ExportMenu";
import { NodeDetail } from "./components/NodeDetail";
import { ReplayBar } from "./components/ReplayBar";
import { RunComparison } from "./components/RunComparison";
import { RunControlBar } from "./components/RunControlBar";
import { ConversationPanel } from "./components/ConversationPanel";
import { RunList } from "./components/RunList";
import { StatusBadge } from "./components/StatusBadge";
import { StoryView } from "./components/StoryView";
import { TagEditor } from "./components/TagEditor";
import { buildGraphAt } from "./lib/replay";
import { useRunStream } from "./hooks/useRunStream";
import { useControlLatch } from "./hooks/useControlLatch";
import { useRunStore, type RunTab } from "./store/runStore";

function RunViewer() {
  const selectedRunId = useRunStore((s) => s.selectedRunId);
  const compareRunId = useRunStore((s) => s.compareRunId);
  const runStates = useRunStore((s) => s.runStates);
  const selectedNodeId = useRunStore((s) => s.selectedNodeId);
  const runs = useRunStore((s) => s.runs);
  const view = useRunStore((s) => s.view);
  const entryTab = useRunStore((s) => s.entryTab);
  const selectRun = useRunStore((s) => s.selectRun);
  const selectNode = useRunStore((s) => s.selectNode);
  const setCompareRun = useRunStore((s) => s.setCompareRun);

  const streamStatus = useRunStream(selectedRunId);

  const state = selectedRunId ? runStates[selectedRunId] : null;
  const selectedNode = state?.nodes.find((n) => n.id === selectedNodeId) ?? null;

  // One shared control-latch poll for the Theater (control bar + conversation
  // panel) so they don't each hit GET /control. UI-only side channel.
  const control = useControlLatch(selectedRunId ?? "", state?.status === "running");

  // Per-run tab — Story is the default legible view; a caller of selectRun can
  // request another landing tab via the store's `entryTab` (e.g. a floor-view
  // room click → "theater").
  const [tab, setTab] = useState<RunTab>(entryTab);
  // Graph "Simplified" hides framework-internal nodes (default on).
  const [graphSimplified, setGraphSimplified] = useState(true);

  // Replay / time-travel: null = live view; a number = events applied so far.
  const [replayIndex, setReplayIndex] = useState<number | null>(null);
  const [replayPlaying, setReplayPlaying] = useState(false);

  // Reset tab + replay when the selected run changes. The tab follows the
  // requested `entryTab` (defaults to "story") so a floor-view room click lands
  // on Theater; entryTab is also a dep so re-selecting the same run still honors
  // a newly requested tab.
  useEffect(() => {
    setTab(entryTab);
    setReplayIndex(null);
    setReplayPlaying(false);
  }, [selectedRunId, entryTab]);

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
      {/* Sidebar — brand plate + run list */}
      <div className="w-64 shrink-0 flex flex-col">
        <div className="px-brand text-center text-sm py-3 bg-surface-inset border-b-2 border-border select-none">
          vapviz
        </div>
        <RunList onSelect={selectRun} />
      </div>

      {/* Main area */}
      {view === "floor" ? (
        <BuildingView />
      ) : view === "dashboard" ? (
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

              {/* Tabs — one adaptive UI: every view for everyone; depth lives
                  behind progressive disclosure inside the views. */}
              <div className="flex items-center gap-1 bg-surface-inset p-1 border-2 border-border">
                <TabButton active={tab === "story"} onClick={() => setTab("story")} icon={BookOpen}>
                  Story
                </TabButton>
                <TabButton active={tab === "theater"} onClick={() => setTab("theater")} icon={Drama}>
                  Theater
                </TabButton>
                <TabButton active={tab === "graph"} onClick={() => setTab("graph")} icon={Network}>
                  Graph
                </TabButton>
                <TabButton active={tab === "logs"} onClick={() => setTab("logs")} icon={ScrollText}>
                  Logs
                </TabButton>
              </div>

              <div className="border-l-2 border-border pl-3">
                <TagEditor
                  runId={selectedRunId!}
                  tags={runs.find((r) => r.run_id === selectedRunId)?.tags ?? []}
                />
              </div>
              <div className="ml-auto flex items-center gap-2">
                {tab === "graph" && (
                  <>
                    {/* Simplified | Detailed toggle */}
                    <div className="flex items-center gap-0.5 bg-surface-inset p-0.5 border-2 border-border">
                      <button
                        onClick={() => setGraphSimplified(true)}
                        className={`px-display text-[10px] px-2 py-1 transition-colors ${
                          graphSimplified ? "bg-surface text-content shadow-sm" : "text-content-faint hover:text-content"
                        }`}
                        title="Hide framework-internal nodes"
                      >
                        Simplified
                      </button>
                      <button
                        onClick={() => setGraphSimplified(false)}
                        className={`px-display text-[10px] px-2 py-1 transition-colors ${
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
                      className={`flex items-center gap-1.5 px-display text-[10px] px-2 py-1 transition-colors ${
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
            </div>

            {/* Body */}
            {tab === "theater" ? (
              <div className="flex-1 min-w-0 flex flex-col min-h-0">
                <RunControlBar
                  runStatus={state.status}
                  latch={control.latch}
                  sendAction={control.sendAction}
                />
                <div className="flex-1 min-h-0 flex">
                  <div className="flex-1 min-w-0">
                    <TheaterView nodes={shownNodes} runId={selectedRunId!} runStatus={state.status} />
                  </div>
                  <ConversationPanel
                    events={state.events}
                    runStatus={state.status}
                    latch={control.latch}
                    sendMessage={control.sendMessage}
                  />
                </div>
                {/* Playback is core to Theater: bar always shown (live runs sit at the end). */}
                <ReplayBar
                  events={state.events}
                  startedAt={state.started_at ?? 0}
                  index={replayIndex ?? state.events.length}
                  setIndex={setReplayIndex}
                  playing={replayPlaying}
                  setPlaying={setReplayPlaying}
                  onExit={() => {
                    setReplayIndex(null);
                    setReplayPlaying(false);
                  }}
                />
              </div>
            ) : tab === "story" ? (
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

          {/* Node detail panel — boundary keyed by node so a bad node's data
              can't blank the run view; picking another node resets it. */}
          {selectedNode && (
            <div className="w-72 shrink-0">
              <ErrorBoundary key={selectedNode.id} label="this step's details">
                <NodeDetail node={selectedNode} />
              </ErrorBoundary>
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
      className={`flex items-center gap-1.5 px-display text-[11px] px-3 py-1.5 transition-colors ${
        active
          ? "bg-accent text-content-on-accent shadow-sm"
          : "text-content-muted hover:text-content hover:bg-surface-hover"
      }`}
    >
      <Icon size={13} /> {children}
    </button>
  );
}

export default RunViewer;
