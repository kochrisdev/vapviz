/**
 * Theater scene model (UI-ROADMAP Phase 3, §4-F).
 *
 * Pure reduction: a run's graph nodes → a coordinate-free "scene" describing the
 * cast and what each agent is doing right now. The view (`TheaterView`) turns
 * this into a room with stations and walking characters; playback feeds it the
 * partial graph from `buildGraphAt`, so the same model drives both live and
 * replayed runs.
 *
 * "Where" is just two shared stations for v1 — an agent walks to `llm` when one
 * of its LLM calls is running, to `tool` when a tool is running, else stays
 * `home`. Coordinates are the view's job, kept out of here so this stays testable.
 */
import type { GraphNode } from "../types/events";
import { isInternalNode } from "./simplify";

/** What a cast member is doing right now (drawn as pose/cue by the stage). */
export type AvatarState = "idle" | "thinking" | "working" | "done" | "error";

/** Strip a leading `kind/` segment from a node label (`agent/Researcher` → `Researcher`). */
export function stripKind(label: string): string {
  const i = label.indexOf("/");
  return i >= 0 ? label.slice(i + 1) : label;
}

export type Station = "llm" | "tool" | "home";

export interface SceneAgent {
  id: string;
  name: string;
  state: AvatarState;
  at: Station;
}

export interface Scene {
  agents: SceneAgent[];
  hotLlm: boolean;
  hotTool: boolean;
}

/**
 * Pick the cast, in order of signal strength:
 *  1. `agent/` label prefix — how vapviz tags real agents (CrewAI →
 *     `agent/Researcher`/`agent/Writer`, Pydantic AI → `agent/weather_agent`).
 *  2. LangGraph nodes carrying the `langgraph_node` marker (set by the LangChain
 *     integration), minus generic `agent`/`tools`/`chain` wrappers — this surfaces
 *     `supervisor`/`math_expert`/`text_expert` as the cast.
 *  3. Agent-kind nodes (the run root), then the first node — so single-agent /
 *     pipeline runs (LlamaIndex, a bare OpenAI agent) show exactly one character
 *     and the stage is never empty.
 *
 * Keying on these explicit markers (not a generic tree walk) is what keeps a
 * pipeline stage or a manual sub-step from being mistaken for an agent.
 */
function langgraphNode(n: GraphNode): string | null {
  const v = n.data?.["langgraph_node"];
  return typeof v === "string" ? v : null;
}

export function actorNodes(nodes: GraphNode[]): GraphNode[] {
  const named = nodes.filter((n) => (n.label ?? "").startsWith("agent/"));
  if (named.length) return named;
  const lg = nodes.filter((n) => langgraphNode(n) && !isInternalNode(n));
  if (lg.length) return lg;
  const agentKind = nodes.filter((n) => n.kind === "agent");
  if (agentKind.length) return agentKind;
  return nodes.length ? [nodes[0]] : [];
}

/** Build the scene from the (possibly partial, during replay) set of graph nodes. */
export function buildScene(nodes: GraphNode[]): Scene {
  const actors = actorNodes(nodes);
  const actorIds = new Set(actors.map((a) => a.id));

  // child index for subtree walks
  const childrenOf = new Map<string, GraphNode[]>();
  for (const n of nodes) {
    if (!n.parent_id) continue;
    (childrenOf.get(n.parent_id) ?? childrenOf.set(n.parent_id, []).get(n.parent_id)!).push(n);
  }

  // Collect the llm/tool calls an actor "owns" — its subtree, stopping at any
  // nested actor (so a supervisor doesn't claim a worker's call).
  type Call = { kind: "llm" | "tool"; started: number; running: boolean };
  const ownedCalls = (actor: GraphNode): Call[] => {
    const out: Call[] = [];
    const stack = [...(childrenOf.get(actor.id) ?? [])];
    while (stack.length) {
      const c = stack.pop()!;
      if (c.id !== actor.id && actorIds.has(c.id)) continue; // stop at a nested actor
      if (c.kind === "llm" || c.kind === "tool") {
        out.push({ kind: c.kind, started: c.started_at ?? 0, running: c.status === "running" });
      }
      stack.push(...(childrenOf.get(c.id) ?? []));
    }
    return out;
  };

  // Group actor nodes by display name: LangGraph re-enters the same node
  // (supervisor/math_expert) many times per run, so collapse those instances
  // into one character whose activity is the union across all its instances.
  const groups = new Map<string, GraphNode[]>();
  for (const a of actors) {
    const name = stripKind(a.label);
    (groups.get(name) ?? groups.set(name, []).get(name)!).push(a);
  }

  let hotLlm = false, hotTool = false;
  const agents: SceneAgent[] = [...groups.entries()].map(([name, insts]) => {
    const calls = insts.flatMap(ownedCalls);
    const running = calls.find((c) => c.running);
    // Linger: while still active, stay at the desk of the most recently started
    // call instead of walking home between calls. Desks only glow for a *running* call.
    const recent = calls.length
      ? calls.reduce((m, c) => (c.started >= m.started ? c : m))
      : null;
    const anyRunning = insts.some((n) => n.status === "running");
    const anyError = insts.some((n) => n.status === "error");
    const anySuccess = insts.some((n) => n.status === "success");

    let state: AvatarState;
    let at: Station;
    if (running) {
      at = running.kind;
      state = running.kind === "llm" ? "thinking" : "working";
      if (running.kind === "llm") hotLlm = true; else hotTool = true;
    } else if (anyRunning && recent) {
      at = recent.kind; // linger at the last desk used (no glow)
      state = recent.kind === "llm" ? "thinking" : "working";
    } else if (anyRunning) {
      at = "home"; state = "thinking"; // active but hasn't hit a desk yet
    } else if (anyError) {
      at = "home"; state = "error";
    } else if (anySuccess) {
      at = "home"; state = "done";
    } else {
      at = "home"; state = "idle";
    }
    return { id: name, name, state, at };
  });

  return { agents, hotLlm, hotTool };
}
