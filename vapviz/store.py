from __future__ import annotations

import asyncio
import json
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import replace
from threading import Lock
from typing import Any, Optional

from .control import DESIRED_STATES, RunControl
from .events import (
    EventType,
    GraphEdge,
    GraphNode,
    NodeKind,
    NodeStatus,
    RunGraph,
    RunSummary,
    VapEvent,
)
from .summary import summarize_run


# ---------------------------------------------------------------------------
# Shared helpers (pure functions, used by all store backends)
# ---------------------------------------------------------------------------

def _total_cost(graph: RunGraph) -> Optional[float]:
    """Sum cost_usd from all LLM nodes in the graph; return None if none have cost.

    Only ``llm``-kind nodes are summed: some integrations (e.g. Pydantic AI)
    also attach an aggregate ``cost_usd`` to the parent agent node, which would
    otherwise be double-counted.
    """
    total = 0.0
    found = False
    for node in graph.nodes:
        if node.kind != NodeKind.LLM:
            continue
        cost = node.data.get("output", {}).get("cost_usd") if isinstance(node.data.get("output"), dict) else None
        if cost is not None:
            total += cost
            found = True
    return round(total, 8) if found else None


def _terminal_status(data: dict[str, Any]) -> NodeStatus:
    """Derive a node/run's terminal status from an end event's data.

    DUAL-LOGIC: mirrors the ternary in ``applyEventToGraph`` (ui/src/store/
    runStore.ts). ``error`` wins over ``stopped`` (a crash is a crash); a
    user-stopped run carries ``stopped`` and no ``error`` → first-class
    ``stopped`` status.
    """
    if data.get("error"):
        return NodeStatus.ERROR
    if data.get("stopped"):
        return NodeStatus.STOPPED
    return NodeStatus.SUCCESS


def _apply_event_to_graph(graph: RunGraph, event: VapEvent) -> None:
    """Mutate *graph* in place according to *event*. No locking — caller's responsibility."""
    node_map = {n.id: n for n in graph.nodes}

    start_types = {
        EventType.AGENT_START,
        EventType.STEP_START,
        EventType.TOOL_CALL,
        EventType.LLM_CALL,
    }
    end_types = {
        EventType.AGENT_END,
        EventType.STEP_END,
        EventType.TOOL_RESULT,
        EventType.LLM_RESPONSE,
    }

    if event.type in start_types:
        if event.node_id not in node_map:
            node = GraphNode(
                id=event.node_id,
                kind=event.node_kind,
                label=event.node_label,
                status=NodeStatus.RUNNING,
                parent_id=event.parent_id,
                started_at=event.timestamp,
                data=dict(event.data),
            )
            graph.nodes.append(node)
            node_map[event.node_id] = node

        if event.parent_id and event.parent_id in node_map:
            edge_id = f"{event.parent_id}→{event.node_id}"
            if edge_id not in {e.id for e in graph.edges}:
                graph.edges.append(
                    GraphEdge(id=edge_id, source=event.parent_id, target=event.node_id)
                )

    elif event.type in end_types:
        node = node_map.get(event.node_id)
        if node:
            node.status = _terminal_status(event.data)
            node.ended_at = event.timestamp
            node.data.update(event.data)
        if event.type == EventType.AGENT_END:
            graph.status = _terminal_status(event.data)
            graph.ended_at = event.timestamp

    elif event.type == EventType.ERROR:
        node = node_map.get(event.node_id)
        if node:
            node.status = NodeStatus.ERROR
            node.ended_at = event.timestamp
            node.data.update(event.data)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class RunStore(ABC):
    """Abstract interface for a vapviz event store."""

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Inject the running asyncio event loop (called by the server on startup).
        Default is a no-op — override if the backend needs it."""

    @abstractmethod
    def add_event(self, event: VapEvent) -> None:
        """Persist *event* and notify SSE subscribers."""

    @abstractmethod
    def get_events(self, run_id: str) -> list[VapEvent]:
        """Return every event for *run_id* in insertion order."""

    @abstractmethod
    def get_graph(self, run_id: str) -> Optional[RunGraph]:
        """Return a deep copy of the current graph snapshot, or *None*."""

    @abstractmethod
    def get_run(self, run_id: str) -> Optional[RunSummary]:
        """Return a single run summary, or *None*."""

    @abstractmethod
    def list_runs(self) -> list[RunSummary]:
        """Return all run summaries, newest first."""

    @abstractmethod
    def delete_run(self, run_id: str) -> None:
        """Remove a run and all its events."""

    @abstractmethod
    def clear(self) -> None:
        """Remove every run."""

    @abstractmethod
    def subscribe(self, run_id: str) -> asyncio.Queue:
        """Return a queue that will receive live VapEvents for *run_id*."""

    @abstractmethod
    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        """Remove *q* from the subscriber list."""

    # ------------------------------------------------------------------
    # Tags — concrete, in-memory by default; SqliteStore persists them.
    # Subclasses provide ``self._tags`` (run_id -> list[str]) and ``self._lock``.
    # ------------------------------------------------------------------

    @staticmethod
    def _norm_tags(tags: list[str]) -> list[str]:
        """Strip, de-duplicate (preserving order), and drop empties."""
        out: list[str] = []
        for t in tags or []:
            s = str(t).strip()
            if s and s not in out:
                out.append(s)
        return out

    def get_tags(self, run_id: str) -> list[str]:
        with self._lock:  # type: ignore[attr-defined]
            return list(self._tags.get(run_id, []))  # type: ignore[attr-defined]

    def set_tags(self, run_id: str, tags: list[str]) -> list[str]:
        """Replace the tags for *run_id*. Returns the normalised list."""
        norm = self._norm_tags(tags)
        with self._lock:  # type: ignore[attr-defined]
            if norm:
                self._tags[run_id] = norm  # type: ignore[attr-defined]
            else:
                self._tags.pop(run_id, None)  # type: ignore[attr-defined]
        return norm

    # ------------------------------------------------------------------
    # Live run control (Pause / Resume / Stop) — ephemeral in-memory side
    # channel, guarded by ``self._lock`` (like tags). NOT part of the event log
    # or graph reducers, and NOT persisted. The tracer reads it at each step
    # checkpoint; the server writes it. Subclasses provide ``self._control``
    # (run_id -> RunControl) and ``self._control_wake`` (run_id -> Event).
    # See docs/notes/DESIGN-agent-control.md.
    # ------------------------------------------------------------------

    def get_control(self, run_id: str) -> RunControl:
        """Return a snapshot copy of the run's control latch (default: running)."""
        with self._lock:  # type: ignore[attr-defined]
            c = self._control.get(run_id)  # type: ignore[attr-defined]
            return replace(c) if c else RunControl()  # replace() copies all fields

    def set_desired(self, run_id: str, desired: str) -> RunControl:
        """Set what the UI wants the run to do next, then wake a parked agent."""
        if desired not in DESIRED_STATES:
            raise ValueError(f"invalid desired control state: {desired!r}")
        with self._lock:  # type: ignore[attr-defined]
            c = self._control.setdefault(run_id, RunControl())  # type: ignore[attr-defined]
            c.desired = desired
            c.updated_at = time.time()
            snap = replace(c)  # copy all fields (incl. the Layer 2 mailbox)
        self._control_wake_for(run_id).set()  # nudge a paused sync agent to re-check now
        return snap

    def set_ack(self, run_id: str, acked: str) -> None:
        """Record what the agent has actually done at a checkpoint (from the tracer)."""
        with self._lock:  # type: ignore[attr-defined]
            c = self._control.setdefault(run_id, RunControl())  # type: ignore[attr-defined]
            c.acked = acked
            c.updated_at = time.time()

    # ── Layer 2 mailbox — inject a message into a running agent ──────────────
    # The UI writes a message (``set_input``); the tracer consumes it at a
    # checkpoint inside ``take_input()`` (``take_input_if_ready``) and flags
    # while it waits (``set_waiting_for_input``). Single-slot, lock-guarded,
    # ephemeral — same side channel as desired/acked, never persisted or reduced.

    def set_input(self, run_id: str, message: str) -> RunControl:
        """UI → agent: write the mailbox, then wake a parked ``take_input()``."""
        with self._lock:  # type: ignore[attr-defined]
            c = self._control.setdefault(run_id, RunControl())  # type: ignore[attr-defined]
            c.pending_input = message  # single-slot: overwrites an unconsumed message
            c.updated_at = time.time()
            snap = replace(c)
        self._control_wake_for(run_id).set()  # nudge the agent to re-check its mailbox now
        return snap

    def take_input_if_ready(self, run_id: str) -> Optional[str]:
        """Tracer → consume-and-clear the pending message, or ``None`` if the
        mailbox is empty. An empty-string message is still a delivered message."""
        with self._lock:  # type: ignore[attr-defined]
            c = self._control.get(run_id)  # type: ignore[attr-defined]
            if c is None or c.pending_input is None:
                return None
            msg = c.pending_input
            c.pending_input = None
            c.updated_at = time.time()
            return msg

    def set_waiting_for_input(self, run_id: str, waiting: bool) -> None:
        """Tracer → flag whether the agent is parked in ``take_input()`` waiting,
        so the UI can honestly show 'agent is waiting for your input'."""
        with self._lock:  # type: ignore[attr-defined]
            c = self._control.setdefault(run_id, RunControl())  # type: ignore[attr-defined]
            c.waiting_for_input = waiting
            c.updated_at = time.time()

    def _control_wake_for(self, run_id: str) -> threading.Event:
        """Get-or-create the per-run wake Event a parked sync agent blocks on."""
        with self._lock:  # type: ignore[attr-defined]
            ev = self._control_wake.get(run_id)  # type: ignore[attr-defined]
            if ev is None:
                ev = threading.Event()
                self._control_wake[run_id] = ev  # type: ignore[attr-defined]
            return ev


# ---------------------------------------------------------------------------
# In-memory implementation (default)
# ---------------------------------------------------------------------------

class MemoryStore(RunStore):
    """Thread-safe in-memory store with asyncio pub/sub for SSE streaming."""

    def __init__(self) -> None:
        self._events: dict[str, list[VapEvent]] = {}
        self._event_ids: dict[str, set[str]] = {}   # run_id -> set of event IDs for dedup
        self._graphs: dict[str, RunGraph] = {}
        self._tags: dict[str, list[str]] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._control: dict[str, RunControl] = {}            # live pause/stop latch (ephemeral)
        self._control_wake: dict[str, threading.Event] = {}  # per-run wake for parked agents
        self._lock = Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def add_event(self, event: VapEvent) -> None:
        with self._lock:
            # Skip duplicates (mirrors SqliteStore — e.g. retried remote ingest)
            known_ids = self._event_ids.setdefault(event.run_id, set())
            if event.id in known_ids:
                return
            known_ids.add(event.id)

            if event.run_id not in self._events:
                self._events[event.run_id] = []
                self._graphs[event.run_id] = RunGraph(
                    run_id=event.run_id,
                    label=event.data.get("label", event.run_id),
                    app_id=event.data.get("app_id"),
                    status=NodeStatus.RUNNING,
                    started_at=event.timestamp,
                )
            self._events[event.run_id].append(event)
            _apply_event_to_graph(self._graphs[event.run_id], event)

        if self._loop and not self._loop.is_closed():
            for q in self._subscribers.get(event.run_id, []):
                self._loop.call_soon_threadsafe(q.put_nowait, event)

    def delete_run(self, run_id: str) -> None:
        with self._lock:
            self._events.pop(run_id, None)
            self._event_ids.pop(run_id, None)
            self._graphs.pop(run_id, None)
            self._tags.pop(run_id, None)
            self._control.pop(run_id, None)
            self._control_wake.pop(run_id, None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._event_ids.clear()
            self._graphs.clear()
            self._tags.clear()
            self._control.clear()
            self._control_wake.clear()

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def list_runs(self) -> list[RunSummary]:
        with self._lock:
            return sorted(
                [
                    RunSummary(
                        run_id=run_id,
                        label=g.label,
                        app_id=g.app_id,
                        status=g.status,
                        started_at=g.started_at,
                        ended_at=g.ended_at,
                        node_count=len(g.nodes),
                        event_count=len(self._events.get(run_id, [])),
                        total_cost_usd=_total_cost(g),
                        tags=list(self._tags.get(run_id, [])),
                        summary=summarize_run(g),
                    )
                    for run_id, g in self._graphs.items()
                ],
                key=lambda s: s.started_at,
                reverse=True,
            )

    def get_run(self, run_id: str) -> Optional[RunSummary]:
        with self._lock:
            g = self._graphs.get(run_id)
            if not g:
                return None
            return RunSummary(
                run_id=run_id,
                label=g.label,
                app_id=g.app_id,
                status=g.status,
                started_at=g.started_at,
                ended_at=g.ended_at,
                node_count=len(g.nodes),
                event_count=len(self._events.get(run_id, [])),
                total_cost_usd=_total_cost(g),
                tags=list(self._tags.get(run_id, [])),
                summary=summarize_run(g),
            )

    def get_graph(self, run_id: str) -> Optional[RunGraph]:
        with self._lock:
            g = self._graphs.get(run_id)
            return g.model_copy(deep=True) if g else None

    def get_events(self, run_id: str) -> list[VapEvent]:
        with self._lock:
            return list(self._events.get(run_id, []))

    # ------------------------------------------------------------------
    # Pub/sub
    # ------------------------------------------------------------------

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(run_id, [])
            try:
                subs.remove(q)
            except ValueError:
                pass


# ---------------------------------------------------------------------------
# Module-level default — replaced by vapviz.configure() or vapviz serve --db
# ---------------------------------------------------------------------------

default_store: RunStore = MemoryStore()
