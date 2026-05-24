from __future__ import annotations

import asyncio
from threading import Lock
from typing import Optional

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


class RunStore:
    """Thread-safe in-memory store with asyncio pub/sub for SSE streaming."""

    def __init__(self) -> None:
        self._events: dict[str, list[VapEvent]] = {}
        self._graphs: dict[str, RunGraph] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._lock = Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ------------------------------------------------------------------
    # Write path (called from sync tracer thread)
    # ------------------------------------------------------------------

    def add_event(self, event: VapEvent) -> None:
        with self._lock:
            if event.run_id not in self._events:
                self._events[event.run_id] = []
                self._graphs[event.run_id] = RunGraph(
                    run_id=event.run_id,
                    label=event.data.get("label", event.run_id),
                    status=NodeStatus.RUNNING,
                    started_at=event.timestamp,
                )

            self._events[event.run_id].append(event)
            self._apply_event_to_graph(event)

        # Notify SSE subscribers outside the lock to avoid deadlock
        if self._loop and not self._loop.is_closed():
            subs = self._subscribers.get(event.run_id, [])
            for q in subs:
                self._loop.call_soon_threadsafe(q.put_nowait, event)

    def _apply_event_to_graph(self, event: VapEvent) -> None:
        graph = self._graphs[event.run_id]
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
                existing_ids = {e.id for e in graph.edges}
                if edge_id not in existing_ids:
                    graph.edges.append(
                        GraphEdge(
                            id=edge_id,
                            source=event.parent_id,
                            target=event.node_id,
                        )
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

    # ------------------------------------------------------------------
    # Read path (called from async FastAPI handlers)
    # ------------------------------------------------------------------

    def list_runs(self) -> list[RunSummary]:
        with self._lock:
            summaries = []
            for run_id, graph in self._graphs.items():
                summaries.append(
                    RunSummary(
                        run_id=run_id,
                        label=graph.label,
                        status=graph.status,
                        started_at=graph.started_at,
                        ended_at=graph.ended_at,
                        node_count=len(graph.nodes),
                        event_count=len(self._events.get(run_id, [])),
                    )
                )
            return sorted(summaries, key=lambda s: s.started_at, reverse=True)

    def get_graph(self, run_id: str) -> Optional[RunGraph]:
        with self._lock:
            g = self._graphs.get(run_id)
            return g.model_copy(deep=True) if g else None

    def get_events(self, run_id: str) -> list[VapEvent]:
        with self._lock:
            return list(self._events.get(run_id, []))

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._graphs.clear()

    # ------------------------------------------------------------------
    # Pub/sub (async SSE)
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


# Global singleton — shared between tracer and server when running in-process
default_store = RunStore()
