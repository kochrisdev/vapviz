"""
Tests for VapPydanticAI.

Uses Pydantic AI's built-in TestModel / FunctionModel so no API key or network
is needed. Skipped automatically if pydantic-ai is not installed.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("pydantic_ai", reason="pydantic-ai not installed")

from pydantic_ai import Agent
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

import vapviz.store as _sm
from vapviz.events import NodeKind, NodeStatus
from vapviz.integrations import pydantic_ai as vap_pai
from vapviz.integrations.pydantic_ai import VapPydanticAI
from vapviz.store import MemoryStore
from vapviz.tracer import Tracer


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def listener_cleanup():
    """Detach any patch and restore default_store after each test."""
    listeners: list[VapPydanticAI] = []
    saved_store = _sm.default_store
    yield listeners
    for ln in listeners:
        ln.detach()
    _sm.default_store = saved_store


def _tool_agent(name="researcher"):
    agent = Agent(TestModel(), name=name, system_prompt="Helper")

    @agent.tool_plain
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    return agent


def _nodes(store: MemoryStore, run_id: str) -> dict:
    graph = store.get_graph(run_id)
    assert graph is not None
    return {n.label: n for n in graph.nodes}


# ---------------------------------------------------------------------------
# Manual mode
# ---------------------------------------------------------------------------

class TestManualMode:
    def test_agent_step_under_trace_root(self, listener_cleanup):
        store = MemoryStore()
        tracer = Tracer(store=store)
        agent = _tool_agent("researcher")

        with tracer.trace("Pipeline") as run:
            listener_cleanup.append(VapPydanticAI(run))
            agent.run_sync("add 2 and 3")

        nodes = _nodes(store, run.run_id)
        assert "agent/researcher" in nodes
        assert nodes["agent/researcher"].parent_id == nodes["Pipeline"].id
        assert nodes["agent/researcher"].kind == NodeKind.STEP

    def test_llm_nodes_created(self, listener_cleanup):
        store = MemoryStore()
        tracer = Tracer(store=store)
        agent = _tool_agent()

        with tracer.trace("P") as run:
            listener_cleanup.append(VapPydanticAI(run))
            agent.run_sync("add 1 and 2")

        graph = store.get_graph(run.run_id)
        llm_nodes = [n for n in graph.nodes if n.kind == NodeKind.LLM]
        # TestModel makes a request, calls the tool, then responds again -> 2 LLM nodes
        assert len(llm_nodes) == 2
        assert all(n.label == "llm/test" for n in llm_nodes)

    def test_tool_parented_to_calling_llm(self, listener_cleanup):
        store = MemoryStore()
        tracer = Tracer(store=store)
        agent = _tool_agent()

        with tracer.trace("P") as run:
            listener_cleanup.append(VapPydanticAI(run))
            agent.run_sync("add 4 and 5")

        graph = store.get_graph(run.run_id)
        tool_nodes = [n for n in graph.nodes if n.kind == NodeKind.TOOL]
        assert len(tool_nodes) == 1
        tool = tool_nodes[0]
        assert tool.label == "add"
        parent = next(n for n in graph.nodes if n.id == tool.parent_id)
        assert parent.kind == NodeKind.LLM       # parented under the model request that called it

    def test_tool_input_and_output_captured(self, listener_cleanup):
        store = MemoryStore()
        tracer = Tracer(store=store)
        agent = _tool_agent()

        with tracer.trace("P") as run:
            listener_cleanup.append(VapPydanticAI(run))
            agent.run_sync("add 7 and 8")

        graph = store.get_graph(run.run_id)
        tool = next(n for n in graph.nodes if n.kind == NodeKind.TOOL)
        assert "a" in tool.data["input"] and "b" in tool.data["input"]
        assert "result" in tool.data["output"]

    def test_usage_aggregated_on_agent(self, listener_cleanup):
        store = MemoryStore()
        tracer = Tracer(store=store)
        agent = _tool_agent()

        with tracer.trace("P") as run:
            listener_cleanup.append(VapPydanticAI(run))
            agent.run_sync("add 1 and 1")

        nodes = _nodes(store, run.run_id)
        usage = nodes["agent/researcher"].data["output"].get("usage")
        assert usage is not None
        assert usage["input_tokens"] > 0
        assert usage["output_tokens"] > 0


# ---------------------------------------------------------------------------
# Cost wiring
# ---------------------------------------------------------------------------

class TestCost:
    def test_cost_attached_when_model_priced(self, listener_cleanup, monkeypatch):
        # TestModel reports model_name "test" (not in the pricing table), so force
        # a known cost to verify the wiring attaches it to LLM and agent nodes.
        monkeypatch.setattr(vap_pai, "calculate_cost", lambda m, i, o: 0.0025)

        store = MemoryStore()
        tracer = Tracer(store=store)
        agent = Agent(TestModel(), name="priced")

        with tracer.trace("P") as run:
            listener_cleanup.append(VapPydanticAI(run))
            agent.run_sync("hello")

        graph = store.get_graph(run.run_id)
        llm = next(n for n in graph.nodes if n.kind == NodeKind.LLM)
        assert llm.data["output"]["cost_usd"] == 0.0025
        agent_node = next(n for n in graph.nodes if n.label == "agent/priced")
        assert agent_node.data["output"]["cost_usd"] > 0

    def test_no_cost_for_unknown_model(self, listener_cleanup):
        store = MemoryStore()
        tracer = Tracer(store=store)
        agent = Agent(TestModel(), name="unknown")

        with tracer.trace("P") as run:
            listener_cleanup.append(VapPydanticAI(run))
            agent.run_sync("hi")

        graph = store.get_graph(run.run_id)
        llm = next(n for n in graph.nodes if n.kind == NodeKind.LLM)
        assert "cost_usd" not in llm.data["output"]


# ---------------------------------------------------------------------------
# Auto mode
# ---------------------------------------------------------------------------

class TestAutoMode:
    def test_new_run_per_call(self, listener_cleanup):
        _sm.default_store = MemoryStore()
        listener_cleanup.append(VapPydanticAI())          # auto mode
        agent = Agent(TestModel(), name="auto")

        agent.run_sync("one")
        agent.run_sync("two")

        runs = _sm.default_store.list_runs()
        assert len(runs) == 2
        assert all(r.label == "auto" for r in runs)
        assert all(r.status == NodeStatus.SUCCESS for r in runs)

    def test_agent_is_run_root(self, listener_cleanup):
        _sm.default_store = MemoryStore()
        listener_cleanup.append(VapPydanticAI())
        agent = Agent(TestModel(), name="rooted")

        agent.run_sync("go")
        run = _sm.default_store.list_runs()[0]
        graph = _sm.default_store.get_graph(run.run_id)
        root = next(n for n in graph.nodes if n.parent_id is None)
        assert root.kind == NodeKind.AGENT
        assert root.label == "rooted"


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------

class TestAsync:
    def test_async_run_traced_once(self, listener_cleanup):
        _sm.default_store = MemoryStore()
        listener_cleanup.append(VapPydanticAI())
        agent = Agent(TestModel(), name="async_agent")

        async def go():
            return await agent.run("hello")

        asyncio.run(go())
        runs = _sm.default_store.list_runs()
        assert len(runs) == 1          # not double-counted via run_sync delegation


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_model_error_marks_run_failed(self, listener_cleanup):
        def boom(messages, info: AgentInfo):
            raise ValueError("model exploded")

        _sm.default_store = MemoryStore()
        listener_cleanup.append(VapPydanticAI())
        agent = Agent(FunctionModel(boom), name="boomer")

        with pytest.raises(Exception):
            agent.run_sync("trigger")

        runs = _sm.default_store.list_runs()
        assert len(runs) == 1
        assert runs[0].status == NodeStatus.ERROR


# ---------------------------------------------------------------------------
# Patch lifecycle
# ---------------------------------------------------------------------------

class TestPatchLifecycle:
    def test_detach_restores_original(self):
        original_sync = Agent.run_sync
        original_async = Agent.run

        listener = VapPydanticAI()
        assert Agent.run_sync is not original_sync     # patched

        listener.detach()
        assert Agent.run_sync is original_sync         # restored
        assert Agent.run is original_async

    def test_double_patch_does_not_stack(self, listener_cleanup):
        # Patching twice then running should still record exactly one run.
        _sm.default_store = MemoryStore()
        listener_cleanup.append(VapPydanticAI())
        listener_cleanup.append(VapPydanticAI())
        agent = Agent(TestModel(), name="once")

        agent.run_sync("x")
        assert len(_sm.default_store.list_runs()) == 1
