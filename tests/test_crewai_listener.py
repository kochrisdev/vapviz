"""
Tests for VapCrewAIListener.

All tests run in manual mode (explicit RunContext) so that each test
writes to its own MemoryStore and doesn't interfere with listeners
accumulated from previous tests (the CrewAI event bus doesn't support
handler deregistration, so listeners from earlier tests stay registered).

Skipped automatically if crewai is not installed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Skip everything if crewai is not installed
# ---------------------------------------------------------------------------

pytest.importorskip("crewai", reason="crewai not installed")

from crewai import Agent, Task
from crewai.events import (
    crewai_event_bus,
    AgentExecutionCompletedEvent,
    AgentExecutionStartedEvent,
    CrewKickoffCompletedEvent,
    CrewKickoffStartedEvent,
    LLMCallCompletedEvent,
    LLMCallStartedEvent,
    TaskCompletedEvent,
    TaskStartedEvent,
    ToolUsageFinishedEvent,
    ToolUsageStartedEvent,
)
from crewai.tasks.task_output import TaskOutput

from vapviz import MemoryStore
from vapviz.integrations.crewai_listener import VapCrewAIListener
from vapviz.tracer import RunContext


# ---------------------------------------------------------------------------
# Shared fixtures — create real Agent / Task objects once per session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def agent_a():
    return Agent(role="Researcher", goal="Find information", backstory="Expert researcher")


@pytest.fixture(scope="session")
def agent_b():
    return Agent(role="Writer", goal="Write summaries", backstory="Expert writer")


@pytest.fixture(scope="session")
def task_research(agent_a):
    return Task(description="Research the topic", expected_output="Findings", agent=agent_a)


@pytest.fixture(scope="session")
def task_write(agent_b):
    return Task(description="Write a summary", expected_output="Summary", agent=agent_b)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _task_output(task: Task, text: str = "Done") -> TaskOutput:
    """Build a minimal TaskOutput for use in TaskCompletedEvent."""
    return TaskOutput(description=task.description, agent=task.agent.role, raw=text)


def _fire(event_class, **kwargs) -> Any:
    """
    Instantiate a CrewAI event and emit it synchronously.

    The event bus dispatches sync handlers via a ThreadPoolExecutor.
    We call .result() on the returned Future so the test blocks until
    all handlers (including VapCrewAIListener callbacks) complete.
    """
    event = event_class(**kwargs)
    future = crewai_event_bus.emit(None, event)
    if future is not None:
        future.result(timeout=10.0)
    return event


def _setup(label="TestRun") -> tuple[VapCrewAIListener, MemoryStore, RunContext]:
    """
    Create a listener in manual mode with its own isolated store.

    Manual mode means:
    - Each listener holds a reference to its own RunContext / store.
    - Accumulated listeners from previous tests write to *their* stores,
      not the current test's store — no cross-test interference.
    """
    store = MemoryStore()
    run = RunContext(label=label, store=store)
    run._start()
    listener = VapCrewAIListener(run=run)
    return listener, store, run


def _nodes(store: MemoryStore, run_id: str) -> dict[str, Any]:
    """Return {label: GraphNode} for all nodes in a run."""
    graph = store.get_graph(run_id)
    assert graph is not None, f"No graph for run_id={run_id}"
    return {n.label: n for n in graph.nodes}


# ---------------------------------------------------------------------------
# Crew lifecycle
# ---------------------------------------------------------------------------

class TestCrewLifecycle:
    def test_crew_step_created_in_manual_mode(self, task_research):
        listener, store, run = _setup("Pipeline")

        crew_evt = _fire(CrewKickoffStartedEvent, crew_name="MyCrew", inputs={"k": "v"})
        nodes = _nodes(store, run.run_id)

        assert "crew/MyCrew" in nodes
        crew_node = nodes["crew/MyCrew"]
        assert crew_node.parent_id == nodes["Pipeline"].id

    def test_crew_step_closed_on_complete(self, task_research):
        listener, store, run = _setup("Pipeline2")

        _fire(CrewKickoffStartedEvent, crew_name="MyCrew2", inputs={})
        _fire(CrewKickoffCompletedEvent, crew_name="MyCrew2", output="done")

        nodes = _nodes(store, run.run_id)
        assert nodes["crew/MyCrew2"].status.value == "success"

    def test_provided_run_not_closed_by_listener(self):
        listener, store, run = _setup("Outer")

        _fire(CrewKickoffStartedEvent, crew_name="Inner", inputs={})
        _fire(CrewKickoffCompletedEvent, crew_name="Inner", output="ok")

        # Run must still be open — the listener must NOT call run._end()
        runs = store.list_runs()
        assert runs[0].status.value in ("running", "pending")

        run._end()
        assert store.list_runs()[0].status.value == "success"


# ---------------------------------------------------------------------------
# Task nodes
# ---------------------------------------------------------------------------

class TestTaskNodes:
    def test_task_node_created(self, task_research):
        listener, store, run = _setup()

        _fire(CrewKickoffStartedEvent, crew_name="TC", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)

        nodes = _nodes(store, run.run_id)
        task_labels = [l for l in nodes if l.startswith("task/")]
        assert len(task_labels) == 1

    def test_task_node_parented_to_crew_step(self, task_research):
        listener, store, run = _setup()

        _fire(CrewKickoffStartedEvent, crew_name="TCParent", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)

        nodes = _nodes(store, run.run_id)
        crew_node = nodes["crew/TCParent"]
        task_node = next(n for l, n in nodes.items() if l.startswith("task/"))
        assert task_node.parent_id == crew_node.id

    def test_task_node_closed_on_complete(self, task_research):
        listener, store, run = _setup()

        _fire(CrewKickoffStartedEvent, crew_name="TCClose", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(TaskCompletedEvent, task=task_research, output=_task_output(task_research))

        nodes = _nodes(store, run.run_id)
        task_label = next(l for l in nodes if l.startswith("task/"))
        assert nodes[task_label].status.value == "success"


# ---------------------------------------------------------------------------
# Agent execution nodes
# ---------------------------------------------------------------------------

class TestAgentNodes:
    def test_agent_node_created(self, agent_a, task_research):
        listener, store, run = _setup()

        _fire(CrewKickoffStartedEvent, crew_name="AgTC", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Go")

        nodes = _nodes(store, run.run_id)
        agent_labels = [l for l in nodes if l.startswith("agent/")]
        assert len(agent_labels) == 1
        assert "agent/Researcher" in nodes

    def test_agent_node_parented_to_task(self, agent_a, task_research):
        listener, store, run = _setup()

        _fire(CrewKickoffStartedEvent, crew_name="AgParent", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Go")

        nodes = _nodes(store, run.run_id)
        task_label = next(l for l in nodes if l.startswith("task/"))
        assert nodes["agent/Researcher"].parent_id == nodes[task_label].id

    def test_agent_node_closed_on_complete(self, agent_a, task_research):
        listener, store, run = _setup()

        _fire(CrewKickoffStartedEvent, crew_name="AgClose", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Go")
        _fire(AgentExecutionCompletedEvent,
              agent=agent_a, task=task_research, output="Research done")

        nodes = _nodes(store, run.run_id)
        assert nodes["agent/Researcher"].status.value == "success"


# ---------------------------------------------------------------------------
# Tool call nodes
# ---------------------------------------------------------------------------

class TestToolNodes:
    def test_tool_node_created(self, agent_a, task_research):
        listener, store, run = _setup()

        _fire(CrewKickoffStartedEvent, crew_name="TlTC", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Search")

        _fire(ToolUsageStartedEvent,
              tool_name="web_search", tool_args={"query": "AI news"},
              agent=agent_a, from_task=task_research, from_agent=agent_a,
              run_attempts=1, delegations=0)

        nodes = _nodes(store, run.run_id)
        assert "web_search" in nodes

    def test_tool_node_parented_to_agent(self, agent_a, task_research):
        listener, store, run = _setup()

        _fire(CrewKickoffStartedEvent, crew_name="TlParent", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Search")

        _fire(ToolUsageStartedEvent,
              tool_name="web_search", tool_args={},
              agent=agent_a, from_task=task_research, from_agent=agent_a,
              run_attempts=1, delegations=0)

        nodes = _nodes(store, run.run_id)
        assert nodes["web_search"].parent_id == nodes["agent/Researcher"].id

    def test_tool_node_closed_on_finish(self, agent_a, task_research):
        listener, store, run = _setup()
        now = datetime.now(timezone.utc)

        _fire(CrewKickoffStartedEvent, crew_name="TlClose", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Search")
        _fire(ToolUsageStartedEvent,
              tool_name="web_search", tool_args={},
              agent=agent_a, from_task=task_research, from_agent=agent_a,
              run_attempts=1, delegations=0)
        _fire(ToolUsageFinishedEvent,
              tool_name="web_search", tool_args={},
              agent=agent_a, from_task=task_research, from_agent=agent_a,
              run_attempts=1, delegations=0,
              output="Some search results", from_cache=False,
              started_at=now, finished_at=now)       # ToolUsageFinishedEvent requires these

        nodes = _nodes(store, run.run_id)
        assert nodes["web_search"].status.value == "success"


# ---------------------------------------------------------------------------
# LLM call nodes
# ---------------------------------------------------------------------------

class TestLLMNodes:
    def test_llm_node_created(self, agent_a, task_research):
        listener, store, run = _setup()
        call_id = _uid()

        _fire(CrewKickoffStartedEvent, crew_name="LlTC", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Think")
        _fire(LLMCallStartedEvent,
              model="gpt-4o-mini", call_id=call_id,
              messages=[{"role": "user", "content": "Hello"}],
              tools=[], from_agent=agent_a)

        nodes = _nodes(store, run.run_id)
        assert "llm/gpt-4o-mini" in nodes

    def test_llm_node_parented_to_agent(self, agent_a, task_research):
        listener, store, run = _setup()
        call_id = _uid()

        _fire(CrewKickoffStartedEvent, crew_name="LlParent", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Think")
        _fire(LLMCallStartedEvent,
              model="gpt-4o-mini", call_id=call_id,
              messages=[], tools=[], from_agent=agent_a)

        nodes = _nodes(store, run.run_id)
        assert nodes["llm/gpt-4o-mini"].parent_id == nodes["agent/Researcher"].id

    def test_llm_node_closed_on_complete(self, agent_a, task_research):
        listener, store, run = _setup()
        call_id = _uid()

        _fire(CrewKickoffStartedEvent, crew_name="LlClose", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Think")
        _fire(LLMCallStartedEvent,
              model="gpt-4o-mini", call_id=call_id,
              messages=[], tools=[], from_agent=agent_a)
        _fire(LLMCallCompletedEvent,
              model="gpt-4o-mini", call_id=call_id,
              response="Hello! How can I help?",
              usage={"prompt_tokens": 10, "completion_tokens": 8},
              call_type="llm_call")

        nodes = _nodes(store, run.run_id)
        assert nodes["llm/gpt-4o-mini"].status.value == "success"

    def test_llm_usage_in_output(self, agent_a, task_research):
        listener, store, run = _setup()
        call_id = _uid()

        _fire(CrewKickoffStartedEvent, crew_name="LlUsage", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Think")
        _fire(LLMCallStartedEvent,
              model="gpt-4o-mini", call_id=call_id,
              messages=[], tools=[], from_agent=agent_a)
        _fire(LLMCallCompletedEvent,
              model="gpt-4o-mini", call_id=call_id,
              response="Answer",
              usage={"prompt_tokens": 100, "completion_tokens": 50},
              call_type="llm_call")

        nodes = _nodes(store, run.run_id)
        node_output = nodes["llm/gpt-4o-mini"].data.get("output", {})
        assert "usage" in node_output
        assert node_output["usage"]["input_tokens"] == 100
        assert node_output["usage"]["output_tokens"] == 50


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

class TestCostTracking:
    def test_cost_attached_for_known_model(self, agent_a, task_research):
        listener, store, run = _setup()
        call_id = _uid()

        _fire(CrewKickoffStartedEvent, crew_name="CostTC", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Think")
        _fire(LLMCallStartedEvent,
              model="gpt-4o", call_id=call_id,
              messages=[], tools=[], from_agent=agent_a)
        _fire(LLMCallCompletedEvent,
              model="gpt-4o", call_id=call_id,
              response="Answer",
              usage={"prompt_tokens": 1000, "completion_tokens": 500},
              call_type="llm_call")

        nodes = _nodes(store, run.run_id)
        node_output = nodes["llm/gpt-4o"].data.get("output", {})
        assert "cost_usd" in node_output
        assert node_output["cost_usd"] > 0

    def test_no_cost_for_unknown_model(self, agent_a, task_research):
        listener, store, run = _setup()
        call_id = _uid()

        _fire(CrewKickoffStartedEvent, crew_name="NoCostTC", inputs={})
        _fire(TaskStartedEvent, task=task_research, context=None)
        _fire(AgentExecutionStartedEvent,
              agent=agent_a, task=task_research, tools=[], task_prompt="Think")
        _fire(LLMCallStartedEvent,
              model="my-private-model", call_id=call_id,
              messages=[], tools=[], from_agent=agent_a)
        _fire(LLMCallCompletedEvent,
              model="my-private-model", call_id=call_id,
              response="Answer",
              usage={"prompt_tokens": 100, "completion_tokens": 50},
              call_type="llm_call")

        nodes = _nodes(store, run.run_id)
        node_output = nodes["llm/my-private-model"].data.get("output", {})
        assert "cost_usd" not in node_output


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

class TestImportGuard:
    def test_raises_if_crewai_missing(self):
        import vapviz.integrations.crewai_listener as mod
        original = mod._CREWAI_AVAILABLE
        mod._CREWAI_AVAILABLE = False
        try:
            with pytest.raises(ImportError, match="crewai"):
                obj = object.__new__(VapCrewAIListener)
                obj.__init__()
        finally:
            mod._CREWAI_AVAILABLE = original
