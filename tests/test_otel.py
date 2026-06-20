"""
Tests for the OpenTelemetry export (vap/integrations/otel.py).

Uses the in-memory span exporter so nothing leaves the process. Skipped
automatically if opentelemetry-sdk is not installed.
"""
from __future__ import annotations

import uuid

import pytest

pytest.importorskip("opentelemetry.sdk", reason="opentelemetry-sdk not installed")

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from vap.events import GraphNode, NodeKind, NodeStatus, RunGraph
from vap.integrations.otel import build_spans, enable_otel_export, export_run
from vap.store import MemoryStore
from vap.tracer import Tracer


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def exporter_provider():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter, provider


def _by_name(spans):
    return {s.name: s for s in spans}


def _parent_name(span, spans):
    if span.parent is None:
        return None
    return next((s.name for s in spans if s.context.span_id == span.parent.span_id), None)


def _graph_with_error():
    """A hand-built graph: root agent → ok step + failed tool."""
    root = GraphNode(id="r", kind=NodeKind.AGENT, label="agent", status=NodeStatus.SUCCESS,
                     started_at=100.0, ended_at=101.0)
    ok = GraphNode(id="s", kind=NodeKind.STEP, label="ok-step", status=NodeStatus.SUCCESS,
                   parent_id="r", started_at=100.1, ended_at=100.4)
    bad = GraphNode(id="t", kind=NodeKind.TOOL, label="bad-tool", status=NodeStatus.ERROR,
                    parent_id="r", started_at=100.5, ended_at=100.6,
                    data={"error": "kaboom"})
    return RunGraph(run_id="run123", label="agent", status=NodeStatus.SUCCESS,
                    nodes=[root, ok, bad], started_at=100.0, ended_at=101.0)


# ---------------------------------------------------------------------------
# build_spans / export_run (one-shot)
# ---------------------------------------------------------------------------

class TestBuildSpans:
    def test_one_trace_per_run_and_span_count(self, exporter_provider):
        exporter, provider = exporter_provider
        n = build_spans(_graph_with_error(), provider.get_tracer("vap"))
        provider.force_flush()
        spans = exporter.get_finished_spans()
        assert n == 3
        assert len(spans) == 3
        assert len({s.context.trace_id for s in spans}) == 1   # single trace

    def test_hierarchy_mirrors_parent_id(self, exporter_provider):
        exporter, provider = exporter_provider
        build_spans(_graph_with_error(), provider.get_tracer("vap"))
        provider.force_flush()
        spans = exporter.get_finished_spans()
        by = _by_name(spans)
        assert _parent_name(by["agent"], spans) is None
        assert _parent_name(by["ok-step"], spans) == "agent"
        assert _parent_name(by["bad-tool"], spans) == "agent"

    def test_error_status_propagated(self, exporter_provider):
        exporter, provider = exporter_provider
        build_spans(_graph_with_error(), provider.get_tracer("vap"))
        provider.force_flush()
        by = _by_name(exporter.get_finished_spans())
        assert by["bad-tool"].status.status_code == StatusCode.ERROR
        assert "kaboom" in (by["bad-tool"].status.description or "")
        assert by["ok-step"].status.status_code == StatusCode.OK

    def test_timestamps_from_node_times(self, exporter_provider):
        exporter, provider = exporter_provider
        build_spans(_graph_with_error(), provider.get_tracer("vap"))
        provider.force_flush()
        by = _by_name(exporter.get_finished_spans())
        root = by["agent"]
        assert root.start_time == 100 * 1_000_000_000
        assert root.end_time == 101 * 1_000_000_000

    def test_attributes_kind_and_runid(self, exporter_provider):
        exporter, provider = exporter_provider
        build_spans(_graph_with_error(), provider.get_tracer("vap"))
        provider.force_flush()
        by = _by_name(exporter.get_finished_spans())
        assert by["bad-tool"].attributes["vap.node.kind"] == "tool"
        assert by["agent"].attributes["vap.run_id"] == "run123"

    def test_export_run_none_is_noop(self, exporter_provider):
        _, provider = exporter_provider
        assert export_run(None, tracer_provider=provider) == 0


# ---------------------------------------------------------------------------
# LLM GenAI attributes via a real trace
# ---------------------------------------------------------------------------

class TestLlmAttributes:
    def test_genai_attributes(self, exporter_provider):
        exporter, provider = exporter_provider
        store = MemoryStore()
        tracer = Tracer(store=store)

        with tracer.trace("agent") as run:
            with run.step("ask", kind="llm") as s:
                s.set_input({"model": "gpt-4o"})
                s.set_output({"text": "hi", "usage": {"input_tokens": 100, "output_tokens": 20},
                              "cost_usd": 0.0025})

        export_run(store.get_graph(run.run_id), tracer_provider=provider)
        provider.force_flush()
        ask = _by_name(exporter.get_finished_spans())["ask"]
        assert ask.attributes["gen_ai.request.model"] == "gpt-4o"
        assert ask.attributes["gen_ai.usage.input_tokens"] == 100
        assert ask.attributes["gen_ai.usage.output_tokens"] == 20
        assert ask.attributes["vap.cost_usd"] == pytest.approx(0.0025)


# ---------------------------------------------------------------------------
# Auto-export via enable_otel_export
# ---------------------------------------------------------------------------

class TestAutoExport:
    def test_run_exported_on_completion(self, exporter_provider):
        exporter, provider = exporter_provider
        store = MemoryStore()
        tracer = Tracer(store=store)
        handle = enable_otel_export(tracer_provider=provider, store=store)

        try:
            with tracer.trace("Demo") as run:
                with run.step("search", kind="tool") as s:
                    s.set_output({"hits": 3})
        finally:
            handle.disable()

        provider.force_flush()
        spans = exporter.get_finished_spans()
        names = {s.name for s in spans}
        assert "Demo" in names and "search" in names
        assert len({s.context.trace_id for s in spans}) == 1

    def test_failed_run_exported_with_error(self, exporter_provider):
        exporter, provider = exporter_provider
        store = MemoryStore()
        tracer = Tracer(store=store)
        handle = enable_otel_export(tracer_provider=provider, store=store)

        try:
            with pytest.raises(ValueError):
                with tracer.trace("Boom"):
                    raise ValueError("nope")
        finally:
            handle.disable()

        provider.force_flush()
        spans = exporter.get_finished_spans()
        assert any(s.name == "Boom" for s in spans)

    def test_disable_stops_export(self, exporter_provider):
        exporter, provider = exporter_provider
        store = MemoryStore()
        tracer = Tracer(store=store)
        handle = enable_otel_export(tracer_provider=provider, store=store)
        handle.disable()

        with tracer.trace("after-disable"):
            pass

        provider.force_flush()
        assert exporter.get_finished_spans() == ()

    def test_disable_restores_original_add_event(self):
        store = MemoryStore()
        class_method = type(store).add_event
        handle = enable_otel_export(tracer_provider=TracerProvider(), store=store)
        assert "add_event" in vars(store)                  # instance-level override present
        handle.disable()
        assert "add_event" not in vars(store)              # reverted to the class method
        assert store.add_event.__func__ is class_method
