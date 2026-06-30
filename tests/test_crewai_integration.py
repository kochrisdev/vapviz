"""
REAL-LLM integration test — CrewAI multi-agent crew (VapCrewAIListener).

A 2-agent / 2-task sequential crew run against OpenRouter, traced in manual mode
under one vapviz run. Asserts the H1 nesting fix (agents nest under their task)
and correct cost aggregation. Skips without OPENROUTER_API_KEY or crewai.

    PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_crewai_integration.py -v
"""
from __future__ import annotations

import pytest

pytest.importorskip("crewai")

from _real_llm import KEY, MODEL, node_cost, summary, llm_cost_sum  # noqa: E402

import vapviz  # noqa: E402
from vapviz.backends.sqlite import SqliteStore  # noqa: E402
from vapviz.integrations.crewai_listener import VapCrewAIListener  # noqa: E402

pytestmark = pytest.mark.skipif(
    not KEY, reason="OPENROUTER_API_KEY not set — real-LLM integration tests skipped"
)

CREW_MODEL = MODEL if MODEL.startswith("openrouter/") else f"openrouter/{MODEL}"


def _run_crew(store) -> str:
    from crewai import Agent, Crew, Process, Task, LLM

    tracer = vapviz.Tracer(store=store)
    llm = LLM(model=CREW_MODEL)  # litellm reads OPENROUTER_API_KEY from env
    researcher = Agent(role="Researcher", goal="Find one fact about {topic}",
                       backstory="Concise.", llm=llm, max_iter=2, verbose=False)
    writer = Agent(role="Writer", goal="Write one sentence from the research",
                   backstory="Concise.", llm=llm, max_iter=2, verbose=False)
    crew = Crew(
        agents=[researcher, writer],
        tasks=[
            Task(description="State one fact about {topic}.",
                 expected_output="One fact.", agent=researcher),
            Task(description="Write one sentence from the research.",
                 expected_output="One sentence.", agent=writer),
        ],
        process=Process.sequential, verbose=False,
    )
    with tracer.trace("CrewAI content crew") as run:
        listener = VapCrewAIListener(run=run)
        try:
            crew.kickoff(inputs={"topic": "agent tracing"})
        finally:
            listener.detach()
    return run.run_id


def test_crew_nests_agents_under_tasks_and_sums_cost(tmp_path):
    store = SqliteStore(str(tmp_path / "crew.db"))
    run_id = _run_crew(store)
    g = store.get_graph(run_id)
    by_id = {n.id: n for n in g.nodes}

    assert not [n.label for n in g.nodes if n.status.value == "running"]

    labels = [n.label for n in g.nodes]
    assert any(l.startswith("crew/") for l in labels), f"no crew node; got {labels}"
    task_nodes = [n for n in g.nodes if n.label.startswith("task/")]
    agent_nodes = [n for n in g.nodes if n.label.startswith("agent/")]
    assert len(task_nodes) == 2, f"expected 2 task nodes, got {len(task_nodes)}"
    assert agent_nodes, "no agent worker nodes recorded"

    # H1: each worker agent nests under a task node (not the crew root).
    for a in agent_nodes:
        parent = by_id.get(a.parent_id)
        assert parent is not None and parent.label.startswith("task/"), (
            f"agent {a.label!r} parented to {parent and parent.label!r}, expected a task"
        )

    # Cost aggregates across both agents' llm calls; total == sum of llm-node costs.
    llm_nodes = [n for n in g.nodes if n.kind.value == "llm"]
    assert llm_nodes and all(node_cost(n) is not None for n in llm_nodes)
    total = summary(store, run_id).total_cost_usd
    assert total and abs(total - llm_cost_sum(g)) < 1e-9
