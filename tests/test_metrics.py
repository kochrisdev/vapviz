"""Tests for vap/metrics.py — cross-run analytics aggregation + /metrics endpoint."""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from vap.events import (
    EventType,
    GraphNode,
    NodeKind,
    NodeStatus,
    RunGraph,
    VapEvent,
)
from vap.metrics import compute_metrics
from vap.server import create_app
from vap.store import MemoryStore


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

# 2026-01-02 00:00:00 UTC and one day later
DAY1 = 1767312000.0
DAY2 = DAY1 + 86400.0


def _llm_node(model: str, in_tok: int, out_tok: int, cost: float | None) -> GraphNode:
    output: dict = {"usage": {"input_tokens": in_tok, "output_tokens": out_tok}}
    if cost is not None:
        output["cost_usd"] = cost
    return GraphNode(
        id=uuid.uuid4().hex[:12],
        kind=NodeKind.LLM,
        label=f"llm/{model}",
        status=NodeStatus.SUCCESS,
        data={"input": {"model": model}, "output": output},
    )


def _run(
    *,
    status: NodeStatus = NodeStatus.SUCCESS,
    started_at: float = DAY1,
    duration_s: float | None = 1.0,
    nodes: list[GraphNode] | None = None,
) -> RunGraph:
    ended_at = started_at + duration_s if duration_s is not None else None
    root = GraphNode(
        id=uuid.uuid4().hex[:12],
        kind=NodeKind.AGENT,
        label="agent",
        status=status,
        started_at=started_at,
        ended_at=ended_at,
    )
    return RunGraph(
        run_id=uuid.uuid4().hex[:12],
        label="run",
        status=status,
        nodes=[root] + (nodes or []),
        started_at=started_at,
        ended_at=ended_at,
    )


# ---------------------------------------------------------------------------
# compute_metrics — empty / trivial
# ---------------------------------------------------------------------------

class TestEmpty:
    def test_no_runs(self):
        m = compute_metrics([])
        assert m.run_count == 0
        assert m.success_rate is None
        assert m.avg_cost_usd is None
        assert m.avg_duration_ms is None
        assert m.total_cost_usd == 0.0
        assert m.by_model == []
        assert m.cost_over_time == []

    def test_single_run_no_llm(self):
        m = compute_metrics([_run()])
        assert m.run_count == 1
        assert m.success_count == 1
        assert m.success_rate == 1.0
        assert m.total_llm_calls == 0
        assert m.total_cost_usd == 0.0
        assert m.avg_cost_usd is None          # no run contributed cost
        assert m.by_kind.agent == 1
        assert m.total_nodes == 1


# ---------------------------------------------------------------------------
# Status / success rate
# ---------------------------------------------------------------------------

class TestStatus:
    def test_success_rate_excludes_running(self):
        m = compute_metrics([
            _run(status=NodeStatus.SUCCESS),
            _run(status=NodeStatus.ERROR),
            _run(status=NodeStatus.RUNNING, duration_s=None),
        ])
        assert m.success_count == 1
        assert m.error_count == 1
        assert m.running_count == 1
        # 1 success out of 2 completed (running excluded)
        assert m.success_rate == 0.5

    def test_all_running_has_no_rate(self):
        m = compute_metrics([_run(status=NodeStatus.RUNNING, duration_s=None)])
        assert m.success_rate is None


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------

class TestDuration:
    def test_avg_duration_over_completed(self):
        m = compute_metrics([
            _run(duration_s=1.0),    # 1000 ms
            _run(duration_s=3.0),    # 3000 ms
            _run(duration_s=None),   # no duration → excluded from avg
        ])
        assert m.total_duration_ms == 4000.0
        assert m.avg_duration_ms == 2000.0


# ---------------------------------------------------------------------------
# Cost / tokens / model breakdown
# ---------------------------------------------------------------------------

class TestCostAndModels:
    def test_single_llm_run(self):
        run = _run(nodes=[_llm_node("gpt-4o", 100, 50, 0.002)])
        m = compute_metrics([run])
        assert m.total_llm_calls == 1
        assert m.total_tokens.input == 100
        assert m.total_tokens.output == 50
        assert m.total_cost_usd == 0.002
        assert m.avg_cost_usd == 0.002
        assert len(m.by_model) == 1
        assert m.by_model[0].model == "gpt-4o"
        assert m.by_model[0].calls == 1
        assert m.by_model[0].cost_usd == 0.002

    def test_model_breakdown_sorted_by_cost(self):
        run = _run(nodes=[
            _llm_node("cheap", 10, 10, 0.0001),
            _llm_node("expensive", 1000, 500, 0.05),
            _llm_node("expensive", 200, 100, 0.01),
        ])
        m = compute_metrics([run])
        assert [s.model for s in m.by_model] == ["expensive", "cheap"]
        exp = m.by_model[0]
        assert exp.calls == 2
        assert exp.cost_usd == pytest.approx(0.06)
        assert exp.input_tokens == 1200
        assert exp.output_tokens == 600

    def test_cost_aggregated_across_runs(self):
        runs = [
            _run(nodes=[_llm_node("m", 10, 10, 0.01)]),
            _run(nodes=[_llm_node("m", 10, 10, 0.03)]),
        ]
        m = compute_metrics(runs)
        assert m.total_cost_usd == pytest.approx(0.04)
        assert m.avg_cost_usd == pytest.approx(0.02)

    def test_llm_without_cost_counts_calls_only(self):
        run = _run(nodes=[_llm_node("free-model", 5, 5, None)])
        m = compute_metrics([run])
        assert m.total_llm_calls == 1
        assert m.total_cost_usd == 0.0
        assert m.avg_cost_usd is None       # no run contributed cost
        assert m.by_model[0].calls == 1

    def test_model_falls_back_to_label(self):
        node = GraphNode(
            id=uuid.uuid4().hex[:12],
            kind=NodeKind.LLM,
            label="llm/claude-3-5-sonnet",
            status=NodeStatus.SUCCESS,
            data={"output": {"usage": {"input_tokens": 1, "output_tokens": 1}}},
        )
        m = compute_metrics([_run(nodes=[node])])
        assert m.by_model[0].model == "claude-3-5-sonnet"


# ---------------------------------------------------------------------------
# Cost over time
# ---------------------------------------------------------------------------

class TestCostOverTime:
    def test_daily_buckets_chronological(self):
        runs = [
            _run(started_at=DAY2, nodes=[_llm_node("m", 1, 1, 0.02)]),
            _run(started_at=DAY1, nodes=[_llm_node("m", 1, 1, 0.01)]),
            _run(started_at=DAY1, nodes=[_llm_node("m", 1, 1, 0.03)]),
        ]
        m = compute_metrics(runs)
        assert len(m.cost_over_time) == 2
        d1, d2 = m.cost_over_time
        assert d1.date < d2.date                 # chronological
        assert d1.run_count == 2
        assert d1.cost_usd == pytest.approx(0.04)
        assert d2.run_count == 1
        assert d2.cost_usd == pytest.approx(0.02)


# ---------------------------------------------------------------------------
# Kind counts
# ---------------------------------------------------------------------------

class TestKindCounts:
    def test_counts_every_kind(self):
        nodes = [
            GraphNode(id="a", kind=NodeKind.STEP, label="s"),
            GraphNode(id="b", kind=NodeKind.TOOL, label="t"),
            _llm_node("m", 1, 1, 0.0),
        ]
        m = compute_metrics([_run(nodes=nodes)])
        assert m.by_kind.agent == 1   # the root
        assert m.by_kind.step == 1
        assert m.by_kind.tool == 1
        assert m.by_kind.llm == 1
        assert m.total_nodes == 4


# ---------------------------------------------------------------------------
# /metrics endpoint
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client():
    store = MemoryStore()
    app = create_app(store=store)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, store


def _seed_llm_run(store: MemoryStore, model="gpt-4o", cost=0.005) -> str:
    run_id = uuid.uuid4().hex[:12]
    root_id = uuid.uuid4().hex[:12]
    llm_id = uuid.uuid4().hex[:12]

    def ev(type, node_id, kind, label, parent_id=None, data=None):
        return VapEvent(
            id=uuid.uuid4().hex[:12],
            run_id=run_id,
            timestamp=time.time(),
            type=type,
            node_id=node_id,
            node_kind=kind,
            node_label=label,
            parent_id=parent_id,
            data=data or {},
        )

    store.add_event(ev(EventType.AGENT_START, root_id, NodeKind.AGENT, "Agent", data={"label": "Agent"}))
    store.add_event(ev(EventType.LLM_CALL, llm_id, NodeKind.LLM, f"llm/{model}", parent_id=root_id,
                       data={"input": {"model": model}}))
    store.add_event(ev(EventType.LLM_RESPONSE, llm_id, NodeKind.LLM, f"llm/{model}", parent_id=root_id,
                       data={"output": {"usage": {"input_tokens": 120, "output_tokens": 60},
                                        "cost_usd": cost}}))
    store.add_event(ev(EventType.AGENT_END, root_id, NodeKind.AGENT, "Agent"))
    return run_id


class TestMetricsEndpoint:
    def test_empty(self, app_client):
        client, _ = app_client
        r = client.get("/metrics")
        assert r.status_code == 200
        body = r.json()
        assert body["run_count"] == 0
        assert body["by_model"] == []

    def test_with_llm_runs(self, app_client):
        client, store = app_client
        _seed_llm_run(store, model="gpt-4o", cost=0.005)
        _seed_llm_run(store, model="gpt-4o", cost=0.003)

        r = client.get("/metrics")
        assert r.status_code == 200
        body = r.json()
        assert body["run_count"] == 2
        assert body["total_llm_calls"] == 2
        assert body["total_tokens"]["input"] == 240
        assert body["total_cost_usd"] == pytest.approx(0.008)
        assert body["by_model"][0]["model"] == "gpt-4o"
        assert body["by_model"][0]["calls"] == 2
        assert body["success_rate"] == 1.0
