import { useState, useEffect } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import type { RunGraph } from "../types/events";
import { AgentGraph } from "./AgentGraph";

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

function fmtCost(usd: number) {
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 0.01) return `$${usd.toFixed(6)}`;
  return `$${usd.toFixed(4)}`;
}

function totalCost(graph: RunGraph): number | null {
  let total = 0;
  let found = false;
  for (const n of graph.nodes) {
    const cost = ((n.data?.output as Record<string, unknown> | undefined)?.cost_usd as number | undefined);
    if (cost != null) { total += cost; found = true; }
  }
  return found ? total : null;
}

function StatCard({ side, graph }: { side: "A" | "B"; graph: RunGraph }) {
  const dur =
    graph.ended_at && graph.started_at
      ? (graph.ended_at - graph.started_at) * 1000
      : null;
  const cost = totalCost(graph);
  const color = side === "A" ? "text-sky-400" : "text-amber-400";

  return (
    <div className="flex-1 space-y-1">
      <div className={`text-[10px] uppercase tracking-wider font-semibold ${color}`}>
        Run {side}
      </div>
      <div className="text-sm font-medium text-slate-200 truncate">{graph.label}</div>
      <div className="flex flex-wrap gap-2 text-xs text-slate-400">
        <span
          className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
            graph.status === "success"
              ? "bg-green-900/40 text-green-300"
              : graph.status === "error"
              ? "bg-red-900/40 text-red-300"
              : "bg-amber-900/40 text-amber-300"
          }`}
        >
          {graph.status}
        </span>
        {dur !== null && <span>{fmtDur(dur)}</span>}
        {cost !== null && (
          <span className="text-purple-400">{fmtCost(cost)}</span>
        )}
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
      <div className="flex-1 flex items-center justify-center text-red-400 text-sm">
        Failed to load comparison: {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-500 text-sm animate-pulse">
        Loading comparison…
      </div>
    );
  }

  const labelsA = new Set(data.a.nodes.map((n) => n.label));
  const labelsB = new Set(data.b.nodes.map((n) => n.label));
  const onlyA = data.a.nodes.filter((n) => !labelsB.has(n.label));
  const onlyB = data.b.nodes.filter((n) => !labelsA.has(n.label));
  const common = data.a.nodes.filter((n) => labelsB.has(n.label));

  const durA =
    data.a.ended_at && data.a.started_at
      ? (data.a.ended_at - data.a.started_at) * 1000
      : null;
  const durB =
    data.b.ended_at && data.b.started_at
      ? (data.b.ended_at - data.b.started_at) * 1000
      : null;
  const costA = totalCost(data.a);
  const costB = totalCost(data.b);

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0">
      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-slate-700 bg-slate-900 shrink-0">
        <button
          onClick={onClose}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={13} />
          Exit comparison
        </button>
        <span className="text-slate-700">|</span>
        <span className="text-xs text-slate-400">
          <span className="text-sky-300 font-medium">{labelA}</span>
          <span className="mx-2 text-slate-600">vs</span>
          <span className="text-amber-300 font-medium">{labelB}</span>
        </span>
      </div>

      {/* ── Stats row ───────────────────────────────────────────────── */}
      <div className="flex items-start gap-4 px-4 py-3 border-b border-slate-700 bg-slate-900/50 shrink-0">
        <StatCard side="A" graph={data.a} />

        {/* Diff pill */}
        <div className="flex flex-col items-center gap-1.5 px-3 text-center shrink-0">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Diff</div>
          <div className="flex gap-2 text-xs flex-wrap justify-center">
            {common.length > 0 && (
              <span className="text-slate-400">{common.length} common</span>
            )}
            {onlyA.length > 0 && (
              <span className="text-sky-400">{onlyA.length} only A</span>
            )}
            {onlyB.length > 0 && (
              <span className="text-amber-400">{onlyB.length} only B</span>
            )}
          </div>
          {durA !== null && durB !== null && (
            <div
              className={`flex items-center gap-1 text-[10px] ${
                durB > durA ? "text-red-400" : "text-green-400"
              }`}
            >
              <ArrowRight size={10} />
              {durB > durA ? "+" : ""}
              {fmtDur(durB - durA)} duration
            </div>
          )}
          {costA !== null && costB !== null && (
            <div
              className={`flex items-center gap-1 text-[10px] ${
                costB > costA ? "text-red-400" : "text-green-400"
              }`}
            >
              <ArrowRight size={10} />
              {costB > costA ? "+" : ""}
              {fmtCost(costB - costA)} cost
            </div>
          )}
        </div>

        <StatCard side="B" graph={data.b} />
      </div>

      {/* ── Two graphs side by side ──────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">
        {/* Graph A */}
        <div className="flex-1 min-w-0 border-r border-slate-700 flex flex-col">
          <div className="shrink-0 h-6 flex items-center px-3 bg-slate-900/40 border-b border-slate-700 text-[11px] text-sky-400 font-medium">
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
          <div className="shrink-0 h-6 flex items-center px-3 bg-slate-900/40 border-b border-slate-700 text-[11px] text-amber-400 font-medium">
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
