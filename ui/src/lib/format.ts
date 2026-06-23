import type { GraphNode } from "../types/events";

/**
 * Humanize a node's raw label for display. The raw label is always preserved
 * by callers (title attr / detail panel); this only changes what's shown.
 *
 * See UI-ROADMAP Appendix A.1. Strips leaked `agent/`/`llm/`/`task/`/`crew/`
 * prefixes, recovers model ids, de-snake/de-camel-cases identifiers, and leaves
 * real tool names (get_temp, add, multiply) and model ids verbatim.
 */
export function formatLabel(node: Pick<GraphNode, "kind" | "label">): string {
  const raw = node.label ?? "";

  // Prefix-based rules apply regardless of node kind (prefixes leak onto steps).
  if (raw.startsWith("llm/")) {
    const rest = raw.slice(4);
    // provider/model -> model id; keep model ids verbatim (don't title-case)
    return rest.includes("/") ? rest.slice(rest.lastIndexOf("/") + 1) : rest;
  }
  if (raw.startsWith("agent/")) return humanize(raw.slice(6));
  if (raw.startsWith("crew/")) {
    const rest = raw.slice(5);
    return rest === "crew" ? "Crew" : humanize(rest);
  }
  if (raw.startsWith("task/")) return `Task: “${truncate(raw.slice(5), 48)}”`;

  // No prefix.
  if (node.kind === "tool") {
    // Class.method internals -> humanized class; real tool names stay verbatim.
    return raw.includes(".") ? humanize(raw.slice(0, raw.indexOf("."))) : raw;
  }
  if (node.kind === "agent") return raw; // root agent labels are already friendly

  // step / default: humanize, collapsing Class.method to the class.
  if (raw.includes(".")) return humanize(raw.slice(0, raw.indexOf(".")));
  return humanize(raw);
}

/** snake/kebab/CamelCase identifier -> sentence-cased words. */
function humanize(s: string): string {
  const spaced = s
    .replace(/[_-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .trim();
  if (!spaced) return s;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}

function truncate(s: string, n: number): string {
  const t = s.trim();
  return t.length > n ? t.slice(0, n - 1).trimEnd() + "…" : t;
}

/**
 * Cost formatter (UI-ROADMAP Appendix A.3). 2 sig-figs in the sub-cent range so
 * tiny runs become comparable instead of all reading `<$0.0001`.
 */
export function formatCost(usd: number | null | undefined): string | null {
  if (usd == null) return null;
  if (usd === 0) return "$0";
  if (usd < 0) return "$0";
  if (usd >= 0.01) return "$" + usd.toFixed(4);
  if (usd >= 0.000001) return "$" + usd.toPrecision(2);
  return "<$0.000001";
}

/** Duration between two epoch-seconds timestamps, human-friendly. */
export function formatDuration(startedAt: number | null, endedAt: number | null): string | null {
  if (startedAt == null || endedAt == null) return null;
  const ms = (endedAt - startedAt) * 1000;
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}
