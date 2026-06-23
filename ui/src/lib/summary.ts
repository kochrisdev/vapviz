import type { GraphNode, NodeStatus, RunSummary } from "../types/events";
import type { RunState } from "../store/runStore";
import { formatCost, formatDuration, formatLabel } from "./format";

export interface RunStats {
  status: NodeStatus;
  agentCount: number;
  stepCount: number;
  toolCount: number;
  llmCount: number;
  models: string[];
  toolNames: string[];
  totalCostUsd: number | null;
  durationMs: number | null;
}

/** Cost attached to an LLM node's output (mirrors the runStore reduce). */
export function nodeCost(node: GraphNode): number | null {
  if (node.kind !== "llm") return null;
  const out = node.data?.output as Record<string, unknown> | undefined;
  const c = out?.cost_usd;
  return typeof c === "number" ? c : null;
}

function uniq(xs: string[]): string[] {
  return Array.from(new Set(xs.filter(Boolean)));
}

export function computeStats(state: RunState): RunStats {
  const nodes = state.nodes;
  const models = uniq(
    nodes
      .filter((n) => n.kind === "llm")
      .map((n) => {
        const model = (n.data?.input as Record<string, unknown> | undefined)?.model;
        return typeof model === "string" ? model : formatLabel(n);
      })
  );
  const totalCostUsd = nodes.reduce<number>((sum, n) => {
    const c = nodeCost(n);
    return c != null ? sum + c : sum;
  }, 0);

  return {
    status: state.status,
    agentCount: nodes.filter((n) => n.kind === "agent").length,
    stepCount: nodes.filter((n) => n.kind === "step").length,
    toolCount: nodes.filter((n) => n.kind === "tool").length,
    llmCount: nodes.filter((n) => n.kind === "llm").length,
    models,
    toolNames: uniq(nodes.filter((n) => n.kind === "tool").map((n) => formatLabel(n))),
    totalCostUsd: totalCostUsd > 0 ? totalCostUsd : null,
    durationMs:
      state.started_at != null && state.ended_at != null
        ? (state.ended_at - state.started_at) * 1000
        : null,
  };
}

/** The primary user-facing input of a run, if we can find one. */
function primaryInput(state: RunState): string | null {
  for (const n of state.nodes) {
    const input = n.data?.input as Record<string, unknown> | undefined;
    if (!input) continue;
    if (typeof input.prompt === "string" && input.prompt.trim()) return input.prompt.trim();
    const messages = input.messages as Array<Record<string, unknown>> | undefined;
    if (Array.isArray(messages)) {
      const user = [...messages]
        .reverse()
        .find((m) => m.role === "user" || m.type === "human");
      if (user && typeof user.content === "string" && user.content.trim()) {
        return user.content.trim();
      }
    }
  }
  return null;
}

function statusClause(status: NodeStatus): string {
  return status === "success" ? "succeeded" : status === "error" ? "failed" : "running";
}

function clip(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;
}

function joinList(xs: string[], max = 3): string {
  if (xs.length === 0) return "";
  if (xs.length <= max) return xs.join(", ");
  return `${xs.slice(0, max).join(", ")} +${xs.length - max}`;
}

/**
 * One-line, template-generated plain-language summary of a run.
 * See UI-ROADMAP Appendix A.2. Deterministic — no LLM involved.
 */
export function summarize(state: RunState): string {
  const root = state.nodes.find((n) => n.parent_id == null) ?? null;
  const title = root ? formatLabel(root) : state.label;
  const stats = computeStats(state);
  const input = primaryInput(state);

  const parts: string[] = [];
  parts.push(title);
  if (input) parts[0] += ` answered “${clip(input, 60)}”`;

  const clauses: string[] = [];
  if (stats.llmCount > 0) {
    const models = stats.models.length ? ` (${joinList(stats.models)})` : "";
    clauses.push(`${stats.llmCount} model call${stats.llmCount === 1 ? "" : "s"}${models}`);
  }
  if (stats.toolCount > 0) {
    const names = stats.toolNames.length ? ` (${joinList(stats.toolNames)})` : "";
    clauses.push(`${stats.toolCount} tool${stats.toolCount === 1 ? "" : "s"}${names}`);
  }

  const dur = formatDuration(state.started_at, state.ended_at);
  let tail = statusClause(stats.status);
  if (dur) tail += ` in ${dur}`;
  const cost = formatCost(stats.totalCostUsd);
  if (cost && cost !== "$0") tail += `, ${cost}`;
  clauses.push(tail);

  return `${parts[0]} — ${clauses.join(", ")}.`;
}

/**
 * Lightweight subtitle for the sidebar, derived from the RunSummary alone
 * (the sidebar has no per-node data for unloaded runs — see Phase-1 decision).
 */
export function runSubtitle(run: RunSummary): string {
  const bits: string[] = [];
  bits.push(`${run.node_count} step${run.node_count === 1 ? "" : "s"}`);
  const cost = formatCost(run.total_cost_usd);
  if (cost && cost !== "$0") bits.push(cost);
  const dur = formatDuration(run.started_at, run.ended_at);
  if (dur) bits.push(dur);
  return bits.join(" · ");
}
