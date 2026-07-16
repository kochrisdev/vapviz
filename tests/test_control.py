"""Tests for the live run control channel (Pause / Resume / Stop).

Covers the store latch, the tracer's cooperative checkpoints (sync + async),
and the server endpoints. Fast + offline (no LLM). See vapviz/control.py and
docs/notes/DESIGN-agent-control.md.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from vapviz.control import PAUSED, RUNNING, STOPPED, VapStopped
from vapviz.events import EventType, NodeKind, NodeStatus, VapEvent
from vapviz.server import create_app
from vapviz.store import MemoryStore
from vapviz.tracer import Tracer


# ---------------------------------------------------------------------------
# Store latch
# ---------------------------------------------------------------------------

def test_control_defaults_to_running():
    store = MemoryStore()
    c = store.get_control("unknown")
    assert c.desired == RUNNING and c.acked == RUNNING


def test_set_desired_and_ack_roundtrip():
    store = MemoryStore()
    store.set_desired("r", PAUSED)
    assert store.get_control("r").desired == PAUSED
    store.set_ack("r", PAUSED)
    assert store.get_control("r").acked == PAUSED


def test_set_desired_rejects_bad_state():
    store = MemoryStore()
    with pytest.raises(ValueError):
        store.set_desired("r", "bogus")


def test_control_cleared_on_delete_and_clear():
    store = MemoryStore()
    store.set_desired("r", PAUSED)
    store.delete_run("r")
    assert store.get_control("r").desired == RUNNING  # back to default
    store.set_desired("r2", STOPPED)
    store.clear()
    assert store.get_control("r2").desired == RUNNING


def test_get_control_returns_a_copy():
    """Mutating the snapshot must not corrupt the stored latch."""
    store = MemoryStore()
    store.set_desired("r", PAUSED)
    snap = store.get_control("r")
    snap.desired = STOPPED
    assert store.get_control("r").desired == PAUSED


# ---------------------------------------------------------------------------
# Tracer — cooperative checkpoints (sync)
# ---------------------------------------------------------------------------

def test_stop_ends_run_as_stopped():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-stop"
    started = threading.Event()

    def agent():
        try:
            with tracer.trace("Stoppable", run_id=run_id) as run:
                with run.step("outer"):
                    started.set()
                    for i in range(500):
                        with run.step(f"work-{i}"):
                            time.sleep(0.005)
        except VapStopped:
            pass  # graceful shutdown

    t = threading.Thread(target=agent)
    t.start()
    assert started.wait(2), "agent never started"
    store.set_desired(run_id, STOPPED)
    t.join(5)
    assert not t.is_alive(), "agent did not stop at the next checkpoint"

    g = store.get_graph(run_id)
    assert g.status == NodeStatus.STOPPED
    by_label = {n.label: n.status for n in g.nodes}
    assert by_label["Stoppable"] == NodeStatus.STOPPED  # root agent node
    assert by_label["outer"] == NodeStatus.STOPPED      # was open when stop hit
    # a stop is not a crash: no node should be 'error'
    assert all(n.status != NodeStatus.ERROR for n in g.nodes)
    # work steps that finished before the stop stay 'success'
    assert any(n.status == NodeStatus.SUCCESS for n in g.nodes)


def test_pause_parks_then_resume_completes():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-pause"
    in_loop = threading.Event()
    done = threading.Event()

    def agent():
        with tracer.trace("Pausable", run_id=run_id) as run:
            for i in range(400):
                with run.step(f"work-{i}"):
                    in_loop.set()
                    time.sleep(0.005)
        done.set()

    t = threading.Thread(target=agent)
    t.start()
    assert in_loop.wait(2)
    store.set_desired(run_id, PAUSED)

    # wait until the agent acknowledges the pause at a checkpoint
    deadline = time.time() + 2
    while store.get_control(run_id).acked != PAUSED and time.time() < deadline:
        time.sleep(0.01)
    assert store.get_control(run_id).acked == PAUSED
    assert not done.is_set()
    time.sleep(0.2)  # stays parked while paused
    assert not done.is_set()

    store.set_desired(run_id, RUNNING)
    t.join(5)
    assert done.is_set(), "agent did not resume"
    assert store.get_graph(run_id).status == NodeStatus.SUCCESS


def test_pause_then_stop_raises():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-pause-stop"
    in_loop = threading.Event()

    def agent():
        try:
            with tracer.trace("PauseStop", run_id=run_id) as run:
                for i in range(400):
                    with run.step(f"work-{i}"):
                        in_loop.set()
                        time.sleep(0.005)
        except VapStopped:
            pass

    t = threading.Thread(target=agent)
    t.start()
    assert in_loop.wait(2)
    store.set_desired(run_id, PAUSED)
    deadline = time.time() + 2
    while store.get_control(run_id).acked != PAUSED and time.time() < deadline:
        time.sleep(0.01)
    assert store.get_control(run_id).acked == PAUSED
    # promote pause → stop; the parked agent must wake and stop
    store.set_desired(run_id, STOPPED)
    t.join(5)
    assert not t.is_alive()
    assert store.get_graph(run_id).status == NodeStatus.STOPPED


# ---------------------------------------------------------------------------
# Tracer — async checkpoints (driven via asyncio.run, no pytest-asyncio dep)
# ---------------------------------------------------------------------------

def test_async_stop_ends_run_as_stopped():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-async-stop"

    async def scenario():
        async def agent():
            try:
                async with tracer.atrace("AsyncStop", run_id=run_id) as run:
                    for i in range(500):
                        async with run.astep(f"w-{i}"):
                            await asyncio.sleep(0.003)
            except VapStopped:
                pass

        task = asyncio.create_task(agent())
        await asyncio.sleep(0.05)
        store.set_desired(run_id, STOPPED)
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(scenario())
    assert store.get_graph(run_id).status == NodeStatus.STOPPED


# ---------------------------------------------------------------------------
# Server endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client():
    store = MemoryStore()
    app = create_app(store=store)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, store


def _seed_running(store: MemoryStore, run_id: str = "live") -> str:
    store.add_event(
        VapEvent(
            id=uuid.uuid4().hex[:12], run_id=run_id, timestamp=time.time(),
            type=EventType.AGENT_START, node_id="root", node_kind=NodeKind.AGENT,
            node_label="Live", parent_id=None, data={},
        )
    )
    return run_id


def _seed_completed(store: MemoryStore, run_id: str = "done") -> str:
    _seed_running(store, run_id)
    store.add_event(
        VapEvent(
            id=uuid.uuid4().hex[:12], run_id=run_id, timestamp=time.time(),
            type=EventType.AGENT_END, node_id="root", node_kind=NodeKind.AGENT,
            node_label="Live", parent_id=None, data={},
        )
    )
    return run_id


def test_control_get_404(app_client):
    client, _ = app_client
    assert client.get("/runs/nope/control").status_code == 404


def test_control_post_404(app_client):
    client, _ = app_client
    assert client.post("/runs/nope/control", json={"action": "pause"}).status_code == 404


def test_control_pause_on_live_run(app_client):
    client, store = app_client
    rid = _seed_running(store)
    r = client.post(f"/runs/{rid}/control", json={"action": "pause"})
    assert r.status_code == 200
    body = r.json()
    assert body["desired"] == "paused" and body["ended"] is False
    assert store.get_control(rid).desired == "paused"
    # inert audit event landed in the timeline
    assert "control" in [e.type.value for e in store.get_events(rid)]
    # GET reflects it
    assert client.get(f"/runs/{rid}/control").json()["desired"] == "paused"


def test_control_resume_maps_to_running(app_client):
    client, store = app_client
    rid = _seed_running(store)
    client.post(f"/runs/{rid}/control", json={"action": "pause"})
    client.post(f"/runs/{rid}/control", json={"action": "resume"})
    assert store.get_control(rid).desired == "running"


def test_control_invalid_action_422(app_client):
    client, store = app_client
    rid = _seed_running(store)
    assert client.post(f"/runs/{rid}/control", json={"action": "boom"}).status_code == 422


def test_control_noop_on_ended_run(app_client):
    client, store = app_client
    rid = _seed_completed(store)
    r = client.post(f"/runs/{rid}/control", json={"action": "stop"})
    assert r.status_code == 200
    assert r.json()["ended"] is True
    # no latch change, no audit event
    assert store.get_control(rid).desired == "running"
    assert "control" not in [e.type.value for e in store.get_events(rid)]
