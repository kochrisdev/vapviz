import type { GraphEdge, GraphNode, NodeStatus, VapEvent } from "../types/events";

const START_TYPES = new Set(["agent_start", "step_start", "tool_call", "llm_call"]);
const END_TYPES = new Set(["agent_end", "step_end", "tool_result", "llm_response"]);

/**
 * Rebuild the run graph as it existed after the first `count` events.
 *
 * Mirrors the store's event → graph reduction, so scrubbing the replay bar
 * shows the graph filling in node by node exactly as it happened.
 */
export function buildGraphAt(events: VapEvent[], count: number): {
  nodes: GraphNode[];
  edges: GraphEdge[];
} {
  const nodeMap = new Map<string, GraphNode>();
  const edgeIds = new Set<string>();
  const edges: GraphEdge[] = [];

  for (const event of events.slice(0, Math.max(0, count))) {
    if (START_TYPES.has(event.type)) {
      if (!nodeMap.has(event.node_id)) {
        nodeMap.set(event.node_id, {
          id: event.node_id,
          kind: event.node_kind,
          label: event.node_label,
          status: "running" as NodeStatus,
          parent_id: event.parent_id,
          started_at: event.timestamp,
          ended_at: null,
          data: { ...event.data },
        });
      }
      if (event.parent_id) {
        const edgeId = `${event.parent_id}→${event.node_id}`;
        if (!edgeIds.has(edgeId)) {
          edgeIds.add(edgeId);
          edges.push({ id: edgeId, source: event.parent_id, target: event.node_id, kind: "execution" });
        }
      }
    } else if (END_TYPES.has(event.type)) {
      const node = nodeMap.get(event.node_id);
      if (node) {
        node.status = (event.data?.error ? "error" : "success") as NodeStatus;
        node.ended_at = event.timestamp;
        node.data = { ...node.data, ...event.data };
      }
    } else if (event.type === "error") {
      const node = nodeMap.get(event.node_id);
      if (node) {
        node.status = "error";
        node.ended_at = event.timestamp;
        node.data = { ...node.data, ...event.data };
      }
    }
  }

  return { nodes: Array.from(nodeMap.values()), edges };
}
