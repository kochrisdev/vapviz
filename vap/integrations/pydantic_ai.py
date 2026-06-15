"""
VaP tracing integration for Pydantic AI.

Wraps ``Agent.run`` / ``Agent.run_sync`` so that every Pydantic AI agent run is
reconstructed as a VaP node graph — the agent, each model request (with token
usage and USD cost), and each tool call (with its arguments and result) — with
no changes to your agent code.

Two usage modes
---------------

**Manual mode** — attach the agent runs to an existing ``vap.trace()`` so they
appear as a sub-section of a larger pipeline::

    import vap
    from vap.integrations.pydantic_ai import VapPydanticAI

    with vap.trace("Support pipeline") as run:
        VapPydanticAI(run)            # patch once, inside the trace
        result = agent.run_sync("How do I reset my password?")

**Auto mode** — create a fresh VaP run for every ``agent.run()`` call::

    import vap
    from vap.integrations.pydantic_ai import VapPydanticAI

    vap.configure(db="vap.db")
    VapPydanticAI()                   # patch once at startup
    result = agent.run_sync("...")    # each call becomes its own VaP run

Call ``.detach()`` to restore the original ``Agent`` methods.

Requirements
------------
    pip install "vap[pydantic-ai]"

Notes
-----
The graph is reconstructed from ``result.all_messages()`` after the run
completes, so node timings come from Pydantic AI's message timestamps. Streaming
methods (``run_stream`` / ``run_stream_events``) are not traced yet.
"""
from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any, Optional

from ..cost import calculate_cost
from ..events import EventType, NodeKind, VapEvent
from ..tracer import RunContext, _uid

# ---------------------------------------------------------------------------
# Optional Pydantic AI import guard
# ---------------------------------------------------------------------------

try:
    from pydantic_ai import Agent
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
    )

    _PYDANTIC_AI_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the dep
    _PYDANTIC_AI_AVAILABLE = False


# Guards against double-recording when run_sync() delegates to run() internally.
# A ContextVar propagates correctly into the asyncio task that run_sync spawns.
_recording: ContextVar[bool] = ContextVar("_vap_pai_recording", default=False)

_PATCH_FLAG = "_vap_pydantic_ai_original"


# ---------------------------------------------------------------------------
# VapPydanticAI
# ---------------------------------------------------------------------------


class VapPydanticAI:
    """
    VaP tracing for Pydantic AI agents.

    Parameters
    ----------
    run:
        Optional ``RunContext`` from ``vap.trace()``. When provided (manual
        mode), each agent run is attached as an ``agent/<name>`` step under that
        run. When omitted (auto mode), every ``agent.run()`` call creates its
        own VaP run in ``vap.store.default_store``.
    patch:
        Patch ``Agent`` immediately on construction (default ``True``). Set
        ``False`` to wire it up later with :meth:`patch`.
    """

    def __init__(self, run: Optional[RunContext] = None, *, patch: bool = True) -> None:
        if not _PYDANTIC_AI_AVAILABLE:
            raise ImportError(
                "pydantic-ai is required for VapPydanticAI. "
                'Install it with: pip install "vap[pydantic-ai]"'
            )
        self._provided_run = run
        self._patched: list[tuple[type, str, Any]] = []
        if patch:
            self.patch()

    # ------------------------------------------------------------------
    # Patch / detach
    # ------------------------------------------------------------------

    def patch(self) -> None:
        """Wrap ``Agent.run`` and ``Agent.run_sync``."""
        self._wrap("run_sync", is_async=False)
        self._wrap("run", is_async=True)

    def detach(self) -> None:
        """Restore the original ``Agent`` methods."""
        for cls, name, original in self._patched:
            setattr(cls, name, original)
        self._patched.clear()

    def _wrap(self, name: str, *, is_async: bool) -> None:
        current = getattr(Agent, name)
        # If already wrapped (by us or a previous instance), recover the pristine
        # original so we never stack wrappers and double-record.
        original = getattr(current, _PATCH_FLAG, current)
        recorder = self

        if is_async:
            async def wrapper(agent_self, *args, **kwargs):  # type: ignore[no-untyped-def]
                if _recording.get():
                    return await original(agent_self, *args, **kwargs)
                token = _recording.set(True)
                start = time.time()
                result = None
                error: Optional[Exception] = None
                try:
                    result = await original(agent_self, *args, **kwargs)
                    return result
                except Exception as exc:  # noqa: BLE001 - re-raised below
                    error = exc
                    raise
                finally:
                    recorder._safe_record(agent_self, result, args, start, time.time(), error)
                    _recording.reset(token)
        else:
            def wrapper(agent_self, *args, **kwargs):  # type: ignore[no-untyped-def]
                if _recording.get():
                    return original(agent_self, *args, **kwargs)
                token = _recording.set(True)
                start = time.time()
                result = None
                error = None
                try:
                    result = original(agent_self, *args, **kwargs)
                    return result
                except Exception as exc:  # noqa: BLE001 - re-raised below
                    error = exc
                    raise
                finally:
                    recorder._safe_record(agent_self, result, args, start, time.time(), error)
                    _recording.reset(token)

        setattr(wrapper, _PATCH_FLAG, original)
        setattr(Agent, name, wrapper)
        self._patched.append((Agent, name, original))

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _safe_record(self, agent, result, args, start_ts, end_ts, error) -> None:
        """Never let a tracing failure break the user's agent run."""
        try:
            self._record(agent, result, args, start_ts, end_ts, error)
        except Exception:  # noqa: BLE001 - tracing must be best-effort
            pass

    def _record(self, agent, result, args, start_ts, end_ts, error) -> None:
        if self._provided_run is not None:
            store = self._provided_run._store
            run_id = self._provided_run.run_id
            root_parent: Optional[str] = self._provided_run._root_node_id
            new_run = False
        else:
            import vap.store as _sm

            store = _sm.default_store
            run_id = _uid()
            root_parent = None
            new_run = True

        agent_name = _safe_str(getattr(agent, "name", None)) or "agent"
        user_prompt = args[0] if args and isinstance(args[0], str) else None

        agent_node_id = _uid()
        if new_run:
            agent_kind = NodeKind.AGENT
            agent_label = agent_name
            agent_parent = None
            start_data: dict[str, Any] = {"label": agent_name}
        else:
            agent_kind = NodeKind.STEP
            agent_label = f"agent/{agent_name}"
            agent_parent = root_parent
            start_data = {}
        if user_prompt:
            start_data["input"] = {"prompt": _truncate(user_prompt)}

        _emit(
            store, run_id,
            EventType.AGENT_START if new_run else EventType.STEP_START,
            agent_node_id, agent_kind, agent_label, agent_parent, start_ts, start_data,
        )

        total_in = total_out = 0
        total_cost = 0.0
        has_cost = False

        if result is not None:
            tool_calls: dict[str, dict[str, Any]] = {}
            for msg in _all_messages(result):
                if isinstance(msg, ModelResponse):
                    model_name = _safe_str(getattr(msg, "model_name", None)) or "model"
                    ts = _epoch(getattr(msg, "timestamp", None), end_ts)
                    usage = getattr(msg, "usage", None)
                    in_tok = int(getattr(usage, "input_tokens", 0) or 0)
                    out_tok = int(getattr(usage, "output_tokens", 0) or 0)

                    text = " ".join(
                        p.content
                        for p in msg.parts
                        if isinstance(p, TextPart) and getattr(p, "content", None)
                    ).strip()

                    out_data: dict[str, Any] = {}
                    if text:
                        out_data["text"] = _truncate(text, 500)
                    if in_tok or out_tok:
                        out_data["usage"] = {"input_tokens": in_tok, "output_tokens": out_tok}
                        total_in += in_tok
                        total_out += out_tok
                        cost = calculate_cost(model_name, in_tok, out_tok)
                        if cost is not None:
                            out_data["cost_usd"] = round(cost, 8)
                            total_cost += cost
                            has_cost = True

                    llm_id = _uid()
                    llm_label = f"llm/{model_name}"
                    _emit(store, run_id, EventType.LLM_CALL, llm_id, NodeKind.LLM,
                          llm_label, agent_node_id, ts, {"input": {"model": model_name}})
                    _emit(store, run_id, EventType.LLM_RESPONSE, llm_id, NodeKind.LLM,
                          llm_label, agent_node_id, ts,
                          {"input": {"model": model_name}, "output": out_data})

                    for p in msg.parts:
                        if isinstance(p, ToolCallPart):
                            tool_calls[p.tool_call_id] = {
                                "name": getattr(p, "tool_name", None),
                                "args": getattr(p, "args", None),
                                "parent": llm_id,
                                "start": ts,
                            }

                elif isinstance(msg, ModelRequest):
                    for p in msg.parts:
                        if isinstance(p, ToolReturnPart):
                            info = tool_calls.get(getattr(p, "tool_call_id", ""), {})
                            parent = info.get("parent", agent_node_id)
                            call_ts = info.get("start", end_ts)
                            ret_ts = _epoch(getattr(p, "timestamp", None), call_ts)
                            tool_name = info.get("name") or _safe_str(getattr(p, "tool_name", None)) or "tool"
                            tool_in = _tool_args(info.get("args"))
                            tool_id = _uid()
                            _emit(store, run_id, EventType.TOOL_CALL, tool_id, NodeKind.TOOL,
                                  tool_name, parent, call_ts, {"input": tool_in})
                            _emit(store, run_id, EventType.TOOL_RESULT, tool_id, NodeKind.TOOL,
                                  tool_name, parent, ret_ts,
                                  {"input": tool_in,
                                   "output": {"result": _truncate(_safe_str(getattr(p, "content", "")), 500)}})

        # ── close the agent node ───────────────────────────────────────
        if error is not None:
            err_data = {"error": _safe_str(error), "error_type": type(error).__name__}
            if new_run:
                _emit(store, run_id, EventType.AGENT_END, agent_node_id, agent_kind,
                      agent_label, None, end_ts, err_data)
            else:
                _emit(store, run_id, EventType.ERROR, agent_node_id, agent_kind,
                      agent_label, agent_parent, end_ts, err_data)
            return

        agent_out: dict[str, Any] = {}
        if result is not None:
            agent_out["output"] = _truncate(_safe_str(getattr(result, "output", "")), 500)
            if total_in or total_out:
                agent_out["usage"] = {"input_tokens": total_in, "output_tokens": total_out}
            if has_cost:
                agent_out["cost_usd"] = round(total_cost, 8)

        if new_run:
            _emit(store, run_id, EventType.AGENT_END, agent_node_id, agent_kind,
                  agent_label, None, end_ts, agent_out)
        else:
            _emit(store, run_id, EventType.STEP_END, agent_node_id, agent_kind,
                  agent_label, agent_parent, end_ts,
                  {"input": start_data.get("input", {}), "output": agent_out})


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def patch_pydantic_ai(run: Optional[RunContext] = None) -> VapPydanticAI:
    """Patch Pydantic AI's ``Agent`` for VaP tracing and return the listener.

    Equivalent to ``VapPydanticAI(run)``; keep the returned object if you want to
    call ``.detach()`` later.
    """
    return VapPydanticAI(run)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _emit(store, run_id, ev_type, node_id, kind, label, parent_id, ts, data) -> None:
    store.add_event(
        VapEvent(
            id=_uid(),
            run_id=run_id,
            timestamp=ts,
            type=ev_type,
            node_id=node_id,
            node_kind=kind,
            node_label=label,
            parent_id=parent_id,
            data=data or {},
        )
    )


def _all_messages(result) -> list:
    getter = getattr(result, "all_messages", None)
    if callable(getter):
        try:
            return list(getter())
        except Exception:  # noqa: BLE001
            return []
    return []


def _epoch(value: Any, fallback: float) -> float:
    """Convert a datetime (or epoch float) to a unix timestamp."""
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    ts = getattr(value, "timestamp", None)
    if callable(ts):
        try:
            return float(ts())
        except Exception:  # noqa: BLE001
            return fallback
    return fallback


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        return ""


def _truncate(value: Any, max_len: int = 300) -> Any:
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "…"
    return value


def _tool_args(args: Any) -> dict[str, Any]:
    """Normalise a ToolCallPart's args (dict or JSON string) for display."""
    if isinstance(args, dict):
        return {k: _truncate(_safe_str(v), 200) for k, v in list(args.items())[:20]}
    if args is None:
        return {}
    return {"args": _truncate(_safe_str(args), 300)}
