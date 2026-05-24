from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from .events import RunGraph, RunSummary, VapEvent
from .store import RunStore, default_store


def create_app(store: RunStore | None = None) -> FastAPI:
    _store = store or default_store

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _store.set_loop(asyncio.get_running_loop())
        yield
        # Graceful shutdown: close SQLite connection if applicable
        if hasattr(_store, "close"):
            _store.close()  # type: ignore[attr-defined]

    app = FastAPI(title="VaP — Visualization Agentic Process", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Run list & summary
    # ------------------------------------------------------------------

    @app.get("/runs", response_model=list[RunSummary])
    async def list_runs():
        return _store.list_runs()

    @app.get("/runs/{run_id}", response_model=RunSummary)
    async def get_run(run_id: str):
        summary = _store.get_run(run_id)
        if not summary:
            raise HTTPException(status_code=404, detail="Run not found")
        return summary

    # ------------------------------------------------------------------
    # Graph snapshot
    # ------------------------------------------------------------------

    @app.get("/runs/{run_id}/graph", response_model=RunGraph)
    async def get_graph(run_id: str):
        graph = _store.get_graph(run_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Run not found")
        return graph

    # ------------------------------------------------------------------
    # SSE event stream
    # ------------------------------------------------------------------

    @app.get("/runs/{run_id}/events")
    async def stream_events(run_id: str):
        """SSE stream — replays history then pushes live events."""

        async def generator() -> AsyncGenerator[dict, None]:
            # Phase 1: replay history (handles late-connecting browsers)
            for event in _store.get_events(run_id):
                yield {"data": event.model_dump_json(), "event": event.type.value}

            # Phase 2: live events from asyncio.Queue
            q = _store.subscribe(run_id)
            try:
                while True:
                    try:
                        event: VapEvent = await asyncio.wait_for(q.get(), timeout=30)
                        yield {"data": event.model_dump_json(), "event": event.type.value}
                    except asyncio.TimeoutError:
                        yield {"data": "{}", "event": "ping"}
            finally:
                _store.unsubscribe(run_id, q)

        return EventSourceResponse(generator())

    # ------------------------------------------------------------------
    # Remote event ingest (out-of-process tracers)
    # ------------------------------------------------------------------

    @app.post("/runs/{run_id}/events", status_code=202)
    async def ingest_event(run_id: str, event: VapEvent):
        """Push an event from a remote/out-of-process tracer."""
        if event.run_id != run_id:
            raise HTTPException(status_code=400, detail="run_id mismatch")
        _store.add_event(event)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    @app.delete("/runs/{run_id}", status_code=204)
    async def delete_run(run_id: str):
        if not _store.get_run(run_id):
            raise HTTPException(status_code=404, detail="Run not found")
        _store.delete_run(run_id)

    @app.delete("/runs", status_code=204)
    async def clear_runs():
        _store.clear()

    return app


# Default ASGI app (in-memory store, used by run_dev.py and tests)
app = create_app()
