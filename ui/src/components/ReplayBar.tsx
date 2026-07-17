import { useEffect } from "react";
import { ChevronLeft, ChevronRight, Pause, Play, X } from "lucide-react";
import type { VapEvent } from "../types/events";

const EVENT_LABEL: Record<string, string> = {
  agent_start: "Agent start", agent_end: "Agent end",
  step_start: "Step start", step_end: "Step end",
  tool_call: "Tool call", tool_result: "Tool result",
  llm_call: "LLM call", llm_response: "LLM response",
  error: "Error", state_update: "State update",
};

interface Props {
  events: VapEvent[];
  startedAt: number;
  index: number;                       // number of events applied (0..events.length)
  setIndex: (i: number) => void;
  playing: boolean;
  setPlaying: (p: boolean) => void;
  onExit: () => void;
}

export function ReplayBar({ events, startedAt, index, setIndex, playing, setPlaying, onExit }: Props) {
  const total = events.length;
  const atEnd = index >= total;
  const current = index > 0 ? events[index - 1] : null;

  // Advance while playing.
  useEffect(() => {
    if (!playing) return;
    if (atEnd) { setPlaying(false); return; }
    const t = setTimeout(() => setIndex(index + 1), 450);
    return () => clearTimeout(t);
  }, [playing, index, atEnd, setIndex, setPlaying]);

  const togglePlay = () => {
    if (atEnd) setIndex(0);           // restart from the beginning
    setPlaying(!playing);
  };

  return (
    <div className="flex items-center gap-3 px-4 py-2 border-t border-border bg-surface shrink-0">
      <span className="text-[10px] px-display text-accent font-semibold shrink-0">
        Replay
      </span>

      <button onClick={() => setIndex(Math.max(0, index - 1))} disabled={index === 0}
        title="Step back"
        className="p-1 rounded text-content-faint hover:text-content disabled:opacity-30">
        <ChevronLeft size={15} />
      </button>

      <button onClick={togglePlay} title={playing ? "Pause" : "Play"}
        className="p-1 rounded bg-accent/15 text-accent hover:bg-accent/25">
        {playing ? <Pause size={15} /> : <Play size={15} />}
      </button>

      <button onClick={() => setIndex(Math.min(total, index + 1))} disabled={atEnd}
        title="Step forward"
        className="p-1 rounded text-content-faint hover:text-content disabled:opacity-30">
        <ChevronRight size={15} />
      </button>

      <input
        type="range" min={0} max={total} value={index}
        onChange={(e) => { setPlaying(false); setIndex(Number(e.target.value)); }}
        className="flex-1 accent-accent cursor-pointer"
      />

      <span className="text-xs text-content-muted font-mono tabular-nums shrink-0 w-16 text-right">
        {index} / {total}
      </span>

      {current && (
        <span className="text-xs text-content shrink-0 w-52 truncate">
          <span className="text-content-faint font-mono tabular-nums mr-2">
            +{((current.timestamp - startedAt) * 1000).toFixed(0)}ms
          </span>
          {EVENT_LABEL[current.type] ?? current.type}
          <span className="text-content-faint"> · {current.node_label}</span>
        </span>
      )}

      <button onClick={onExit} title="Exit replay"
        className="p-1 rounded text-content-faint hover:text-content shrink-0">
        <X size={15} />
      </button>
    </div>
  );
}
