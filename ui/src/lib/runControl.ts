import type { NodeStatus } from "../types/events";

/**
 * Pure UI state for the run control bar (Pause / Resume / Stop).
 *
 * Given the run's control latch (`desired` = what the user asked, `acked` = what
 * the agent has actually done at its last checkpoint) and the run's status, it
 * decides what the bar shows. The `desired`/`acked` split is what lets us show
 * the honest cooperative lag ("pausing…" until the agent reaches a checkpoint).
 *
 * UI-only — NOT part of the dual-logic reducer rule. Mirrors the table in
 * docs/notes/DESIGN-agent-control.md §4. Unit-tested in runControl.test.ts.
 */

export type ControlDesired = "running" | "paused" | "stopped";
export type ControlAction = "pause" | "resume" | "stop";

export interface ControlButton {
  action: ControlAction;
  /** In-flight action (e.g. "pausing…") → render but disable. */
  disabled: boolean;
}

export interface ControlUiState {
  /** False when the run has ended — the bar should render nothing. */
  live: boolean;
  /** Transient status text, or null when running normally. */
  banner: string | null;
  /** Buttons to show, in order. */
  buttons: ControlButton[];
  /** True while the agent is parked in `take_input()` — the bar emphasizes the
   *  message box (sending a message is what unblocks it). */
  awaitingInput: boolean;
}

const TERMINAL: ReadonlySet<NodeStatus> = new Set<NodeStatus>(["success", "error", "stopped"]);

export function controlUiState(
  desired: ControlDesired,
  acked: ControlDesired,
  runStatus: NodeStatus,
  waitingForInput = false,
): ControlUiState {
  // A finished run is not controllable — hide the bar.
  if (TERMINAL.has(runStatus)) return { live: false, banner: null, buttons: [], awaitingInput: false };

  if (desired === "stopped") {
    // Stop requested; waiting for the agent to reach a checkpoint and end. Stop
    // interrupts a waiting-for-input agent too, so this takes precedence.
    return { live: true, banner: "stopping…", buttons: [{ action: "stop", disabled: true }], awaitingInput: false };
  }

  if (waitingForInput) {
    // Agent is blocked in take_input(): a message unblocks it, Stop interrupts
    // it. Pause is hidden — it wouldn't take effect until after the message is
    // received, so offering it here would be misleading.
    return {
      live: true,
      banner: "waiting for your input",
      buttons: [{ action: "stop", disabled: false }],
      awaitingInput: true,
    };
  }

  if (desired === "paused") {
    if (acked === "paused") {
      return {
        live: true,
        banner: "paused",
        buttons: [
          { action: "resume", disabled: false },
          { action: "stop", disabled: false },
        ],
        awaitingInput: false,
      };
    }
    // Pause requested but the agent is still between checkpoints.
    return {
      live: true,
      banner: "pausing…",
      buttons: [
        { action: "pause", disabled: true },
        { action: "stop", disabled: false },
      ],
      awaitingInput: false,
    };
  }

  // Running normally.
  return {
    live: true,
    banner: null,
    buttons: [
      { action: "pause", disabled: false },
      { action: "stop", disabled: false },
    ],
    awaitingInput: false,
  };
}
