import type { GraphNode } from "../types/events";
import { AgentStage } from "./AgentStage";

/**
 * Per-run Theater (UI-ROADMAP Phase 3, §4-F) — one full-size stage of the run's
 * cast. The room + walking choreography live in the shared `AgentStage`; here we
 * just pass the run's nodes (live, or the partial graph from `buildGraphAt`
 * during replay). The playback bar is wired up alongside this in App.
 */
export function TheaterView({ nodes }: { nodes: GraphNode[] }) {
  return <AgentStage nodes={nodes} />;
}
