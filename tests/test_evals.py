"""Tests for vapviz/evals.py — checks, eval_run, declarative specs, and the endpoint."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from vapviz.evals import (
    custom,
    eval_run,
    judge,
    max_cost,
    max_latency,
    max_tokens,
    no_errors,
    output_contains,
    run_checks,
)
from vapviz.events import GraphNode, NodeKind, NodeStatus, RunGraph
from vapviz.server import create_app
from vapviz.store import MemoryStore
from vapviz.tracer import Tracer


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _llm(model="gpt-4o", in_tok=100, out_tok=50, cost=0.01, text="the summary is ready"):
    return GraphNode(
        id=uuid.uuid4().hex[:12], kind=NodeKind.LLM, label=f"llm/{model}",
        status=NodeStatus.SUCCESS,
        data={"input": {"model": model},
              "output": {"text": text,
                         "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
                         "cost_usd": cost}},
    )


def _graph(*, duration_s=1.0, status=NodeStatus.SUCCESS, nodes=()):
    ended = 100.0 + duration_s if duration_s is not None else None
    root = GraphNode(id="r", kind=NodeKind.AGENT, label="agent", status=status,
                     started_at=100.0, ended_at=ended)
    return RunGraph(run_id="run1", label="agent", status=status,
                    nodes=[root, *nodes], started_at=100.0, ended_at=ended)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

class TestChecks:
    def test_max_cost_pass_and_fail(self):
        g = _graph(nodes=[_llm(cost=0.01)])
        assert eval_run(g, [max_cost(0.02)]).passed
        assert not eval_run(g, [max_cost(0.005)]).passed

    def test_max_latency(self):
        assert eval_run(_graph(duration_s=1.0), [max_latency(3.0)]).passed
        assert not eval_run(_graph(duration_s=5.0), [max_latency(3.0)]).passed

    def test_max_latency_no_duration_fails(self):
        assert not eval_run(_graph(duration_s=None), [max_latency(1.0)]).passed

    def test_max_tokens(self):
        g = _graph(nodes=[_llm(in_tok=600, out_tok=600)])
        assert not eval_run(g, [max_tokens(1000)]).passed
        assert eval_run(g, [max_tokens(2000)]).passed

    def test_no_errors(self):
        ok = _graph(nodes=[_llm()])
        assert eval_run(ok, [no_errors()]).passed
        bad = _graph(nodes=[GraphNode(id="x", kind=NodeKind.TOOL, label="boom",
                                      status=NodeStatus.ERROR)])
        assert not eval_run(bad, [no_errors()]).passed

    def test_output_contains(self):
        g = _graph(nodes=[_llm(text="The SUMMARY is ready")])
        assert eval_run(g, [output_contains("summary")]).passed              # case-insensitive
        assert not eval_run(g, [output_contains("summary", case_sensitive=True)]).passed
        assert not eval_run(g, [output_contains("banana")]).passed

    def test_output_contains_specific_node(self):
        g = _graph(nodes=[_llm(model="gpt-4o", text="ticket created")])
        assert eval_run(g, [output_contains("ticket", node_label="llm/gpt-4o")]).passed
        assert not eval_run(g, [output_contains("ticket", node_label="llm/other")]).passed

    def test_custom_check(self):
        g = _graph(nodes=[_llm()])
        assert eval_run(g, [custom("has_3_nodes", lambda gr: len(gr.nodes) == 2)]).passed
        assert eval_run(g, [custom("with_detail", lambda gr: (True, "looks good"))]).passed

    def test_judge_with_score(self):
        g = _graph(nodes=[_llm()])
        result = eval_run(g, [judge("quality", lambda gr: (True, "coherent", 0.8))])
        assert result.passed
        assert result.checks[0].score == 0.8

    def test_throwing_check_is_a_failure(self):
        def boom(gr):
            raise RuntimeError("kaboom")
        result = eval_run(_graph(), [custom("explodes", boom)])
        assert not result.passed
        assert "kaboom" in result.checks[0].detail


# ---------------------------------------------------------------------------
# Aggregate result
# ---------------------------------------------------------------------------

class TestEvalResult:
    def test_passed_requires_all(self):
        g = _graph(nodes=[_llm(cost=0.01)])
        result = eval_run(g, [max_cost(0.02), max_cost(0.005)])
        assert result.passed is False
        assert [c.passed for c in result.checks] == [True, False]

    def test_score_is_mean(self):
        g = _graph(nodes=[_llm(cost=0.01)])
        result = eval_run(g, [max_cost(0.02), max_cost(0.005)])   # one pass, one fail
        assert result.score == 0.5

    def test_empty_checks_pass(self):
        result = eval_run(_graph(), [])
        assert result.passed and result.score == 1.0

    def test_accepts_run_context(self):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("r") as run:
            with run.step("ask", kind="llm") as s:
                s.set_output({"text": "done", "cost_usd": 0.001})
        result = eval_run(run, [max_cost(0.01), no_errors()])
        assert result.passed
        assert result.run_id == run.run_id


# ---------------------------------------------------------------------------
# Declarative specs
# ---------------------------------------------------------------------------

class TestDeclarative:
    def test_run_checks_from_specs(self):
        g = _graph(nodes=[_llm(cost=0.01, text="summary done")])
        result = run_checks(g, [
            {"type": "max_cost", "value": 0.02},
            {"type": "output_contains", "value": "summary"},
            {"type": "no_errors"},
        ])
        assert result.passed
        assert len(result.checks) == 3

    def test_unknown_spec_raises(self):
        with pytest.raises(ValueError):
            run_checks(_graph(), [{"type": "nonsense"}])


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client():
    store = MemoryStore()
    app = create_app(store=store)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, store


def _seed(store, run_id, cost=0.01, text="the summary"):
    tracer = Tracer(store=store)
    # write via a real trace so the graph is built normally
    with tracer.trace("agent", run_id=run_id) as run:
        with run.step("ask", kind="llm") as s:
            s.set_output({"text": text, "usage": {"input_tokens": 10, "output_tokens": 10},
                          "cost_usd": cost})


class TestEndpoint:
    def test_eval_endpoint_pass(self, app_client):
        client, store = app_client
        _seed(store, "r1", cost=0.01, text="summary ready")
        resp = client.post("/runs/r1/eval", json=[
            {"type": "max_cost", "value": 0.05},
            {"type": "output_contains", "value": "summary"},
        ])
        assert resp.status_code == 200
        body = resp.json()
        assert body["passed"] is True
        assert body["score"] == 1.0

    def test_eval_endpoint_fail(self, app_client):
        client, store = app_client
        _seed(store, "r1", cost=0.5)
        resp = client.post("/runs/r1/eval", json=[{"type": "max_cost", "value": 0.01}])
        assert resp.json()["passed"] is False

    def test_eval_endpoint_unknown_run(self, app_client):
        client, _ = app_client
        assert client.post("/runs/nope/eval", json=[{"type": "no_errors"}]).status_code == 404

    def test_eval_endpoint_bad_spec(self, app_client):
        client, store = app_client
        _seed(store, "r1")
        assert client.post("/runs/r1/eval", json=[{"type": "bogus"}]).status_code == 400
