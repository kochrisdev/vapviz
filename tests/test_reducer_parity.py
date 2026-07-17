"""
DUAL-LOGIC GUARDRAIL — Python half of the cross-impl reducer parity test.

The events->graph reduction is implemented twice: Python `_apply_event_to_graph`
(vapviz/store.py) and TypeScript `applyEventToGraph` (ui/src/store/runStore.ts).
Both are checked against the SAME shared fixtures in tests/fixtures/reducer_parity/.
Change one reducer without the other (or without updating the fixture) and one of
the two suites goes red — drift fails the gate.

The TS half lives in ui/src/store/runStore.parity.test.ts and `normalize()` there
mirrors `_normalize()` here. To add a case: drop another JSON in the fixtures dir —
both suites pick it up automatically (this is the "flexible, grows with the project"
part). If parity logic changes, keep the two `normalize` functions identical.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vapviz.events import NodeStatus, RunGraph, VapEvent
from vapviz.store import _apply_event_to_graph, _total_cost

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reducer_parity"
FIXTURES = sorted(FIXTURE_DIR.glob("*.json"))


def _normalize(graph: RunGraph) -> dict:
    """Reduce a graph to the comparable shape shared with the TS test."""
    return {
        "status": graph.status.value,
        "ended_at": graph.ended_at,
        "nodes": sorted(
            (
                {
                    "id": n.id,
                    "kind": n.kind.value,
                    "label": n.label,
                    "status": n.status.value,
                    "parent_id": n.parent_id,
                    "started_at": n.started_at,
                    "ended_at": n.ended_at,
                }
                for n in graph.nodes
            ),
            key=lambda x: x["id"],
        ),
        "edges": sorted(
            ({"id": e.id, "source": e.source, "target": e.target} for e in graph.edges),
            key=lambda x: x["id"],
        ),
        "total_cost_usd": _total_cost(graph),
    }


def _replay(events: list[dict]) -> RunGraph:
    graph = RunGraph(
        run_id=events[0]["run_id"],
        label=events[0]["node_label"],
        status=NodeStatus.RUNNING,
        started_at=events[0]["timestamp"],
    )
    for raw in events:
        _apply_event_to_graph(graph, VapEvent(**raw))
    return graph


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_python_reducer_matches_fixture(path: Path):
    fixture = json.loads(path.read_text())
    got = _normalize(_replay(fixture["events"]))
    assert got == fixture["expected"], f"{path.name}: Python reducer diverged from fixture"


def test_fixtures_exist():
    assert FIXTURES, "no reducer-parity fixtures found — the guardrail would be a no-op"
