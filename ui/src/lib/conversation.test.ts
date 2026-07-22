import { describe, it, expect } from "vitest";
import { toTurns } from "./conversation";
import type { VapEvent } from "../types/events";

function ev(partial: Partial<VapEvent> & { id: string }): VapEvent {
  return {
    run_id: "r",
    timestamp: 0,
    type: "control",
    node_id: "a1",
    node_kind: "agent",
    node_label: "Agent",
    parent_id: null,
    data: {},
    ...partial,
  } as VapEvent;
}

describe("toTurns", () => {
  it("maps ask/say to agent turns and input to a user turn, in order", () => {
    const turns = toTurns([
      ev({ id: "1", timestamp: 1, data: { action: "ask", message: "Which region?" } }),
      ev({ id: "2", timestamp: 2, data: { action: "input", message: "us-west" } }),
      ev({ id: "3", timestamp: 3, data: { action: "say", message: "Switching." } }),
    ]);
    expect(turns.map((t) => [t.who, t.kind, t.text])).toEqual([
      ["agent", "ask", "Which region?"],
      ["user", "input", "us-west"],
      ["agent", "say", "Switching."],
    ]);
  });

  it("ignores non-conversation control actions and non-control events", () => {
    const turns = toTurns([
      ev({ id: "1", type: "agent_start", data: {} }),
      ev({ id: "2", data: { action: "pause" } }),
      ev({ id: "3", data: { action: "stop" } }),
      ev({ id: "4", data: { action: "say", message: "hi" } }),
    ]);
    expect(turns).toHaveLength(1);
    expect(turns[0].text).toBe("hi");
  });

  it("keeps an empty-string message (a real delivered turn) but drops missing text", () => {
    const turns = toTurns([
      ev({ id: "1", data: { action: "input", message: "" } }),
      ev({ id: "2", data: { action: "ask" } }), // no message → dropped
    ]);
    expect(turns).toHaveLength(1);
    expect(turns[0]).toMatchObject({ who: "user", text: "" });
  });
});
