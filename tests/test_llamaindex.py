"""
Tests for VapLlamaIndex.

Uses LlamaIndex's MockLLM + MockEmbedding so no API key or network is needed.
Skipped automatically if llama-index-core is not installed.
"""
from __future__ import annotations

import inspect

import pytest

pytest.importorskip("llama_index.core", reason="llama-index-core not installed")

from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.instrumentation import get_dispatcher
from llama_index.core.llms import MockLLM

import vapviz.store as _sm
from vapviz.events import NodeKind, NodeStatus
from vapviz.integrations.llamaindex import VapLlamaIndex
from vapviz.store import MemoryStore
from vapviz.tracer import Tracer


@pytest.fixture(autouse=True)
def _mock_models():
    """Offline LLM + embeddings for every test.

    Assign the mocks directly — reading ``Settings.llm`` first would resolve the
    default (OpenAI) model, which isn't installed.
    """
    Settings.llm = MockLLM(max_tokens=16)
    Settings.embed_model = MockEmbedding(embed_dim=8)
    yield
    Settings._llm = None
    Settings._embed_model = None


@pytest.fixture
def handlers():
    """Track created handlers and detach them after each test."""
    created: list[VapLlamaIndex] = []
    saved_store = _sm.default_store
    yield created
    for h in created:
        h.detach()
    _sm.default_store = saved_store


def _run_query(run=None, handlers=None, *, question="What does vapviz do?"):
    h = VapLlamaIndex(run)
    if handlers is not None:
        handlers.append(h)
    index = VectorStoreIndex.from_documents(
        [Document(text="vapviz traces AI agents."), Document(text="LlamaIndex does RAG.")]
    )
    index.as_query_engine().query(question)
    return h


# ---------------------------------------------------------------------------
# Manual mode
# ---------------------------------------------------------------------------

class TestManualMode:
    def test_query_produces_nodes(self, handlers):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("RAG") as run:
            _run_query(run, handlers)
        graph = store.get_graph(run.run_id)
        assert len(graph.nodes) > 5            # a real RAG call tree

    def test_single_root_and_connected_tree(self, handlers):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("RAG") as run:
            _run_query(run, handlers)
        graph = store.get_graph(run.run_id)
        ids = {n.id for n in graph.nodes}
        roots = [n for n in graph.nodes if n.parent_id is None]
        assert len(roots) == 1                 # only the trace's own agent root
        assert roots[0].label == "RAG"
        # every other node's parent exists in the graph
        for n in graph.nodes:
            assert n.parent_id is None or n.parent_id in ids

    def test_llm_and_tool_nodes_classified(self, handlers):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("RAG") as run:
            _run_query(run, handlers)
        graph = store.get_graph(run.run_id)
        kinds = {n.kind for n in graph.nodes}
        assert NodeKind.LLM in kinds
        assert NodeKind.TOOL in kinds          # retriever + embedding
        # the query engine orchestrator is a step, not a tool
        qe = next(n for n in graph.nodes if n.label.startswith("RetrieverQueryEngine.query"))
        assert qe.kind == NodeKind.STEP

    def test_retriever_is_tool(self, handlers):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("RAG") as run:
            _run_query(run, handlers)
        graph = store.get_graph(run.run_id)
        retr = [n for n in graph.nodes if n.label.startswith("VectorIndexRetriever.retrieve")]
        assert retr and all(n.kind == NodeKind.TOOL for n in retr)


# ---------------------------------------------------------------------------
# Auto mode
# ---------------------------------------------------------------------------

class TestAutoMode:
    def test_query_creates_runs(self, handlers):
        _sm.default_store = MemoryStore()
        _run_query(None, handlers)
        runs = _sm.default_store.list_runs()
        assert len(runs) >= 1
        # at least one run's root span is the query engine, as an agent root
        graphs = [_sm.default_store.get_graph(r.run_id) for r in runs]
        roots = [next(n for n in g.nodes if n.parent_id is None) for g in graphs]
        assert any(r.kind == NodeKind.AGENT for r in roots)
        assert any(r.label.startswith("RetrieverQueryEngine.query") for r in roots)


# ---------------------------------------------------------------------------
# Error handling (drop span)
# ---------------------------------------------------------------------------

class TestErrors:
    def test_dropped_span_marks_node_error(self, handlers):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("R") as run:
            h = VapLlamaIndex(run)
            handlers.append(h)

            def f(self, x):  # noqa: ANN001
                pass

            ba = inspect.signature(f).bind(object(), 1)
            sid = "Engine.query-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            h.new_span(sid, ba, instance=None, parent_span_id=None)
            h.prepare_to_drop_span(sid, ba, instance=None, err=ValueError("boom"))

        graph = store.get_graph(run.run_id)
        node = next(n for n in graph.nodes if n.label == "Engine.query")
        assert node.status == NodeStatus.ERROR


# ---------------------------------------------------------------------------
# Register / detach
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_register_and_detach(self):
        before = len(get_dispatcher().span_handlers)
        h = VapLlamaIndex()
        assert h in get_dispatcher().span_handlers
        assert len(get_dispatcher().span_handlers) == before + 1
        h.detach()
        assert h not in get_dispatcher().span_handlers
        assert len(get_dispatcher().span_handlers) == before

    def test_register_false_does_not_register(self):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("R") as run:
            h = VapLlamaIndex(run, register=False)
        assert h not in get_dispatcher().span_handlers


# ---------------------------------------------------------------------------
# _extract_usage_and_cost — price an LLM response (regression for LI1)
# ---------------------------------------------------------------------------

class _Usage:
    """Mimics the OpenAI ChatCompletion.usage object on a LlamaIndex response."""
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class _Raw:
    def __init__(self, usage):
        self.usage = usage


class _Resp:
    """Mimics a LlamaIndex ChatResponse carrying the raw provider payload."""
    def __init__(self, usage=None, additional_kwargs=None):
        self.raw = _Raw(usage) if usage is not None else None
        self.additional_kwargs = additional_kwargs or {}


class TestExtractUsageAndCost:
    """LlamaIndex llm spans must be priced from their response token usage.

    Before LI1 the integration never called calculate_cost(), so llm nodes had
    no cost_usd and total_cost_usd was None. See SESSION-FINDINGS LI1.
    """

    def test_prices_from_raw_usage(self):
        from vapviz.integrations.llamaindex import _extract_usage_and_cost

        out = _extract_usage_and_cost(_Resp(usage=_Usage(100, 50)), "gpt-4o-mini")
        assert out["usage"] == {"input_tokens": 100, "output_tokens": 50}
        assert out["cost_usd"] > 0

    def test_falls_back_to_additional_kwargs(self):
        from vapviz.integrations.llamaindex import _extract_usage_and_cost

        resp = _Resp(additional_kwargs={"prompt_tokens": 80, "completion_tokens": 20})
        out = _extract_usage_and_cost(resp, "gpt-4o-mini")
        assert out["usage"] == {"input_tokens": 80, "output_tokens": 20}
        assert out["cost_usd"] > 0

    def test_no_usage_returns_empty(self):
        from vapviz.integrations.llamaindex import _extract_usage_and_cost

        assert _extract_usage_and_cost(_Resp(), "gpt-4o-mini") == {}

    def test_unknown_model_has_usage_but_no_cost(self):
        from vapviz.integrations.llamaindex import _extract_usage_and_cost

        out = _extract_usage_and_cost(_Resp(usage=_Usage(10, 5)), "totally-unknown-model")
        assert out["usage"] == {"input_tokens": 10, "output_tokens": 5}
        assert "cost_usd" not in out
