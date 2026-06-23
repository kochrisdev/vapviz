import type { NodeKind, NodeStatus } from "../types/events";

/**
 * Resolve a CSS-var design token to a concrete `rgb(...)` string.
 *
 * ReactFlow needs concrete colours for edge strokes, markers, the minimap and
 * the background dots (it can't always resolve `var()` inside SVG <defs>). Read
 * the computed value off the document root and rebuild the colour; callers
 * recompute on theme change by keying a useMemo on the current theme.
 */
export function cssColor(token: string, alpha = 1): string {
  if (typeof window === "undefined") return "#000";
  const channels = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  if (!channels) return "#000";
  return alpha === 1 ? `rgb(${channels})` : `rgb(${channels} / ${alpha})`;
}

export const KIND_TOKEN: Record<NodeKind, string> = {
  agent: "--kind-agent",
  step: "--kind-step",
  tool: "--kind-tool",
  llm: "--kind-llm",
};

export const STATUS_TOKEN: Record<NodeStatus, string> = {
  pending: "--status-pending",
  running: "--status-running",
  success: "--status-success",
  error: "--status-error",
};
