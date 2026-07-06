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
  app_id?: string | null; // set at run creation from agent_start data, not by the reducer
  status: NodeStatus;
  nodes: GraphNode[];
  edges: GraphEdge[];
  started_at: number;
  ended_at: number | null;
}

export interface RunSummary {
  run_id: string;
  label: string;
  app_id?: string | null; // stable pipeline id (trace(app_id=...)); grouping key = app_id ?? label
  status: NodeStatus;
  started_at: number;
  ended_at: number | null;
  node_count: number;
  event_count: number;
  total_cost_usd: number | null;
  tags: string[];
  summary?: string | null; // plain-language one-liner from vapviz/summary.py
}

// ── Cross-run analytics (GET /metrics) ──────────────────────────────────────

export interface TokenTotals {
  input: number;
  output: number;
}

export interface ModelStat {
  model: string;
  calls: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
}

export interface KindCounts {
  agent: number;
  step: number;
  tool: number;
  llm: number;
}

export interface DailyCost {
  date: string;
  cost_usd: number;
  run_count: number;
}

export interface Metrics {
  run_count: number;
  success_count: number;
  error_count: number;
  running_count: number;
  success_rate: number | null;

  total_cost_usd: number;
  avg_cost_usd: number | null;

  total_duration_ms: number;
  avg_duration_ms: number | null;

  total_nodes: number;
  total_llm_calls: number;
  total_tokens: TokenTotals;

  by_model: ModelStat[];
  by_kind: KindCounts;
  cost_over_time: DailyCost[];
}
