from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, AsyncIterator, Generator, Iterator, Optional

from .control import CONTROL_POLL, PAUSED, RUNNING, STOPPED, VapStopped
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
# Cooperative control checkpoint (Pause / Resume / Stop)
# ---------------------------------------------------------------------------
# Called at the top of every step/astep — the "turnstiles" the agent already
# passes through. Reads the run's control latch from the store and obeys it:
# park while paused, raise VapStopped while stopped. In-process only for now
# (the tracer reads the store's in-memory latch directly). A polite halt at the
# next checkpoint, never a force-kill. See docs/notes/DESIGN-agent-control.md.


def _check_control(run_id: str, store: "RunStore") -> None:
    """Sync checkpoint: parks the calling *thread* while paused (safe — the
    agent runs on its own thread; the server keeps serving), raises VapStopped
    while stopped, and acks the run's actual state so the UI can show the lag."""
    while True:
        c = store.get_control(run_id)
        if c.desired == STOPPED:
            store.set_ack(run_id, STOPPED)
            raise VapStopped(run_id)
        if c.desired != PAUSED:
            store.set_ack(run_id, RUNNING)
            return
        store.set_ack(run_id, PAUSED)
        ev = store._control_wake_for(run_id)  # woken immediately by set_desired…
        ev.wait(timeout=CONTROL_POLL)         # …else re-poll (bounds resume latency)
        ev.clear()


async def _acheck_control(run_id: str, store: "RunStore") -> None:
    """Async checkpoint: ``await``s instead of blocking, so a paused async agent
    yields to the shared event loop (letting the Resume request be served)
    rather than freezing it."""
    while True:
        c = store.get_control(run_id)
        if c.desired == STOPPED:
            store.set_ack(run_id, STOPPED)
            raise VapStopped(run_id)
        if c.desired != PAUSED:
            store.set_ack(run_id, RUNNING)
            return
        store.set_ack(run_id, PAUSED)
        await asyncio.sleep(CONTROL_POLL)


# ---------------------------------------------------------------------------
# Public control API for agent authors (Layer 2)
# ---------------------------------------------------------------------------
# Calls an author sprinkles into agent code to cooperate with the UI's control
# channel beyond the automatic per-step checkpoint:
#   * checkpoint()/acheckpoint() — an extra pause/stop checkpoint for a long
#     loop with no natural step boundary.
#   * take_input()/atake_input()  — receive a message the UI injected.
# All require an active trace; called outside one they raise RuntimeError (a
# deliberate author call, unlike the SDK monkey-patches which no-op untraced).


def _require_ctx(fn_name: str) -> StepContext:
    ctx = _current_step.get()
    if ctx is None:
        raise RuntimeError(
            f"vapviz.{fn_name}() called outside an active trace "
            "(no run is in progress on this thread/task)"
        )
    return ctx


def checkpoint() -> None:
    """Manual control checkpoint for a long loop with no natural step boundary.

    Obeys Pause/Stop exactly like the automatic per-step checkpoint: parks while
    the run is paused, raises :class:`VapStopped` while it is stopped::

        for row in huge_dataset:      # no per-row step → add a checkpoint
            vapviz.checkpoint()
            process(row)
    """
    ctx = _require_ctx("checkpoint")
    _check_control(ctx.run_id, ctx._store)


async def acheckpoint() -> None:
    """Async variant of :func:`checkpoint` — ``await`` it inside an async loop so
    a paused agent yields to the event loop instead of blocking it."""
    ctx = _require_ctx("acheckpoint")
    await _acheck_control(ctx.run_id, ctx._store)


def take_input(timeout: Optional[float] = None) -> Optional[str]:
    """Receive a message the UI injected into this run (Layer 2 mailbox).

    By default blocks at this checkpoint until a message arrives — the "agent
    asks, then waits for the human" pattern — and returns the message. While
    waiting, the UI shows "agent is waiting for your input". Stop still
    interrupts a waiting agent (raises :class:`VapStopped`).

    ``timeout``:
      * ``None`` (default) — wait indefinitely for a message.
      * ``0`` — non-blocking peek: return the pending message, or ``None`` now.
      * ``> 0`` — wait up to that many seconds, then return ``None`` on timeout.

    Requires an active trace; raises ``RuntimeError`` otherwise. (Pause is not
    separately honored here — waiting for input already is a wait; a pause takes
    effect at the next step checkpoint after the message is received.)
    """
    ctx = _require_ctx("take_input")
    run_id, store = ctx.run_id, ctx._store
    deadline = None if timeout is None else time.monotonic() + timeout
    store.set_waiting_for_input(run_id, True)
    try:
        while True:
            # Stop takes priority — a waiting agent must still be stoppable.
            if store.get_control(run_id).desired == STOPPED:
                store.set_ack(run_id, STOPPED)
                raise VapStopped(run_id)
            msg = store.take_input_if_ready(run_id)
            if msg is not None:
                return msg
            if timeout == 0:
                return None  # non-blocking peek
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None  # timed out
                wait = min(CONTROL_POLL, remaining)
            else:
                wait = CONTROL_POLL
            ev = store._control_wake_for(run_id)  # woken immediately by set_input…
            ev.wait(timeout=wait)                 # …else re-poll (also catches Stop)
            ev.clear()
    finally:
        store.set_waiting_for_input(run_id, False)


async def atake_input(timeout: Optional[float] = None) -> Optional[str]:
    """Async variant of :func:`take_input` — ``await``s instead of blocking, so a
    waiting async agent yields the shared event loop (Stop and the injected
    message are still served)."""
    ctx = _require_ctx("atake_input")
    run_id, store = ctx.run_id, ctx._store
    deadline = None if timeout is None else time.monotonic() + timeout
    store.set_waiting_for_input(run_id, True)
    try:
        while True:
            if store.get_control(run_id).desired == STOPPED:
                store.set_ack(run_id, STOPPED)
                raise VapStopped(run_id)
            msg = store.take_input_if_ready(run_id)
            if msg is not None:
                return msg
            if timeout == 0:
                return None
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                await asyncio.sleep(min(CONTROL_POLL, remaining))
            else:
                await asyncio.sleep(CONTROL_POLL)
    finally:
        store.set_waiting_for_input(run_id, False)


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

    def _end(self, error: Optional[Exception] = None, stopped: bool = False) -> None:
        extra: dict[str, Any] = {}
        if stopped:
            # First-class 'stopped' status (no 'error' key → not a crash).
            extra["stopped"] = True
            extra["error_type"] = "VapStopped"
        elif error:
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
        _check_control(self.run_id, self._store)  # obey pause/stop between steps
        ctx = _make_step_ctx(self.run_id, label, kind, self._store)
        ctx._emit(_start_event(ctx.node_kind))
        token = _current_step.set(ctx)
        error: Optional[Exception] = None
        stopped = False
        try:
            yield ctx
        except VapStopped:
            # A nested checkpoint stopped the run; close this open node as
            # 'stopped' (not an error) and keep propagating so the run unwinds.
            stopped = True
            raise
        except Exception as exc:
            error = exc
            ctx._emit(EventType.ERROR, {"error": str(exc), "error_type": type(exc).__name__})
            raise
        finally:
            _current_step.reset(token)
            if stopped:
                ctx._emit(_end_event(ctx.node_kind),
                          {"input": ctx._input, "output": ctx._output, "stopped": True})
            elif not error:
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
        await _acheck_control(self.run_id, self._store)  # obey pause/stop between steps
        ctx = _make_step_ctx(self.run_id, label, kind, self._store)
        ctx._emit(_start_event(ctx.node_kind))
        token = _current_step.set(ctx)
        error: Optional[Exception] = None
        stopped = False
        try:
            yield ctx
        except VapStopped:
            stopped = True
            raise
        except Exception as exc:
            error = exc
            ctx._emit(EventType.ERROR, {"error": str(exc), "error_type": type(exc).__name__})
            raise
        finally:
            _current_step.reset(token)
            if stopped:
                ctx._emit(_end_event(ctx.node_kind),
                          {"input": ctx._input, "output": ctx._output, "stopped": True})
            elif not error:
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
        stopped = False
        try:
            yield run
        except VapStopped:
            # User stopped the run; end it cleanly as 'stopped' and re-raise so
            # the agent's own code unwinds and actually halts.
            stopped = True
            raise
        except Exception as exc:
            error = exc
            raise
        finally:
            run._end(error=error, stopped=stopped)

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
        stopped = False
        try:
            yield run
        except VapStopped:
            stopped = True
            raise
        except Exception as exc:
            error = exc
            raise
        finally:
            run._end(error=error, stopped=stopped)

    def get_current_step(self) -> Optional[StepContext]:
        return _current_step.get()


# ---------------------------------------------------------------------------
# Module-level default tracer (uses default_store dynamically)
# ---------------------------------------------------------------------------

_default_tracer = Tracer()

trace = _default_tracer.trace
atrace = _default_tracer.atrace
get_current_step = _default_tracer.get_current_step
