import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import type { VapEvent } from "../types/events";
import { useRunStore } from "../store/runStore";
import { formatLabel } from "../lib/format";

const EVENT_LABEL: Record<string, string> = {
  agent_start: "Agent start",
  agent_end: "Agent end",
  step_start: "Step start",
  step_end: "Step end",
  tool_call: "Tool call",
  tool_result: "Tool result",
  llm_call: "LLM call",
  llm_response: "LLM response",
  error: "Error",
  state_update: "State update",
  control: "Control",
};

// A `control` event's specific meaning lives in data.action (pause/resume/stop).
const CONTROL_LABEL: Record<string, string> = {
  pause: "Paused by user",
  resume: "Resumed by user",
  stop: "Stopped by user",
};

/** Event label, resolving `control` events to their specific action. */
function eventLabel(ev: VapEvent): string {
  if (ev.type === "control") return CONTROL_LABEL[String(ev.data?.action)] ?? "Control";
  return EVENT_LABEL[ev.type] ?? ev.type;
}

const EVENT_DOT: Record<string, string> = {
  agent_start: "--kind-agent",
  agent_end: "--kind-agent",
  step_start: "--kind-step",
  step_end: "--kind-step",
  tool_call: "--kind-tool",
  tool_result: "--kind-tool",
  llm_call: "--kind-llm",
  llm_response: "--kind-llm",
  error: "--status-error",
  state_update: "--content-faint",
  control: "--status-stopped",
};

interface Props {
  events: VapEvent[];
  startedAt: number;
}

/** Clean, full-width event log with its own breathing room (UI-ROADMAP §4-D). */
export function LogsView({ events, startedAt }: Props) {
  const selectNode = useRunStore((s) => s.selectNode);
  const selectedNodeId = useRunStore((s) => s.selectedNodeId);
  const [filter, setFilter] = useState("");

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return events;
    return events.filter(
      (e) => eventLabel(e).toLowerCase().includes(q) || e.node_label.toLowerCase().includes(q)
    );
  }, [events, filter]);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-5">
      <div className="max-w-4xl mx-auto">
        {/* Header + filter */}
        <div className="flex items-center justify-between gap-3 mb-3">
          <h2 className="text-sm font-semibold text-content">
            Event log <span className="text-content-faint font-normal">({shown.length})</span>
          </h2>
          <div className="flex items-center gap-2 bg-surface-inset border border-border rounded px-2 py-1.5 w-64">
            <Search size={12} className="text-content-faint shrink-0" />
            <input
              type="text"
              placeholder="Filter events…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="bg-transparent text-xs text-content placeholder-content-faint outline-none w-full"
            />
            {filter && (
              <button onClick={() => setFilter("")} className="text-content-faint hover:text-content shrink-0">
                <X size={11} />
              </button>
            )}
          </div>
        </div>

        {/* Table */}
        <div className="rounded-xl border border-border bg-surface overflow-hidden">
          <div className="grid grid-cols-[80px_1fr_1.4fr] gap-3 px-4 py-2 border-b border-border text-[10px] px-display text-content-faint">
            <span className="text-right">Time</span>
            <span>Event</span>
            <span>Node</span>
          </div>
          {shown.map((ev) => {
            const isSel = ev.node_id === selectedNodeId;
            return (
              <button
                key={ev.id}
                onClick={() => selectNode(isSel ? null : ev.node_id)}
                className={`w-full grid grid-cols-[80px_1fr_1.4fr] gap-3 px-4 py-2 border-b border-border/50 text-left items-center transition-colors ${
                  isSel ? "bg-accent/10" : "hover:bg-surface-hover"
                }`}
              >
                <span className="text-[11px] text-content-faint font-mono tabular-nums text-right">
                  +{((ev.timestamp - startedAt) * 1000).toFixed(0)}ms
                </span>
                <span className="flex items-center gap-2 min-w-0">
                  <span
                    className="h-1.5 w-1.5 rounded-full shrink-0"
                    style={{ background: `rgb(var(${EVENT_DOT[ev.type] ?? "--content-faint"}))` }}
                  />
                  <span className="text-xs text-content truncate">{eventLabel(ev)}</span>
                </span>
                <span className="text-xs text-content-muted truncate" title={ev.node_label}>
                  {formatLabel({ kind: ev.node_kind, label: ev.node_label })}
                </span>
              </button>
            );
          })}
          {shown.length === 0 && (
            <div className="px-4 py-10 text-content-faint text-sm text-center">
              {events.length === 0 ? "No events yet" : `No events matching “${filter}”`}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
