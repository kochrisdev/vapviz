from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from .events import RunGraph, RunSummary, VapEvent
from .store import RunStore, default_store


def create_app(store: RunStore | None = None) -> FastAPI:
    _store = store or default_store

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _store.set_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(title="VaP — Visualization Agentic Process", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/runs", response_model=list[RunSummary])
    async def list_runs():
        return _store.list_runs()

    @app.get("/runs/{run_id}/graph", response_model=RunGraph)
    async def get_graph(run_id: str):
        graph = _store.get_graph(run_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Run not found")
        return graph

    @app.get("/runs/{run_id}/events")
    async def stream_events(run_id: str):
        """SSE stream — replays past events then pushes new ones live."""

        async def generator() -> AsyncGenerator[dict, None]:
            past = _store.get_events(run_id)
            for event in past:
                yield {"data": event.model_dump_json(), "event": event.type.value}

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

    @app.post("/runs/{run_id}/events", status_code=202)
    async def ingest_event(run_id: str, event: VapEvent):
        """Remote ingest — allows out-of-process tracers to push events."""
        if event.run_id != run_id:
            raise HTTPException(status_code=400, detail="run_id mismatch")
        _store.add_event(event)
        return {"ok": True}

    @app.delete("/runs", status_code=204)
    async def clear_runs():
        _store.clear()

    return app


# Default ASGI app
app = create_app()
