import { describe, expect, it } from "vitest";
import type { GraphNode } from "../types/events";
import { PALETTE, WALK, colorway } from "./sprites";
import { callsByAgent, lineFor, stationForCall, type OfficeCall } from "./officeScene";

/* ── sprite data integrity — a ragged row or unknown key corrupts the raster ── */
describe("worker sprite grids", () => {
  it("every frame is 12×16 with constant row widths", () => {
    expect(WALK).toHaveLength(4);
    for (const frame of WALK) {
      expect(frame.w).toBe(12);
      expect(frame.h).toBe(16);
      expect(frame.rows).toHaveLength(16);
      for (const row of frame.rows) expect(row).toHaveLength(12);
    }
  });

  it("every grid key exists in the palette", () => {
    for (const frame of WALK)
      for (const row of frame.rows)
        for (const key of row) expect(PALETTE[key], `key "${key}"`).toBeDefined();
  });
});

describe("colorway", () => {
  it("is deterministic per id and covers all four groups", () => {
    const a = colorway("run-a17f"), b = colorway("run-a17f");
    expect(a).toEqual(b);
    for (const group of ["skin", "hair", "shirt", "pants"] as const) {
      expect(a[group]).toHaveLength(3);
    }
  });

  it("distinguishes different ids", () => {
    const ids = ["run-a17f", "run-9c2e", "run-5b81", "Researcher", "Writer"];
    const keys = new Set(ids.map((id) => JSON.stringify(colorway(id))));
    expect(keys.size).toBeGreaterThan(1);
  });
});

/* ── tool → station keyword mapping ────────────────────────────────────── */
const call = (kind: "llm" | "tool", label: string): OfficeCall => ({
  kind,
  label,
  started: 0,
  running: true,
});

describe("stationForCall", () => {
  it("routes llm calls to the LLM desk", () => {
    expect(stationForCall(call("llm", "gpt-4o"))).toBe("LLM");
  });

  it("keyword-matches tool labels (snake_case, camelCase and prose)", () => {
    expect(stationForCall(call("tool", "search_web"))).toBe("SEARCH");
    expect(stationForCall(call("tool", "wikipedia lookup"))).toBe("SEARCH");
    expect(stationForCall(call("tool", "get_weather"))).toBe("FETCH");
    expect(stationForCall(call("tool", "getWeather"))).toBe("FETCH"); // camelCase split
    expect(stationForCall(call("tool", "http_request"))).toBe("FETCH");
    expect(stationForCall(call("tool", "fetch_web_page"))).toBe("FETCH"); // fetch beats generic "web"
    expect(stationForCall(call("tool", "query_db"))).toBe("DATA");
    expect(stationForCall(call("tool", "get_record"))).toBe("DATA"); // no generic get/post → cabinet
    expect(stationForCall(call("tool", "write_file"))).toBe("DATA");
    expect(stationForCall(call("tool", "print_report"))).toBe("PRINT");
    expect(stationForCall(call("tool", "summarize_findings"))).toBe("PRINT");
  });

  it("falls back deterministically to a tool station for unknown labels", () => {
    const s1 = stationForCall(call("tool", "frobnicate_widget"));
    const s2 = stationForCall(call("tool", "frobnicate_widget"));
    expect(s1).toBe(s2);
    expect(["SEARCH", "FETCH", "DATA", "PRINT"]).toContain(s1);
  });
});

describe("lineFor", () => {
  it("is deterministic and non-empty per agent+station", () => {
    expect(lineFor("Researcher", "SEARCH")).toBe(lineFor("Researcher", "SEARCH"));
    expect(lineFor("Researcher", "FETCH").length).toBeGreaterThan(0);
  });
});

/* ── per-agent call attribution ────────────────────────────────────────── */
function node(p: Partial<GraphNode> & { id: string; kind: GraphNode["kind"]; label: string }): GraphNode {
  return {
    status: "success",
    parent_id: null,
    started_at: 0,
    ended_at: null,
    data: {},
    ...p,
  };
}

describe("callsByAgent", () => {
  it("attributes calls to the nearest cast actor, not an outer supervisor", () => {
    const nodes: GraphNode[] = [
      node({ id: "a1", kind: "agent", label: "agent/Researcher", status: "running", started_at: 1 }),
      node({ id: "s1", kind: "step", label: "step/plan", parent_id: "a1", started_at: 2 }),
      node({ id: "l1", kind: "llm", label: "llm/gpt-4o", parent_id: "a1", started_at: 3 }),
      node({ id: "t1", kind: "tool", label: "tool/search_web", parent_id: "s1", status: "running", started_at: 5 }),
      node({ id: "a2", kind: "agent", label: "agent/Writer", parent_id: "a1", started_at: 6 }),
      node({ id: "t2", kind: "tool", label: "tool/print_report", parent_id: "a2", status: "running", started_at: 7 }),
    ];
    const calls = callsByAgent(nodes);

    const researcher = calls.get("Researcher")!;
    expect(researcher.runningTool?.label).toBe("search_web");
    expect(researcher.recent?.label).toBe("search_web"); // latest started wins over the llm call
    const writer = calls.get("Writer")!;
    expect(writer.runningTool?.label).toBe("print_report");
  });

  it("tracks concurrent running llm and tool calls in separate slots", () => {
    const nodes: GraphNode[] = [
      node({ id: "a1", kind: "agent", label: "agent/Multi", status: "running", started_at: 1 }),
      node({ id: "t1", kind: "tool", label: "tool/search_web", parent_id: "a1", status: "running", started_at: 5 }),
      node({ id: "l1", kind: "llm", label: "llm/gpt-4o", parent_id: "a1", status: "running", started_at: 10 }),
    ];
    const multi = callsByAgent(nodes).get("Multi")!;
    // the later-started llm call must not shadow the running tool call
    expect(multi.runningTool?.label).toBe("search_web");
    expect(multi.runningLlm?.label).toBe("gpt-4o");
    expect(multi.recent?.label).toBe("gpt-4o");
  });

  it("keeps the most recent completed call for lingering", () => {
    const nodes: GraphNode[] = [
      node({ id: "a1", kind: "agent", label: "agent/Solo", status: "running", started_at: 1 }),
      node({ id: "l1", kind: "llm", label: "llm/claude", parent_id: "a1", started_at: 2, ended_at: 3 }),
    ];
    const solo = callsByAgent(nodes).get("Solo")!;
    expect(solo.runningLlm).toBeNull();
    expect(solo.runningTool).toBeNull();
    expect(solo.recent?.kind).toBe("llm");
  });
});
