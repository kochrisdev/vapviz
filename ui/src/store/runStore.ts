import { create } from "zustand";
import type { GraphEdge, GraphNode, NodeStatus, RunSummary, VapEvent } from "../types/events";

export interface RunState {
  nodes: GraphNode[];
  edges: GraphEdge[];
  status: NodeStatus;
  label: string;
  started_at: number | null;
  ended_at: number | null;
  events: VapEvent[];
}

export type View = "runs" | "dashboard" | "floor";

// Audience mode: Simple = plain-language narrative only; Technical = graph,
// logs, and raw JSON unlocked. Persisted across sessions.
export type AppMode = "simple" | "technical";

const MODE_KEY = "vapviz-mode";
function initialMode(): AppMode {
  if (typeof window === "undefined") return "simple";
  return window.localStorage.getItem(MODE_KEY) === "technical" ? "technical" : "simple";
}

interface Store {
  runs: RunSummary[];
  selectedRunId: string | null;
  runStates: Record<string, RunState>;
  selectedNodeId: string | null;
  compareRunId: string | null;
  view: View;
  mode: AppMode;

  setRuns: (runs: RunSummary[]) => void;
  setMode: (mode: AppMode) => void;
  selectRun: (runId: string | null) => void;
  selectNode: (nodeId: string | null) => void;
  applyEvent: (event: VapEvent) => void;
  setRunGraph: (runId: string, nodes: GraphNode[], edges: GraphEdge[], label: string, status: NodeStatus, started_at: number, ended_at: number | null) => void;
  setCompareRun: (runId: string | null) => void;
  setView: (view: View) => void;
  setRunTags: (runId: string, tags: string[]) => void;
}

const START_TYPES = new Set(["agent_start", "step_start", "tool_call", "llm_call"]);
const END_TYPES = new Set(["agent_end", "step_end", "tool_result", "llm_response"]);

// ── DUAL LOGIC ──────────────────────────────────────────────────────────────
// `applyEventToGraph` + `totalLlmCost` are the events→graph reduction. They MUST
// stay byte-for-byte equivalent to Python `_apply_event_to_graph` / `_total_cost`
// in vapviz/store.py. The cross-impl parity test (tests/fixtures/reducer_parity/,
// tests/test_reducer_parity.py, runStore.parity.test.ts) fails the gate on drift.
// See ui/src/CLAUDE.md.

export interface GraphState {
  nodes: GraphNode[];
  edges: GraphEdge[];
  status: NodeStatus;
  ended_at: number | null;
}

/** Pure: fold one event into the graph state, returning fresh arrays. */
export function applyEventToGraph(prev: GraphState, event: VapEvent): GraphState {
  let nodes = [...prev.nodes];
  let edges = [...prev.edges];
  let status = prev.status;
  let ended_at = prev.ended_at;

  if (START_TYPES.has(event.type)) {
    const exists = nodes.find((n) => n.id === event.node_id);
    if (!exists) {
      nodes.push({
        id: event.node_id,
        kind: event.node_kind,
        label: event.node_label,
        status: "running",
        parent_id: event.parent_id,
        started_at: event.timestamp,
        ended_at: null,
        data: event.data,
      });
    }
    if (event.parent_id) {
      const edgeId = `${event.parent_id}→${event.node_id}`;
      if (!edges.find((e) => e.id === edgeId)) {
        edges.push({ id: edgeId, source: event.parent_id, target: event.node_id, kind: "execution" });
      }
    }
  } else if (END_TYPES.has(event.type)) {
    nodes = nodes.map((n) =>
      n.id === event.node_id
        ? { ...n, status: event.data.error ? "error" : "success", ended_at: event.timestamp, data: { ...n.data, ...event.data } }
        : n
    );
    if (event.type === "agent_end") {
      status = event.data.error ? "error" : "success";
      ended_at = event.timestamp;
    }
  } else if (event.type === "error") {
    nodes = nodes.map((n) =>
      n.id === event.node_id ? { ...n, status: "error", ended_at: event.timestamp, data: { ...n.data, ...event.data } } : n
    );
  }

  return { nodes, edges, status, ended_at };
}

/** Pure: run total = sum of cost_usd over LLM-kind nodes only (null if none priced). */
export function totalLlmCost(nodes: GraphNode[]): number | null {
  const total = nodes.reduce((sum, n) => {
    if (n.kind !== "llm") return sum;
    const cost = (n.data?.output as Record<string, unknown> | undefined)?.cost_usd as number | undefined;
    return cost != null ? sum + cost : sum;
  }, 0);
  return total > 0 ? Number(total.toFixed(8)) : null;
}

export const useRunStore = create<Store>((set) => ({
  runs: [],
  selectedRunId: null,
  runStates: {},
  selectedNodeId: null,
  compareRunId: null,
  // The global analytics Dashboard is the default landing view — the first
  // thing users see. Selecting a run switches to the per-run view.
  view: "dashboard",
  mode: initialMode(),

  setRuns: (runs) => set({ runs }),

  setMode: (mode) =>
    set(() => {
      if (typeof window !== "undefined") window.localStorage.setItem(MODE_KEY, mode);
      return { mode };
    }),

  // Selecting a run always returns to the run (graph) view
  selectRun: (runId) => set({ selectedRunId: runId, selectedNodeId: null, compareRunId: null, view: "runs" }),

  selectNode: (nodeId) => set({ selectedNodeId: nodeId }),

  setCompareRun: (runId) => set({ compareRunId: runId }),

  setView: (view) => set({ view }),

  setRunTags: (runId, tags) =>
    set((s) => ({ runs: s.runs.map((r) => (r.run_id === runId ? { ...r, tags } : r)) })),

  setRunGraph: (runId, nodes, edges, label, status, started_at, ended_at) =>
    set((s) => ({
      runStates: {
        ...s.runStates,
        [runId]: { nodes, edges, label, status, started_at, ended_at, events: s.runStates[runId]?.events ?? [] },
      },
    })),

  applyEvent: (event) =>
    set((s) => {
      const prev = s.runStates[event.run_id] ?? {
        nodes: [],
        edges: [],
        status: "running" as NodeStatus,
        label: event.run_id,
        started_at: event.timestamp,
        ended_at: null,
        events: [],
      };

      // Skip duplicates — the server replays full history on every SSE
      // (re)connect, so a reconnect would otherwise double the timeline.
      if (prev.events.some((e) => e.id === event.id)) return s;

      const { nodes, edges, status, ended_at } = applyEventToGraph(
        { nodes: prev.nodes, edges: prev.edges, status: prev.status, ended_at: prev.ended_at },
        event
      );

      return {
        runStates: {
          ...s.runStates,
          [event.run_id]: { ...prev, nodes, edges, status, ended_at, events: [...prev.events, event] },
        },
        runs: (() => {
          // Recompute total cost from llm nodes only — some integrations also
          // attach an aggregate cost_usd to the parent agent node (would double-count).
          const costForRun = totalLlmCost(nodes);

          return s.runs.some((r) => r.run_id === event.run_id)
            ? s.runs.map((r) =>
                r.run_id === event.run_id
                  ? { ...r, status, ended_at, node_count: nodes.length, event_count: prev.events.length + 1, total_cost_usd: costForRun }
                  : r
              )
            : [
                {
                  run_id: event.run_id,
                  label: event.node_label,
                  status,
                  started_at: prev.started_at ?? event.timestamp,
                  ended_at,
                  node_count: nodes.length,
                  event_count: 1,
                  total_cost_usd: costForRun,
                  tags: [],
                },
                ...s.runs,
              ];
        })(),
      };
    }),
}));
