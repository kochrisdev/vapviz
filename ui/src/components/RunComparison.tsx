import { useState, useEffect } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import type { RunGraph } from "../types/events";
import { AgentGraph } from "./AgentGraph";
import { formatCost } from "../lib/format";

interface Props {
  runIdA: string;
  runIdB: string;
  labelA: string;
  labelB: string;
  onClose: () => void;
}

function fmtDur(ms: number) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${ms.toFixed(0)} ms`;
}

function totalCost(graph: RunGraph): number | null {
  let total = 0;
  let found = false;
  for (const n of graph.nodes) {
    const cost = (n.data?.output as Record<string, unknown> | undefined)?.cost_usd as number | undefined;
    if (cost != null) {
      total += cost;
      found = true;
    }
  }
  return found ? total : null;
}

function StatCard({ side, graph }: { side: "A" | "B"; graph: RunGraph }) {
  const dur = graph.ended_at && graph.started_at ? (graph.ended_at - graph.started_at) * 1000 : null;
  const cost = totalCost(graph);
  const color = side === "A" ? "text-kind-step" : "text-status-running";

  return (
    <div className="flex-1 space-y-1">
      <div className={`text-[10px] px-display ${color}`}>Run {side}</div>
      <div className="text-sm font-medium text-content truncate">{graph.label}</div>
      <div className="flex flex-wrap gap-2 text-xs text-content-muted">
        <span
          className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
            graph.status === "success"
              ? "bg-status-success/15 text-status-success"
              : graph.status === "error"
              ? "bg-status-error/15 text-status-error"
              : "bg-status-running/15 text-status-running"
          }`}
        >
          {graph.status}
        </span>
        {dur !== null && <span>{fmtDur(dur)}</span>}
        {cost !== null && <span className="text-kind-llm">{formatCost(cost)}</span>}
        <span>{graph.nodes.length} nodes</span>
      </div>
    </div>
  );
}

export function RunComparison({ runIdA, runIdB, labelA, labelB, onClose }: Props) {
  const [data, setData] = useState<{ a: RunGraph; b: RunGraph } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    fetch(`/runs/compare?a=${runIdA}&b=${runIdB}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<{ a: RunGraph; b: RunGraph }>;
      })
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [runIdA, runIdB]);

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center text-status-error text-sm">
        Failed to load comparison: {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center text-content-faint text-sm animate-pulse">
        Loading comparison…
      </div>
    );
  }

  const labelsA = new Set(data.a.nodes.map((n) => n.label));
  const labelsB = new Set(data.b.nodes.map((n) => n.label));
  const onlyA = data.a.nodes.filter((n) => !labelsB.has(n.label));
  const onlyB = data.b.nodes.filter((n) => !labelsA.has(n.label));
  const common = data.a.nodes.filter((n) => labelsB.has(n.label));

  const durA = data.a.ended_at && data.a.started_at ? (data.a.ended_at - data.a.started_at) * 1000 : null;
  const durB = data.b.ended_at && data.b.started_at ? (data.b.ended_at - data.b.started_at) * 1000 : null;
  const costA = totalCost(data.a);
  const costB = totalCost(data.b);

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-surface shrink-0">
        <button
          onClick={onClose}
          className="flex items-center gap-1.5 text-xs text-content-faint hover:text-content transition-colors"
        >
          <ArrowLeft size={13} />
          Exit comparison
        </button>
        <span className="text-border-strong">|</span>
        <span className="text-xs text-content-muted">
          <span className="text-kind-step font-medium">{labelA}</span>
          <span className="mx-2 text-content-faint">vs</span>
          <span className="text-status-running font-medium">{labelB}</span>
        </span>
      </div>

      {/* ── Stats row ───────────────────────────────────────────────── */}
      <div className="flex items-start gap-4 px-4 py-3 border-b border-border bg-surface/50 shrink-0">
        <StatCard side="A" graph={data.a} />

        {/* Diff pill */}
        <div className="flex flex-col items-center gap-1.5 px-3 text-center shrink-0">
          <div className="text-[10px] px-display text-content-faint">Diff</div>
          <div className="flex gap-2 text-xs flex-wrap justify-center">
            {common.length > 0 && <span className="text-content-muted">{common.length} common</span>}
            {onlyA.length > 0 && <span className="text-kind-step">{onlyA.length} only A</span>}
            {onlyB.length > 0 && <span className="text-status-running">{onlyB.length} only B</span>}
          </div>
          {durA !== null && durB !== null && (
            <div className={`flex items-center gap-1 text-[10px] ${durB > durA ? "text-status-error" : "text-status-success"}`}>
              <ArrowRight size={10} />
              {durB > durA ? "+" : ""}
              {fmtDur(durB - durA)} duration
            </div>
          )}
          {costA !== null && costB !== null && (
            <div className={`flex items-center gap-1 text-[10px] ${costB > costA ? "text-status-error" : "text-status-success"}`}>
              <ArrowRight size={10} />
              {costB > costA ? "+" : ""}
              {formatCost(Math.abs(costB - costA))} cost
            </div>
          )}
        </div>

        <StatCard side="B" graph={data.b} />
      </div>

      {/* ── Two graphs side by side ──────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">
        {/* Graph A */}
        <div className="flex-1 min-w-0 border-r border-border flex flex-col">
          <div className="shrink-0 h-6 flex items-center px-3 bg-surface border-b border-border text-[11px] text-kind-step font-medium">
            A — {data.a.label}
          </div>
          <div className="flex-1 min-h-0">
            <ReactFlowProvider>
              <AgentGraph graphNodes={data.a.nodes} graphEdges={data.a.edges} />
            </ReactFlowProvider>
          </div>
        </div>

        {/* Graph B */}
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="shrink-0 h-6 flex items-center px-3 bg-surface border-b border-border text-[11px] text-status-running font-medium">
            B — {data.b.label}
          </div>
          <div className="flex-1 min-h-0">
            <ReactFlowProvider>
              <AgentGraph graphNodes={data.b.nodes} graphEdges={data.b.edges} />
            </ReactFlowProvider>
          </div>
        </div>
      </div>
    </div>
  );
}
