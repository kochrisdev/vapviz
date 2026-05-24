import { useEffect, useRef } from "react";
import { useRunStore } from "../store/runStore";
import type { VapEvent } from "../types/events";

export function useRunStream(runId: string | null) {
  const applyEvent = useRunStore((s) => s.applyEvent);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!runId) return;

    esRef.current?.close();
    const es = new EventSource(`/runs/${runId}/events`);
    esRef.current = es;

    const handler = (e: MessageEvent) => {
      try {
        const event: VapEvent = JSON.parse(e.data);
        applyEvent(event);
      } catch {
        // ping or malformed — ignore
      }
    };

    es.addEventListener("agent_start", handler);
    es.addEventListener("agent_end", handler);
    es.addEventListener("step_start", handler);
    es.addEventListener("step_end", handler);
    es.addEventListener("tool_call", handler);
    es.addEventListener("tool_result", handler);
    es.addEventListener("llm_call", handler);
    es.addEventListener("llm_response", handler);
    es.addEventListener("state_update", handler);
    es.addEventListener("error", handler);

    return () => {
      es.close();
    };
  }, [runId, applyEvent]);
}
