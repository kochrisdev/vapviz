"""
Plain-language, template-generated run summaries.

``summarize_run`` is a pure function over a :class:`RunGraph` — deterministic,
no LLM involved (an LLM-narrated summary would cost the user money on every
view). Sibling to ``metrics.py``; surfaced on each ``RunSummary`` (sidebar
subtitle) and reusable by the CLI / report exports.

The grammar mirrors the UI's ``ui/src/lib/summary.ts`` (Appendix A.2):

    {root_label} answered "{primary_input}" — {n} model call(s) ({models}),
    {n} tool(s) ({tools}), {status_clause} in {duration}, {cost}.

NOTE — dual-logic: this intentionally parallels ``summary.ts``. Keep the two in
sync if the grammar changes. The UI uses the TS version for the live Story view
(it has full node data); the API serves this version for the run list.
"""
from __future__ import annotations

import math
from typing import Optional

from .events import NodeKind, NodeStatus, RunGraph


# ---------------------------------------------------------------------------
# Small formatting helpers (mirror format.ts / Appendix A.3)
# ---------------------------------------------------------------------------

_INTERNAL_CLASSES = ("SentenceSplitter", "TokenTextSplitter", "MockEmbedding")
_GENERIC_WRAPPERS = {"chain", "agent", "tools"}


def _is_internal(kind: NodeKind, label: str) -> bool:
    """Framework-internal node? Mirrors ui/src/lib/simplify.ts (Appendix A.4)."""
    if kind in (NodeKind.AGENT, NodeKind.LLM):
        return False
    label = (label or "").strip()
    if label.lower() in _GENERIC_WRAPPERS:
        return True
    if label.startswith("_") or "._" in label or ".__" in label:
        return True
    if any(label.startswith(c) for c in _INTERNAL_CLASSES):
        return True
    if kind == NodeKind.TOOL and "." in label:
        return True
    return False


def _strip_model(label: str) -> str:
    """``llm/openai/gpt-4o-mini`` / ``openai/gpt-4o-mini`` -> ``gpt-4o-mini``."""
    if label.startswith("llm/"):
        label = label[4:]
    if "/" in label:
        label = label.rsplit("/", 1)[-1]
    return label


def _format_cost(usd: Optional[float]) -> Optional[str]:
    if usd is None or usd <= 0:
        return None
    if usd >= 0.01:
        return f"${usd:.4f}"
    if usd >= 0.000001:
        # 2 significant figures in fixed notation (matches JS toPrecision(2)).
        decimals = -math.floor(math.log10(usd)) + 1
        return f"${usd:.{decimals}f}"
    return "<$0.000001"


def _format_duration(started: Optional[float], ended: Optional[float]) -> Optional[str]:
    if started is None or ended is None:
        return None
    ms = (ended - started) * 1000
    if ms < 1000:
        return f"{ms:.0f} ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f} s"
    m = int(ms // 60_000)
    s = round((ms % 60_000) / 1000)
    return f"{m}m {s}s"


def _clip(s: str, n: int) -> str:
    s = s.strip()
    return (s[: n - 1].rstrip() + "…") if len(s) > n else s


def _join_list(xs: list[str], max_items: int = 3) -> str:
    if not xs:
        return ""
    if len(xs) <= max_items:
        return ", ".join(xs)
    return f"{', '.join(xs[:max_items])} +{len(xs) - max_items}"


def _uniq(xs: list[str]) -> list[str]:
    seen: list[str] = []
    for x in xs:
        if x and x not in seen:
            seen.append(x)
    return seen


def _primary_input(graph: RunGraph) -> Optional[str]:
    """The first user-facing input we can find (prompt or last user message)."""
    for n in graph.nodes:
        if _is_internal(n.kind, n.label):
            continue
        inp = n.data.get("input") if isinstance(n.data, dict) else None
        if not isinstance(inp, dict):
            continue
        prompt = inp.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            return prompt.strip()
        messages = inp.get("messages")
        if isinstance(messages, list):
            for m in reversed(messages):
                if not isinstance(m, dict):
                    continue
                if m.get("role") in ("user",) or m.get("type") in ("human",):
                    content = m.get("content")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
    return None


def _status_clause(status: NodeStatus) -> str:
    if status == NodeStatus.SUCCESS:
        return "succeeded"
    if status == NodeStatus.ERROR:
        return "failed"
    return "running"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def summarize_run(graph: RunGraph) -> str:
    """Return a one-line plain-language summary of *graph*."""
    root = next((n for n in graph.nodes if n.parent_id is None), None)
    title = (root.label if root else graph.label) or graph.label

    llm_nodes = [n for n in graph.nodes if n.kind == NodeKind.LLM]
    # Count only real user tools — framework-internal "tools" (e.g.
    # MockEmbedding._get_text_embedding) are noise (mirrors the Simplified view).
    tool_nodes = [
        n for n in graph.nodes if n.kind == NodeKind.TOOL and not _is_internal(n.kind, n.label)
    ]

    models = _uniq(
        [
            _strip_model(
                str((n.data.get("input") or {}).get("model") or n.label)
                if isinstance(n.data, dict)
                else n.label
            )
            for n in llm_nodes
        ]
    )
    tool_names = _uniq([n.label for n in tool_nodes])

    total_cost = 0.0
    has_cost = False
    for n in llm_nodes:
        out = n.data.get("output") if isinstance(n.data, dict) else None
        cost = out.get("cost_usd") if isinstance(out, dict) else None
        if isinstance(cost, (int, float)):
            total_cost += cost
            has_cost = True

    head = title
    primary = _primary_input(graph)
    if primary:
        head += f' answered “{_clip(primary, 60)}”'

    clauses: list[str] = []
    if llm_nodes:
        models_str = f" ({_join_list(models)})" if models else ""
        clauses.append(f"{len(llm_nodes)} model call{'' if len(llm_nodes) == 1 else 's'}{models_str}")
    if tool_nodes:
        tools_str = f" ({_join_list(tool_names)})" if tool_names else ""
        clauses.append(f"{len(tool_nodes)} tool{'' if len(tool_nodes) == 1 else 's'}{tools_str}")

    tail = _status_clause(graph.status)
    dur = _format_duration(graph.started_at, graph.ended_at)
    if dur:
        tail += f" in {dur}"
    cost = _format_cost(total_cost if has_cost else None)
    if cost:
        tail += f", {cost}"
    clauses.append(tail)

    return f"{head} — {', '.join(clauses)}."
