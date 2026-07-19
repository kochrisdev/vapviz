from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from pydantic import BaseModel

from .budgets import Budget, BudgetReport, check_budget
from .control import ACTION_TO_DESIRED
from .evals import EvalResult, run_checks
from .events import EventType, NodeKind, NodeStatus, RunGraph, RunSummary, VapEvent
from .metrics import Metrics, compute_metrics
from .search import run_matches
from . import store as _sm
from .store import RunStore

# Terminal run statuses — control is a no-op once a run has ended.
_TERMINAL = {NodeStatus.SUCCESS, NodeStatus.ERROR, NodeStatus.STOPPED}


class TagUpdate(BaseModel):
    tags: list[str]


class ControlCommand(BaseModel):
    action: str  # "pause" | "resume" | "stop"


class RunControlOut(BaseModel):
    desired: str
    acked: str
    updated_at: float
    ended: bool = False  # true when the run already terminated (control was a no-op)


def create_app(store: RunStore | None = None, static_dir: str | None = None) -> FastAPI:
    # Resolve the default store at CALL time, not import time (M3): a frozen
    # `from .store import default_store` would ignore an earlier
    # `vapviz.configure(db=...)` and silently serve an empty MemoryStore.
    _store = store or _sm.default_store

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _store.set_loop(asyncio.get_running_loop())
        yield
        # Graceful shutdown: close SQLite connection if applicable
        if hasattr(_store, "close"):
            _store.close()  # type: ignore[attr-defined]

    app = FastAPI(title="vapviz — Visualization Agentic Process", lifespan=lifespan)

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
            headers={"Content-Disposition": f'attachment; filename="vapviz-{run_id}.json"'},
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
    # Live run control (Pause / Resume / Stop) — the return lane.
    # In-process agents obey it at each step checkpoint (see tracer.py). The
    # live latch is a side channel (NOT the event log); each action also emits
    # an inert `control` audit event so it shows in the timeline. See
    # docs/notes/DESIGN-agent-control.md.
    # ------------------------------------------------------------------

    @app.get("/runs/{run_id}/control", response_model=RunControlOut)
    async def read_control(run_id: str):
        """Current control latch — the UI polls this to render pausing…/paused."""
        summary = _store.get_run(run_id)
        if not summary:
            raise HTTPException(status_code=404, detail="Run not found")
        c = _store.get_control(run_id)
        return RunControlOut(
            desired=c.desired, acked=c.acked, updated_at=c.updated_at,
            ended=summary.status in _TERMINAL,
        )

    @app.post("/runs/{run_id}/control", response_model=RunControlOut)
    async def send_control(run_id: str, cmd: ControlCommand):
        """Pause / resume / stop a live in-process run."""
        summary = _store.get_run(run_id)
        if not summary:
            raise HTTPException(status_code=404, detail="Run not found")
        desired = ACTION_TO_DESIRED.get(cmd.action)
        if desired is None:
            raise HTTPException(status_code=422, detail=f"invalid action: {cmd.action!r}")

        # No-op on an already-ended run — nothing live to control.
        if summary.status in _TERMINAL:
            c = _store.get_control(run_id)
            return RunControlOut(desired=c.desired, acked=c.acked, updated_at=c.updated_at, ended=True)

        c = _store.set_desired(run_id, desired)

        # Inert audit marker for the Logs/Story timeline (ignored by the reducers).
        graph = _store.get_graph(run_id)
        root_id = graph.nodes[0].id if graph and graph.nodes else run_id
        _store.add_event(
            VapEvent(
                id=uuid.uuid4().hex[:12],
                run_id=run_id,
                timestamp=time.time(),
                type=EventType.CONTROL,
                node_id=root_id,
                node_kind=NodeKind.AGENT,
                node_label=summary.label,
                parent_id=None,
                data={"action": cmd.action},
            )
        )
        return RunControlOut(desired=c.desired, acked=c.acked, updated_at=c.updated_at, ended=False)

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
    #
    # Resolution order:
    #   1. an explicit static_dir argument
    #   2. the UI bundled into the installed package (vapviz/_static) — present in
    #      the published wheel, so `pip install vapviz && vapviz serve` just works
    # ------------------------------------------------------------------

    from pathlib import Path
    from fastapi.staticfiles import StaticFiles

    if static_dir is not None:
        dist = Path(static_dir)
        if not dist.is_dir():
            raise RuntimeError(
                f"static_dir '{static_dir}' does not exist or is not a directory. "
                "Run 'npm run build' inside the ui/ directory first."
            )
    else:
        bundled = Path(__file__).parent / "_static"
        dist = bundled if (bundled / "index.html").is_file() else None

    if dist is not None:
        # html=True enables SPA fallback: unknown paths → index.html
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="ui")

    return app


# Default ASGI app (in-memory store, used by run_dev.py and tests).
# Built at import, so it snapshots default_store NOW — configure(db=...) after
# this import does not retarget it; call create_app() yourself in that case.
app = create_app()
