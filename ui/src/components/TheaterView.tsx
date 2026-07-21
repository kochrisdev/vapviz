import type { GraphNode, NodeStatus } from "../types/events";
import { OfficeStage } from "./OfficeStage";
import { useOfficeControl } from "../hooks/useOfficeControl";

/**
 * Per-run Theater (UI-ROADMAP Phase 3, §4-F) — the run's cast at work in the
 * cozy sprite office. The room + walking choreography live in `OfficeStage`
 * (art-as-data sprites, layout locked 2026-07-01); here we just pass the run's
 * nodes (live, or the partial graph from `buildGraphAt` during replay). The
 * playback bar is wired up alongside this in App. The global Floor tiles the
 * same engine in `compact` mode.
 *
 * While the run is live we also poll its control latch so the office can rest
 * (dim + badge) when the agent is paused or waiting for the user's input.
 */
export function TheaterView({
  nodes,
  runId,
  runStatus,
}: {
  nodes: GraphNode[];
  runId: string;
  runStatus: NodeStatus;
}) {
  const control = useOfficeControl(runId, runStatus === "running");
  return <OfficeStage nodes={nodes} control={control} />;
}
