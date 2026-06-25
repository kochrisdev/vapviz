import { useEffect, useMemo, useRef } from "react";
import type { GraphNode } from "../types/events";
import { buildScene, type Station } from "../lib/theater";
import { agentSprite, thoughtBubble } from "../lib/avatar";
import { cssColor } from "../lib/cssColor";
import { useTheme } from "../lib/theme";

/**
 * AgentStage — one room of walking pixel agents (UI-ROADMAP Phase 3, §4-F).
 *
 * The shared building block for both views: the per-run Theater renders one
 * full-size stage; the global Floor tiles many `compact` stages as soft run-zones
 * on a single office floor. Given a run's `nodes`, `buildScene` says who's where
 * doing what; characters glide to a desk when active (CSS transition) and the
 * legs shuffle while moving. Driven purely by props, so it animates equally for
 * live SSE updates and scrubbed replay.
 */

const STATION = { llm: { x: 16, y: 24 }, tool: { x: 84, y: 26 } };
const APPROACH = { llm: { x: 16, y: 52 }, tool: { x: 84, y: 54 } };
const WALK_MS = 600; // matches the CSS .vt-char transition (.55s + a hair)

function homePos(i: number, n: number): { x: number; y: number } {
  if (n <= 1) return { x: 50, y: 74 };
  const cols = Math.min(n, 4);
  const col = i % cols, row = Math.floor(i / cols);
  const x = cols === 1 ? 50 : 18 + col * (64 / (cols - 1));
  const y = Math.min(90, 66 + row * 14);
  return { x, y };
}
function posFor(at: Station, i: number, n: number): { x: number; y: number } {
  if (at === "llm") return APPROACH.llm;
  if (at === "tool") return APPROACH.tool;
  return homePos(i, n);
}

function llmGlyph(): string {
  const c = cssColor("--kind-llm"), screen = cssColor("--screen"), b = cssColor("--border-strong");
  return `<svg class="sprite" width="34" height="24" viewBox="0 0 17 12" shape-rendering="crispEdges">`
    + `<rect x="1" y="1" width="15" height="8" fill="${screen}" stroke="${c}" stroke-width=".7"/>`
    + `<rect x="5" y="4" width="1" height="1" fill="${c}"/><rect x="8" y="4" width="1" height="1" fill="${c}"/><rect x="11" y="4" width="1" height="1" fill="${c}"/>`
    + `<rect x="6" y="10" width="5" height="1" fill="${b}"/></svg>`;
}
function toolGlyph(): string {
  const c = cssColor("--kind-tool");
  return `<svg class="sprite" width="30" height="24" viewBox="0 0 15 12" shape-rendering="crispEdges">`
    + `<rect x="3" y="7" width="2" height="2" fill="${c}"/><rect x="5" y="5" width="2" height="2" fill="${c}"/>`
    + `<rect x="7" y="3" width="3" height="2" fill="${c}"/><rect x="9" y="2" width="2" height="2" fill="${c}"/></svg>`;
}

interface Props {
  nodes: GraphNode[];
  /** Compact = smaller desks/sprites/labels, for the Floor's tiled zones. */
  compact?: boolean;
}

export function AgentStage({ nodes, compact = false }: Props) {
  const { theme } = useTheme(); // re-render so token-derived colours refresh on toggle
  const scene = useMemo(() => buildScene(nodes), [nodes]);
  const n = scene.agents.length;

  const placed = scene.agents.map((a, i) => ({ ...a, pos: posFor(a.at, i, n) }));
  const placedKey = placed.map((a) => `${a.id}:${a.pos.x},${a.pos.y}`).join("|");

  const refs = useRef(new Map<string, HTMLDivElement>());
  const prev = useRef(new Map<string, { x: number; y: number }>());
  const timers = useRef(new Map<string, number>());

  // When an agent's slot changes between renders, add the walking class (legs
  // shuffle) and face the direction of travel; CSS transitions the glide.
  useEffect(() => {
    for (const a of placed) {
      const el = refs.current.get(a.id);
      if (!el) continue;
      const before = prev.current.get(a.id);
      if (before && (before.x !== a.pos.x || before.y !== a.pos.y)) {
        const facing = el.querySelector<HTMLElement>(".vt-facing");
        if (facing) facing.style.transform = a.pos.x < before.x ? "scaleX(-1)" : "scaleX(1)";
        el.classList.add("vt-walking");
        const t = timers.current.get(a.id);
        if (t) window.clearTimeout(t);
        timers.current.set(a.id, window.setTimeout(() => el.classList.remove("vt-walking"), WALK_MS));
      }
      prev.current.set(a.id, a.pos);
    }
    for (const id of [...prev.current.keys()]) {
      if (!placed.find((p) => p.id === id)) prev.current.delete(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placedKey, theme]);

  useEffect(() => () => { timers.current.forEach((t) => window.clearTimeout(t)); }, []);

  return (
    <div className={`vt-stage${compact ? " vt-compact" : ""}`}>
      <div className={`vt-station${scene.hotLlm ? " vt-hot" : ""}`} data-kind="llm"
        style={{ left: STATION.llm.x + "%", top: STATION.llm.y + "%" }}>
        <div className="vt-pad" dangerouslySetInnerHTML={{ __html: llmGlyph() }} />
        {!compact && <div className="vt-lbl mono">LLM</div>}
      </div>
      <div className={`vt-station${scene.hotTool ? " vt-hot" : ""}`} data-kind="tool"
        style={{ left: STATION.tool.x + "%", top: STATION.tool.y + "%" }}>
        <div className="vt-pad" dangerouslySetInnerHTML={{ __html: toolGlyph() }} />
        {!compact && <div className="vt-lbl mono">Tool bench</div>}
      </div>

      {placed.map((a) => (
        <div
          key={a.id}
          ref={(el) => { if (el) refs.current.set(a.id, el); else refs.current.delete(a.id); }}
          className="vt-char"
          style={{ left: a.pos.x + "%", top: a.pos.y + "%" }}
        >
          <div className="vt-tag mono">{a.name}</div>
          {a.state === "thinking" && (
            <div className="vt-bubble" dangerouslySetInnerHTML={{ __html: thoughtBubble() }} />
          )}
          <div className="vt-facing" dangerouslySetInnerHTML={{ __html: agentSprite(a.name, a.state) }} />
        </div>
      ))}

      {n === 0 && <div className="vt-empty">No agents yet…</div>}
    </div>
  );
}
