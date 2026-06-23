import type { GraphEdge, GraphNode } from "../types/events";

/**
 * View-layer "Simplified" graph transform (UI-ROADMAP §4-C / Appendix A.4).
 *
 * Hides framework-internal nodes (private methods, dunders, known-internal
 * classes, generic chain/agent/tools wrappers) and re-parents their children to
 * the nearest visible ancestor. NEVER mutates the stored graph — returns a new
 * node/edge set rebuilt from `parent_id` (the tree source of truth). `agent` and
 * `llm` nodes, and real user tools, are never hidden.
 */

const INTERNAL_CLASSES = ["SentenceSplitter", "TokenTextSplitter", "MockEmbedding"];
const GENERIC_WRAPPERS = new Set(["chain", "agent", "tools"]);

export function isInternalNode(node: Pick<GraphNode, "kind" | "label">): boolean {
  if (node.kind === "agent" || node.kind === "llm") return false; // never hide
  const label = (node.label ?? "").trim();

  // Generic LangGraph wrappers (kind === step).
  if (GENERIC_WRAPPERS.has(label.toLowerCase())) return true;
  // Private method / dunder.
  if (label.startsWith("_")) return true;
  if (label.includes("._") || label.includes(".__")) return true;
  // Known-internal class, with or without a method suffix.
  if (INTERNAL_CLASSES.some((c) => label.startsWith(c))) return true;
  // A "tool" that's actually a class method (mislabeled internal).
  if (node.kind === "tool" && label.includes(".")) return true;

  return false;
}

export function simplifyGraph(
  nodes: GraphNode[],
  _edges: GraphEdge[]
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const visible = new Set(nodes.filter((n) => !isInternalNode(n)).map((n) => n.id));

  const nearestVisibleAncestor = (n: GraphNode): string | null => {
    let p = n.parent_id;
    while (p) {
      if (visible.has(p)) return p;
      p = byId.get(p)?.parent_id ?? null;
    }
    return null;
  };

  const vNodes = nodes.filter((n) => visible.has(n.id));
  const vEdges: GraphEdge[] = [];
  for (const n of vNodes) {
    const anc = nearestVisibleAncestor(n);
    if (anc) vEdges.push({ id: `${anc}→${n.id}`, source: anc, target: n.id, kind: "execution" });
  }
  return { nodes: vNodes, edges: vEdges };
}
