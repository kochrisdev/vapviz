"""
REAL-LLM integration test — LlamaIndex RAG query (VapLlamaIndex).

A tiny vector index queried through a query engine; LLM synthesis runs on a real
OpenRouter model, embeddings use MockEmbedding (offline). Asserts the RAG
pipeline (retriever + llm) is traced and persists cleanly.

Also guards the LI1 fix (see test_llm_nodes_are_priced): LlamaIndex llm nodes now
read token usage from the span result and attach cost_usd, so total_cost_usd > 0.

    PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_llamaindex_integration.py -v
"""
from __future__ import annotations

import pytest

pytest.importorskip("llama_index.core")
pytest.importorskip("llama_index.llms.openai")

from _real_llm import KEY, MODEL, BASE_URL, summary  # noqa: E402

import vapviz  # noqa: E402
from vapviz.backends.sqlite import SqliteStore  # noqa: E402
from vapviz.integrations.llamaindex import VapLlamaIndex  # noqa: E402

pytestmark = pytest.mark.skipif(
    not KEY, reason="OPENROUTER_API_KEY not set — real-LLM integration tests skipped"
)


def _run(store) -> str:
    from llama_index.core import Document, Settings, VectorStoreIndex
    from llama_index.core.embeddings import MockEmbedding
    from llama_index.llms.openai import OpenAI as LIOpenAI

    # LlamaIndex's OpenAI validates bare OpenAI names → strip the "openai/" prefix.
    Settings.llm = LIOpenAI(model=MODEL.split("/")[-1], api_base=BASE_URL, api_key=KEY)
    Settings.embed_model = MockEmbedding(embed_dim=8)

    tracer = vapviz.Tracer(store=store)
    docs = [
        Document(text="vapviz is a self-hosted tracer/visualizer for AI agent pipelines."),
        Document(text="RAG grounds LLM answers in retrieved documents."),
    ]
    with tracer.trace("LlamaIndex RAG query") as run:
        listener = VapLlamaIndex(run)
        try:
            index = VectorStoreIndex.from_documents(docs)
            index.as_query_engine().query("What is vapviz?")
        finally:
            listener.detach()
    return run.run_id


def test_rag_pipeline_is_traced(tmp_path):
    store = SqliteStore(str(tmp_path / "li.db"))
    run_id = _run(store)
    g = store.get_graph(run_id)

    assert not [n.label for n in g.nodes if n.status.value == "running"]

    labels = [n.label for n in g.nodes]
    # The retrieval + synthesis pipeline shows up.
    assert any("etriev" in l for l in labels), f"no retriever node; got {labels}"
    assert any(n.kind.value == "llm" for n in g.nodes), f"no llm node; got {labels}"
    # Reasonable nesting depth (query engine -> retriever/synthesizer -> llm).
    assert len(g.nodes) >= 5


def test_llm_nodes_are_priced(tmp_path):
    store = SqliteStore(str(tmp_path / "li_cost.db"))
    run_id = _run(store)
    total = summary(store, run_id).total_cost_usd
    assert total is not None and total > 0
