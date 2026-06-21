"""
Run search for vapviz.

A pure predicate over a run graph: does it match a free-text query and/or a set
of structural filters (status, node kind, tool name)? The server composes this
with tag filtering (tags live in the store, not the graph) to power ``GET /search``.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .events import NodeKind, NodeStatus, RunGraph


def _node_haystack(node) -> str:
    """All searchable text for one node: label + stringified input/output."""
    parts = [node.label]
    data = node.data if isinstance(node.data, dict) else {}
    for key in ("input", "output", "error"):
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(value)
        else:
            try:
                parts.append(json.dumps(value, default=str))
            except Exception:  # noqa: BLE001
                parts.append(str(value))
    return "\n".join(parts)


def run_matches(
    graph: RunGraph,
    *,
    query: Optional[str] = None,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    tool: Optional[str] = None,
) -> bool:
    """Return True if *graph* satisfies every supplied filter.

    - ``query``  — case-insensitive substring across the run label and every
      node's label / input / output / error.
    - ``status`` — the run's overall status equals this.
    - ``kind``   — at least one node has this kind (agent/step/tool/llm).
    - ``tool``   — at least one ``tool`` node whose label contains this string.
    """
    if status is not None and graph.status.value != status:
        return False

    if kind is not None and not any(n.kind.value == kind for n in graph.nodes):
        return False

    if tool is not None:
        t = tool.lower()
        if not any(n.kind == NodeKind.TOOL and t in n.label.lower() for n in graph.nodes):
            return False

    if query:
        q = query.lower()
        if q in graph.label.lower():
            return True
        return any(q in _node_haystack(n).lower() for n in graph.nodes)

    return True
