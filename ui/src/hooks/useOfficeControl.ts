import { useEffect, useState } from "react";

/**
 * The office's paused/waiting cue for a live run, polled from the control latch.
 *
 * UI-only presentation (like the rest of the Theater) — it drives a visual cue,
 * not any graph logic. Independent of `RunControlBar`'s own poll; both hit the
 * trivial in-memory `GET /runs/{id}/control` endpoint, which is fine for a
 * local-first tool. Returns all-false when the run isn't live.
 *
 * `paused` keys off `acked` (not `desired`), so the office rests only once the
 * agent has actually parked at a checkpoint — matching the "paused" (vs
 * "pausing…") distinction the control bar draws.
 */
export interface OfficeControl {
  paused: boolean; // agent has actually parked (acked === "paused")
  waiting: boolean; // agent is blocked in take_input() waiting for a message
}

const IDLE: OfficeControl = { paused: false, waiting: false };
const POLL_MS = 1000;

export function useOfficeControl(runId: string, live: boolean): OfficeControl {
  const [control, setControl] = useState<OfficeControl>(IDLE);

  useEffect(() => {
    if (!live) {
      setControl(IDLE);
      return;
    }
    let alive = true;
    const poll = async () => {
      try {
        const r = await fetch(`/runs/${runId}/control`);
        if (!r.ok || !alive) return;
        const j = await r.json();
        setControl({ paused: j.acked === "paused", waiting: !!j.waiting_for_input });
      } catch {
        /* transient — next tick reconciles */
      }
    };
    poll();
    const t = setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [runId, live]);

  return control;
}
