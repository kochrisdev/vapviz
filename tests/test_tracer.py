"""Tests for vapviz/tracer.py — sync/async tracing, nesting, ContextVar, errors."""
from __future__ import annotations

import asyncio
import pytest

from vapviz.events import EventType, NodeKind, NodeStatus
from vapviz.store import MemoryStore
from vapviz.tracer import Tracer, _current_step


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def events_of(store: MemoryStore, run_id: str) -> list:
    return store.get_events(run_id)


def types_of(store: MemoryStore, run_id: str) -> list[str]:
    return [e.type.value for e in events_of(store, run_id)]


# ---------------------------------------------------------------------------
# Synchronous tracing
# ---------------------------------------------------------------------------

class TestSyncTrace:
    def test_basic_run_emits_agent_events(self, tracer, store):
        with tracer.trace("test") as run:
            pass

        t = types_of(store, run.run_id)
        assert t == ["agent_start", "agent_end"]

    def test_run_id_is_set(self, tracer):
        with tracer.trace("test") as run:
            assert len(run.run_id) == 12

    def test_custom_run_id(self, tracer, store):
        with tracer.trace("test", run_id="aabbccdd1122") as run:
            assert run.run_id == "aabbccdd1122"

    def test_step_emits_step_events(self, tracer, store):
        with tracer.trace("test") as run:
            with run.step("do_thing", kind="step"):
                pass

        t = types_of(store, run.run_id)
        assert "step_start" in t
        assert "step_end" in t

    def test_tool_step_emits_tool_events(self, tracer, store):
        with tracer.trace("test") as run:
            with run.step("call_api", kind="tool"):
                pass

        t = types_of(store, run.run_id)
        assert "tool_call" in t
        assert "tool_result" in t

    def test_llm_step_emits_llm_events(self, tracer, store):
        with tracer.trace("test") as run:
            with run.step("ask", kind="llm"):
                pass

        t = types_of(store, run.run_id)
        assert "llm_call" in t
        assert "llm_response" in t

    def test_set_input_output_stored(self, tracer, store):
        with tracer.trace("test") as run:
            with run.step("work", kind="tool") as step:
                step.set_input({"x": 1})
                step.set_output({"y": 2})

        close_event = [e for e in events_of(store, run.run_id) if e.type == EventType.TOOL_RESULT][0]
        assert close_event.data["input"] == {"x": 1}
        assert close_event.data["output"] == {"y": 2}

    def test_nesting_sets_parent_ids(self, tracer, store):
        with tracer.trace("test") as run:
            with run.step("parent", kind="step") as parent:
                with run.step("child", kind="tool") as child:
                    pass

        graph = store.get_graph(run.run_id)
        child_node = next(n for n in graph.nodes if n.label == "child")
        parent_node = next(n for n in graph.nodes if n.label == "parent")
        assert child_node.parent_id == parent_node.id

    def test_error_in_step_emits_error_event(self, tracer, store):
        with pytest.raises(ValueError, match="boom"):
            with tracer.trace("test") as run:
                with run.step("risky", kind="tool"):
                    raise ValueError("boom")

        t = types_of(store, run.run_id)
        assert "error" in t
        # Normal close event must NOT be emitted after an error
        assert "tool_result" not in t

    def test_error_on_step_does_not_prevent_agent_end(self, tracer, store):
        with pytest.raises(ValueError):
            with tracer.trace("test") as run:
                with run.step("risky", kind="tool"):
                    raise ValueError("oops")

        t = types_of(store, run.run_id)
        assert "agent_end" in t

    def test_context_var_cleared_after_trace(self, tracer):
        with tracer.trace("test"):
            pass
        assert _current_step.get() is None

    def test_context_var_cleared_after_exception(self, tracer):
        try:
            with tracer.trace("test") as run:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        assert _current_step.get() is None

    def test_set_meta_appears_in_events(self, tracer, store):
        with tracer.trace("test") as run:
            with run.step("work", kind="step") as step:
                step.set_meta(worker="w1")

        events = events_of(store, run.run_id)
        step_end = next(e for e in events if e.type == EventType.STEP_END)
        assert step_end.data.get("worker") == "w1"

    def test_event_ordering(self, tracer, store):
        with tracer.trace("test") as run:
            with run.step("a", kind="step"):
                with run.step("b", kind="tool"):
                    pass

        t = types_of(store, run.run_id)
        # agent_start must come before step_start
        assert t.index("agent_start") < t.index("step_start")
        # step_start before tool_call
        assert t.index("step_start") < t.index("tool_call")
        # tool_result before step_end
        assert t.index("tool_result") < t.index("step_end")

    def test_graph_has_correct_node_count(self, tracer, store):
        with tracer.trace("test") as run:
            with run.step("s1", kind="step"):
                pass
            with run.step("s2", kind="tool"):
                pass

        graph = store.get_graph(run.run_id)
        # root agent + 2 steps
        assert len(graph.nodes) == 3

    def test_graph_edges_created(self, tracer, store):
        with tracer.trace("test") as run:
            with run.step("child", kind="step"):
                pass

        graph = store.get_graph(run.run_id)
        assert len(graph.edges) == 1
        edge = graph.edges[0]
        assert edge.target == next(n.id for n in graph.nodes if n.label == "child")

    def test_graph_status_success_after_clean_run(self, tracer, store):
        with tracer.trace("test") as run:
            pass

        graph = store.get_graph(run.run_id)
        assert graph.status == NodeStatus.SUCCESS

    def test_node_status_error_on_exception(self, tracer, store):
        try:
            with tracer.trace("test") as run:
                with run.step("bad", kind="tool"):
                    raise ValueError("x")
        except ValueError:
            pass

        graph = store.get_graph(run.run_id)
        bad = next(n for n in graph.nodes if n.label == "bad")
        assert bad.status == NodeStatus.ERROR


# ---------------------------------------------------------------------------
# Asynchronous tracing
# ---------------------------------------------------------------------------

class TestAsyncTrace:
    def test_basic_async_run(self, tracer, store):
        async def _inner():
            async with tracer.atrace("async test") as run:
                pass
            return run

        run = asyncio.run(_inner())
        t = types_of(store, run.run_id)
        assert t == ["agent_start", "agent_end"]

    def test_astep_emits_events(self, tracer, store):
        async def _inner():
            async with tracer.atrace("test") as run:
                async with run.astep("fetch", kind="tool") as step:
                    step.set_input({"url": "http://example.com"})
                    await asyncio.sleep(0)
                    step.set_output({"ok": True})
            return run

        run = asyncio.run(_inner())
        t = types_of(store, run.run_id)
        assert "tool_call" in t
        assert "tool_result" in t

    def test_concurrent_asteps_have_correct_parents(self, tracer, store):
        """Two concurrent astep tasks must each see their own parent."""
        results = []

        async def child(run, label):
            async with run.astep(label, kind="tool") as step:
                step.set_input({"label": label})
                await asyncio.sleep(0.01)
                step.set_output({"done": True})
                results.append(label)

        async def _inner():
            async with tracer.atrace("concurrent") as run:
                async with run.astep("parent", kind="step"):
                    await asyncio.gather(
                        child(run, "child_a"),
                        child(run, "child_b"),
                    )
            return run

        run = asyncio.run(_inner())
        graph = store.get_graph(run.run_id)
        parent_node = next(n for n in graph.nodes if n.label == "parent")
        for label in ("child_a", "child_b"):
            child_node = next(n for n in graph.nodes if n.label == label)
            assert child_node.parent_id == parent_node.id

        assert set(results) == {"child_a", "child_b"}

    def test_async_error_recorded(self, tracer, store):
        async def _inner():
            async with tracer.atrace("test") as run:
                async with run.astep("bad", kind="step"):
                    raise RuntimeError("async fail")

        with pytest.raises(RuntimeError):
            asyncio.run(_inner())

        runs = store.list_runs()
        run_id = runs[0].run_id
        t = types_of(store, run_id)
        assert "error" in t
        assert "step_end" not in t

    def test_context_var_cleared_after_async_trace(self, tracer):
        async def _inner():
            async with tracer.atrace("test"):
                pass

        asyncio.run(_inner())
        assert _current_step.get() is None


# ---------------------------------------------------------------------------
# get_current_step()
# ---------------------------------------------------------------------------

class TestGetCurrentStep:
    def test_returns_none_outside_trace(self, tracer):
        assert tracer.get_current_step() is None

    def test_returns_context_inside_trace(self, tracer):
        with tracer.trace("test") as run:
            ctx = tracer.get_current_step()
            assert ctx is not None
            assert ctx.run_id == run.run_id

    def test_returns_step_context_inside_step(self, tracer):
        with tracer.trace("test") as run:
            with run.step("work", kind="step") as step:
                ctx = tracer.get_current_step()
                assert ctx.node_id == step.node_id


# ---------------------------------------------------------------------------
# Multiple independent runs
# ---------------------------------------------------------------------------

class TestMultipleRuns:
    def test_two_runs_are_isolated(self, tracer, store):
        with tracer.trace("run1") as r1:
            with r1.step("a", kind="step"):
                pass

        with tracer.trace("run2") as r2:
            with r2.step("b", kind="tool"):
                pass

        assert r1.run_id != r2.run_id
        assert store.get_graph(r1.run_id) is not None
        assert store.get_graph(r2.run_id) is not None
        assert len(store.list_runs()) == 2

    def test_list_runs_newest_first(self, tracer, store):
        with tracer.trace("first"):
            pass
        with tracer.trace("second"):
            pass

        summaries = store.list_runs()
        assert summaries[0].label == "second"
        assert summaries[1].label == "first"
