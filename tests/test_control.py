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
from vapviz.tracer import (
    Tracer,
    aask,
    acheckpoint,
    ask,
    asay,
    atake_input,
    checkpoint,
    say,
    take_input,
)


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


# ===========================================================================
# Layer 2 — inject a message (mailbox) + checkpoint()
# ===========================================================================

# ---------------------------------------------------------------------------
# Store mailbox
# ---------------------------------------------------------------------------

def test_mailbox_defaults_empty():
    store = MemoryStore()
    c = store.get_control("r")
    assert c.pending_input is None and c.waiting_for_input is False
    assert store.take_input_if_ready("r") is None


def test_set_and_take_input_roundtrip():
    store = MemoryStore()
    store.set_input("r", "hello")
    assert store.get_control("r").pending_input == "hello"
    assert store.take_input_if_ready("r") == "hello"
    # consume-and-clear: a second take gets nothing
    assert store.take_input_if_ready("r") is None
    assert store.get_control("r").pending_input is None


def test_set_input_overwrites_unconsumed_message():
    """Single-slot mailbox — last write wins (see DESIGN §19)."""
    store = MemoryStore()
    store.set_input("r", "first")
    store.set_input("r", "second")
    assert store.take_input_if_ready("r") == "second"


def test_empty_string_message_is_delivered():
    """'' is a real message, distinct from an empty mailbox (None)."""
    store = MemoryStore()
    store.set_input("r", "")
    assert store.get_control("r").pending_input == ""
    assert store.take_input_if_ready("r") == ""  # not None


def test_set_waiting_for_input_roundtrip():
    store = MemoryStore()
    store.set_waiting_for_input("r", True)
    assert store.get_control("r").waiting_for_input is True
    store.set_waiting_for_input("r", False)
    assert store.get_control("r").waiting_for_input is False


def test_mailbox_cleared_on_delete():
    store = MemoryStore()
    store.set_input("r", "x")
    store.set_waiting_for_input("r", True)
    store.delete_run("r")
    c = store.get_control("r")
    assert c.pending_input is None and c.waiting_for_input is False


def test_get_control_copy_includes_mailbox_fields():
    """The snapshot must carry the new fields (regression: positional copy dropped them)."""
    store = MemoryStore()
    store.set_input("r", "msg")
    store.set_waiting_for_input("r", True)
    snap = store.get_control("r")
    assert snap.pending_input == "msg" and snap.waiting_for_input is True
    # and it is a copy — mutating it must not corrupt the store
    snap.pending_input = "tampered"
    assert store.get_control("r").pending_input == "msg"


# ── Layer 2b — the agent → user question latch ──────────────────────────────

def test_set_question_roundtrip_and_clear():
    store = MemoryStore()
    assert store.get_control("r").question is None
    store.set_question("r", "Which region?")
    assert store.get_control("r").question == "Which region?"
    store.set_question("r", None)  # cleared when ask() returns
    assert store.get_control("r").question is None


def test_get_control_copy_includes_question():
    store = MemoryStore()
    store.set_question("r", "Which region?")
    snap = store.get_control("r")
    assert snap.question == "Which region?"
    snap.question = "tampered"  # a copy — must not corrupt the store
    assert store.get_control("r").question == "Which region?"


def test_question_cleared_on_delete():
    store = MemoryStore()
    store.set_question("r", "Which region?")
    store.delete_run("r")
    assert store.get_control("r").question is None


# ---------------------------------------------------------------------------
# Tracer — take_input (sync)
# ---------------------------------------------------------------------------

def _wait_until(pred, timeout=2.0):
    deadline = time.time() + timeout
    while not pred() and time.time() < deadline:
        time.sleep(0.01)
    return pred()


def test_take_input_blocks_until_message():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-input"
    entered = threading.Event()
    received: dict[str, object] = {}

    def agent():
        with tracer.trace("Asker", run_id=run_id) as run:
            with run.step("ask"):
                entered.set()
                received["msg"] = take_input()  # blocks until a message arrives

    t = threading.Thread(target=agent)
    t.start()
    assert entered.wait(2)
    # the agent flags that it is waiting
    assert _wait_until(lambda: store.get_control(run_id).waiting_for_input)
    store.set_input(run_id, "do the thing")
    t.join(5)
    assert not t.is_alive()
    assert received["msg"] == "do the thing"
    # flag cleared once take_input returns
    assert store.get_control(run_id).waiting_for_input is False
    assert store.get_graph(run_id).status == NodeStatus.SUCCESS


def test_take_input_peek_and_present():
    """timeout=0 returns None on an empty mailbox, the message when one is present."""
    store = MemoryStore()
    tracer = Tracer(store=store)
    got: dict[str, object] = {}
    with tracer.trace("Peek", run_id="peek") as run:
        with run.step("s"):
            got["empty"] = take_input(timeout=0)
            store.set_input("peek", "later")
            got["present"] = take_input(timeout=0)
    assert got["empty"] is None
    assert got["present"] == "later"


def test_take_input_times_out():
    store = MemoryStore()
    tracer = Tracer(store=store)
    t0 = time.time()
    with tracer.trace("T", run_id="t") as run:
        with run.step("s"):
            out = take_input(timeout=0.2)
    assert out is None
    assert time.time() - t0 >= 0.2


def test_take_input_interrupted_by_stop():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-input-stop"
    entered = threading.Event()

    def agent():
        try:
            with tracer.trace("Asker", run_id=run_id) as run:
                with run.step("ask"):
                    entered.set()
                    take_input()  # blocks; Stop must break the wait
        except VapStopped:
            pass

    t = threading.Thread(target=agent)
    t.start()
    assert entered.wait(2)
    assert _wait_until(lambda: store.get_control(run_id).waiting_for_input)
    store.set_desired(run_id, STOPPED)
    t.join(5)
    assert not t.is_alive()
    assert store.get_graph(run_id).status == NodeStatus.STOPPED


def test_take_input_outside_trace_raises():
    with pytest.raises(RuntimeError):
        take_input(timeout=0)


# ---------------------------------------------------------------------------
# Tracer — checkpoint()
# ---------------------------------------------------------------------------

def test_checkpoint_outside_trace_raises():
    with pytest.raises(RuntimeError):
        checkpoint()


def test_checkpoint_makes_a_stepless_loop_stoppable():
    """An agent with no per-iteration step stays stoppable via checkpoint()."""
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-ckpt"
    in_loop = threading.Event()

    def agent():
        try:
            with tracer.trace("Looper", run_id=run_id) as run:
                for _ in range(500):  # NB: no run.step() — checkpoint() is the only turnstile
                    checkpoint()
                    in_loop.set()
                    time.sleep(0.005)
        except VapStopped:
            pass

    t = threading.Thread(target=agent)
    t.start()
    assert in_loop.wait(2)
    store.set_desired(run_id, STOPPED)
    t.join(5)
    assert not t.is_alive()
    assert store.get_graph(run_id).status == NodeStatus.STOPPED


def test_checkpoint_parks_while_paused():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-ckpt-pause"
    in_loop = threading.Event()
    done = threading.Event()

    def agent():
        with tracer.trace("Looper", run_id=run_id) as run:
            for _ in range(400):
                checkpoint()
                in_loop.set()
                time.sleep(0.005)
        done.set()

    t = threading.Thread(target=agent)
    t.start()
    assert in_loop.wait(2)
    store.set_desired(run_id, PAUSED)
    assert _wait_until(lambda: store.get_control(run_id).acked == PAUSED)
    assert not done.is_set()
    store.set_desired(run_id, RUNNING)
    t.join(5)
    assert done.is_set()


# ---------------------------------------------------------------------------
# Tracer — async variants (driven via asyncio.run, no pytest-asyncio dep)
# ---------------------------------------------------------------------------

def test_async_take_input_blocks_until_message():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-ainput"
    received: dict[str, object] = {}

    async def scenario():
        async def agent():
            async with tracer.atrace("AsyncAsker", run_id=run_id) as run:
                async with run.astep("ask"):
                    received["msg"] = await atake_input()

        task = asyncio.create_task(agent())
        # let it reach atake_input and flag waiting
        for _ in range(200):
            if store.get_control(run_id).waiting_for_input:
                break
            await asyncio.sleep(0.01)
        store.set_input(run_id, "async hello")
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(scenario())
    assert received["msg"] == "async hello"
    assert store.get_control(run_id).waiting_for_input is False


def test_async_acheckpoint_stops_stepless_loop():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-ackpt"

    async def scenario():
        async def agent():
            try:
                async with tracer.atrace("ALooper", run_id=run_id) as run:
                    for _ in range(500):
                        await acheckpoint()
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
# Server — POST /input + GET /control mailbox fields
# ---------------------------------------------------------------------------

def test_input_post_404(app_client):
    client, _ = app_client
    assert client.post("/runs/nope/input", json={"message": "hi"}).status_code == 404


def test_input_on_live_run(app_client):
    client, store = app_client
    rid = _seed_running(store)
    r = client.post(f"/runs/{rid}/input", json={"message": "hello agent"})
    assert r.status_code == 200
    body = r.json()
    assert body["pending_input"] is True and body["ended"] is False
    assert store.get_control(rid).pending_input == "hello agent"
    # inert control audit event with action=input (+ the message) landed
    controls = [e for e in store.get_events(rid) if e.type.value == "control"]
    assert controls and controls[-1].data["action"] == "input"
    assert controls[-1].data["message"] == "hello agent"


def test_input_noop_on_ended_run(app_client):
    client, store = app_client
    rid = _seed_completed(store)
    r = client.post(f"/runs/{rid}/input", json={"message": "too late"})
    assert r.status_code == 200
    assert r.json()["ended"] is True
    assert store.get_control(rid).pending_input is None
    assert "control" not in [e.type.value for e in store.get_events(rid)]


def test_get_control_reflects_waiting_and_pending(app_client):
    client, store = app_client
    rid = _seed_running(store)
    store.set_waiting_for_input(rid, True)
    store.set_input(rid, "queued")
    body = client.get(f"/runs/{rid}/control").json()
    assert body["waiting_for_input"] is True
    assert body["pending_input"] is True


def test_get_control_does_not_leak_message_text(app_client):
    """The response exposes only that a message is pending, never its text."""
    client, store = app_client
    rid = _seed_running(store)
    store.set_input(rid, "secret plan")
    body = client.get(f"/runs/{rid}/control").json()
    assert "secret plan" not in str(body)
    assert body["pending_input"] is True


# ---------------------------------------------------------------------------
# Layer 2b — ask() / say() (agent → user conversation)
# ---------------------------------------------------------------------------

def _controls(store, run_id):
    return [e for e in store.get_events(run_id) if e.type.value == "control"]


def test_ask_blocks_sets_question_and_returns_reply():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-ask"
    entered = threading.Event()
    received: dict[str, object] = {}

    def agent():
        with tracer.trace("Asker", run_id=run_id) as run:
            with run.step("plan"):
                entered.set()
                received["ans"] = ask("Which region?")

    t = threading.Thread(target=agent)
    t.start()
    assert entered.wait(2)
    # the question is visible while the agent waits, and it flags waiting
    assert _wait_until(lambda: store.get_control(run_id).question == "Which region?")
    assert _wait_until(lambda: store.get_control(run_id).waiting_for_input)
    # the ask turn landed on the timeline as an inert control event
    asks = [e for e in _controls(store, run_id) if e.data.get("action") == "ask"]
    assert asks and asks[-1].data["message"] == "Which region?"
    # reply arrives on the same mailbox the UI writes
    store.set_input(run_id, "us-west")
    t.join(5)
    assert not t.is_alive()
    assert received["ans"] == "us-west"
    # question cleared once ask() returns; run finished clean
    assert store.get_control(run_id).question is None
    assert store.get_control(run_id).waiting_for_input is False
    assert store.get_graph(run_id).status == NodeStatus.SUCCESS


def test_ask_times_out_returns_none_and_clears_question():
    store = MemoryStore()
    tracer = Tracer(store=store)
    with tracer.trace("T", run_id="ask-timeout") as run:
        with run.step("s"):
            out = ask("Which region?", timeout=0.2)
    assert out is None
    assert store.get_control("ask-timeout").question is None  # cleared via finally


def test_ask_interrupted_by_stop_clears_question():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "ask-stop"
    entered = threading.Event()

    def agent():
        try:
            with tracer.trace("Asker", run_id=run_id) as run:
                with run.step("plan"):
                    entered.set()
                    ask("Which region?")  # blocks; Stop must break it
        except VapStopped:
            pass

    t = threading.Thread(target=agent)
    t.start()
    assert entered.wait(2)
    assert _wait_until(lambda: store.get_control(run_id).waiting_for_input)
    store.set_desired(run_id, STOPPED)
    t.join(5)
    assert not t.is_alive()
    assert store.get_control(run_id).question is None  # cleared even on interrupt
    assert store.get_graph(run_id).status == NodeStatus.STOPPED


def test_say_emits_turn_without_blocking():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-say"
    with tracer.trace("Teller", run_id=run_id) as run:
        with run.step("plan"):
            say("Switching to us-west.")
    says = [e for e in _controls(store, run_id) if e.data.get("action") == "say"]
    assert says and says[-1].data["message"] == "Switching to us-west."
    # say() never touches the question latch and never blocks
    assert store.get_control(run_id).question is None
    assert store.get_graph(run_id).status == NodeStatus.SUCCESS


def test_ask_and_say_outside_trace_raise():
    with pytest.raises(RuntimeError):
        ask("x", timeout=0)
    with pytest.raises(RuntimeError):
        say("x")


@pytest.mark.asyncio
async def test_aask_blocks_and_returns_reply():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-aask"

    async def agent():
        async with tracer.atrace("Asker", run_id=run_id) as run:
            async with run.astep("plan"):
                return await aask("Which region?")

    task = asyncio.create_task(agent())
    # wait until the async agent is parked, then answer
    for _ in range(200):
        if store.get_control(run_id).waiting_for_input:
            break
        await asyncio.sleep(0.01)
    assert store.get_control(run_id).question == "Which region?"
    store.set_input(run_id, "eu-central")
    ans = await asyncio.wait_for(task, timeout=5)
    assert ans == "eu-central"
    assert store.get_control(run_id).question is None


@pytest.mark.asyncio
async def test_asay_emits_turn():
    store = MemoryStore()
    tracer = Tracer(store=store)
    run_id = "run-asay"
    async with tracer.atrace("Teller", run_id=run_id) as run:
        async with run.astep("plan"):
            await asay("done")
    says = [e for e in _controls(store, run_id) if e.data.get("action") == "say"]
    assert says and says[-1].data["message"] == "done"


def test_get_control_echoes_question(app_client):
    """Unlike the injected message, the agent's question text IS surfaced."""
    client, store = app_client
    rid = _seed_running(store)
    store.set_question(rid, "Which region?")
    body = client.get(f"/runs/{rid}/control").json()
    assert body["question"] == "Which region?"


def test_get_control_question_null_when_not_asking(app_client):
    client, store = app_client
    rid = _seed_running(store)
    assert client.get(f"/runs/{rid}/control").json()["question"] is None
