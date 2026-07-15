import { useState } from "react";
import { Check, ChevronRight, Copy, X } from "lucide-react";
import type { GraphNode, NodeKind } from "../types/events";
import { useRunStore } from "../store/runStore";
import { formatCost, formatDuration, formatLabel } from "../lib/format";
import { explainNode } from "../lib/explain";
import { redact } from "../lib/redact";
import { StatusBadge } from "./StatusBadge";

const KIND_TOKEN: Record<NodeKind, string> = {
  agent: "--kind-agent",
  step: "--kind-step",
  tool: "--kind-tool",
  llm: "--kind-llm",
};

// ── chat bubbles ────────────────────────────────────────────────────────────────

const ROLE_LABEL: Record<string, string> = {
  system: "System",
  user: "User",
  human: "User",
  assistant: "Assistant",
  ai: "Assistant",
  tool: "Tool",
};

function normRole(m: Record<string, unknown>): string {
  const r = (m.role ?? m.type) as string | undefined;
  return r ?? "message";
}

function asText(content: unknown): string {
  if (typeof content === "string") return content;
  if (content == null) return "";
  return JSON.stringify(content, null, 2);
}

function ChatBubble({ role, content }: { role: string; content: string }) {
  const isUser = role === "user" || role === "human";
  const isSystem = role === "system";
  const label = ROLE_LABEL[role] ?? role;
  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <span className="text-[10px] px-display text-content-faint mb-0.5">{label}</span>
      <div
        className={`max-w-[95%] rounded-lg px-2.5 py-1.5 text-xs leading-relaxed whitespace-pre-wrap break-words ${
          isSystem
            ? "bg-surface-inset text-content-muted italic w-full"
            : isUser
            ? "bg-accent/15 text-content"
            : "bg-surface-hover text-content"
        }`}
      >
        {String(redact(content))}
      </div>
    </div>
  );
}

// ── JSON block with copy ─────────────────────────────────────────────────────────

function JsonBlock({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false);
  if (value === null || value === undefined) return <span className="text-content-faint">—</span>;

  const text = JSON.stringify(redact(value), null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="relative group/json">
      <pre className="text-xs bg-surface-inset rounded p-2 overflow-auto max-h-48 text-content-muted leading-relaxed">
        {text}
      </pre>
      <button
        onClick={handleCopy}
        title="Copy to clipboard"
        className="absolute top-1.5 right-1.5 p-1 rounded bg-surface-hover text-content-faint hover:text-content opacity-0 group-hover/json:opacity-100 transition-opacity"
      >
        {copied ? <Check size={11} className="text-status-success" /> : <Copy size={11} />}
      </button>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] text-content-faint px-display mb-1.5">{title}</div>
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 items-start">
      <span className="text-content-faint w-20 shrink-0 text-xs pt-0.5">{label}</span>
      <span className="text-xs text-content">{children}</span>
    </div>
  );
}

// ── main component ────────────────────────────────────────────────────────────────

interface Props {
  node: GraphNode;
}

export function NodeDetail({ node }: Props) {
  const selectNode = useRunStore((s) => s.selectNode);
  const [showRaw, setShowRaw] = useState(false);

  const duration =
    formatDuration(node.started_at, node.ended_at) ?? (node.started_at ? "running…" : "—");

  const input = node.data.input as Record<string, unknown> | undefined;
  const output = node.data.output as Record<string, unknown> | undefined;
  // Usage comes from arbitrary user/integration data — never trust its shape.
  // Accept the canonical keys plus the common OpenAI-style aliases.
  const rawUsage = output?.usage as Record<string, unknown> | undefined;
  const asCount = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const tokensIn = asCount(rawUsage?.input_tokens) ?? asCount(rawUsage?.prompt_tokens);
  const tokensOut = asCount(rawUsage?.output_tokens) ?? asCount(rawUsage?.completion_tokens);
  const costUsd = typeof output?.cost_usd === "number" ? output.cost_usd : undefined;

  // Chat rendering when an LLM node carries structured messages.
  const messages =
    node.kind === "llm" && Array.isArray(input?.messages)
      ? (input!.messages as Array<Record<string, unknown>>)
      : null;
  const replyText =
    typeof output?.text === "string"
      ? output.text
      : typeof output?.output === "string"
      ? output.output
      : typeof output?.response === "string"
      ? output.response
      : null;
  const toolNames = Array.isArray(input?.tools)
    ? (input!.tools as unknown[]).map(String).filter(Boolean)
    : null;

  return (
    <div className="flex flex-col h-full bg-surface border-l-4 text-content text-sm" style={{ borderLeftColor: `rgb(var(${KIND_TOKEN[node.kind]}))` }}>
      {/* Header */}
      <div className="flex items-start justify-between px-4 py-3 border-b border-border gap-2">
        <div className="min-w-0">
          <div
            className="text-[10px] px-display mb-0.5"
            style={{ color: `rgb(var(${KIND_TOKEN[node.kind]}))` }}
          >
            {node.kind}
          </div>
          <div className="font-semibold text-content break-words leading-snug" title={node.label}>
            {formatLabel(node)}
          </div>
        </div>
        <button
          onClick={() => selectNode(null)}
          className="text-content-faint hover:text-content mt-0.5 shrink-0 transition-colors"
        >
          <X size={15} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {/* Status + duration */}
        <div className="flex items-center gap-3 flex-wrap">
          <StatusBadge status={node.status} />
          <span className="text-xs text-content-muted font-mono">{duration}</span>
        </div>

        {/* Plain-language "what happened" */}
        <div
          className="rounded-lg px-3 py-2 text-sm leading-relaxed text-content"
          style={{
            background: `rgb(var(${node.status === "error" ? "--status-error" : KIND_TOKEN[node.kind]}) / 0.1)`,
          }}
        >
          {explainNode(node)}
        </div>

        {/* Token usage */}
        {(tokensIn !== null || tokensOut !== null) && (
          <Row label="Tokens">
            <span className="text-content-muted">
              {(tokensIn ?? 0).toLocaleString()} in&nbsp;/&nbsp;{(tokensOut ?? 0).toLocaleString()} out
            </span>
          </Row>
        )}

        {/* Cost */}
        {costUsd !== undefined && (
          <Row label="Cost">
            <span className="bg-kind-llm/15 text-kind-llm px-2 py-0.5 rounded">{formatCost(costUsd)}</span>
          </Row>
        )}

        {/* Tools available to the model */}
        {toolNames && toolNames.length > 0 && (
          <Row label="Tools">
            <span className="flex flex-wrap gap-1">
              {toolNames.map((t) => (
                <span key={t} className="bg-kind-tool/15 text-kind-tool px-1.5 py-0.5 rounded text-[11px]">
                  {t}
                </span>
              ))}
            </span>
          </Row>
        )}

        {/* Conversation (LLM nodes with structured messages) */}
        {messages && (
          <Section title="Conversation">
            <div className="space-y-2">
              {messages.map((m, i) => (
                <ChatBubble key={i} role={normRole(m)} content={asText(m.content)} />
              ))}
              {replyText && <ChatBubble role="assistant" content={replyText} />}
            </div>
          </Section>
        )}

        {/* Reply for LLM nodes without a structured conversation */}
        {!messages && node.kind === "llm" && replyText && (
          <Section title="Reply">
            <div className="bg-surface-hover rounded-lg px-2.5 py-1.5 text-xs leading-relaxed whitespace-pre-wrap break-words text-content">
              {String(redact(replyText))}
            </div>
          </Section>
        )}

        {/* Error message */}
        {node.data.error !== undefined && (
          <Section title="Error">
            <pre className="text-xs bg-status-error/10 text-status-error rounded p-2 overflow-auto max-h-48 leading-relaxed">
              {String(node.data.error)}
            </pre>
          </Section>
        )}

        {/* Raw JSON — progressive disclosure for everyone: plain-language
            explanation above, exact data one click away. */}
        {(input !== undefined || output !== undefined) &&
          (showRaw ? (
            <div className="space-y-3 pt-1">
              <button
                onClick={() => setShowRaw(false)}
                className="flex items-center gap-1 text-[11px] text-content-faint hover:text-content"
              >
                <ChevronRight size={12} className="rotate-90" /> Hide technical details
              </button>
              {input !== undefined && (
                <Section title="Raw input">
                  <JsonBlock value={input} />
                </Section>
              )}
              {output !== undefined && (
                <Section title="Raw output">
                  <JsonBlock value={output} />
                </Section>
              )}
            </div>
          ) : (
            <button
              onClick={() => setShowRaw(true)}
              className="flex items-center gap-1 text-[11px] text-content-faint hover:text-content pt-1"
            >
              <ChevronRight size={12} /> Show technical details
            </button>
          ))}
      </div>
    </div>
  );
}
