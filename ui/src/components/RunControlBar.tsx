import { Pause, Play, Square, type LucideIcon } from "lucide-react";
import type { NodeStatus } from "../types/events";
import { controlUiState, type ControlAction, type ControlDesired } from "../lib/runControl";
import type { ControlLatch } from "../hooks/useControlLatch";

/**
 * Pause / Resume / Stop bar for a live, in-process run (Theater tab). Purely
 * presentational: it reads the shared control latch and calls `sendAction`
 * (both from `useControlLatch`, lifted to App so the bar and the conversation
 * panel share one poll). Messaging now lives in the ConversationPanel, so the
 * bar is lifecycle-only. Renders nothing once the run ends.
 * See docs/notes/DESIGN-agent-control.md.
 */

const ICON: Record<ControlAction, LucideIcon> = { pause: Pause, resume: Play, stop: Square };
const LABEL: Record<ControlAction, string> = { pause: "Pause", resume: "Resume", stop: "Stop" };

export function RunControlBar({
  runStatus,
  latch,
  sendAction,
}: {
  runStatus: NodeStatus;
  latch: ControlLatch | null;
  sendAction: (action: ControlAction) => void;
}) {
  const desired = (latch?.desired ?? "running") as ControlDesired;
  const acked = (latch?.acked ?? "running") as ControlDesired;
  const waiting = latch?.waiting_for_input ?? false;
  const ui = controlUiState(desired, acked, runStatus, waiting, latch?.question ?? null);
  if (!ui.live) return null;

  const busyBanner = ui.banner?.endsWith("…");

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 border-b border-border bg-surface-inset shrink-0 flex-wrap">
      <span className="px-display text-[10px] text-content-muted">Agent control</span>
      {ui.buttons.map(({ action, disabled }) => {
        const Icon = ICON[action];
        return (
          <button
            key={action}
            onClick={() => sendAction(action)}
            disabled={disabled}
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
            ui.awaitingInput
              ? "text-status-running animate-pulse"
              : busyBanner
                ? "text-content-faint animate-pulse"
                : "text-content-muted"
          }`}
        >
          {ui.banner}
          {ui.awaitingInput && <span className="text-content-faint"> — reply in the chat panel →</span>}
        </span>
      )}
    </div>
  );
}
