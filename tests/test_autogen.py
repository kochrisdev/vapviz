"""
Tests for VapAutoGen.

Uses offline ConversableAgents (``llm_config=False`` + registered reply
functions), so no API key or network is needed. Skipped automatically if
autogen (ag2) is not installed.
"""
from __future__ import annotations

import pytest

pytest.importorskip("autogen", reason="autogen (ag2) not installed")

from autogen import ConversableAgent

import vap.store as _sm
from vap.events import NodeKind, NodeStatus
from vap.integrations.autogen import VapAutoGen
from vap.store import MemoryStore
from vap.tracer import Tracer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agent(name, reply="ok"):
    a = ConversableAgent(name, llm_config=False, human_input_mode="NEVER",
                         max_consecutive_auto_reply=2)
    a.register_reply(
        [ConversableAgent, None],
        lambda self, messages=None, sender=None, config=None: (True, f"{reply} from {name}"),
    )
    return a


def _nodes(store, run_id):
    g = store.get_graph(run_id)
    assert g is not None
    return g, {n.id: n for n in g.nodes}


# ---------------------------------------------------------------------------
# Manual mode
# ---------------------------------------------------------------------------

class TestManualMode:
    def test_chat_and_turn_nodes(self):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("Conv") as run:
            h = VapAutoGen(run)
            try:
                a, u = _agent("assistant"), _agent("user")
                u.initiate_chat(a, message="Hi", max_turns=2)
            finally:
                h.detach()

        g, _ = _nodes(store, run.run_id)
        labels = [n.label for n in g.nodes]
        assert any(l.startswith("chat/") for l in labels)
        assert any(l.startswith("agent/") for l in labels)

    def test_turns_nested_under_chat(self):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("Conv") as run:
            h = VapAutoGen(run)
            try:
                a, u = _agent("assistant"), _agent("user")
                u.initiate_chat(a, message="Hi", max_turns=2)
            finally:
                h.detach()

        g, by = _nodes(store, run.run_id)
        chat = next(n for n in g.nodes if n.label.startswith("chat/"))
        turns = [n for n in g.nodes if n.label.startswith("agent/")]
        assert turns
        assert all(t.parent_id == chat.id for t in turns)
        # chat hangs under the trace's run root
        assert by[chat.parent_id].label == "Conv"

    def test_turn_labels_use_agent_name(self):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("Conv") as run:
            h = VapAutoGen(run)
            try:
                a, u = _agent("assistant"), _agent("user")
                u.initiate_chat(a, message="Hi", max_turns=2)
            finally:
                h.detach()

        g, _ = _nodes(store, run.run_id)
        turn_labels = {n.label for n in g.nodes if n.label.startswith("agent/")}
        assert "agent/assistant" in turn_labels
        assert "agent/user" in turn_labels


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class TestTools:
    def test_execute_function_creates_tool_node(self):
        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("Conv") as run:
            h = VapAutoGen(run)
            try:
                agent = ConversableAgent("worker", llm_config=False, human_input_mode="NEVER",
                                         function_map={"add": lambda a, b: a + b})
                ok, _ = agent.execute_function({"name": "add", "arguments": '{"a": 2, "b": 3}'})
            finally:
                h.detach()

        g, _ = _nodes(store, run.run_id)
        tools = [n for n in g.nodes if n.kind == NodeKind.TOOL]
        assert len(tools) == 1
        assert tools[0].label == "add"
        assert tools[0].data["output"]["success"] is True


# ---------------------------------------------------------------------------
# Auto mode
# ---------------------------------------------------------------------------

class TestAutoMode:
    def test_chat_creates_run(self):
        _sm.default_store = MemoryStore()
        h = VapAutoGen()
        try:
            a, u = _agent("assistant"), _agent("user")
            u.initiate_chat(a, message="Hi", max_turns=2)
        finally:
            h.detach()

        runs = _sm.default_store.list_runs()
        assert len(runs) == 1
        g, _ = _nodes(_sm.default_store, runs[0].run_id)
        root = next(n for n in g.nodes if n.parent_id is None)
        assert root.kind == NodeKind.AGENT
        assert root.label.startswith("chat/")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class TestErrors:
    def test_reply_error_marks_turn_error(self):
        store = MemoryStore()
        tracer = Tracer(store=store)

        def boom(self, messages=None, sender=None, config=None):
            raise ValueError("reply exploded")

        with tracer.trace("Conv") as run:
            h = VapAutoGen(run)
            try:
                a = ConversableAgent("assistant", llm_config=False, human_input_mode="NEVER")
                a.register_reply([ConversableAgent, None], boom)
                u = _agent("user")
                with pytest.raises(Exception):
                    u.initiate_chat(a, message="Hi", max_turns=2)
            finally:
                h.detach()

        g, _ = _nodes(store, run.run_id)
        assert any(n.status == NodeStatus.ERROR for n in g.nodes)


# ---------------------------------------------------------------------------
# Patch lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_detach_restores_originals(self):
        original = ConversableAgent.generate_reply
        h = VapAutoGen()
        assert ConversableAgent.generate_reply is not original
        h.detach()
        assert ConversableAgent.generate_reply is original

    def test_double_patch_does_not_stack(self):
        _sm.default_store = MemoryStore()
        h1 = VapAutoGen()
        h2 = VapAutoGen()
        try:
            a, u = _agent("assistant"), _agent("user")
            u.initiate_chat(a, message="Hi", max_turns=1)
        finally:
            h2.detach()
            h1.detach()
        # Exactly one run recorded (no double-counting from stacked wrappers).
        assert len(_sm.default_store.list_runs()) == 1
