export type EventType =
  | "agent_start"
  | "agent_end"
  | "step_start"
  | "step_end"
  | "tool_call"
  | "tool_result"
  | "llm_call"
  | "llm_response"
  | "state_update"
  | "error";

export type NodeKind = "agent" | "step" | "tool" | "llm";
export type NodeStatus = "pending" | "running" | "success" | "error";

export interface VapEvent {
  id: string;
  run_id: string;
  timestamp: number;
  type: EventType;
  node_id: string;
  node_kind: NodeKind;
  node_label: string;
  parent_id: string | null;
  data: Record<string, unknown>;
}

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  status: NodeStatus;
  parent_id: string | null;
  started_at: number | null;
  ended_at: number | null;
  data: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
}

export interface RunGraph {
  run_id: string;
  label: string;
  status: NodeStatus;
  nodes: GraphNode[];
  edges: GraphEdge[];
  started_at: number;
  ended_at: number | null;
}

export interface RunSummary {
  run_id: string;
  label: string;
  status: NodeStatus;
  started_at: number;
  ended_at: number | null;
  node_count: number;
  event_count: number;
}
