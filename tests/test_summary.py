"""Tests for vapviz/summary.py — plain-language run summaries."""
from __future__ import annotations

import uuid

from vapviz.events import GraphNode, NodeKind, NodeStatus, RunGraph
from vapviz.summary import _format_cost, summarize_run


def _node(kind: NodeKind, label: str, *, parent=None, data=None) -> GraphNode:
    return GraphNode(
        id=uuid.uuid4().hex[:12],
        kind=kind,
        label=label,
        status=NodeStatus.SUCCESS,
        parent_id=parent,
        data=data or {},
    )


def _weather_run() -> RunGraph:
    root = _node(NodeKind.AGENT, "Weather agent")
    step = _node(
        NodeKind.STEP,
        "agent/weather_agent",
        parent=root.id,
        data={"input": {"prompt": "What's the weather in Paris?"}},
    )
    llm = _node(
        NodeKind.LLM,
        "llm/openai/gpt-4o-mini",
        parent=step.id,
        data={"input": {"model": "openai/gpt-4o-mini"}, "output": {"cost_usd": 0.00004125}},
    )
    tool = _node(NodeKind.TOOL, "get_temp", parent=step.id)
    return RunGraph(
        run_id=uuid.uuid4().hex[:12],
        label="Weather run",
        status=NodeStatus.SUCCESS,
        nodes=[root, step, llm, tool],
        started_at=1000.0,
        ended_at=1001.6,
    )


def test_summary_includes_title_input_models_tools_status_cost():
    s = summarize_run(_weather_run())
    assert s.startswith("Weather agent")
    assert "What's the weather in Paris?" in s
    assert "1 model call (gpt-4o-mini)" in s
    assert "1 tool (get_temp)" in s
    assert "succeeded in 1.6 s" in s
    assert "$0.000041" in s
    assert s.endswith(".")


def test_summary_handles_run_with_no_llm_or_tools():
    root = _node(NodeKind.AGENT, "Bare agent")
    g = RunGraph(
        run_id=uuid.uuid4().hex[:12],
        label="bare",
        status=NodeStatus.SUCCESS,
        nodes=[root],
        started_at=1000.0,
        ended_at=1000.5,
    )
    s = summarize_run(g)
    assert s.startswith("Bare agent")
    assert "succeeded in 500 ms" in s
    assert "model call" not in s


def test_summary_reports_failure():
    root = _node(NodeKind.AGENT, "Crashy agent")
    g = RunGraph(
        run_id=uuid.uuid4().hex[:12],
        label="crash",
        status=NodeStatus.ERROR,
        nodes=[root],
        started_at=1000.0,
        ended_at=1000.2,
    )
    assert "failed" in summarize_run(g)


def test_summary_excludes_framework_internal_tools():
    root = _node(NodeKind.AGENT, "LlamaIndex RAG query")
    real_tool = _node(NodeKind.TOOL, "get_temp", parent=root.id)
    internal1 = _node(NodeKind.TOOL, "MockEmbedding._get_text_embedding", parent=root.id)
    internal2 = _node(NodeKind.TOOL, "VectorIndexRetriever.retrieve", parent=root.id)
    g = RunGraph(
        run_id=uuid.uuid4().hex[:12],
        label="rag",
        status=NodeStatus.SUCCESS,
        nodes=[root, real_tool, internal1, internal2],
        started_at=1000.0,
        ended_at=1001.0,
    )
    s = summarize_run(g)
    assert "1 tool (get_temp)" in s
    assert "MockEmbedding" not in s and "VectorIndexRetriever" not in s


def test_format_cost_two_sig_figs():
    assert _format_cost(0.00004125) == "$0.000041"
    assert _format_cost(0.000172) == "$0.00017"
    assert _format_cost(0.5) == "$0.5000"
    assert _format_cost(0) is None
    assert _format_cost(None) is None
    assert _format_cost(0.0000001) == "<$0.000001"
