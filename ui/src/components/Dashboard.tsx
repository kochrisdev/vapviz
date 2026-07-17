import { useEffect, useState } from "react";
import { Activity, AlertTriangle, Coins, Cpu, Gauge, Layers, RefreshCw } from "lucide-react";
import type { Metrics, NodeKind } from "../types/events";

// ── formatters ──────────────────────────────────────────────────────────────

function fmtCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.000001) return "<$0.000001";
  if (usd < 0.01) return `$${usd.toPrecision(2)}`;
  if (usd < 1) return `$${usd.toFixed(4)}`;
  return `$${usd.toFixed(2)}`;
}

function fmtDur(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

function fmtNum(n: number): string {
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function fmtPct(rate: number | null): string {
  return rate == null ? "—" : `${(rate * 100).toFixed(0)}%`;
}

const KIND_COLOR: Record<NodeKind, string> = {
  agent: "rgb(var(--kind-agent))",
  step: "rgb(var(--kind-step))",
  tool: "rgb(var(--kind-tool))",
  llm: "rgb(var(--kind-llm))",
};

// ── stat card ─────────────────────────────────────────────────────────────

function StatCard({
  icon,
  label,
  value,
  sub,
  accent = "text-content",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3 flex flex-col gap-1">
      <div className="flex items-center gap-1.5 text-content-faint text-[11px] px-display">
        {icon}
        {label}
      </div>
      <div className={`text-2xl font-semibold tabular-nums ${accent}`}>{value}</div>
      {sub && <div className="text-xs text-content-faint">{sub}</div>}
    </div>
  );
}

// ── cost-over-time bar chart ────────────────────────────────────────────────

function CostChart({ data }: { data: Metrics["cost_over_time"] }) {
  const max = Math.max(...data.map((d) => d.cost_usd), 0);
  const hasCost = max > 0;

  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="text-[11px] px-display text-content-faint mb-3">Cost over time</div>
      {data.length === 0 ? (
        <div className="text-content-faint text-sm py-6 text-center">No runs yet</div>
      ) : (
        <div className="flex items-end gap-1.5 h-32 justify-start">
          {data.map((d) => {
            const pct = hasCost ? (d.cost_usd / max) * 100 : 0;
            return (
              <div
                key={d.date}
                className="flex-1 h-full flex flex-col items-center gap-1 group min-w-0 max-w-[72px]"
                title={`${d.date} · ${fmtCost(d.cost_usd)} · ${d.run_count} run${d.run_count === 1 ? "" : "s"}`}
              >
                <div className="flex-1 w-full flex items-end">
                  <div
                    className="w-full rounded-t bg-gradient-to-t from-accent to-accent-hover opacity-90 group-hover:opacity-100 transition-opacity"
                    style={{ height: `${Math.max(pct, hasCost ? 2 : 0)}%`, minHeight: hasCost ? 2 : 0 }}
                  />
                </div>
                <div className="text-[9px] text-content-faint tabular-nums truncate w-full text-center">
                  {d.date.slice(5)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── by-model table ──────────────────────────────────────────────────────────

function ModelTable({ models }: { models: Metrics["by_model"] }) {
  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="text-[11px] px-display text-content-faint mb-3">By model</div>
      {models.length === 0 ? (
        <div className="text-content-faint text-sm py-6 text-center">No LLM calls recorded</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] px-display text-content-faint text-left">
              <th className="font-medium pb-2">Model</th>
              <th className="font-medium pb-2 text-right">Calls</th>
              <th className="font-medium pb-2 text-right">Tokens</th>
              <th className="font-medium pb-2 text-right">Cost</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.model} className="border-t border-border">
                <td className="py-1.5 text-content font-mono text-xs truncate max-w-[160px]" title={m.model}>
                  {m.model}
                </td>
                <td className="py-1.5 text-right text-content-muted tabular-nums">{m.calls}</td>
                <td className="py-1.5 text-right text-content-muted tabular-nums">
                  {fmtNum(m.input_tokens + m.output_tokens)}
                </td>
                <td className="py-1.5 text-right text-kind-llm tabular-nums font-medium">{fmtCost(m.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── by-kind breakdown ───────────────────────────────────────────────────────

function KindBreakdown({ counts, total }: { counts: Metrics["by_kind"]; total: number }) {
  const rows: { kind: NodeKind; count: number }[] = [
    { kind: "agent", count: counts.agent },
    { kind: "step", count: counts.step },
    { kind: "tool", count: counts.tool },
    { kind: "llm", count: counts.llm },
  ];

  return (
    <div className="bg-surface border border-border rounded-xl px-4 py-3">
      <div className="text-[11px] px-display text-content-faint mb-3">Nodes by kind</div>
      <div className="flex flex-col gap-2.5">
        {rows.map(({ kind, count }) => {
          const pct = total > 0 ? (count / total) * 100 : 0;
          return (
            <div key={kind} className="flex items-center gap-3">
              <span className="text-xs text-content-muted w-12">{kind === "llm" ? "LLM" : kind[0].toUpperCase() + kind.slice(1)}</span>
              <div className="flex-1 h-2.5 bg-surface-inset rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${pct}%`, background: KIND_COLOR[kind] }}
                />
              </div>
              <span className="text-xs text-content-muted tabular-nums w-8 text-right">{count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── main component ──────────────────────────────────────────────────────────

export function Dashboard() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const load = () =>
      fetch("/metrics")
        .then((r) => r.json())
        .then((data: Metrics) => {
          if (active) {
            setMetrics(data);
            setLoading(false);
          }
        })
        .catch(() => active && setLoading(false));
    load();
    const id = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="flex-1 flex flex-col min-w-0">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border bg-surface shrink-0">
        <span className="px-display text-xs text-content">Analytics</span>
        {metrics && (
          <span className="text-xs text-content-faint">
            across {metrics.run_count} run{metrics.run_count === 1 ? "" : "s"}
          </span>
        )}
        <RefreshCw size={12} className={`ml-auto text-content-faint ${loading ? "animate-spin" : ""}`} />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4">
        {!metrics ? (
          <div className="text-content-faint text-sm text-center py-20">Loading metrics…</div>
        ) : metrics.run_count === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
            <Activity size={26} className="text-accent" />
            <p className="text-content-muted text-sm">No runs to analyze yet.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-4 max-w-5xl mx-auto">
            {/* Stat cards — control-room glance */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <StatCard icon={<Layers size={12} />} label="Runs" value={`${metrics.run_count}`} />
              <StatCard
                icon={<Activity size={12} />}
                label="Running"
                value={`${metrics.running_count}`}
                accent={metrics.running_count > 0 ? "text-status-running" : "text-content"}
              />
              <StatCard
                icon={<AlertTriangle size={12} />}
                label="Failed"
                value={`${metrics.error_count}`}
                accent={metrics.error_count > 0 ? "text-status-error" : "text-content"}
              />
              <StatCard
                icon={<Gauge size={12} />}
                label="Success rate"
                value={fmtPct(metrics.success_rate)}
                accent={
                  metrics.success_rate != null && metrics.success_rate >= 0.9
                    ? "text-status-success"
                    : metrics.success_rate != null && metrics.success_rate < 0.5
                    ? "text-status-error"
                    : "text-status-running"
                }
              />
              <StatCard
                icon={<Coins size={12} />}
                label="Total cost"
                value={fmtCost(metrics.total_cost_usd)}
                sub={metrics.avg_cost_usd != null ? `${fmtCost(metrics.avg_cost_usd)} avg` : undefined}
                accent="text-kind-llm"
              />
              <StatCard icon={<Activity size={12} />} label="Avg duration" value={fmtDur(metrics.avg_duration_ms)} />
              <StatCard icon={<Cpu size={12} />} label="LLM calls" value={`${metrics.total_llm_calls}`} />
              <StatCard
                icon={<Cpu size={12} />}
                label="Tokens"
                value={fmtNum(metrics.total_tokens.input + metrics.total_tokens.output)}
                sub={`${fmtNum(metrics.total_tokens.input)} in · ${fmtNum(metrics.total_tokens.output)} out`}
              />
            </div>

            {/* Cost chart */}
            <CostChart data={metrics.cost_over_time} />

            {/* Model table + kind breakdown */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <ModelTable models={metrics.by_model} />
              <KindBreakdown counts={metrics.by_kind} total={metrics.total_nodes} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
