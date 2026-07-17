/**
 * DUAL-LOGIC GUARDRAIL — TypeScript half of the cross-impl reducer parity test.
 *
 * Mirrors tests/test_reducer_parity.py. Both replay the SAME shared fixtures
 * (tests/fixtures/reducer_parity/*.json) through their respective reducers and
 * assert the normalized graph equals the fixture's `expected`. Change one
 * reducer without the other and one suite goes red. Keep `normalize()` here
 * identical to `_normalize()` in the Python test.
 */
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, it, expect } from "vitest";

import { applyEventToGraph, totalLlmCost, type GraphState } from "./runStore";
import { buildGraphAt } from "../lib/replay";
import type { GraphNode, NodeStatus, VapEvent } from "../types/events";

const here = dirname(fileURLToPath(import.meta.url));
const fxDir = join(here, "..", "..", "..", "tests", "fixtures", "reducer_parity");
const fixtures = readdirSync(fxDir)
  .filter((f) => f.endsWith(".json"))
  .map((f) => ({ name: f, data: JSON.parse(readFileSync(join(fxDir, f), "utf8")) }));

function normalize(state: GraphState) {
  return {
    status: state.status,
    ended_at: state.ended_at,
    nodes: state.nodes
      .map((n: GraphNode) => ({
        id: n.id,
        kind: n.kind,
        label: n.label,
        status: n.status,
        parent_id: n.parent_id,
        started_at: n.started_at,
        ended_at: n.ended_at,
      }))
      .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
    edges: state.edges
      .map((e) => ({ id: e.id, source: e.source, target: e.target }))
      .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
    total_cost_usd: totalLlmCost(state.nodes),
  };
}

function replay(events: VapEvent[]): GraphState {
  let state: GraphState = { nodes: [], edges: [], status: "running" as NodeStatus, ended_at: null };
  for (const ev of events) state = applyEventToGraph(state, ev);
  return state;
}

describe("reducer parity (TS half)", () => {
  it("finds shared fixtures", () => {
    expect(fixtures.length).toBeGreaterThan(0);
  });

  for (const { name, data } of fixtures) {
    it(`TS reducer matches fixture: ${data.name ?? name}`, () => {
      expect(normalize(replay(data.events))).toEqual(data.expected);
    });
  }

  // lib/replay.ts's buildGraphAt is a THIRD implementation of the event→graph
  // reduction (it powers the replay scrubber). It only derives nodes + edges
  // (no run status / cost), but its node statuses must agree with the fixtures
  // — a `stopped` node once replayed as `success` because it was missed.
  for (const { name, data } of fixtures) {
    it(`replay buildGraphAt matches fixture nodes: ${data.name ?? name}`, () => {
      const { nodes, edges } = buildGraphAt(data.events as VapEvent[], data.events.length);
      const got = normalize({ nodes, edges, status: "running", ended_at: null } as GraphState);
      expect(got.nodes).toEqual(data.expected.nodes);
      expect(got.edges).toEqual(data.expected.edges);
    });
  }
});
