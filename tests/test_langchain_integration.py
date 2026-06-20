"""
REAL-LLM integration tests for the LangChain/LangGraph integration.

Unlike test_langchain.py (which feeds the handler stub/mock inputs), these run
actual LangGraph agents against a real LLM (OpenRouter) and assert on the graph
VaP records. They use a real SqliteStore so persistence-only bugs (events must
be JSON-serializable to be written) are exercised too.

They SKIP automatically when OPENROUTER_API_KEY is absent or langchain/langgraph
aren't installed, so the suite still passes without a key. Run them with:

    PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_langchain_integration.py -v

Covers the 2026-06-18 fixes end-to-end:
  * LG1 — LLM nodes get cost_usd; run total_cost_usd sums.
  * LG2 — no node left stuck "running" when persisting to SQLite.
  * U4/LG3 — chain nodes labeled by langgraph_node (agent identity readable).
plus concurrency, failure localization, and mixed handler + patch_openai.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    p = REPO / "scratch" / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = os.environ.get("VAP_MODEL", "openai/gpt-4o-mini")
BASE_URL = "https://openrouter.ai/api/v1"

# Skip the whole module unless we can really make calls.
pytest.importorskip("langchain_openai")
pytest.importorskip("langgraph.prebuilt")
pytestmark = pytest.mark.skipif(
    not KEY, reason="OPENROUTER_API_KEY not set — real-LLM integration tests skipped"
)

from typing import Literal  # noqa: E402
from typing_extensions import TypedDict  # noqa: E402

from langchain_core.messages import AIMessage, SystemMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.graph import StateGraph, START, END, MessagesState  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402
from langgraph.types import Command  # noqa: E402

from vap import Tracer  # noqa: E402
from vap.backends.sqlite import SqliteStore  # noqa: E402
from vap.integrations.langchain import VapCallbackHandler  # noqa: E402


# Defined at module level: a function-local TypedDict breaks
# with_structured_output (issubclass() can't resolve it).
class _Router(TypedDict):
    next: Literal["math_expert", "FINISH"]


# --------------------------------------------------------------------------
# Shared helpers / tools
# --------------------------------------------------------------------------

def _llm() -> "ChatOpenAI":
    return ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=KEY, temperature=0)


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool
def explode(x: int) -> int:
    """Process a number. (Always fails.)"""
    raise RuntimeError(f"boom: cannot process {x}")


def _cost(node) -> float | None:
    out = (node.data or {}).get("output", {})
    return out.get("cost_usd") if isinstance(out, dict) else None


def _summary(store: SqliteStore, run_id: str):
    return next(r for r in store.list_runs() if r.run_id == run_id)


# --------------------------------------------------------------------------
# Single ReAct agent — LG1 (cost) + LG2 (no stuck "running")
# --------------------------------------------------------------------------

def test_single_agent_costs_and_closes(tmp_path):
    store = SqliteStore(str(tmp_path / "single.db"))
    tracer = Tracer(store=store)
    agent = create_react_agent(_llm(), [add])

    with tracer.trace("real-single") as run:
        agent.invoke(
            {"messages": [("user", "What is 21 + 21? You MUST call the add tool.")]},
            config={"callbacks": [VapCallbackHandler(run)]},
        )

    g = store.get_graph(run.run_id)

    # LG2: persisting to SQLite must not leave any node stuck running.
    running = [n.label for n in g.nodes if n.status.value == "running"]
    assert not running, f"nodes stuck running: {running}"

    # The tool was actually traced.
    assert any(n.kind.value == "tool" and n.label == "add" for n in g.nodes)

    # LG1: every LLM node priced, and the run total is a positive sum.
    llm_nodes = [n for n in g.nodes if n.kind.value == "llm"]
    assert llm_nodes, "no llm nodes recorded"
    assert all(_cost(n) is not None for n in llm_nodes), "an llm node has no cost_usd"
    total = _summary(store, run.run_id).total_cost_usd
    assert total and total > 0
    assert abs(total - sum(_cost(n) for n in llm_nodes)) < 1e-9


# --------------------------------------------------------------------------
# U4/LG3 — chain nodes labeled by langgraph_node (single agent)
# --------------------------------------------------------------------------

def test_single_agent_nodes_are_named_not_chain(tmp_path):
    store = SqliteStore(str(tmp_path / "labels.db"))
    tracer = Tracer(store=store)
    agent = create_react_agent(_llm(), [add])

    with tracer.trace("real-labels") as run:
        agent.invoke(
            {"messages": [("user", "What is 2 + 2? You MUST call the add tool.")]},
            config={"callbacks": [VapCallbackHandler(run)]},
        )

    labels = {n.label for n in store.get_graph(run.run_id).nodes}
    # LangGraph's own node names should surface (not just generic "chain").
    assert "agent" in labels, f"expected an 'agent' node; got {labels}"
    assert "tools" in labels, f"expected a 'tools' node; got {labels}"


# --------------------------------------------------------------------------
# Multi-agent supervisor — agent identity + cost aggregation
# --------------------------------------------------------------------------

def _build_supervisor():
    llm = _llm()
    math_agent = create_react_agent(llm, [add, multiply])

    prompt = (
        "You are a supervisor managing a worker named math_expert (arithmetic). "
        "Route to math_expert to do the calculation, then respond FINISH."
    )

    def supervisor(state: "MessagesState"):
        decision = llm.with_structured_output(_Router).invoke(
            [SystemMessage(content=prompt)] + state["messages"]
        )
        goto = decision["next"]
        return Command(goto=END if goto == "FINISH" else goto)

    def math_node(state: "MessagesState"):
        result = math_agent.invoke(state)
        out = result["messages"][-1].content
        return Command(goto="supervisor",
                       update={"messages": [AIMessage(content=out, name="math_expert")]})

    builder = StateGraph(MessagesState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("math_expert", math_node)
    builder.add_edge(START, "supervisor")
    return builder.compile()


def test_multiagent_shows_worker_identity_and_sums_cost(tmp_path):
    store = SqliteStore(str(tmp_path / "multi.db"))
    tracer = Tracer(store=store)
    graph = _build_supervisor()

    with tracer.trace("real-multi") as run:
        graph.invoke(
            {"messages": [("user", "Add 21 and 21, then report the result.")]},
            config={"callbacks": [VapCallbackHandler(run)], "recursion_limit": 25},
        )

    g = store.get_graph(run.run_id)
    labels = {n.label for n in g.nodes}

    # You can tell which agent did what.
    assert "supervisor" in labels, f"supervisor not labeled; got {labels}"
    assert "math_expert" in labels, f"worker not labeled; got {labels}"

    assert not [n for n in g.nodes if n.status.value == "running"]
    total = _summary(store, run.run_id).total_cost_usd
    assert total and total > 0


# --------------------------------------------------------------------------
# Concurrency — two agents in parallel, no cross-wiring
# --------------------------------------------------------------------------

def test_concurrent_agents_do_not_cross_wire(tmp_path):
    store = SqliteStore(str(tmp_path / "concurrent.db"))
    tracer = Tracer(store=store)
    agent_add = create_react_agent(_llm(), [add])
    agent_mul = create_react_agent(_llm(), [multiply])
    out: dict[str, str] = {}

    def go(name, agent, prompt):
        with tracer.trace(f"real-conc-{name}") as run:
            agent.invoke({"messages": [("user", prompt)]},
                         config={"callbacks": [VapCallbackHandler(run)]})
            out[name] = run.run_id

    threads = [
        threading.Thread(target=go, args=("add", agent_add, "What is 21 + 21? You MUST call add.")),
        threading.Thread(target=go, args=("mul", agent_mul, "What is 6 * 7? You MUST call multiply.")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = {"add": "add", "mul": "multiply"}
    for name, run_id in out.items():
        g = store.get_graph(run_id)
        ids = {n.id for n in g.nodes}
        # No node parents outside its own run.
        orphans = [n.label for n in g.nodes if n.parent_id is not None and n.parent_id not in ids]
        assert not orphans, f"[{name}] orphan parents: {orphans}"
        # Only this run's own tool appears.
        tools = sorted({n.label for n in g.nodes if n.kind.value == "tool"})
        assert tools == [expected[name]], f"[{name}] wrong tools: {tools}"


# --------------------------------------------------------------------------
# Failure localization — a failing tool turns its branch red, others green
# --------------------------------------------------------------------------

def test_failing_tool_is_localized(tmp_path):
    store = SqliteStore(str(tmp_path / "fail.db"))
    tracer = Tracer(store=store)
    agent = create_react_agent(_llm(), [explode])

    with tracer.trace("real-fail") as run:
        try:
            agent.invoke(
                {"messages": [("user", "Call the explode tool with x=5.")]},
                config={"callbacks": [VapCallbackHandler(run)]},
            )
        except Exception:
            pass  # the tool raises; we only care how VaP recorded it

    g = store.get_graph(run.run_id)
    statuses = {n.label: n.status.value for n in g.nodes if n.kind.value == "tool"}
    assert statuses.get("explode") == "error", f"explode not red: {statuses}"
    # Localized: at least one other node stayed green.
    assert any(n.status.value == "success" for n in g.nodes)


# --------------------------------------------------------------------------
# Mixed integration — callback handler + patch_openai, no double-counting
# --------------------------------------------------------------------------

def test_mixed_handler_and_patch_openai_no_double_count(tmp_path):
    from openai import OpenAI

    from vap.integrations.openai_sdk import patch_openai

    store = SqliteStore(str(tmp_path / "mixed.db"))
    tracer = Tracer(store=store)

    raw = OpenAI(base_url=BASE_URL, api_key=KEY)
    patch_openai(raw)
    agent = create_react_agent(_llm(), [add])

    with tracer.trace("real-mixed") as run:
        agent.invoke(
            {"messages": [("user", "What is 10 + 5? You MUST call add.")]},
            config={"callbacks": [VapCallbackHandler(run)]},
        )
        raw.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "Say the single word: pong"}],
        )

    g = store.get_graph(run.run_id)
    llm_nodes = [n for n in g.nodes if n.kind.value == "llm"]
    # The direct patched call is labeled by model id and must appear exactly once.
    direct = [n for n in llm_nodes if n.label == f"llm/{MODEL}"]
    assert len(direct) == 1, f"direct patched call counted {len(direct)}x"
    # The agent's calls are labeled by class name and must also be present.
    handler_calls = [n for n in llm_nodes if n.label == "llm/ChatOpenAI"]
    assert handler_calls, "handler llm nodes missing"
    # Node ids are unique — nothing recorded twice.
    assert len({n.id for n in g.nodes}) == len(g.nodes)
