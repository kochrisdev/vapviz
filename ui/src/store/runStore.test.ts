import { beforeEach, describe, expect, it } from "vitest";
import { useRunStore } from "./runStore";
import type { VapEvent } from "../types/events";

// Regression: streamed runs used to keep the run id as their label forever —
// applyEvent never read agent_start's node_label (only the Building's
// setRunGraph poll path set a real one), so the header/Story title showed hex.

function ev(partial: Partial<VapEvent>): VapEvent {
  return {
    id: partial.id ?? Math.random().toString(36).slice(2),
    run_id: "run-1",
    timestamp: 1,
    type: "agent_start",
    node_id: "n1",
    node_kind: "agent",
    node_label: "Research Agent",
    parent_id: null,
    data: {},
    ...partial,
  };
}

describe("applyEvent run label", () => {
  beforeEach(() => {
    useRunStore.setState({ runStates: {}, runs: [] });
  });

  it("sets the run label from agent_start", () => {
    useRunStore.getState().applyEvent(ev({ type: "agent_start", node_label: "Research Agent" }));
    expect(useRunStore.getState().runStates["run-1"].label).toBe("Research Agent");
  });

  it("keeps the run id placeholder until agent_start arrives, then upgrades", () => {
    useRunStore
      .getState()
      .applyEvent(ev({ id: "e1", type: "tool_call", node_kind: "tool", node_id: "t1", node_label: "search_web", parent_id: "n1" }));
    expect(useRunStore.getState().runStates["run-1"].label).toBe("run-1");

    useRunStore.getState().applyEvent(ev({ id: "e2", type: "agent_start", node_label: "Research Agent" }));
    expect(useRunStore.getState().runStates["run-1"].label).toBe("Research Agent");
  });

  it("does not let later events overwrite the label", () => {
    useRunStore.getState().applyEvent(ev({ id: "e1", type: "agent_start", node_label: "Research Agent" }));
    useRunStore
      .getState()
      .applyEvent(ev({ id: "e2", type: "tool_call", node_kind: "tool", node_id: "t1", node_label: "search_web", parent_id: "n1" }));
    expect(useRunStore.getState().runStates["run-1"].label).toBe("Research Agent");
  });
});
