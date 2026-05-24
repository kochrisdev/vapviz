from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Optional

from ..events import (
    EventType,
    NodeStatus,
    RunGraph,
    RunSummary,
    VapEvent,
)
from ..store import RunStore, _apply_event_to_graph

_DDL = """
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    timestamp    REAL NOT NULL,
    type         TEXT NOT NULL,
    node_id      TEXT NOT NULL,
    node_kind    TEXT NOT NULL,
    node_label   TEXT NOT NULL,
    parent_id    TEXT,
    data_json    TEXT NOT NULL DEFAULT '{}',
    schema_ver   INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_events_run_id        ON events (run_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp     ON events (timestamp);
"""


class SqliteStore(RunStore):
    """
    Persistent store backed by SQLite.

    Events are written to disk on every add_event call (synchronous, fast).
    An in-memory graph cache is kept for low-latency reads and SSE pub/sub —
    identical to MemoryStore's behaviour after the initial DB load.

    Usage::

        store = SqliteStore("vap.db")
        app   = vap.create_app(store=store)
        tracer = vap.Tracer(store=store)

    Or via the CLI::

        vap serve --db vap.db
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads
        self._conn.execute("PRAGMA synchronous=NORMAL") # safe + fast
        self._conn.executescript(_DDL)
        self._conn.commit()

        # In-memory caches (rebuilt from DB on init)
        self._events: dict[str, list[VapEvent]] = {}
        self._graphs: dict[str, RunGraph] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._lock = Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self._load_from_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_event(self, row: tuple) -> VapEvent:
        id_, run_id, timestamp, type_, node_id, node_kind, node_label, parent_id, data_json, schema_ver = row
        return VapEvent(
            id=id_,
            run_id=run_id,
            timestamp=timestamp,
            type=type_,
            node_id=node_id,
            node_kind=node_kind,
            node_label=node_label,
            parent_id=parent_id,
            data=json.loads(data_json),
            schema_version=schema_ver,
        )

    def _load_from_db(self) -> None:
        """Replay all persisted events into the in-memory caches on startup."""
        cur = self._conn.execute(
            "SELECT id, run_id, timestamp, type, node_id, node_kind, node_label, "
            "parent_id, data_json, schema_ver FROM events ORDER BY timestamp ASC"
        )
        for row in cur.fetchall():
            event = self._row_to_event(row)
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

    def _write_event(self, event: VapEvent) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO events "
            "(id, run_id, timestamp, type, node_id, node_kind, node_label, parent_id, data_json, schema_ver) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.run_id,
                event.timestamp,
                event.type.value,
                event.node_id,
                event.node_kind.value,
                event.node_label,
                event.parent_id,
                json.dumps(event.data),
                event.schema_version,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # RunStore interface
    # ------------------------------------------------------------------

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def add_event(self, event: VapEvent) -> None:
        with self._lock:
            # Persist first
            self._write_event(event)

            # Update in-memory caches
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

        # Notify SSE subscribers
        if self._loop and not self._loop.is_closed():
            for q in self._subscribers.get(event.run_id, []):
                self._loop.call_soon_threadsafe(q.put_nowait, event)

    def get_events(self, run_id: str) -> list[VapEvent]:
        with self._lock:
            return list(self._events.get(run_id, []))

    def get_graph(self, run_id: str) -> Optional[RunGraph]:
        with self._lock:
            g = self._graphs.get(run_id)
            return g.model_copy(deep=True) if g else None

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
            )

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
                    )
                    for run_id, g in self._graphs.items()
                ],
                key=lambda s: s.started_at,
                reverse=True,
            )

    def delete_run(self, run_id: str) -> None:
        with self._lock:
            self._events.pop(run_id, None)
            self._graphs.pop(run_id, None)
            self._conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._graphs.clear()
            self._conn.execute("DELETE FROM events")
            self._conn.commit()

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

    def close(self) -> None:
        """Close the SQLite connection. Call on server shutdown."""
        self._conn.close()
