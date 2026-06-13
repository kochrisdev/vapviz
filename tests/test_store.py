"""Tests for MemoryStore and SqliteStore (vapviz/store.py, vapviz/backends/sqlite.py)."""
from __future__ import annotations

import os
import tempfile
import threading
import time

import pytest

from vapviz.events import EventType, NodeKind, NodeStatus, VapEvent
from vapviz.store import MemoryStore, _apply_event_to_graph
from vapviz.events import RunGraph


# ---------------------------------------------------------------------------
# Helper: build a minimal VapEvent
# ---------------------------------------------------------------------------

_seq = 0

def _event(run_id: str, type: EventType, node_id: str, node_kind: NodeKind,
           label: str, parent_id=None, data=None) -> VapEvent:
    global _seq
    _seq += 1
    return VapEvent(
        id=f"evt{_seq:06d}",
        run_id=run_id,
        timestamp=time.time() + _seq * 0.001,
        type=type,
        node_id=node_id,
        node_kind=node_kind,
        node_label=label,
        parent_id=parent_id,
        data=data or {},
    )


def _agent_start(run_id, node_id="root", label="Agent"):
    return _event(run_id, EventType.AGENT_START, node_id, NodeKind.AGENT, label,
                  data={"label": label})

def _agent_end(run_id, node_id="root"):
    return _event(run_id, EventType.AGENT_END, node_id, NodeKind.AGENT, "Agent")

def _step_start(run_id, node_id, label, parent_id=None):
    return _event(run_id, EventType.STEP_START, node_id, NodeKind.STEP, label, parent_id)

def _step_end(run_id, node_id, label, parent_id=None):
    return _event(run_id, EventType.STEP_END, node_id, NodeKind.STEP, label, parent_id)


# ---------------------------------------------------------------------------
# _apply_event_to_graph (pure function)
# ---------------------------------------------------------------------------

class TestApplyEventToGraph:
    def test_agent_start_creates_node(self):
        graph = RunGraph(run_id="r1", label="A", status=NodeStatus.RUNNING, started_at=1.0)
        _apply_event_to_graph(graph, _agent_start("r1", "n1"))
        assert len(graph.nodes) == 1
        assert graph.nodes[0].id == "n1"
        assert graph.nodes[0].status == NodeStatus.RUNNING

    def test_agent_end_sets_success(self):
        graph = RunGraph(run_id="r1", label="A", status=NodeStatus.RUNNING, started_at=1.0)
        _apply_event_to_graph(graph, _agent_start("r1", "n1"))
        _apply_event_to_graph(graph, _agent_end("r1", "n1"))
        assert graph.nodes[0].status == NodeStatus.SUCCESS
        assert graph.status == NodeStatus.SUCCESS

    def test_child_step_creates_edge(self):
        graph = RunGraph(run_id="r1", label="A", status=NodeStatus.RUNNING, started_at=1.0)
        _apply_event_to_graph(graph, _agent_start("r1", "root"))
        _apply_event_to_graph(graph, _step_start("r1", "child", "do_work", parent_id="root"))
        assert len(graph.edges) == 1
        assert graph.edges[0].source == "root"
        assert graph.edges[0].target == "child"

    def test_error_event_sets_node_error(self):
        graph = RunGraph(run_id="r1", label="A", status=NodeStatus.RUNNING, started_at=1.0)
        _apply_event_to_graph(graph, _step_start("r1", "n1", "work"))
        err = _event("r1", EventType.ERROR, "n1", NodeKind.STEP, "work",
                     data={"error": "boom", "error_type": "ValueError"})
        _apply_event_to_graph(graph, err)
        assert graph.nodes[0].status == NodeStatus.ERROR

    def test_duplicate_node_id_not_added_twice(self):
        graph = RunGraph(run_id="r1", label="A", status=NodeStatus.RUNNING, started_at=1.0)
        e = _agent_start("r1", "n1")
        _apply_event_to_graph(graph, e)
        _apply_event_to_graph(graph, e)  # same event again
        assert len(graph.nodes) == 1

    def test_duplicate_edge_not_added_twice(self):
        graph = RunGraph(run_id="r1", label="A", status=NodeStatus.RUNNING, started_at=1.0)
        _apply_event_to_graph(graph, _agent_start("r1", "root"))
        s = _step_start("r1", "child", "work", parent_id="root")
        _apply_event_to_graph(graph, s)
        _apply_event_to_graph(graph, s)
        assert len(graph.edges) == 1


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------

class TestMemoryStore:
    def test_add_and_get_events(self, store):
        e = _agent_start("r1")
        store.add_event(e)
        events = store.get_events("r1")
        assert len(events) == 1
        assert events[0].id == e.id

    def test_get_events_empty_run(self, store):
        assert store.get_events("nonexistent") == []

    def test_duplicate_event_id_ignored(self, store):
        # Regression (U6): MemoryStore must dedupe by event.id like
        # SqliteStore does — e.g. retried remote ingest or SSE replay.
        e = _agent_start("r1")
        store.add_event(e)
        store.add_event(e)
        assert len(store.get_events("r1")) == 1
        assert store.get_run("r1").event_count == 1

    def test_duplicate_id_cleared_on_delete(self, store):
        e = _agent_start("r1")
        store.add_event(e)
        store.delete_run("r1")
        store.add_event(e)
        assert len(store.get_events("r1")) == 1

    def test_list_runs_empty(self, store):
        assert store.list_runs() == []

    def test_list_runs_after_add(self, store):
        store.add_event(_agent_start("r1", label="Run One"))
        runs = store.list_runs()
        assert len(runs) == 1
        assert runs[0].run_id == "r1"
        assert runs[0].label == "Run One"

    def test_list_runs_newest_first(self, store):
        store.add_event(_agent_start("r1"))
        time.sleep(0.01)
        store.add_event(_agent_start("r2"))
        runs = store.list_runs()
        assert runs[0].run_id == "r2"

    def test_get_run_returns_summary(self, store):
        store.add_event(_agent_start("r1", label="MyRun"))
        summary = store.get_run("r1")
        assert summary is not None
        assert summary.label == "MyRun"
        assert summary.status == NodeStatus.RUNNING

    def test_get_run_missing(self, store):
        assert store.get_run("nope") is None

    def test_get_graph_returns_copy(self, store):
        store.add_event(_agent_start("r1", "root"))
        g1 = store.get_graph("r1")
        g2 = store.get_graph("r1")
        assert g1 is not g2          # deep copy, not same object

    def test_delete_run(self, store):
        store.add_event(_agent_start("r1"))
        store.add_event(_agent_start("r2"))
        store.delete_run("r1")
        assert store.get_run("r1") is None
        assert store.get_run("r2") is not None

    def test_clear_removes_all_runs(self, store):
        store.add_event(_agent_start("r1"))
        store.add_event(_agent_start("r2"))
        store.clear()
        assert store.list_runs() == []

    def test_event_count_tracked(self, store):
        for e in [_agent_start("r1", "n"), _step_start("r1", "s", "work", "n"), _agent_end("r1", "n")]:
            store.add_event(e)
        summary = store.get_run("r1")
        assert summary.event_count == 3

    def test_node_count_tracked(self, store):
        store.add_event(_agent_start("r1", "root"))
        store.add_event(_step_start("r1", "child", "work", "root"))
        summary = store.get_run("r1")
        assert summary.node_count == 2

    def test_thread_safe_concurrent_writes(self, store):
        """Multiple threads writing events to the same run must not corrupt state."""
        errors = []

        def writer(run_id, label):
            try:
                for i in range(20):
                    store.add_event(
                        _step_start(run_id, f"{label}_{i}", f"{label}_{i}")
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=("r1", f"t{n}")) for n in range(5)]
        store.add_event(_agent_start("r1", "root"))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        events = store.get_events("r1")
        # 1 agent_start + 5 threads * 20 step_starts
        assert len(events) == 101

    def test_pub_sub_delivers_events(self, store):
        import asyncio

        async def run():
            loop = asyncio.get_running_loop()
            store.set_loop(loop)
            q = store.subscribe("r1")
            store.add_event(_agent_start("r1", "root"))
            event = await asyncio.wait_for(q.get(), timeout=1.0)
            store.unsubscribe("r1", q)
            return event

        event = asyncio.run(run())
        assert event.run_id == "r1"

    def test_unsubscribe_stops_delivery(self, store):
        import asyncio

        async def run():
            loop = asyncio.get_running_loop()
            store.set_loop(loop)
            q = store.subscribe("r1")
            store.unsubscribe("r1", q)
            store.add_event(_agent_start("r1", "root"))
            # Queue should still be empty since we unsubscribed
            await asyncio.sleep(0.05)
            return q.empty()

        assert asyncio.run(run()) is True


# ---------------------------------------------------------------------------
# SqliteStore
# ---------------------------------------------------------------------------

class TestSqliteStore:
    @pytest.fixture
    def db_path(self, tmp_path):
        return str(tmp_path / "test.db")

    @pytest.fixture
    def sqlite_store(self, db_path):
        from vapviz.backends.sqlite import SqliteStore
        s = SqliteStore(db_path)
        yield s
        s.close()

    def test_add_and_get_events(self, sqlite_store):
        e = _agent_start("r1")
        sqlite_store.add_event(e)
        events = sqlite_store.get_events("r1")
        assert len(events) == 1
        assert events[0].id == e.id

    def test_persistence_across_instances(self, db_path):
        from vapviz.backends.sqlite import SqliteStore

        s1 = SqliteStore(db_path)
        e = _agent_start("r1", label="Persistent")
        s1.add_event(e)
        s1.close()

        s2 = SqliteStore(db_path)
        runs = s2.list_runs()
        assert len(runs) == 1
        assert runs[0].label == "Persistent"
        s2.close()

    def test_replay_on_startup_rebuilds_graph(self, db_path):
        from vapviz.backends.sqlite import SqliteStore

        s1 = SqliteStore(db_path)
        s1.add_event(_agent_start("r1", "root"))
        s1.add_event(_step_start("r1", "child", "work", "root"))
        s1.add_event(_agent_end("r1", "root"))
        s1.close()

        s2 = SqliteStore(db_path)
        graph = s2.get_graph("r1")
        assert graph is not None
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert graph.status == NodeStatus.SUCCESS
        s2.close()

    def test_delete_run_removes_from_db(self, db_path):
        from vapviz.backends.sqlite import SqliteStore

        s1 = SqliteStore(db_path)
        s1.add_event(_agent_start("r1"))
        s1.delete_run("r1")
        s1.close()

        s2 = SqliteStore(db_path)
        assert s2.get_run("r1") is None
        s2.close()

    def test_clear_removes_all_from_db(self, db_path):
        from vapviz.backends.sqlite import SqliteStore

        s1 = SqliteStore(db_path)
        s1.add_event(_agent_start("r1"))
        s1.add_event(_agent_start("r2"))
        s1.clear()
        s1.close()

        s2 = SqliteStore(db_path)
        assert s2.list_runs() == []
        s2.close()

    def test_insert_or_ignore_prevents_duplicate(self, db_path):
        from vapviz.backends.sqlite import SqliteStore

        s = SqliteStore(db_path)
        e = _agent_start("r1")
        s.add_event(e)
        s.add_event(e)  # duplicate
        assert len(s.get_events("r1")) == 1
        s.close()
