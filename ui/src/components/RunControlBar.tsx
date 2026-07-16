import { useCallback, useEffect, useState } from "react";
import { Pause, Play, Square, type LucideIcon } from "lucide-react";
import type { NodeStatus } from "../types/events";
import { controlUiState, type ControlAction, type ControlDesired } from "../lib/runControl";

/**
 * Pause / Resume / Stop bar for a live, in-process run. Shown in the Theater tab
 * (where a floor-view room click lands). Polls the control latch so the banner
 * honestly shows the cooperative lag ("pausing…" until the agent parks). Renders
 * nothing once the run ends. See docs/notes/DESIGN-agent-control.md.
 */

const POLL_MS = 1000;

interface ControlLatch {
  desired: string;
  acked: string;
  updated_at: number;
  ended: boolean;
}

const ICON: Record<ControlAction, LucideIcon> = { pause: Pause, resume: Play, stop: Square };
const LABEL: Record<ControlAction, string> = { pause: "Pause", resume: "Resume", stop: "Stop" };

export function RunControlBar({ runId, runStatus }: { runId: string; runStatus: NodeStatus }) {
  const [latch, setLatch] = useState<ControlLatch | null>(null);
  const [sending, setSending] = useState(false);

  const live = runStatus === "running";

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`/runs/${runId}/control`);
      if (r.ok) setLatch(await r.json());
    } catch {
      /* transient — next poll reconciles */
    }
  }, [runId]);

  // Poll the latch while the run is live so pausing…/stopping… update honestly.
  useEffect(() => {
    if (!live) return;
    refresh();
    const t = setInterval(refresh, POLL_MS);
    return () => clearInterval(t);
  }, [live, refresh]);

  const send = async (action: ControlAction) => {
    setSending(true);
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
    } finally {
      setSending(false);
    }
  };

  const desired = (latch?.desired ?? "running") as ControlDesired;
  const acked = (latch?.acked ?? "running") as ControlDesired;
  const ui = controlUiState(desired, acked, runStatus);
  if (!ui.live) return null;

  const busyBanner = ui.banner?.endsWith("…");

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 border-b border-border bg-surface-inset shrink-0">
      <span className="px-display text-[10px] text-content-muted">Agent control</span>
      {ui.buttons.map(({ action, disabled }) => {
        const Icon = ICON[action];
        return (
          <button
            key={action}
            onClick={() => send(action)}
            disabled={disabled || sending}
            title={`${LABEL[action]} this run`}
            className={`flex items-center gap-1.5 px-display text-[10px] px-2.5 py-1 border-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
              action === "stop"
                ? "border-status-error/50 text-status-error hover:bg-status-error/15"
                : "border-border text-content hover:bg-surface-hover"
            }`}
          >
            <Icon size={12} /> {LABEL[action]}
          </button>
        );
      })}
      {ui.banner && (
        <span
          className={`px-display text-[10px] ml-1 ${
            busyBanner ? "text-content-faint animate-pulse" : "text-content-muted"
          }`}
        >
          {ui.banner}
        </span>
      )}
    </div>
  );
}
