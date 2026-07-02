import type { GraphNode } from "../types/events";
import { OfficeStage } from "./OfficeStage";

/**
 * Per-run Theater (UI-ROADMAP Phase 3, §4-F) — the run's cast at work in the
 * cozy sprite office. The room + walking choreography live in `OfficeStage`
 * (art-as-data sprites, layout locked 2026-07-01); here we just pass the run's
 * nodes (live, or the partial graph from `buildGraphAt` during replay). The
 * playback bar is wired up alongside this in App. The global Floor still tiles
 * the older compact `AgentStage`.
 */
export function TheaterView({ nodes }: { nodes: GraphNode[] }) {
  return <OfficeStage nodes={nodes} />;
}
