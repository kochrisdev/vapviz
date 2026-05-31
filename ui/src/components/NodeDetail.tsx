import { useState } from "react";
import { Check, Copy, X } from "lucide-react";
import type { GraphNode, NodeKind } from "../types/events";
import { useRunStore } from "../store/runStore";

// Left-border accent colour per node kind
const KIND_BORDER: Record<NodeKind, string> = {
  agent: "border-l-indigo-500",
  step:  "border-l-sky-500",
  tool:  "border-l-emerald-500",
  llm:   "border-l-purple-500",
};

const KIND_LABEL_COLOR: Record<NodeKind, string> = {
  agent: "text-indigo-400",
  step:  "text-sky-400",
  tool:  "text-emerald-400",
  llm:   "text-purple-400",
};

const STATUS_BADGE: Record<string, string> = {
  running: "bg-amber-500/20 text-amber-300 border border-amber-500/30",
  success: "bg-green-500/20 text-green-300 border border-green-500/30",
  error:   "bg-red-500/20   text-red-300   border border-red-500/30",
  pending: "bg-slate-500/20 text-slate-300  border border-slate-500/30",
};

function formatCost(usd: number): string {
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 0.01)   return `$${usd.toFixed(6)}`;
  return `$${usd.toFixed(4)}`;
}

// ── JSON block with copy button ───────────────────────────────────────────────

function JsonBlock({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false);
  if (value === null || value === undefined) return <span className="text-slate-500">—</span>;

  const text = JSON.stringify(value, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="relative group/json">
      <pre className="text-xs bg-slate-900 rounded p-2 overflow-auto max-h-48 text-slate-300 leading-relaxed">
        {text}
      </pre>
      <button
        onClick={handleCopy}
        title="Copy to clipboard"
        className="absolute top-1.5 right-1.5 p-1 rounded bg-slate-700 text-slate-400 hover:text-white opacity-0 group-hover/json:opacity-100 transition-opacity"
      >
        {copied ? <Check size={11} className="text-green-400" /> : <Copy size={11} />}
      </button>
    </div>
  );
}

// ── Row ───────────────────────────────────────────────────────────────────────

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 items-start">
      <span className="text-slate-500 w-20 shrink-0 text-xs pt-0.5">{label}</span>
      <span className="font-mono text-xs text-slate-200">{children}</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

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

  const output  = node.data.output as Record<string, unknown> | undefined;
  const usage   = output?.usage   as { input_tokens: number; output_tokens: number } | undefined;
  const costUsd = output?.cost_usd as number | undefined;

  return (
    <div
      className={`flex flex-col h-full bg-slate-800 border-l-4 border-l border-slate-700 text-slate-200 text-sm ${KIND_BORDER[node.kind]}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between px-4 py-3 border-b border-slate-700 gap-2">
        <div className="min-w-0">
          <div className={`text-[10px] uppercase tracking-wider font-semibold mb-0.5 ${KIND_LABEL_COLOR[node.kind]}`}>
            {node.kind}
          </div>
          <div className="font-semibold text-slate-100 break-all leading-snug">{node.label}</div>
        </div>
        <button
          onClick={() => selectNode(null)}
          className="text-slate-500 hover:text-white mt-0.5 shrink-0 transition-colors"
        >
          <X size={15} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {/* Status + duration */}
        <div className="flex items-center gap-3 flex-wrap">
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE[node.status] ?? STATUS_BADGE.pending}`}>
            {node.status}
          </span>
          <span className="text-xs text-slate-400 font-mono">{duration}</span>
        </div>

        {/* Token usage */}
        {usage && (
          <Row label="Tokens">
            <span className="text-slate-300">
              {usage.input_tokens.toLocaleString()} in&nbsp;/&nbsp;{usage.output_tokens.toLocaleString()} out
            </span>
          </Row>
        )}

        {/* Cost badge */}
        {costUsd !== undefined && (
          <Row label="Cost">
            <span className="bg-purple-900/50 text-purple-300 px-2 py-0.5 rounded">
              {formatCost(costUsd)}
            </span>
          </Row>
        )}

        {/* Input */}
        {node.data.input !== undefined && (
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">Input</div>
            <JsonBlock value={node.data.input} />
          </div>
        )}

        {/* Output */}
        {node.data.output !== undefined && (
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">Output</div>
            <JsonBlock value={node.data.output} />
          </div>
        )}

        {/* Error */}
        {node.data.error !== undefined && (
          <div>
            <div className="text-[10px] text-red-400 uppercase tracking-wider mb-1.5">Error</div>
            <pre className="text-xs bg-red-950/60 text-red-300 rounded p-2 overflow-auto max-h-48 leading-relaxed">
              {String(node.data.error)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
