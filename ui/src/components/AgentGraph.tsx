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
import { AlertTriangle, Bot, Layers, Sparkles, Wrench, type LucideIcon } from "lucide-react";
import type { GraphEdge, GraphNode, NodeKind } from "../types/events";
import { useRunStore } from "../store/runStore";
import { cssColor, KIND_TOKEN, STATUS_TOKEN } from "../lib/cssColor";
import { formatCost, formatLabel } from "../lib/format";
import { nodeCost } from "../lib/summary";
import { simplifyGraph } from "../lib/simplify";
import { useTheme } from "../lib/theme";

/** First line of any error message attached to a node, if present. */
function errorSnippet(node: GraphNode): string | null {
  const raw =
    (node.data?.error as unknown) ??
    ((node.data?.output as Record<string, unknown> | undefined)?.error as unknown);
  if (raw == null) return null;
  const text = String(raw).split("\n")[0].trim();
  return text.length > 48 ? text.slice(0, 47) + "…" : text;
}

const KIND_ICON: Record<NodeKind, LucideIcon> = {
  agent: Bot,
  step: Layers,
  tool: Wrench,
  llm: Sparkles,
};

// ── custom node ────────────────────────────────────────────────────────────────

function VapNode({ data, selected }: NodeProps) {
  const { node } = data as { node: GraphNode };
  const isRunning = node.status === "running";
  const isError = node.status === "error";
  const Icon = KIND_ICON[node.kind];
  const kindVar = KIND_TOKEN[node.kind];
  const statusVar = STATUS_TOKEN[node.status];

  const costLabel = formatCost(nodeCost(node));
  const errMsg = isError ? errorSnippet(node) : null;

  return (
    <div
      title={node.label}
      className="relative rounded-lg px-3 py-2 text-xs font-medium shadow-md cursor-pointer select-none text-content"
      style={{
        // Error nodes get a loud red fill; others a subtle kind tint.
        background: isError ? `rgb(var(--status-error) / 0.22)` : `rgb(var(${kindVar}) / 0.16)`,
        border: `2px solid rgb(var(${statusVar}) / ${selected ? 1 : isError ? 1 : 0.85})`,
        boxShadow: selected
          ? `0 0 0 2px rgb(var(--accent))`
          : isError
          ? `0 0 0 1px rgb(var(--status-error) / 0.4)`
          : undefined,
        minWidth: 110,
        maxWidth: 190,
      }}
    >
      {isRunning && (
        <span
          className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full animate-ping"
          style={{ background: `rgb(var(--status-running))` }}
        />
      )}

      <Handle type="target" position={Position.Top} style={{ background: `rgb(var(${statusVar}))`, border: "none" }} />

      {/* Kind badge with icon (error icon takes over on failure) */}
      <div
        className="flex items-center gap-1 text-[10px] px-display mb-1"
        style={{ color: `rgb(var(${isError ? "--status-error" : kindVar}))` }}
      >
        {isError ? <AlertTriangle size={10} /> : <Icon size={9} />}
        {node.kind}
      </div>

      {/* Humanized label */}
      <div className="truncate leading-tight">{formatLabel(node)}</div>

      {/* Error snippet */}
      {errMsg && (
        <div className="mt-0.5 text-[10px] leading-tight" style={{ color: `rgb(var(--status-error))` }}>
          {errMsg}
        </div>
      )}

      {/* Duration */}
      {node.started_at && node.ended_at && (
        <div className="opacity-60 mt-0.5 text-[10px] tabular-nums">
          {((node.ended_at - node.started_at) * 1000).toFixed(0)} ms
        </div>
      )}

      {/* Cost (LLM nodes only) */}
      {costLabel && (
        <div className="text-[10px] mt-0.5" style={{ color: `rgb(var(--kind-llm))` }}>
          {costLabel}
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ background: `rgb(var(${statusVar}))`, border: "none" }} />
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

const nodeTypes = { vapviz: VapNode };

interface Props {
  graphNodes: GraphNode[];
  graphEdges: GraphEdge[];
  /** Hide framework-internal nodes and re-parent their children (default true). */
  simplified?: boolean;
}

export function AgentGraph({ graphNodes, graphEdges, simplified = true }: Props) {
  const selectNode = useRunStore((s) => s.selectNode);
  const selectedNodeId = useRunStore((s) => s.selectedNodeId);
  const { theme } = useTheme();

  const { nodes, edges } = useMemo(() => {
    const view = simplified ? simplifyGraph(graphNodes, graphEdges) : { nodes: graphNodes, edges: graphEdges };
    const viewNodes = view.nodes;
    const viewEdges = view.edges;
    const nodeMap = new Map(viewNodes.map((n) => [n.id, n]));

    const rawNodes: Node[] = viewNodes.map((n) => ({
      id: n.id,
      type: "vapviz",
      position: { x: 0, y: 0 },
      data: { node: n },
      selected: n.id === selectedNodeId,
    }));

    const rawEdges: Edge[] = viewEdges.map((e) => {
      const src = nodeMap.get(e.source);
      const tgt = nodeMap.get(e.target);
      const color = src ? cssColor(KIND_TOKEN[src.kind], 0.7) : cssColor("--border-strong");
      const isRunning = src?.status === "running" || tgt?.status === "running";
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        type: "smoothstep",
        animated: isRunning,
        style: { stroke: color, strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
      };
    });

    const laid = applyDagreLayout(rawNodes, rawEdges);
    return { nodes: laid, edges: rawEdges };
    // `theme` participates so concrete edge/marker colours re-resolve on toggle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphNodes, graphEdges, selectedNodeId, theme, simplified]);

  const onNodeClick = useCallback((_: unknown, node: Node) => selectNode(node.id), [selectNode]);

  // Concrete colours for ReactFlow chrome; re-resolved when the theme flips.
  const chrome = useMemo(
    () => ({
      dots: cssColor("--border", 0.9),
      mask: cssColor("--bg", 0.6),
      miniBg: cssColor("--surface"),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [theme]
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
      colorMode={theme}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} color={chrome.dots} gap={20} size={1.5} />
      <Controls showInteractive={false} />
      <MiniMap
        nodeColor={(n) => cssColor(KIND_TOKEN[(n.data as { node: GraphNode }).node.kind], 0.8)}
        maskColor={chrome.mask}
        style={{ background: chrome.miniBg }}
      />
    </ReactFlow>
  );
}
