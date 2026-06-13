from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from threading import Lock
from typing import Optional

from .events import (
    EventType,
    GraphEdge,
    GraphNode,
    NodeStatus,
    RunGraph,
    RunSummary,
    VapEvent,
)


# ---------------------------------------------------------------------------
# Shared helpers (pure functions, used by all store backends)
# ---------------------------------------------------------------------------

def _total_cost(graph: RunGraph) -> Optional[float]:
    """Sum cost_usd from all LLM nodes in the graph; return None if none have cost."""
    total = 0.0
    found = False
    for node in graph.nodes:
        cost = node.data.get("output", {}).get("cost_usd") if isinstance(node.data.get("output"), dict) else None
        if cost is not None:
            total += cost
            found = True
    return round(total, 8) if found else None


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
            node.status = NodeStatus.ERROR if event.data.get("error") else NodeStatus.SUCCESS
            node.ended_at = event.timestamp
            node.data.update(event.data)
        if event.type == EventType.AGENT_END:
            graph.status = NodeStatus.ERROR if event.data.get("error") else NodeStatus.SUCCESS
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
    """Abstract interface for a VaP event store."""

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


# ---------------------------------------------------------------------------
# In-memory implementation (default)
# ---------------------------------------------------------------------------

class MemoryStore(RunStore):
    """Thread-safe in-memory store with asyncio pub/sub for SSE streaming."""

    def __init__(self) -> None:
        self._events: dict[str, list[VapEvent]] = {}
        self._event_ids: dict[str, set[str]] = {}   # run_id -> set of event IDs for dedup
        self._graphs: dict[str, RunGraph] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
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

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._event_ids.clear()
            self._graphs.clear()

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
                        status=g.status,
                        started_at=g.started_at,
                        ended_at=g.ended_at,
                        node_count=len(g.nodes),
                        event_count=len(self._events.get(run_id, [])),
                        total_cost_usd=_total_cost(g),
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
                status=g.status,
                started_at=g.started_at,
                ended_at=g.ended_at,
                node_count=len(g.nodes),
                event_count=len(self._events.get(run_id, [])),
                total_cost_usd=_total_cost(g),
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
# Module-level default — replaced by vap.configure() or vap serve --db
# ---------------------------------------------------------------------------

default_store: RunStore = MemoryStore()
