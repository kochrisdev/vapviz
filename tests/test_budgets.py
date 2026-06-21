"""Tests for vapviz/budgets.py — cost/latency budget checks + alerting + endpoint."""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

import vapviz.budgets as budgets_mod
from vapviz.budgets import (
    Budget,
    check_budget,
    enable_budget_alerts,
    otel_alert,
    slack_alert,
    webhook_alert,
)
from vapviz.events import (
    EventType,
    GraphNode,
    NodeKind,
    NodeStatus,
    RunGraph,
    VapEvent,
)
from vapviz.server import create_app
from vapviz.store import MemoryStore


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _llm(model, in_tok, out_tok, cost):
    return GraphNode(
        id=uuid.uuid4().hex[:12], kind=NodeKind.LLM, label=f"llm/{model}",
        status=NodeStatus.SUCCESS,
        data={"input": {"model": model},
              "output": {"usage": {"input_tokens": in_tok, "output_tokens": out_tok},
                         "cost_usd": cost}},
    )


def _graph(*, started=100.0, duration_s=1.0, llms=()):
    ended = started + duration_s if duration_s is not None else None
    root = GraphNode(id="r", kind=NodeKind.AGENT, label="agent",
                     status=NodeStatus.SUCCESS, started_at=started, ended_at=ended)
    return RunGraph(run_id="run1", label="agent", status=NodeStatus.SUCCESS,
                    nodes=[root, *llms], started_at=started, ended_at=ended)


# ---------------------------------------------------------------------------
# check_budget
# ---------------------------------------------------------------------------

class TestCheckBudget:
    def test_ok_when_under_all_limits(self):
        g = _graph(duration_s=1.0, llms=[_llm("gpt-4o", 100, 50, 0.01)])
        r = check_budget(g, Budget(max_cost_usd=0.05, max_duration_ms=3000, max_total_tokens=1000))
        assert r.status == "ok"
        assert r.violations == []
        assert r.cost_usd == 0.01
        assert r.total_tokens == 150
        assert r.duration_ms == 1000.0

    def test_cost_violation(self):
        g = _graph(llms=[_llm("gpt-4o", 100, 50, 0.05)])
        r = check_budget(g, Budget(max_cost_usd=0.02))
        assert r.status == "exceeded"
        assert len(r.violations) == 1
        v = r.violations[0]
        assert v.metric == "cost_usd"
        assert v.limit == 0.02
        assert v.actual == 0.05
        assert v.pct_over == pytest.approx(150.0)

    def test_duration_violation(self):
        g = _graph(duration_s=5.0)
        r = check_budget(g, Budget(max_duration_ms=3000))
        assert r.status == "exceeded"
        assert r.violations[0].metric == "duration_ms"
        assert r.violations[0].actual == 5000.0

    def test_token_violation(self):
        g = _graph(llms=[_llm("m", 800, 400, 0.0)])
        r = check_budget(g, Budget(max_total_tokens=1000))
        assert r.status == "exceeded"
        assert r.violations[0].metric == "total_tokens"
        assert r.violations[0].actual == 1200

    def test_multiple_violations(self):
        g = _graph(duration_s=10.0, llms=[_llm("m", 5000, 5000, 0.5)])
        r = check_budget(g, Budget(max_cost_usd=0.01, max_duration_ms=1000, max_total_tokens=100))
        assert r.status == "exceeded"
        assert {v.metric for v in r.violations} == {"cost_usd", "duration_ms", "total_tokens"}

    def test_none_limits_are_ignored(self):
        g = _graph(duration_s=99.0, llms=[_llm("m", 1, 1, 99.0)])
        r = check_budget(g, Budget())          # no limits set
        assert r.status == "ok"

    def test_missing_duration_skips_duration_check(self):
        g = _graph(duration_s=None)            # running / no end time
        r = check_budget(g, Budget(max_duration_ms=1))
        assert r.status == "ok"
        assert r.duration_ms is None


# ---------------------------------------------------------------------------
# enable_budget_alerts
# ---------------------------------------------------------------------------

def _seed_run(store, run_id, cost, duration_s=1.0):
    root = uuid.uuid4().hex[:12]
    llm = uuid.uuid4().hex[:12]
    t0 = 1000.0

    def ev(type, node_id, kind, label, ts, parent_id=None, data=None):
        return VapEvent(id=uuid.uuid4().hex[:12], run_id=run_id, timestamp=ts, type=type,
                        node_id=node_id, node_kind=kind, node_label=label,
                        parent_id=parent_id, data=data or {})

    store.add_event(ev(EventType.AGENT_START, root, NodeKind.AGENT, "agent", t0, data={"label": "agent"}))
    store.add_event(ev(EventType.LLM_CALL, llm, NodeKind.LLM, "llm/m", t0, parent_id=root))
    store.add_event(ev(EventType.LLM_RESPONSE, llm, NodeKind.LLM, "llm/m", t0, parent_id=root,
                       data={"output": {"usage": {"input_tokens": 10, "output_tokens": 10}, "cost_usd": cost}}))
    store.add_event(ev(EventType.AGENT_END, root, NodeKind.AGENT, "agent", t0 + duration_s))


class TestAlerts:
    def test_alert_fires_on_exceeded(self):
        store = MemoryStore()
        alerts = []
        handle = enable_budget_alerts(Budget(max_cost_usd=0.01), store=store,
                                      on_alert=alerts.append)
        try:
            _seed_run(store, "over", cost=0.05)
        finally:
            handle.disable()
        assert len(alerts) == 1
        assert alerts[0].run_id == "over"
        assert alerts[0].status == "exceeded"

    def test_no_alert_when_within_budget(self):
        store = MemoryStore()
        alerts = []
        handle = enable_budget_alerts(Budget(max_cost_usd=1.0), store=store,
                                      on_alert=alerts.append)
        try:
            _seed_run(store, "under", cost=0.01)
        finally:
            handle.disable()
        assert alerts == []

    def test_disable_stops_checking(self):
        store = MemoryStore()
        alerts = []
        handle = enable_budget_alerts(Budget(max_cost_usd=0.01), store=store,
                                      on_alert=alerts.append)
        handle.disable()
        _seed_run(store, "over", cost=0.05)
        assert alerts == []
        assert "add_event" not in vars(store)


# ---------------------------------------------------------------------------
# Alert channels
# ---------------------------------------------------------------------------

class TestChannels:
    def test_multiple_channels_all_fire(self):
        store = MemoryStore()
        a, b = [], []
        handle = enable_budget_alerts(Budget(max_cost_usd=0.01), store=store,
                                      on_alert=[a.append, b.append])
        try:
            _seed_run(store, "over", cost=0.05)
        finally:
            handle.disable()
        assert len(a) == 1 and len(b) == 1

    def test_one_failing_channel_does_not_break_others(self):
        store = MemoryStore()
        good = []

        def boom(report):
            raise RuntimeError("channel down")

        handle = enable_budget_alerts(Budget(max_cost_usd=0.01), store=store,
                                      on_alert=[boom, good.append])
        try:
            _seed_run(store, "over", cost=0.05)
        finally:
            handle.disable()
        assert len(good) == 1          # the good channel still ran

    def test_webhook_alert_posts_report(self, monkeypatch):
        sent = []
        monkeypatch.setattr(budgets_mod, "_deliver",
                            lambda url, payload, headers, timeout: sent.append((url, payload)))
        store = MemoryStore()
        handle = enable_budget_alerts(Budget(max_cost_usd=0.01), store=store,
                                      on_alert=webhook_alert("https://example.com/hook"))
        try:
            _seed_run(store, "over", cost=0.05)
        finally:
            handle.disable()
        assert len(sent) == 1
        url, payload = sent[0]
        assert url == "https://example.com/hook"
        assert payload["run_id"] == "over" and payload["status"] == "exceeded"
        assert payload["violations"][0]["metric"] == "cost_usd"

    def test_slack_alert_formats_message(self, monkeypatch):
        sent = []
        monkeypatch.setattr(budgets_mod, "_deliver",
                            lambda url, payload, headers, timeout: sent.append((url, payload)))
        store = MemoryStore()
        handle = enable_budget_alerts(Budget(max_cost_usd=0.01), store=store,
                                      on_alert=slack_alert("https://hooks.slack.com/x"))
        try:
            _seed_run(store, "over", cost=0.05)
        finally:
            handle.disable()
        assert len(sent) == 1
        url, payload = sent[0]
        assert "hooks.slack.com" in url
        assert "text" in payload and "over" in payload["text"] and "budget exceeded" in payload["text"]

    def test_otel_alert_emits_span(self):
        pytest.importorskip("opentelemetry.sdk")
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from opentelemetry.trace import StatusCode

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        store = MemoryStore()
        handle = enable_budget_alerts(Budget(max_cost_usd=0.01), store=store,
                                      on_alert=otel_alert(tracer_provider=provider))
        try:
            _seed_run(store, "over", cost=0.05)
        finally:
            handle.disable()
        provider.force_flush()
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "vapviz.budget_exceeded"
        assert span.attributes["vapviz.run_id"] == "over"
        assert span.status.status_code == StatusCode.ERROR


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client():
    store = MemoryStore()
    app = create_app(store=store)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, store


class TestEndpoint:
    def test_budget_endpoint_exceeded(self, app_client):
        client, store = app_client
        _seed_run(store, "r1", cost=0.05)
        resp = client.get("/runs/r1/budget", params={"max_cost_usd": 0.02})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "exceeded"
        assert body["violations"][0]["metric"] == "cost_usd"

    def test_budget_endpoint_ok(self, app_client):
        client, store = app_client
        _seed_run(store, "r1", cost=0.005)
        resp = client.get("/runs/r1/budget", params={"max_cost_usd": 0.02})
        assert resp.json()["status"] == "ok"

    def test_budget_endpoint_unknown_run(self, app_client):
        client, _ = app_client
        assert client.get("/runs/nope/budget", params={"max_cost_usd": 1}).status_code == 404
