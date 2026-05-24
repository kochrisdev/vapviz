import type { VapEvent } from "../types/events";

const EVENT_COLOR: Record<string, string> = {
  agent_start: "bg-indigo-500",
  agent_end: "bg-indigo-400",
  step_start: "bg-sky-500",
  step_end: "bg-sky-400",
  tool_call: "bg-emerald-500",
  tool_result: "bg-emerald-400",
  llm_call: "bg-purple-500",
  llm_response: "bg-purple-400",
  error: "bg-red-500",
  state_update: "bg-slate-400",
};

interface Props {
  events: VapEvent[];
  startedAt: number;
}

export function EventTimeline({ events, startedAt }: Props) {
  return (
    <div className="flex flex-col overflow-y-auto h-full">
      <div className="px-4 py-2 text-xs text-slate-400 uppercase tracking-wider border-b border-slate-700">
        Event timeline ({events.length})
      </div>
      <div className="flex-1 overflow-y-auto">
        {events.map((ev) => (
          <div key={ev.id} className="flex items-center gap-3 px-4 py-1.5 hover:bg-slate-700 border-b border-slate-800">
            <span className={`h-2 w-2 rounded-full shrink-0 ${EVENT_COLOR[ev.type] ?? "bg-slate-500"}`} />
            <span className="text-xs text-slate-400 w-16 shrink-0 font-mono">
              +{((ev.timestamp - startedAt) * 1000).toFixed(0)}ms
            </span>
            <span className="text-xs text-slate-300 truncate">{ev.type}</span>
            <span className="text-xs text-slate-500 truncate ml-auto">{ev.node_label}</span>
          </div>
        ))}
        {events.length === 0 && (
          <div className="px-4 py-6 text-slate-500 text-sm text-center">No events yet</div>
        )}
      </div>
    </div>
  );
}
