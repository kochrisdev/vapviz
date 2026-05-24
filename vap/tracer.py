from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Generator, Optional

from .events import EventType, NodeKind, VapEvent
from .store import RunStore, default_store


def _now() -> float:
    return time.time()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# Context var tracks the currently active StepContext so nested calls
# can find their parent automatically.
_current_step: ContextVar[Optional["StepContext"]] = ContextVar(
    "_current_step", default=None
)


class StepContext:
    """Represents one node in the run graph — a step, tool call, or LLM call."""

    def __init__(
        self,
        run_id: str,
        node_id: str,
        node_kind: NodeKind,
        label: str,
        parent_id: Optional[str],
        store: RunStore,
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


class RunContext:
    """Top-level context for a single agent run."""

    def __init__(self, label: str, store: RunStore, run_id: Optional[str] = None) -> None:
        self.run_id = run_id or _uid()
        self.label = label
        self._store = store
        self._root_node_id = _uid()

    def _start(self) -> None:
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
                data={"label": self.label},
            )
        )
        # The root agent node becomes the initial "current step"
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
        _current_step.reset(self._token)

    @contextmanager
    def step(
        self,
        label: str,
        kind: str = "step",
    ) -> Generator[StepContext, None, None]:
        """Open a child step within this run."""
        node_kind = NodeKind(kind) if kind in NodeKind._value2member_map_ else NodeKind.STEP
        parent = _current_step.get()
        parent_id = parent.node_id if parent else self._root_node_id

        ctx = StepContext(
            run_id=self.run_id,
            node_id=_uid(),
            node_kind=node_kind,
            label=label,
            parent_id=parent_id,
            store=self._store,
        )

        start_event = {
            NodeKind.TOOL: EventType.TOOL_CALL,
            NodeKind.LLM: EventType.LLM_CALL,
        }.get(node_kind, EventType.STEP_START)

        ctx._emit(start_event)
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
                end_event = {
                    NodeKind.TOOL: EventType.TOOL_RESULT,
                    NodeKind.LLM: EventType.LLM_RESPONSE,
                }.get(node_kind, EventType.STEP_END)
                ctx._emit(end_event, {"input": ctx._input, "output": ctx._output})


class Tracer:
    """Entry point for the VaP tracing API."""

    def __init__(self, store: RunStore | None = None) -> None:
        self._store = store or default_store

    @contextmanager
    def trace(
        self,
        label: str,
        run_id: Optional[str] = None,
    ) -> Generator[RunContext, None, None]:
        run = RunContext(label=label, store=self._store, run_id=run_id)
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


# Module-level default tracer
_default_tracer = Tracer()

trace = _default_tracer.trace
get_current_step = _default_tracer.get_current_step
