/**
 * Graph → office wiring for the sprite Theater (pure, testable, no DOM).
 *
 * `buildScene` (theater.ts, unchanged) already says WHO is in the cast and
 * whether each agent is at the llm desk, a tool, or home. This module adds the
 * office-level detail the sprite room needs on top of that:
 *
 *  - which of the tool stations (SEARCH / FETCH / DATA / PRINT) a running tool
 *    call belongs to, by keyword-matching the call's label — with a
 *    deterministic hash fallback so unknown tools still spread across the room;
 *  - per-agent running/most-recent call lookup (label + start time), attributed
 *    by walking up the parent chain to the nearest cast actor — the same
 *    ownership rule as buildScene's subtree walk, from the other end;
 *  - the playful per-station dialogue lines (deterministic per agent+station).
 */
import type { GraphNode } from "../types/events";
import { actorNodes, stripKind } from "./theater";
import type { StationName } from "./officeArt";
import { fnv } from "./sprites";

export interface OfficeCall {
  kind: "llm" | "tool";
  label: string;
  started: number;
  running: boolean;
}

/**
 * Tool-station keyword table, checked in order (first match wins). Specific
 * verbs/nouns come before generic ones: FETCH's distinctive transport words
 * are checked first, then SEARCH, then PRINT, and DATA's broad storage nouns
 * last — so `get_record` lands at the cabinet, not the server racks.
 */
const TOOL_MATCH: [Exclude<StationName, "LLM">, RegExp][] = [
  ["FETCH", /\b(fetch|http|https|url|api|request|download|curl|endpoint|weather|remote)\b/],
  ["SEARCH", /\b(search|google|bing|duckduckgo|web|browse|browser|wiki|wikipedia|lookup|look up|find|retrieve|retrieval|index|scrape|crawl|serp)\b/],
  ["PRINT", /\b(print|report|export|render|publish|summarize|summarise|summary|email|send|output|notify)\b/],
  ["DATA", /\b(db|sql|sqlite|postgres|database|query|table|record|records|store|storage|vault|file|files|read|write|save|load|memory|cache|calc|calculator|compute)\b/],
];
export const TOOL_STATIONS: Exclude<StationName, "LLM">[] = ["SEARCH", "FETCH", "DATA", "PRINT"];

/** Deterministic tool station for labels no keyword matches (spreads unknowns out). */
export function fallbackStation(id: string): Exclude<StationName, "LLM"> {
  return TOOL_STATIONS[fnv(id) % TOOL_STATIONS.length];
}

/** Normalize a call label for word matching (`tool/getWeather` → `tool get weather`). */
function words(label: string): string {
  return label
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2") // split camelCase
    .toLowerCase()
    .replace(/[_\-./:]+/g, " ");
}

/** Map a call to its station: LLM for model calls, else keyword → tool station. */
export function stationForCall(call: OfficeCall): StationName {
  if (call.kind === "llm") return "LLM";
  const w = words(call.label);
  for (const [station, re] of TOOL_MATCH) if (re.test(w)) return station;
  return fallbackStation(call.label);
}

export interface AgentCalls {
  /**
   * Latest-started RUNNING call of each kind, tracked separately: buildScene
   * decides *where* an agent is (`at: "llm" | "tool"`), so the view must be
   * able to pick the running call of that same kind — with one combined slot,
   * a concurrent llm+tool pair could hand the view a call of the wrong kind
   * and strand the agent at a hash-fallback desk with no glow.
   */
  runningLlm: OfficeCall | null;
  runningTool: OfficeCall | null;
  /** The most recently started call overall — where a lingering agent stands. */
  recent: OfficeCall | null;
}

/**
 * Attribute every llm/tool call to its owning cast agent (by display name,
 * matching buildScene's grouping): walk each call's parent chain to the
 * nearest actor node, so a supervisor never claims a worker's call.
 */
export function callsByAgent(nodes: GraphNode[]): Map<string, AgentCalls> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const actors = actorNodes(nodes);
  const nameOf = new Map(actors.map((a) => [a.id, stripKind(a.label)]));

  const out = new Map<string, AgentCalls>();
  for (const n of nodes) {
    if (n.kind !== "llm" && n.kind !== "tool") continue;
    if (nameOf.has(n.id)) continue; // an actor is never its own call
    // nearest actor ancestor
    let owner: string | null = null;
    const seen = new Set<string>([n.id]);
    let p = n.parent_id ? byId.get(n.parent_id) : undefined;
    while (p && !seen.has(p.id)) {
      const name = nameOf.get(p.id);
      if (name !== undefined) { owner = name; break; }
      seen.add(p.id);
      p = p.parent_id ? byId.get(p.parent_id) : undefined;
    }
    if (owner === null) continue;

    const call: OfficeCall = {
      kind: n.kind,
      label: stripKind(n.label ?? ""),
      started: n.started_at ?? 0,
      running: n.status === "running",
    };
    const cur = out.get(owner) ?? { runningLlm: null, runningTool: null, recent: null };
    if (!cur.recent || call.started >= cur.recent.started) cur.recent = call;
    if (call.running) {
      const slot = call.kind === "llm" ? "runningLlm" : "runningTool";
      if (!cur[slot] || call.started >= cur[slot]!.started) cur[slot] = call;
    }
    out.set(owner, cur);
  }
  return out;
}

/* ── dialogue — short / fun / informative, a couple variants per station
      (tone locked PLAYFUL by Nick, 2026-07-01) ──────────────────────────── */
const DIALOGUE: Record<StationName, string[]> = {
  LLM: ["thinking it through", "connecting the dots", "reasoning hard"],
  SEARCH: ["scouring the web", "googling furiously", "hunting for sources"],
  FETCH: ["phoning the API", "fetching the data", "grabbing the payload"],
  DATA: ["querying the DB", "digging the records", "reading the vault"],
  PRINT: ["printing the report", "spooling the pages", "warming up"],
};
export const ERROR_LINES = ["hit a snag", "ran into an error"];

/** Deterministic playful line for an agent working at a station. */
export function lineFor(id: string, station: StationName): string {
  const a = DIALOGUE[station] ?? ["working…"];
  return a[fnv(id + station) % a.length];
}

/** Deterministic error line, shown when an agent's run errored. */
export function errorLineFor(id: string): string {
  return ERROR_LINES[fnv(id) % ERROR_LINES.length];
}
