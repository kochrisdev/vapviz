"""
REAL-LLM integration test — Anthropic SDK auto-instrumentation (patch_anthropic).

GATED: the Anthropic SDK speaks a different wire protocol than OpenRouter's
OpenAI-compatible endpoint, so this needs a real ANTHROPIC_API_KEY (not the
OpenRouter key). Skips cleanly until one is provided in the environment.

    ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_anthropic_integration.py -v
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("anthropic")

import vapviz  # noqa: E402
from vapviz.backends.sqlite import SqliteStore  # noqa: E402

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("VAP_ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

pytestmark = pytest.mark.skipif(
    not ANTHROPIC_KEY,
    reason="ANTHROPIC_API_KEY not set — Anthropic real-LLM test skipped (OpenRouter is OpenAI-only)",
)


def test_patch_anthropic_traces_cost(tmp_path):
    import anthropic

    store = SqliteStore(str(tmp_path / "anthropic.db"))
    tracer = vapviz.Tracer(store=store)
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    vapviz.patch_anthropic(client)

    with tracer.trace("Anthropic agent") as run:
        with run.step("answer"):
            client.messages.create(
                model=ANTHROPIC_MODEL, max_tokens=64, temperature=0,
                messages=[{"role": "user", "content": "Reply with one short sentence about RAG."}],
            )

    g = store.get_graph(run.run_id)
    assert not [n for n in g.nodes if n.status.value == "running"]
    llm_nodes = [n for n in g.nodes if n.kind.value == "llm"]
    assert len(llm_nodes) == 1
    out = (llm_nodes[0].data or {}).get("output", {})
    assert out.get("cost_usd") is not None, "anthropic llm node not priced"
    assert summary_total(store, run.run_id) > 0


def summary_total(store, run_id):
    return next(r for r in store.list_runs() if r.run_id == run_id).total_cost_usd
