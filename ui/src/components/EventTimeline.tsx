import type { VapEvent } from "../types/events";
import { useRunStore } from "../store/runStore";

// Human-readable labels for event types
const EVENT_LABEL: Record<string, string> = {
  agent_start:  "Agent start",
  agent_end:    "Agent end",
  step_start:   "Step start",
  step_end:     "Step end",
  tool_call:    "Tool call",
  tool_result:  "Tool result",
  llm_call:     "LLM call",
  llm_response: "LLM response",
  error:        "Error",
  state_update: "State update",
};

const EVENT_DOT: Record<string, string> = {
  agent_start:  "bg-indigo-500",
  agent_end:    "bg-indigo-400",
  step_start:   "bg-sky-500",
  step_end:     "bg-sky-400",
  tool_call:    "bg-emerald-500",
  tool_result:  "bg-emerald-400",
  llm_call:     "bg-purple-500",
  llm_response: "bg-purple-400",
  error:        "bg-red-500",
  state_update: "bg-slate-400",
};

interface Props {
  events:    VapEvent[];
  startedAt: number;
}

export function EventTimeline({ events, startedAt }: Props) {
  const selectNode     = useRunStore((s) => s.selectNode);
  const selectedNodeId = useRunStore((s) => s.selectedNodeId);

  return (
    <div className="flex flex-col overflow-y-auto h-full">
      <div className="px-4 py-2 text-xs text-slate-400 uppercase tracking-wider border-b border-slate-700 shrink-0">
        Timeline ({events.length})
      </div>
      <div className="flex-1 overflow-y-auto">
        {events.map((ev) => {
          const isHighlighted = ev.node_id === selectedNodeId;
          return (
            <button
              key={ev.id}
              onClick={() => selectNode(isHighlighted ? null : ev.node_id)}
              title={`${ev.type} — ${ev.node_label}`}
              className={`w-full flex items-center gap-2.5 px-3 py-1.5 border-b border-slate-800 text-left transition-colors ${
                isHighlighted
                  ? "bg-indigo-950/60 border-l-2 border-l-indigo-500"
                  : "hover:bg-slate-800/70"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full shrink-0 ${
                  EVENT_DOT[ev.type] ?? "bg-slate-500"
                }`}
              />
              <span className="text-[10px] text-slate-500 w-14 shrink-0 font-mono tabular-nums text-right">
                +{((ev.timestamp - startedAt) * 1000).toFixed(0)}ms
              </span>
              <span className="text-xs text-slate-300 truncate min-w-0">
                {EVENT_LABEL[ev.type] ?? ev.type}
              </span>
              <span className="text-[10px] text-slate-600 truncate ml-auto shrink-0 max-w-[80px]">
                {ev.node_label}
              </span>
            </button>
          );
        })}
        {events.length === 0 && (
          <div className="px-4 py-6 text-slate-500 text-sm text-center">No events yet</div>
        )}
      </div>
    </div>
  );
}
