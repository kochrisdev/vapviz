import { useEffect, useRef, useState } from "react";
import { useRunStore } from "../store/runStore";
import type { EventType, VapEvent } from "../types/events";

export type StreamStatus = "connected" | "reconnecting";

// SSE named events are silently dropped without a listener, so EVERY VapEvent
// type must appear here. The `satisfies Record<EventType, …>` makes tsc reject
// this file whenever a new EventType is added but not listed.
const EVENT_TYPES = Object.keys({
  agent_start: true,
  agent_end: true,
  step_start: true,
  step_end: true,
  tool_call: true,
  tool_result: true,
  llm_call: true,
  llm_response: true,
  state_update: true,
  control: true,
  error: true,
} satisfies Record<EventType, true>) as EventType[];

// The server emits a "ping" event every 30 s when idle. If neither a ping
// nor a real event arrives within this window, the connection is presumed
// dead and the EventSource is recreated. Must be > the 30 s ping interval
// so a healthy-but-idle stream is never flagged. This is what catches an
// outage the browser never reports — notably the Vite dev proxy, which
// swallows upstream disconnects so `onerror` never fires.
const HEARTBEAT_TIMEOUT_MS = 45_000;

// While reconnecting, retry on this cadence. EventSource does NOT auto-retry
// after an HTTP error (e.g. a 500 while the backend is down) — it closes for
// good — so we drive reconnection ourselves to recover promptly once the
// backend returns. Reconnecting replays full history; the store dedups events
// by id, so no duplication results.
const RETRY_MS = 3_000;

export function useRunStream(runId: string | null): StreamStatus {
  const applyEvent = useRunStore((s) => s.applyEvent);
  const esRef = useRef<EventSource | null>(null);
  const [status, setStatus] = useState<StreamStatus>("connected");

  useEffect(() => {
    if (!runId) return;

    let disposed = false;
    let heartbeat: number | undefined;
    let retry: number | undefined;

    const clearTimers = () => {
      window.clearTimeout(heartbeat);
      window.clearTimeout(retry);
      heartbeat = undefined;
      retry = undefined;
    };

    // Liveness is proven by data actually received (a real event or a ping),
    // never by the socket merely opening — through the dev proxy a new
    // EventSource fires `onopen` even when the backend is down.
    const markAlive = () => {
      if (disposed) return;
      setStatus("connected");
      clearTimers();
      heartbeat = window.setTimeout(onStale, HEARTBEAT_TIMEOUT_MS);
    };

    const onStale = () => {
      if (disposed) return; // healthy stream went silent past the heartbeat
      setStatus("reconnecting");
      connect();
    };

    const scheduleRetry = () => {
      if (disposed) return;
      setStatus("reconnecting");
      if (retry !== undefined) return; // a retry is already pending
      retry = window.setTimeout(() => { retry = undefined; connect(); }, RETRY_MS);
    };

    const handler = (e: MessageEvent) => {
      // VaP's "error" event type collides with EventSource's *native*
      // connection-error event (which has no string data). Ignore those —
      // a connection error must not be mistaken for a live event.
      if (typeof e.data !== "string") return;
      markAlive();
      try {
        applyEvent(JSON.parse(e.data) as VapEvent);
      } catch {
        // malformed — ignore (liveness already recorded)
      }
    };

    const connect = () => {
      if (disposed) return;
      clearTimers();
      esRef.current?.close();
      const es = new EventSource(`/runs/${runId}/events`);
      esRef.current = es;

      es.onerror = scheduleRetry;
      es.addEventListener("ping", markAlive);
      for (const type of EVENT_TYPES) es.addEventListener(type, handler);

      // If no data arrives within the window, treat the stream as dead.
      heartbeat = window.setTimeout(onStale, HEARTBEAT_TIMEOUT_MS);
    };

    connect();

    return () => {
      disposed = true;
      clearTimers();
      esRef.current?.close();
      esRef.current = null;
    };
  }, [runId, applyEvent]);

  return status;
}
