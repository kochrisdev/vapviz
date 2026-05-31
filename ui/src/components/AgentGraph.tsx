import dagre from "dagre";
import { useCallback, useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Bot, Layers, Sparkles, Wrench, type LucideIcon } from "lucide-react";
import type { GraphEdge, GraphNode, NodeKind, NodeStatus } from "../types/events";
import { useRunStore } from "../store/runStore";

// ── colour maps ────────────────────────────────────────────────────────────────

const KIND_BG: Record<NodeKind, string> = {
  agent: "#6366f1",
  step:  "#0ea5e9",
  tool:  "#10b981",
  llm:   "#a855f7",
};

const STATUS_RING: Record<NodeStatus, string> = {
  pending: "#94a3b8",
  running: "#f59e0b",
  success: "#22c55e",
  error:   "#ef4444",
};

const KIND_ICON: Record<NodeKind, LucideIcon> = {
  agent: Bot,
  step:  Layers,
  tool:  Wrench,
  llm:   Sparkles,
};

// ── custom node ────────────────────────────────────────────────────────────────

function VapNode({ data, selected }: NodeProps) {
  const { node } = data as { node: GraphNode };
  const bg        = KIND_BG[node.kind];
  const ring      = STATUS_RING[node.status];
  const isRunning = node.status === "running";
  const Icon      = KIND_ICON[node.kind];

  const costUsd = (node.data?.output as Record<string, unknown> | undefined)
    ?.cost_usd as number | undefined;
  const costLabel = costUsd == null
    ? null
    : costUsd < 0.0001
    ? "<$0.0001"
    : costUsd < 0.01
    ? `$${costUsd.toFixed(6)}`
    : `$${costUsd.toFixed(4)}`;

  return (
    <div
      title={node.label}
      className="relative rounded-lg px-3 py-2 text-white text-xs font-medium shadow-lg cursor-pointer select-none"
      style={{
        background:  bg,
        outline:     selected ? `3px solid ${ring}` : `2px solid ${ring}`,
        minWidth:    110,
        maxWidth:    190,
      }}
    >
      {/* Pulsing dot for running state */}
      {isRunning && (
        <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-amber-400 animate-ping" />
      )}

      <Handle type="target" position={Position.Top}    style={{ background: ring, border: "none" }} />

      {/* Kind badge with icon */}
      <div className="flex items-center gap-1 opacity-70 text-[10px] uppercase tracking-wider mb-1">
        <Icon size={9} />
        {node.kind}
      </div>

      {/* Label */}
      <div className="truncate leading-tight">{node.label}</div>

      {/* Duration */}
      {node.started_at && node.ended_at && (
        <div className="opacity-60 mt-0.5 text-[10px] tabular-nums">
          {((node.ended_at - node.started_at) * 1000).toFixed(0)} ms
        </div>
      )}

      {/* Cost (LLM nodes only) */}
      {costLabel && (
        <div className="opacity-80 text-[10px] mt-0.5 text-purple-200">{costLabel}</div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ background: ring, border: "none" }} />
    </div>
  );
}

// ── dagre layout ───────────────────────────────────────────────────────────────

function applyDagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", nodesep: 48, ranksep: 64 });
  g.setDefaultEdgeLabel(() => ({}));

  nodes.forEach((n) => g.setNode(n.id, { width: 190, height: 64 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - 95, y: pos.y - 32 } };
  });
}

// ── main component ─────────────────────────────────────────────────────────────

const nodeTypes = { vap: VapNode };

interface Props {
  graphNodes: GraphNode[];
  graphEdges: GraphEdge[];
}

export function AgentGraph({ graphNodes, graphEdges }: Props) {
  const selectNode     = useRunStore((s) => s.selectNode);
  const selectedNodeId = useRunStore((s) => s.selectedNodeId);

  const { nodes, edges } = useMemo(() => {
    const nodeMap = new Map(graphNodes.map((n) => [n.id, n]));

    const rawNodes: Node[] = graphNodes.map((n) => ({
      id:       n.id,
      type:     "vap",
      position: { x: 0, y: 0 },
      data:     { node: n },
      selected: n.id === selectedNodeId,
    }));

    const rawEdges: Edge[] = graphEdges.map((e) => {
      const src        = nodeMap.get(e.source);
      const tgt        = nodeMap.get(e.target);
      const color      = src ? KIND_BG[src.kind] : "#64748b";
      const isRunning  = src?.status === "running" || tgt?.status === "running";
      return {
        id:        e.id,
        source:    e.source,
        target:    e.target,
        type:      "smoothstep",
        animated:  isRunning,
        style:     { stroke: color + "bb", strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: color + "bb", width: 14, height: 14 },
      };
    });

    const laid = applyDagreLayout(rawNodes, rawEdges);
    return { nodes: laid, edges: rawEdges };
  }, [graphNodes, graphEdges, selectedNodeId]);

  const onNodeClick = useCallback(
    (_: unknown, node: Node) => selectNode(node.id),
    [selectNode]
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick}
      fitView
      fitViewOptions={{ padding: 0.25 }}
      minZoom={0.15}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} color="#1e293b" gap={20} size={1.5} />
      <Controls showInteractive={false} />
      <MiniMap
        nodeColor={(n) => KIND_BG[(n.data as { node: GraphNode }).node.kind] ?? "#6366f1"}
        maskColor="rgba(2,6,23,0.6)"
        style={{ background: "#0f172a" }}
      />
    </ReactFlow>
  );
}
