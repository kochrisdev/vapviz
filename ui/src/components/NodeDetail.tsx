import { X } from "lucide-react";
import type { GraphNode } from "../types/events";
import { useRunStore } from "../store/runStore";

function JsonBlock({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-slate-500">—</span>;
  return (
    <pre className="text-xs bg-slate-900 rounded p-2 overflow-auto max-h-48 text-slate-300">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function formatCost(usd: number): string {
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 0.01)   return `$${usd.toFixed(6)}`;
  return `$${usd.toFixed(4)}`;
}

interface Props {
  node: GraphNode;
}

export function NodeDetail({ node }: Props) {
  const selectNode = useRunStore((s) => s.selectNode);
  const duration =
    node.started_at && node.ended_at
      ? `${((node.ended_at - node.started_at) * 1000).toFixed(1)} ms`
      : node.started_at
      ? "running…"
      : "—";

  const output   = node.data.output as Record<string, unknown> | undefined;
  const usage    = output?.usage   as { input_tokens: number; output_tokens: number } | undefined;
  const costUsd  = output?.cost_usd as number | undefined;

  return (
    <div className="flex flex-col h-full bg-slate-800 border-l border-slate-700 text-slate-200 text-sm">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
        <span className="font-semibold truncate">{node.label}</span>
        <button onClick={() => selectNode(null)} className="text-slate-400 hover:text-white ml-2">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        <Row label="Kind"     value={node.kind} />
        <Row label="Status"   value={node.status} />
        <Row label="Duration" value={duration} />

        {/* Token usage — flat display for LLM nodes */}
        {usage && (
          <div className="flex gap-3">
            <span className="text-slate-400 w-20 shrink-0">Tokens</span>
            <span className="font-mono text-xs">
              {usage.input_tokens.toLocaleString()} in&nbsp;/&nbsp;
              {usage.output_tokens.toLocaleString()} out
            </span>
          </div>
        )}

        {/* Cost badge — only shown when pricing is known */}
        {costUsd !== undefined && (
          <div className="flex gap-3 items-center">
            <span className="text-slate-400 w-20 shrink-0">Cost</span>
            <span className="font-mono text-xs bg-purple-900/50 text-purple-300 px-2 py-0.5 rounded">
              {formatCost(costUsd)}
            </span>
          </div>
        )}

        {node.data.input !== undefined && (
          <div>
            <div className="text-xs text-slate-400 uppercase tracking-wider mb-1">Input</div>
            <JsonBlock value={node.data.input} />
          </div>
        )}

        {node.data.output !== undefined && (
          <div>
            <div className="text-xs text-slate-400 uppercase tracking-wider mb-1">Output</div>
            <JsonBlock value={node.data.output} />
          </div>
        )}

        {node.data.error !== undefined && (
          <div>
            <div className="text-xs text-red-400 uppercase tracking-wider mb-1">Error</div>
            <pre className="text-xs bg-red-950 text-red-300 rounded p-2 overflow-auto max-h-48">
              {String(node.data.error)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3">
      <span className="text-slate-400 w-20 shrink-0">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
