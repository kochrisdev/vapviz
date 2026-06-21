"""
REAL-LLM integration test — Pydantic AI agent (VapPydanticAI).

A weather agent with one tool, run against OpenRouter and traced in manual mode
under one vapviz run. Asserts the agent/llm/tool graph + tool tracing.

Also guards the PA1 fix (see test_run_total_is_sum_of_llm_costs): the integration
sets cost_usd on BOTH the agent node (aggregate) and each llm node, so
store._total_cost must sum only llm-kind nodes to avoid double-counting (~2x).

    PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_pydantic_ai_integration.py -v
"""
from __future__ import annotations

import pytest

pytest.importorskip("pydantic_ai")

from _real_llm import KEY, MODEL, BASE_URL, node_cost, summary, llm_cost_sum  # noqa: E402

import vapviz  # noqa: E402
from vapviz.backends.sqlite import SqliteStore  # noqa: E402
from vapviz.integrations.pydantic_ai import VapPydanticAI  # noqa: E402

pytestmark = pytest.mark.skipif(
    not KEY, reason="OPENROUTER_API_KEY not set — real-LLM integration tests skipped"
)


def _agent():
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    model = OpenAIChatModel(MODEL, provider=OpenAIProvider(base_url=BASE_URL, api_key=KEY))
    agent = Agent(model, name="weather_agent",
                  system_prompt="Use the get_temp tool, then answer in one sentence.")

    @agent.tool_plain
    def get_temp(city: str) -> str:
        """Return the current temperature for a city."""
        return f"{city}: 21C, clear"

    return agent


def _run(store) -> str:
    tracer = vapviz.Tracer(store=store)
    agent = _agent()
    with tracer.trace("Pydantic AI weather agent") as run:
        listener = VapPydanticAI(run)
        try:
            agent.run_sync("What's the weather in Paris?")
        finally:
            listener.detach()
    return run.run_id


def test_agent_run_traces_llm_and_tool(tmp_path):
    store = SqliteStore(str(tmp_path / "pyd.db"))
    run_id = _run(store)
    g = store.get_graph(run_id)

    assert not [n.label for n in g.nodes if n.status.value == "running"]

    kinds = {n.kind.value for n in g.nodes}
    assert "agent" in kinds and "llm" in kinds, f"missing agent/llm nodes; kinds={kinds}"
    llm_nodes = [n for n in g.nodes if n.kind.value == "llm"]
    assert len(llm_nodes) >= 2, "expected >=2 model requests (tool call + final answer)"

    # The tool the model called is captured by name.
    tool_nodes = [n for n in g.nodes if n.kind.value == "tool"]
    assert any(n.label == "get_temp" for n in tool_nodes), \
        f"get_temp tool not traced; tools={[n.label for n in tool_nodes]}"

    # Each model request is priced.
    assert all(node_cost(n) is not None for n in llm_nodes)


def test_run_total_is_sum_of_llm_costs(tmp_path):
    """PA1 (fixed): the agent node also carries an aggregate cost_usd, but
    _total_cost sums only llm-kind nodes, so the run total is not double-counted."""
    store = SqliteStore(str(tmp_path / "pyd_cost.db"))
    run_id = _run(store)
    g = store.get_graph(run_id)
    total = summary(store, run_id).total_cost_usd
    # Run total == sum of llm-node costs (no double count from the agent aggregate).
    assert total is not None
    assert abs(total - llm_cost_sum(g)) < 1e-9
