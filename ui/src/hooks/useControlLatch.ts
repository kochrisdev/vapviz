import { useCallback, useEffect, useState } from "react";
import type { ControlAction, ControlDesired } from "../lib/runControl";

/**
 * One poll of a live run's control latch, shared by the Theater's control bar and
 * the conversation panel so they don't each poll `GET /runs/{id}/control`. Also
 * owns the writes: `sendAction` (pause/resume/stop) and `sendMessage` (a reply /
 * unprompted steer → `POST /input`). UI-only side channel — not dual-logic.
 *
 * Returns `latch === null` until the first poll lands or when the run isn't live.
 */
export interface ControlLatch {
  desired: string;
  acked: string;
  updated_at: number;
  ended: boolean;
  waiting_for_input: boolean;
  pending_input: boolean;
  question: string | null; // the prompt ask() is currently displaying (Layer 2b)
}

export interface ControlLatchApi {
  latch: ControlLatch | null;
  sendAction: (action: ControlAction) => Promise<void>;
  /** POST a message to the agent's mailbox; resolves true on success. */
  sendMessage: (text: string) => Promise<boolean>;
}

const POLL_MS = 1000;

export function useControlLatch(runId: string, live: boolean): ControlLatchApi {
  const [latch, setLatch] = useState<ControlLatch | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`/runs/${runId}/control`);
      if (r.ok) setLatch(await r.json());
    } catch {
      /* transient — next poll reconciles */
    }
  }, [runId]);

  // Poll while the run is live so pausing…/waiting… and the open question update
  // honestly. Reset to null when it isn't live (a finished run isn't controllable).
  useEffect(() => {
    if (!live) {
      setLatch(null);
      return;
    }
    refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [live, refresh]);

  const sendAction = useCallback(
    async (action: ControlAction) => {
      // Optimistic: reflect the requested desired state immediately.
      const optimistic: ControlDesired =
        action === "pause" ? "paused" : action === "resume" ? "running" : "stopped";
      setLatch((p) => (p ? { ...p, desired: optimistic } : p));
      try {
        const r = await fetch(`/runs/${runId}/control`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action }),
        });
        if (r.ok) setLatch(await r.json());
      } catch {
        /* transient — the poll will reconcile */
      }
    },
    [runId],
  );

  const sendMessage = useCallback(
    async (text: string) => {
      try {
        const r = await fetch(`/runs/${runId}/input`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text }),
        });
        if (r.ok) {
          setLatch(await r.json());
          return true;
        }
      } catch {
        /* transient — the poll will reconcile */
      }
      return false;
    },
    [runId],
  );

  return { latch, sendAction, sendMessage };
}
