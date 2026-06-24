import { useState } from "react";
import { Bot, ChevronRight, Clock, Coins, Layers, Sparkles, Wrench, type LucideIcon } from "lucide-react";
import type { GraphNode, NodeKind } from "../types/events";
import type { RunState } from "../store/runStore";
import { useRunStore } from "../store/runStore";
import { formatCost, formatDuration, formatLabel } from "../lib/format";
import { computeStats, nodeCost, summarize } from "../lib/summary";
import { explainNode } from "../lib/explain";
import { StatusBadge } from "./StatusBadge";

const KIND_ICON: Record<NodeKind, LucideIcon> = {
  agent: Bot,
  step: Layers,
  tool: Wrench,
  llm: Sparkles,
};

const KIND_TOKEN: Record<NodeKind, string> = {
  agent: "--kind-agent",
  step: "--kind-step",
  tool: "--kind-tool",
  llm: "--kind-llm",
};

interface StoryNodeProps {
  node: GraphNode;
  childrenByParent: Map<string, GraphNode[]>;
  depth: number;
}

function StoryNode({ node, childrenByParent, depth }: StoryNodeProps) {
  const selectNode = useRunStore((s) => s.selectNode);
  const selectedNodeId = useRunStore((s) => s.selectedNodeId);
  // Root level (the agent box) starts open; deeper levels collapsed for scale.
  const [open, setOpen] = useState(depth === 0);

  const children = childrenByParent.get(node.id) ?? [];
  const hasChildren = children.length > 0;
  const Icon = KIND_ICON[node.kind];
  const cost = formatCost(nodeCost(node));
  const dur = formatDuration(node.started_at, node.ended_at);
  const isSelected = node.id === selectedNodeId;
  // One-line plain explanation for the steps that "do" something concrete.
  const explanation = node.kind === "llm" || node.kind === "tool" ? explainNode(node) : null;

  const onClick = () => {
    selectNode(isSelected ? null : node.id);
    if (hasChildren) setOpen((o) => (isSelected ? o : true));
  };

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={onClick}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onClick();
          }
        }}
        className={`flex items-start gap-2 rounded-lg px-2.5 py-2 cursor-pointer border transition-colors ${
          isSelected
            ? "bg-surface-hover border-accent/50"
            : "bg-surface border-border hover:bg-surface-hover"
        }`}
        style={{ marginLeft: depth * 18 }}
      >
        {/* Expand caret */}
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setOpen((o) => !o);
            }}
            className="text-content-faint hover:text-content shrink-0 mt-0.5"
            title={open ? "Collapse" : "Expand"}
          >
            <ChevronRight size={14} className={`transition-transform ${open ? "rotate-90" : ""}`} />
          </button>
        ) : (
          <span className="w-[14px] shrink-0" />
        )}

        {/* Kind icon */}
        <Icon size={14} className="shrink-0 mt-0.5" style={{ color: `rgb(var(${KIND_TOKEN[node.kind]}))` }} />

        {/* Label + one-line explanation */}
        <div className="min-w-0 flex-1">
          <div className="text-sm text-content truncate" title={node.label}>
            {formatLabel(node)}
          </div>
          {explanation && <div className="text-[11px] text-content-faint truncate">{explanation}</div>}
        </div>

        {/* Meta */}
        <div className="flex items-center gap-2 shrink-0 mt-0.5">
          {cost && <span className="text-[11px] text-kind-llm tabular-nums">{cost}</span>}
          {dur && <span className="text-[11px] text-content-faint tabular-nums">{dur}</span>}
          {hasChildren && !open && (
            <span className="text-[10px] text-content-faint bg-surface-inset px-1.5 py-0.5 rounded-full">
              {children.length}
            </span>
          )}
          <StatusBadge status={node.status} showLabel={false} className="!px-1" />
        </div>
      </div>

      {/* Children */}
      {open && hasChildren && (
        <div className="mt-1 space-y-1">
          {children.map((c) => (
            <StoryNode key={c.id} node={c} childrenByParent={childrenByParent} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function Chip({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-content-muted bg-surface-inset border border-border rounded-full px-2.5 py-1">
      <Icon size={12} className="text-content-faint" />
      {children}
    </span>
  );
}

interface Props {
  state: RunState;
}

export function StoryView({ state }: Props) {
  const childrenByParent = new Map<string, GraphNode[]>();
  for (const n of state.nodes) {
    if (n.parent_id != null) {
      const arr = childrenByParent.get(n.parent_id) ?? [];
      arr.push(n);
      childrenByParent.set(n.parent_id, arr);
    }
  }
  const roots = state.nodes.filter((n) => n.parent_id == null);
  const stats = computeStats(state);
  const cost = formatCost(stats.totalCostUsd);
  const dur = formatDuration(state.started_at, state.ended_at);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-5">
      <div className="max-w-3xl mx-auto space-y-5">
        {/* Summary card */}
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="flex items-start justify-between gap-3 mb-2">
            <h2 className="text-base font-semibold text-content">{state.label}</h2>
            <StatusBadge status={state.status} />
          </div>
          <p className="text-sm text-content-muted leading-relaxed mb-3">{summarize(state)}</p>
          <div className="flex flex-wrap gap-2">
            {stats.llmCount > 0 && (
              <Chip icon={Sparkles}>
                {stats.llmCount} model call{stats.llmCount === 1 ? "" : "s"}
              </Chip>
            )}
            {stats.toolCount > 0 && (
              <Chip icon={Wrench}>
                {stats.toolCount} tool{stats.toolCount === 1 ? "" : "s"}
              </Chip>
            )}
            {stats.stepCount > 0 && (
              <Chip icon={Layers}>
                {stats.stepCount} step{stats.stepCount === 1 ? "" : "s"}
              </Chip>
            )}
            {dur && <Chip icon={Clock}>{dur}</Chip>}
            {cost && cost !== "$0" && <Chip icon={Coins}>{cost}</Chip>}
          </div>
        </div>

        {/* Tree */}
        <div className="space-y-1">
          {roots.length === 0 ? (
            <div className="text-content-faint text-sm text-center py-8">No activity recorded yet.</div>
          ) : (
            roots.map((r) => (
              <StoryNode key={r.id} node={r} childrenByParent={childrenByParent} depth={0} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
