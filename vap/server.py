from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from pydantic import BaseModel

from .budgets import Budget, BudgetReport, check_budget
from .evals import EvalResult, run_checks
from .events import RunGraph, RunSummary, VapEvent
from .metrics import Metrics, compute_metrics
from .search import run_matches
from .store import RunStore, default_store


class TagUpdate(BaseModel):
    tags: list[str]


def create_app(store: RunStore | None = None, static_dir: str | None = None) -> FastAPI:
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

    # ------------------------------------------------------------------
    # Cross-run analytics
    # ------------------------------------------------------------------

    @app.get("/metrics", response_model=Metrics)
    async def metrics():
        """Aggregate statistics across every stored run."""
        graphs = [
            g
            for g in (_store.get_graph(s.run_id) for s in _store.list_runs())
            if g is not None
        ]
        return compute_metrics(graphs)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @app.get("/search", response_model=list[RunSummary])
    async def search(
        q: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        tool: str | None = None,
        tag: str | None = None,
    ):
        """Search runs by free-text query and/or filters (status, kind, tool, tag)."""
        results: list[RunSummary] = []
        for summary in _store.list_runs():
            if tag is not None and tag not in summary.tags:
                continue
            graph = _store.get_graph(summary.run_id)
            if graph is None:
                continue
            if run_matches(graph, query=q, status=status, kind=kind, tool=tool):
                results.append(summary)
        return results

    # NOTE: /runs/compare must be registered BEFORE /runs/{run_id} so that
    # FastAPI treats "compare" as a literal path segment, not a run_id.
    @app.get("/runs/compare")
    async def compare_runs(a: str, b: str):
        """Return two run graphs for client-side diff comparison."""
        graph_a = _store.get_graph(a)
        graph_b = _store.get_graph(b)
        if graph_a is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {a}")
        if graph_b is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {b}")
        return {"a": graph_a, "b": graph_b}

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

    @app.get("/runs/{run_id}/budget", response_model=BudgetReport)
    async def run_budget(
        run_id: str,
        max_cost_usd: float | None = None,
        max_duration_ms: float | None = None,
        max_total_tokens: int | None = None,
    ):
        """Check a run against a budget supplied as query parameters."""
        graph = _store.get_graph(run_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Run not found")
        budget = Budget(
            max_cost_usd=max_cost_usd,
            max_duration_ms=max_duration_ms,
            max_total_tokens=max_total_tokens,
        )
        return check_budget(graph, budget)

    @app.get("/runs/{run_id}/tags", response_model=list[str])
    async def get_tags(run_id: str):
        if not _store.get_run(run_id):
            raise HTTPException(status_code=404, detail="Run not found")
        return _store.get_tags(run_id)

    @app.put("/runs/{run_id}/tags", response_model=list[str])
    async def set_tags(run_id: str, body: TagUpdate):
        if not _store.get_run(run_id):
            raise HTTPException(status_code=404, detail="Run not found")
        return _store.set_tags(run_id, body.tags)

    @app.post("/runs/{run_id}/eval", response_model=EvalResult)
    async def eval_run_endpoint(run_id: str, checks: list[dict]):
        """Evaluate a run against a list of declarative check specs."""
        graph = _store.get_graph(run_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Run not found")
        try:
            return run_checks(graph, checks)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/runs/{run_id}/export")
    async def export_run(run_id: str):
        """Download the full run graph as a JSON file."""
        graph = _store.get_graph(run_id)
        if not graph:
            raise HTTPException(status_code=404, detail="Run not found")
        return Response(
            content=graph.model_dump_json(indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="vap-{run_id}.json"'},
        )

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

    # ------------------------------------------------------------------
    # Optional: serve the built React UI as static files
    # Must be mounted AFTER all API routes so the catch-all SPA fallback
    # does not shadow /runs/*, /docs, etc.
    # ------------------------------------------------------------------

    if static_dir is not None:
        from pathlib import Path
        from fastapi.staticfiles import StaticFiles

        dist = Path(static_dir)
        if not dist.is_dir():
            raise RuntimeError(
                f"static_dir '{static_dir}' does not exist or is not a directory. "
                "Run 'npm run build' inside the ui/ directory first."
            )
        # html=True enables SPA fallback: unknown paths → index.html
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="ui")

    return app


# Default ASGI app (in-memory store, used by run_dev.py and tests)
app = create_app()
