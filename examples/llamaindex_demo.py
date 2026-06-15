"""
LlamaIndex demo — traces a RAG query with VapLlamaIndex.

VapLlamaIndex registers a span handler on LlamaIndex's instrumentation
dispatcher, so the whole query pipeline — query engine, retriever, embeddings,
response synthesizer, LLM calls — appears as a nested VaP graph with real timings.

This demo uses LlamaIndex's MockLLM + MockEmbedding, so it runs with **no API key
and no network**. To use real models, set an API key and install the provider
package (e.g. `pip install llama-index-llms-openai`) and drop the Settings overrides.

Requirements:
    pip install "vap[llamaindex]"

Run (server + query in one process):
    python examples/llamaindex_demo.py

Or start the server first:
    vap serve --db vap.db
    python examples/llamaindex_demo.py --agent-only

Open http://localhost:8001 to see the graph.
"""
import sys
import threading
import time

import vap


def _check_deps() -> None:
    try:
        import llama_index.core  # noqa: F401
    except ImportError:
        raise SystemExit(
            "llama-index-core is not installed.\n"
            'Run: pip install "vap[llamaindex]"'
        )


def run_agent() -> None:
    _check_deps()

    from llama_index.core import Document, Settings, VectorStoreIndex
    from llama_index.core.embeddings import MockEmbedding
    from llama_index.core.llms import MockLLM

    from vap.integrations.llamaindex import VapLlamaIndex

    # Offline models — no API key needed.
    Settings.llm = MockLLM(max_tokens=32)
    Settings.embed_model = MockEmbedding(embed_dim=8)

    documents = [
        Document(text="VaP traces and visualizes AI agent pipelines in real time."),
        Document(text="LlamaIndex is a framework for building RAG applications."),
        Document(text="Retrieval-augmented generation grounds LLM answers in your data."),
    ]

    print("\n── RAG query traced under one VaP run (manual mode) ───────────")
    with vap.trace("LlamaIndex RAG") as run:
        listener = VapLlamaIndex(run)
        index = VectorStoreIndex.from_documents(documents)
        response = index.as_query_engine().query("What is VaP and how does it relate to RAG?")
        listener.detach()

    print(f"[demo] answer: {str(response)[:80]}")
    print(f"[vap] Run complete (run_id={run.run_id}). View at http://localhost:8001")


def main_with_server() -> None:
    import uvicorn

    vap.configure(db="vap.db")
    server_app = vap.create_app()

    t = threading.Thread(
        target=lambda: uvicorn.run(server_app, host="0.0.0.0", port=8001, log_level="warning"),
        daemon=True,
    )
    t.start()
    time.sleep(1.0)

    run_agent()
    input("\nPress Enter to exit…")


def main_agent_only() -> None:
    vap.configure(db="vap.db")
    run_agent()


if __name__ == "__main__":
    if "--agent-only" in sys.argv:
        main_agent_only()
    else:
        main_with_server()
