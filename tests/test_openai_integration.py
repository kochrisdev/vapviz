"""
REAL-LLM integration test — OpenAI SDK auto-instrumentation (patch_openai).

Runs a small research agent against OpenRouter (OpenAI-compatible), persists to a
real SqliteStore, and asserts on the recorded graph. Skips cleanly when
OPENROUTER_API_KEY is unset or the openai SDK isn't installed.

    PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_openai_integration.py -v
"""
from __future__ import annotations

import pytest

pytest.importorskip("openai")

from _real_llm import KEY, MODEL, openrouter_client, node_cost, summary, llm_cost_sum  # noqa: E402

import vapviz  # noqa: E402
from vapviz.backends.sqlite import SqliteStore  # noqa: E402

pytestmark = pytest.mark.skipif(
    not KEY, reason="OPENROUTER_API_KEY not set — real-LLM integration tests skipped"
)


def _run_research_agent(store) -> str:
    tracer = vapviz.Tracer(store=store)
    client = openrouter_client()
    vapviz.patch_openai(client)

    with tracer.trace("OpenAI research agent") as run:
        with run.step("plan") as plan:
            topics = ["agent tracing", "multi-agent systems"]
            plan.set_output({"topics": topics})
        findings = []
        for topic in topics:
            with run.step(f"research: {topic}"):
                resp = client.chat.completions.create(
                    model=MODEL, temperature=0,
                    messages=[{"role": "user", "content": f"In one sentence, what is {topic}?"}],
                )
                findings.append(resp.choices[0].message.content)
        with run.step("synthesize"):
            client.chat.completions.create(
                model=MODEL, temperature=0,
                messages=[{"role": "user", "content": "Summarize: " + " ".join(findings)}],
            )
    return run.run_id


def test_patch_openai_traces_costs_and_nests(tmp_path):
    store = SqliteStore(str(tmp_path / "openai.db"))
    run_id = _run_research_agent(store)
    g = store.get_graph(run_id)

    # Persisting to SQLite leaves nothing stuck "running".
    assert not [n.label for n in g.nodes if n.status.value == "running"]

    # One llm node per chat.completions.create() call (2 research + 1 synthesis).
    llm_nodes = [n for n in g.nodes if n.kind.value == "llm"]
    assert len(llm_nodes) == 3, f"expected 3 llm nodes, got {len(llm_nodes)}"

    # Every llm node is priced; the run total equals their sum (no double-count).
    assert all(node_cost(n) is not None for n in llm_nodes), "an llm node has no cost_usd"
    total = summary(store, run_id).total_cost_usd
    assert total and total > 0
    assert abs(total - llm_cost_sum(g)) < 1e-9

    # Each llm node nests under a step (auto-parented via the ContextVar), not the root.
    ids = {n.id for n in g.nodes}
    step_ids = {n.id for n in g.nodes if n.kind.value == "step"}
    assert all(n.parent_id in step_ids for n in llm_nodes), "llm nodes not nested under steps"
    # The graph is fully connected (every non-root node has a real parent).
    roots = [n for n in g.nodes if n.parent_id is None or n.parent_id not in ids]
    assert len(roots) == 1 and roots[0].kind.value == "agent"
