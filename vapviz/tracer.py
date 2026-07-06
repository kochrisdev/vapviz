from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, AsyncIterator, Generator, Iterator, Optional

from .events import EventType, NodeKind, VapEvent

if TYPE_CHECKING:
    from .store import RunStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> float:
    return time.time()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ContextVar tracks the active StepContext so nested calls auto-wire parent IDs.
# Python propagates ContextVar into asyncio.Task children automatically (PEP 567).
_current_step: ContextVar[Optional["StepContext"]] = ContextVar(
    "_current_step", default=None
)


# ---------------------------------------------------------------------------
# StepContext — one node in the run graph
# ---------------------------------------------------------------------------


class StepContext:
    """Represents one node in the run graph — a step, tool call, or LLM call."""

    def __init__(
        self,
        run_id: str,
        node_id: str,
        node_kind: NodeKind,
        label: str,
        parent_id: Optional[str],
        store: "RunStore",
    ) -> None:
        self.run_id = run_id
        self.node_id = node_id
        self.node_kind = node_kind
        self.label = label
        self.parent_id = parent_id
        self._store = store
        self._input: dict[str, Any] = {}
        self._output: dict[str, Any] = {}
        self._metadata: dict[str, Any] = {}

    def set_input(self, data: dict[str, Any]) -> None:
        self._input = data

    def set_output(self, data: dict[str, Any]) -> None:
        self._output = data

    def set_meta(self, **kwargs: Any) -> None:
        self._metadata.update(kwargs)

    def _emit(self, event_type: EventType, extra: dict[str, Any] | None = None) -> None:
        data: dict[str, Any] = {}
        data.update(self._metadata)
        if extra:
            data.update(extra)
        self._store.add_event(
            VapEvent(
                id=_uid(),
                run_id=self.run_id,
                timestamp=_now(),
                type=event_type,
                node_id=self.node_id,
                node_kind=self.node_kind,
                node_label=self.label,
                parent_id=self.parent_id,
                data=data,
            )
        )


# ---------------------------------------------------------------------------
# Shared step logic (used by both sync and async context managers)
# ---------------------------------------------------------------------------


def _make_step_ctx(run_id: str, label: str, kind: str, store: "RunStore") -> StepContext:
    node_kind = NodeKind(kind) if kind in NodeKind._value2member_map_ else NodeKind.STEP
    parent = _current_step.get()
    parent_id = parent.node_id if parent else None
    return StepContext(
        run_id=run_id,
        node_id=_uid(),
        node_kind=node_kind,
        label=label,
        parent_id=parent_id,
        store=store,
    )


def _start_event(node_kind: NodeKind) -> EventType:
    return {NodeKind.TOOL: EventType.TOOL_CALL, NodeKind.LLM: EventType.LLM_CALL}.get(
        node_kind, EventType.STEP_START
    )


def _end_event(node_kind: NodeKind) -> EventType:
    return {NodeKind.TOOL: EventType.TOOL_RESULT, NodeKind.LLM: EventType.LLM_RESPONSE}.get(
        node_kind, EventType.STEP_END
    )


# ---------------------------------------------------------------------------
# RunContext — top-level context for a single agent run
# ---------------------------------------------------------------------------


class RunContext:
    """Top-level context for a single agent run."""

    def __init__(
        self,
        label: str,
        store: "RunStore",
        run_id: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> None:
        self.run_id = run_id or _uid()
        self.label = label
        self.app_id = app_id
        self._store = store
        self._root_node_id = _uid()

    def _start(self) -> None:
        data: dict[str, Any] = {"label": self.label}
        if self.app_id:  # empty string counts as absent — the UI would group all "" apps together
            data["app_id"] = self.app_id
        self._store.add_event(
            VapEvent(
                id=_uid(),
                run_id=self.run_id,
                timestamp=_now(),
                type=EventType.AGENT_START,
                node_id=self._root_node_id,
                node_kind=NodeKind.AGENT,
                node_label=self.label,
                parent_id=None,
                data=data,
            )
        )
        self._root_ctx = StepContext(
            run_id=self.run_id,
            node_id=self._root_node_id,
            node_kind=NodeKind.AGENT,
            label=self.label,
            parent_id=None,
            store=self._store,
        )
        self._token = _current_step.set(self._root_ctx)

    def _end(self, error: Optional[Exception] = None) -> None:
        extra: dict[str, Any] = {}
        if error:
            extra["error"] = str(error)
            extra["error_type"] = type(error).__name__
        self._store.add_event(
            VapEvent(
                id=_uid(),
                run_id=self.run_id,
                timestamp=_now(),
                type=EventType.AGENT_END,
                node_id=self._root_node_id,
                node_kind=NodeKind.AGENT,
                node_label=self.label,
                parent_id=None,
                data=extra,
            )
        )
        # In CrewAI auto mode the run is opened on one bus thread and closed on
        # another, so this token belongs to a different context — reset() would
        # raise "Token created in a different Context". The listener tracks
        # parents via its own dicts and doesn't rely on this ContextVar, so a
        # plain clear is enough in that case.
        try:
            _current_step.reset(self._token)
        except ValueError:
            _current_step.set(None)

    # ------------------------------------------------------------------
    # Synchronous step context manager
    # ------------------------------------------------------------------

    @contextmanager
    def step(self, label: str, kind: str = "step") -> Iterator[StepContext]:
        """Open a synchronous child step within this run."""
        ctx = _make_step_ctx(self.run_id, label, kind, self._store)
        ctx._emit(_start_event(ctx.node_kind))
        token = _current_step.set(ctx)
        error: Optional[Exception] = None
        try:
            yield ctx
        except Exception as exc:
            error = exc
            ctx._emit(EventType.ERROR, {"error": str(exc), "error_type": type(exc).__name__})
            raise
        finally:
            _current_step.reset(token)
            if not error:
                ctx._emit(_end_event(ctx.node_kind), {"input": ctx._input, "output": ctx._output})

    # ------------------------------------------------------------------
    # Asynchronous step context manager
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def astep(self, label: str, kind: str = "step") -> AsyncIterator[StepContext]:
        """Open an asynchronous child step within this run.

        ContextVar propagates into asyncio.Task children automatically (PEP 567),
        so concurrent tasks each see their own correct parent without any extra work.
        """
        ctx = _make_step_ctx(self.run_id, label, kind, self._store)
        ctx._emit(_start_event(ctx.node_kind))
        token = _current_step.set(ctx)
        error: Optional[Exception] = None
        try:
            yield ctx
        except Exception as exc:
            error = exc
            ctx._emit(EventType.ERROR, {"error": str(exc), "error_type": type(exc).__name__})
            raise
        finally:
            _current_step.reset(token)
            if not error:
                ctx._emit(_end_event(ctx.node_kind), {"input": ctx._input, "output": ctx._output})


# ---------------------------------------------------------------------------
# Tracer — entry point
# ---------------------------------------------------------------------------


class Tracer:
    """Entry point for the vapviz tracing API.

    Uses ``vapviz.store.default_store`` at call time if no explicit store is passed,
    so ``vapviz.configure(db=...)`` takes effect even after import.
    """

    def __init__(self, store: "RunStore | None" = None) -> None:
        self._store_explicit = store

    @property
    def _store(self) -> "RunStore":
        if self._store_explicit is not None:
            return self._store_explicit
        import vapviz.store as _sm
        return _sm.default_store

    # ------------------------------------------------------------------
    # Synchronous trace
    # ------------------------------------------------------------------

    @contextmanager
    def trace(
        self, label: str, run_id: Optional[str] = None, app_id: Optional[str] = None
    ) -> Iterator[RunContext]:
        """Start a synchronous agent run trace.

        ``app_id`` is a stable identifier for the pipeline ("app") this run
        belongs to; runs sharing an ``app_id`` are grouped in the UI. Falls
        back to exact-label grouping when omitted.
        """
        run = RunContext(label=label, store=self._store, run_id=run_id, app_id=app_id)
        run._start()
        error: Optional[Exception] = None
        try:
            yield run
        except Exception as exc:
            error = exc
            raise
        finally:
            run._end(error=error)

    # ------------------------------------------------------------------
    # Asynchronous trace
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def atrace(
        self, label: str, run_id: Optional[str] = None, app_id: Optional[str] = None
    ) -> AsyncIterator[RunContext]:
        """Start an asynchronous agent run trace.

        ``app_id`` groups runs of the same pipeline, as in :meth:`trace`.

        Example::

            async with vapviz.atrace("My async agent") as run:
                async with run.astep("fetch", kind="tool") as step:
                    step.set_input({"url": "..."})
                    data = await fetch(url)
                    step.set_output({"bytes": len(data)})
        """
        run = RunContext(label=label, store=self._store, run_id=run_id, app_id=app_id)
        run._start()
        error: Optional[Exception] = None
        try:
            yield run
        except Exception as exc:
            error = exc
            raise
        finally:
            run._end(error=error)

    def get_current_step(self) -> Optional[StepContext]:
        return _current_step.get()


# ---------------------------------------------------------------------------
# Module-level default tracer (uses default_store dynamically)
# ---------------------------------------------------------------------------

_default_tracer = Tracer()

trace = _default_tracer.trace
atrace = _default_tracer.atrace
get_current_step = _default_tracer.get_current_step
