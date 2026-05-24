import dagre from "dagre";
import { useCallback, useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphEdge, GraphNode, NodeKind, NodeStatus } from "../types/events";
import { useRunStore } from "../store/runStore";

// ── colour maps ────────────────────────────────────────────────────────────────

const KIND_BG: Record<NodeKind, string> = {
  agent: "#6366f1",
  step: "#0ea5e9",
  tool: "#10b981",
  llm: "#a855f7",
};

const STATUS_RING: Record<NodeStatus, string> = {
  pending: "#94a3b8",
  running: "#f59e0b",
  success: "#22c55e",
  error: "#ef4444",
};

// ── custom node ────────────────────────────────────────────────────────────────

function VapNode({ data, selected }: NodeProps) {
  const { node } = data as { node: GraphNode };
  const bg = KIND_BG[node.kind];
  const ring = STATUS_RING[node.status];
  const isRunning = node.status === "running";

  return (
    <div
      className="relative rounded-lg px-3 py-2 text-white text-xs font-medium shadow-lg cursor-pointer"
      style={{
        background: bg,
        outline: selected ? `3px solid ${ring}` : `2px solid ${ring}`,
        minWidth: 100,
        maxWidth: 180,
      }}
    >
      {isRunning && (
        <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-amber-400 animate-ping" />
      )}
      <Handle type="target" position={Position.Top} style={{ background: ring }} />
      <div className="opacity-60 text-[10px] uppercase tracking-wider mb-0.5">{node.kind}</div>
      <div className="truncate">{node.label}</div>
      {node.started_at && node.ended_at && (
        <div className="opacity-60 mt-0.5 text-[10px]">
          {((node.ended_at - node.started_at) * 1000).toFixed(0)} ms
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ background: ring }} />
    </div>
  );
}

// ── dagre layout ───────────────────────────────────────────────────────────────

function applyDagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 60 });
  g.setDefaultEdgeLabel(() => ({}));

  nodes.forEach((n) => g.setNode(n.id, { width: 180, height: 60 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - 90, y: pos.y - 30 } };
  });
}

// ── main component ─────────────────────────────────────────────────────────────

const nodeTypes = { vap: VapNode };

interface Props {
  graphNodes: GraphNode[];
  graphEdges: GraphEdge[];
}

export function AgentGraph({ graphNodes, graphEdges }: Props) {
  const selectNode = useRunStore((s) => s.selectNode);
  const selectedNodeId = useRunStore((s) => s.selectedNodeId);

  const { nodes, edges } = useMemo(() => {
    const rawNodes: Node[] = graphNodes.map((n) => ({
      id: n.id,
      type: "vap",
      position: { x: 0, y: 0 },
      data: { node: n },
      selected: n.id === selectedNodeId,
    }));

    const rawEdges: Edge[] = graphEdges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      style: { stroke: "#64748b", strokeWidth: 1.5 },
      animated: false,
    }));

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
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.2}
    >
      <Background color="#1e293b" gap={20} />
      <Controls />
      <MiniMap nodeColor={(n) => KIND_BG[(n.data as { node: GraphNode }).node.kind] ?? "#6366f1"} />
    </ReactFlow>
  );
}
