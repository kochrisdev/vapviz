import type { VapEvent } from "../types/events";

/**
 * Derive the agent ↔ user conversation transcript (Layer 2b) from a run's event
 * log. The turns ride the inert `control` events — actions `ask` / `say` (agent)
 * and `input` (user) — so this reads straight from the already-streamed events
 * and works live *and* for a completed run. Pure + unit-tested; the
 * ConversationPanel just renders what this returns. UI-only (not dual-logic).
 */

export interface Turn {
  id: string;
  who: "agent" | "user";
  kind: "ask" | "say" | "input";
  text: string;
  ts: number;
}

const CONVERSATION_ACTIONS = new Set(["ask", "say", "input"]);

export function toTurns(events: VapEvent[]): Turn[] {
  const turns: Turn[] = [];
  for (const ev of events) {
    if (ev.type !== "control") continue;
    const action = String(ev.data?.action ?? "");
    if (!CONVERSATION_ACTIONS.has(action)) continue;
    const text = ev.data?.message;
    if (typeof text !== "string") continue;
    turns.push({
      id: ev.id,
      who: action === "input" ? "user" : "agent",
      kind: action as Turn["kind"],
      text,
      ts: ev.timestamp,
    });
  }
  return turns;
}
