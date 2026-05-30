"""
Tests for VapCrewAIListener.

Uses mock CrewAI event objects — no real CrewAI or LLM calls needed.
Skipped automatically if crewai is not installed.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Skip everything if crewai is not installed
# ---------------------------------------------------------------------------

pytest.importorskip("crewai", reason="crewai not installed")

from crewai.events import (
    crewai_event_bus,
    CrewKickoffStartedEvent,
    CrewKickoffCompletedEvent,
    TaskStartedEvent,
    TaskCompletedEvent,
    AgentExecutionStartedEvent,
    AgentExecutionCompletedEvent,
    ToolUsageStartedEvent,
    ToolUsageFinishedEvent,
    LLMCallStartedEvent,
    LLMCallCompletedEvent,
)

from vap import MemoryStore
from vap.integrations.crewai_listener import VapCrewAIListener
from vap.tracer import RunContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _fire(event_class, **kwargs) -> Any:
    """Emit a CrewAI event on the bus and return the event instance."""
    event = event_class(**kwargs)
    crewai_event_bus.emit(event_class, source=None, event=event)
    return event


def _make_listener(run=None):
    store = MemoryStore()
    if run is None:
        # Auto mode: point vap.store.default_store to our test store
        import vap.store as _sm
        _sm.default_store = store
        return VapCrewAIListener(), store
    return VapCrewAIListener(run=run), store


def _get_nodes(store, run_id):
    """Return all GraphNode objects for a run."""
    graph = store.get_graph(run_id)
    assert graph is not None, f"No graph found for run_id={run_id}"
    return {n.label: n for n in graph.nodes}


# ---------------------------------------------------------------------------
# Auto-mode tests
# ---------------------------------------------------------------------------

class TestAutoMode:
    def test_crew_start_creates_run(self):
        listener, store = _make_listener()
        crew_event_id = _uid()

        start_evt = _fire(
            CrewKickoffStartedEvent,
            crew_name="TestCrew",
            inputs={"topic": "AI"},
        )

        # A run should have been created
        runs = store.list_runs()
        assert len(runs) == 1
        assert runs[0].label == "TestCrew"
        assert runs[0].status.value in ("running", "pending")

        # Close the run
        _fire(CrewKickoffCompletedEvent, output=MagicMock(raw="done"))
        runs = store.list_runs()
        assert runs[0].status.value == "success"

    def test_task_node_created(self):
        listener, store = _make_listener()

        _fire(CrewKickoffStartedEvent, crew_name="TC", inputs={})

        task_mock = MagicMock()
        task_mock.description = "Analyse the data"
        task_mock.name = "analyse"

        task_evt = _fire(TaskStartedEvent, task=task_mock, context=None)

        run_id = store.list_runs()[0].run_id
        nodes = _get_nodes(store, run_id)
        assert "task/analyse" in nodes

        _fire(
            TaskCompletedEvent,
            task=task_mock,
            output=MagicMock(raw="Analysis complete."),
            started_event_id=task_evt.event_id,
        )
        nodes = _get_nodes(store, run_id)
        assert nodes["task/analyse"].status.value == "success"

        _fire(CrewKickoffCompletedEvent, output=MagicMock(raw="done"))

    def test_agent_exec_node_under_task(self):
        listener, store = _make_listener()

        _fire(CrewKickoffStartedEvent, crew_name="TC", inputs={})

        task_mock = MagicMock()
        task_mock.description = "Research topic"
        task_mock.name = "research"
        task_evt = _fire(TaskStartedEvent, task=task_mock, context=None)

        agent_mock = MagicMock()
        agent_mock.role = "Researcher"
        agent_mock.id = _uid()
        agent_evt = _fire(
            AgentExecutionStartedEvent,
            agent=agent_mock,
            task=task_mock,
            tools=[],
            task_prompt="Research AI",
        )

        run_id = store.list_runs()[0].run_id
        nodes = _get_nodes(store, run_id)
        assert "agent/Researcher" in nodes

        # Agent node should be a child of the task node
        task_node = nodes["task/research"]
        agent_node = nodes["agent/Researcher"]
        assert agent_node.parent_id == task_node.id

        _fire(
            AgentExecutionCompletedEvent,
            agent=agent_mock,
            task=task_mock,
            output="Research findings",
            started_event_id=agent_evt.event_id,
        )
        _fire(TaskCompletedEvent, task=task_mock, output=MagicMock(raw="done"),
              started_event_id=task_evt.event_id)
        _fire(CrewKickoffCompletedEvent, output=MagicMock(raw="done"))

    def test_tool_node_under_agent(self):
        listener, store = _make_listener()

        _fire(CrewKickoffStartedEvent, crew_name="TC", inputs={})

        task_mock = MagicMock()
        task_mock.description = "Search task"; task_mock.name = "search"
        task_evt = _fire(TaskStartedEvent, task=task_mock, context=None)

        agent_mock = MagicMock()
        agent_mock.role = "Searcher"; agent_mock.id = "agent_abc"
        agent_evt = _fire(AgentExecutionStartedEvent, agent=agent_mock,
                          task=task_mock, tools=[], task_prompt="Search")

        tool_evt = _fire(
            ToolUsageStartedEvent,
            tool_name="web_search",
            tool_args={"query": "AI news"},
            agent_id="agent_abc",
        )

        run_id = store.list_runs()[0].run_id
        nodes = _get_nodes(store, run_id)
        assert "web_search" in nodes

        # Tool should be child of the agent node
        agent_node = nodes["agent/Searcher"]
        tool_node = nodes["web_search"]
        assert tool_node.parent_id == agent_node.id

        _fire(ToolUsageFinishedEvent, output="Some results",
              from_cache=False, started_event_id=tool_evt.event_id)

        _fire(AgentExecutionCompletedEvent, agent=agent_mock, task=task_mock,
              output="done", started_event_id=agent_evt.event_id)
        _fire(TaskCompletedEvent, task=task_mock, output=MagicMock(raw="done"),
              started_event_id=task_evt.event_id)
        _fire(CrewKickoffCompletedEvent, output=MagicMock(raw="done"))

    def test_llm_node_under_agent(self):
        listener, store = _make_listener()

        _fire(CrewKickoffStartedEvent, crew_name="TC", inputs={})

        task_mock = MagicMock()
        task_mock.description = "LLM task"; task_mock.name = "llm_task"
        task_evt = _fire(TaskStartedEvent, task=task_mock, context=None)

        agent_mock = MagicMock()
        agent_mock.role = "LLM Agent"; agent_mock.id = "agent_xyz"
        agent_evt = _fire(AgentExecutionStartedEvent, agent=agent_mock,
                          task=task_mock, tools=[], task_prompt="Generate")

        call_id = _uid()
        _fire(
            LLMCallStartedEvent,
            model="gpt-4o-mini",
            call_id=call_id,
            messages=[{"role": "user", "content": "Hello"}],
            tools=[],
            agent_id="agent_xyz",
        )

        run_id = store.list_runs()[0].run_id
        nodes = _get_nodes(store, run_id)
        assert "llm/gpt-4o-mini" in nodes

        _fire(
            LLMCallCompletedEvent,
            call_id=call_id,
            model="gpt-4o-mini",
            response="Hello! How can I help?",
            usage={"prompt_tokens": 10, "completion_tokens": 8},
            call_type="LLM_CALL",
        )

        nodes = _get_nodes(store, run_id)
        llm_node = nodes["llm/gpt-4o-mini"]
        assert llm_node.status.value == "success"
        # Token usage and cost should be in node data
        assert "usage" in llm_node.data.get("output", {})

        _fire(AgentExecutionCompletedEvent, agent=agent_mock, task=task_mock,
              output="done", started_event_id=agent_evt.event_id)
        _fire(TaskCompletedEvent, task=task_mock, output=MagicMock(raw="done"),
              started_event_id=task_evt.event_id)
        _fire(CrewKickoffCompletedEvent, output=MagicMock(raw="done"))

    def test_llm_cost_attached_for_known_model(self):
        listener, store = _make_listener()

        _fire(CrewKickoffStartedEvent, crew_name="CostCrew", inputs={})

        task_mock = MagicMock()
        task_mock.description = "Cost task"; task_mock.name = "cost_task"
        task_evt = _fire(TaskStartedEvent, task=task_mock, context=None)

        agent_mock = MagicMock()
        agent_mock.role = "Coster"; agent_mock.id = "agent_cost"
        agent_evt = _fire(AgentExecutionStartedEvent, agent=agent_mock,
                          task=task_mock, tools=[], task_prompt="Calc")

        call_id = _uid()
        _fire(LLMCallStartedEvent, model="gpt-4o", call_id=call_id,
              messages=[], tools=[], agent_id="agent_cost")
        _fire(
            LLMCallCompletedEvent,
            call_id=call_id,
            model="gpt-4o",
            response="Answer",
            usage={"prompt_tokens": 1000, "completion_tokens": 500},
            call_type="LLM_CALL",
        )

        run_id = store.list_runs()[0].run_id
        nodes = _get_nodes(store, run_id)
        llm_node = nodes["llm/gpt-4o"]
        assert llm_node.data.get("output", {}).get("cost_usd") is not None

        _fire(AgentExecutionCompletedEvent, agent=agent_mock, task=task_mock,
              output="done", started_event_id=agent_evt.event_id)
        _fire(TaskCompletedEvent, task=task_mock, output=MagicMock(raw="ok"),
              started_event_id=task_evt.event_id)
        _fire(CrewKickoffCompletedEvent, output=MagicMock(raw="done"))

    def test_run_status_on_completion(self):
        listener, store = _make_listener()
        _fire(CrewKickoffStartedEvent, crew_name="StatusCrew", inputs={})
        _fire(CrewKickoffCompletedEvent, output=MagicMock(raw="finished"))
        runs = store.list_runs()
        assert runs[0].status.value == "success"


# ---------------------------------------------------------------------------
# Manual-mode tests
# ---------------------------------------------------------------------------

class TestManualMode:
    def test_crew_step_under_provided_run(self):
        store = MemoryStore()
        run = RunContext(label="MyPipeline", store=store)
        run._start()

        listener = VapCrewAIListener(run=run)

        crew_evt = _fire(CrewKickoffStartedEvent, crew_name="SubCrew", inputs={})
        _fire(CrewKickoffCompletedEvent, output=MagicMock(raw="done"),
              started_event_id=crew_evt.event_id)

        run._end()

        nodes = _get_nodes(store, run.run_id)
        assert "MyPipeline" in nodes          # root agent node
        assert "crew/SubCrew" in nodes        # crew step node
        # crew step must be child of root
        assert nodes["crew/SubCrew"].parent_id == nodes["MyPipeline"].id

    def test_task_nodes_parented_to_crew_step(self):
        store = MemoryStore()
        run = RunContext(label="Pipeline", store=store)
        run._start()

        listener = VapCrewAIListener(run=run)

        crew_evt = _fire(CrewKickoffStartedEvent, crew_name="InnerCrew", inputs={})

        task_mock = MagicMock()
        task_mock.description = "Write a report"
        task_mock.name = "write_report"
        task_evt = _fire(TaskStartedEvent, task=task_mock, context=None)

        run_id = run.run_id
        nodes = _get_nodes(store, run_id)
        assert "task/write_report" in nodes
        # Task should be parented to the crew step (crew/InnerCrew)
        crew_step = nodes["crew/InnerCrew"]
        task_node = nodes["task/write_report"]
        assert task_node.parent_id == crew_step.id

        _fire(TaskCompletedEvent, task=task_mock, output=MagicMock(raw="done"),
              started_event_id=task_evt.event_id)
        _fire(CrewKickoffCompletedEvent, output=MagicMock(raw="done"),
              started_event_id=crew_evt.event_id)
        run._end()

    def test_provided_run_not_closed_by_listener(self):
        """The provided RunContext must NOT be ended by the listener."""
        store = MemoryStore()
        run = RunContext(label="Outer", store=store)
        run._start()

        listener = VapCrewAIListener(run=run)
        crew_evt = _fire(CrewKickoffStartedEvent, crew_name="Inner", inputs={})
        _fire(CrewKickoffCompletedEvent, output=MagicMock(raw="ok"),
              started_event_id=crew_evt.event_id)

        # Run should still be open (running) — listener must not have closed it
        runs = store.list_runs()
        assert runs[0].status.value in ("running", "pending")

        run._end()
        assert store.list_runs()[0].status.value == "success"


# ---------------------------------------------------------------------------
# Import-guard test
# ---------------------------------------------------------------------------

class TestImportGuard:
    def test_raises_if_crewai_missing(self, monkeypatch):
        import vap.integrations.crewai_listener as mod
        monkeypatch.setattr(mod, "_CREWAI_AVAILABLE", False)
        with pytest.raises(ImportError, match="crewai"):
            VapCrewAIListener.__new__(VapCrewAIListener).__init__()
