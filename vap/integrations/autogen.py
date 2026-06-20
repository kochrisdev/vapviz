"""
VaP tracing integration for AutoGen (AG2).

Wraps ``ConversableAgent`` so a multi-agent conversation is reproduced as a VaP
graph: the chat as a root, each agent turn (``generate_reply``) as a child node,
and each tool/function call (``execute_function``) nested under the turn that
made it. Node timings are real (turns are captured live as they run).

Targets the classic ``autogen.ConversableAgent`` API (``ag2`` / ``pyautogen``).

Two usage modes
---------------

**Manual mode** — attach the conversation to an existing ``vap.trace()``::

    import vap
    from vap.integrations.autogen import VapAutoGen

    with vap.trace("Support chat") as run:
        VapAutoGen(run)
        user.initiate_chat(assistant, message="...")

**Auto mode** — each ``initiate_chat`` becomes its own VaP run::

    import vap
    from vap.integrations.autogen import VapAutoGen

    vap.configure(db="vap.db")
    VapAutoGen()
    user.initiate_chat(assistant, message="...")

Call ``.detach()`` to restore the original ``ConversableAgent`` methods.

Requirements
------------
    pip install "vap[autogen]"
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from ..events import EventType, NodeKind, VapEvent
from ..tracer import RunContext, _uid

try:
    from autogen import ConversableAgent

    _AUTOGEN_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the dep
    _AUTOGEN_AVAILABLE = False


_START_EVENT = {
    NodeKind.AGENT: EventType.AGENT_START,
    NodeKind.STEP: EventType.STEP_START,
    NodeKind.TOOL: EventType.TOOL_CALL,
    NodeKind.LLM: EventType.LLM_CALL,
}
_END_EVENT = {
    NodeKind.AGENT: EventType.AGENT_END,
    NodeKind.STEP: EventType.STEP_END,
    NodeKind.TOOL: EventType.TOOL_RESULT,
    NodeKind.LLM: EventType.LLM_RESPONSE,
}

_PATCH_FLAG = "_vap_autogen_original"


# ---------------------------------------------------------------------------
# VapAutoGen
# ---------------------------------------------------------------------------


class VapAutoGen:
    """
    VaP tracing for AutoGen / AG2 ``ConversableAgent`` conversations.

    Parameters
    ----------
    run:
        Optional ``RunContext`` from ``vap.trace()``. When provided (manual
        mode), conversations attach under that run. When omitted (auto mode),
        each ``initiate_chat`` creates its own VaP run.
    patch:
        Patch ``ConversableAgent`` immediately (default ``True``).
    """

    def __init__(self, run: Optional[RunContext] = None, *, patch: bool = True) -> None:
        if not _AUTOGEN_AVAILABLE:
            raise ImportError(
                "autogen (ag2) is required for VapAutoGen. "
                'Install it with: pip install "vap[autogen]"'
            )
        self._provided_run = run
        self._patched: list[tuple[type, str, Any]] = []
        # Thread-local stack of open node frames for correct parent nesting.
        self._local = threading.local()
        if patch:
            self.patch()

    # ------------------------------------------------------------------
    # Patch / detach
    # ------------------------------------------------------------------

    def patch(self) -> None:
        self._wrap("initiate_chat", self._chat_wrapper)
        self._wrap("generate_reply", self._reply_wrapper)
        self._wrap("execute_function", self._tool_wrapper)

    def detach(self) -> None:
        """Restore the original ``ConversableAgent`` methods."""
        for cls, name, original in self._patched:
            setattr(cls, name, original)
        self._patched.clear()

    def _wrap(self, name: str, make_wrapper) -> None:
        current = getattr(ConversableAgent, name)
        original = getattr(current, _PATCH_FLAG, current)   # never stack wrappers
        wrapper = make_wrapper(original)
        setattr(wrapper, _PATCH_FLAG, original)
        setattr(ConversableAgent, name, wrapper)
        self._patched.append((ConversableAgent, name, original))

    # ------------------------------------------------------------------
    # Wrappers
    # ------------------------------------------------------------------

    def _chat_wrapper(self, original):
        recorder = self

        def initiate_chat(agent_self, recipient, *args, **kwargs):
            label = f"chat/{getattr(recipient, 'name', 'agent')}"
            frame = recorder._begin(NodeKind.STEP, label,
                                    inp={"message": _truncate(_safe_str(kwargs.get("message")))})
            result = None
            error = None
            try:
                result = original(agent_self, recipient, *args, **kwargs)
                return result
            except Exception as exc:  # noqa: BLE001
                error = exc
                raise
            finally:
                recorder._end(frame, _chat_output(result), error)

        return initiate_chat

    def _reply_wrapper(self, original):
        recorder = self

        def generate_reply(agent_self, *args, **kwargs):
            label = f"agent/{getattr(agent_self, 'name', 'agent')}"
            frame = recorder._begin(NodeKind.STEP, label)
            result = None
            error = None
            try:
                result = original(agent_self, *args, **kwargs)
                return result
            except Exception as exc:  # noqa: BLE001
                error = exc
                raise
            finally:
                recorder._end(frame, {"reply": _truncate(_safe_str(result))} if result is not None else {}, error)

        return generate_reply

    def _tool_wrapper(self, original):
        recorder = self

        def execute_function(agent_self, func_call, *args, **kwargs):
            name = "tool"
            tool_input: dict[str, Any] = {}
            if isinstance(func_call, dict):
                name = func_call.get("name") or "tool"
                tool_input = {"arguments": _truncate(_safe_str(func_call.get("arguments")))}
            frame = recorder._begin(NodeKind.TOOL, name, inp=tool_input)
            result = None
            error = None
            try:
                result = original(agent_self, func_call, *args, **kwargs)
                return result
            except Exception as exc:  # noqa: BLE001
                error = exc
                raise
            finally:
                recorder._end(frame, _tool_output(result), error)

        return execute_function

    # ------------------------------------------------------------------
    # Node lifecycle
    # ------------------------------------------------------------------

    def _stack(self) -> list:
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = []
            self._local.stack = stack
        return stack

    def _begin(self, kind: NodeKind, label: str, inp: Optional[dict] = None) -> Optional[dict]:
        try:
            stack = self._stack()
            ts = time.time()
            if stack:
                parent = stack[-1]
                store, run_id, parent_id = parent["store"], parent["run_id"], parent["node_id"]
                is_run_root = False
            elif self._provided_run is not None:
                store = self._provided_run._store
                run_id = self._provided_run.run_id
                parent_id = self._provided_run._root_node_id
                is_run_root = False
            else:
                import vap.store as _sm

                store = _sm.default_store
                run_id = _uid()
                parent_id = None
                is_run_root = True
                kind = NodeKind.AGENT

            node_id = _uid()
            frame = {
                "store": store, "run_id": run_id, "node_id": node_id,
                "kind": kind, "label": label, "parent_id": parent_id,
                "is_run_root": is_run_root,
            }
            data: dict[str, Any] = {}
            if is_run_root:
                data["label"] = label
            if inp:
                data["input"] = inp
            _emit(store, run_id, _START_EVENT[kind], node_id, kind, label, parent_id, ts, data)
            stack.append(frame)
            return frame
        except Exception:  # noqa: BLE001 - tracing must never break the chat
            return None

    def _end(self, frame: Optional[dict], output: dict, error) -> None:
        if frame is None:
            return
        try:
            stack = self._stack()
            if stack and stack[-1] is frame:
                stack.pop()
            else:  # defensive: remove by identity if nesting was unexpected
                try:
                    stack.remove(frame)
                except ValueError:
                    pass

            ts = time.time()
            kind = frame["kind"]
            if error is not None:
                data = {"error": _truncate(_safe_str(error)), "error_type": type(error).__name__}
                ev = EventType.AGENT_END if frame["is_run_root"] else EventType.ERROR
                _emit(frame["store"], frame["run_id"], ev, frame["node_id"], kind,
                      frame["label"], frame["parent_id"], ts, data)
            else:
                _emit(frame["store"], frame["run_id"], _END_EVENT[kind], frame["node_id"], kind,
                      frame["label"], frame["parent_id"], ts, {"output": output} if output else {})
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Helpers
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


def _chat_output(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    summary = getattr(result, "summary", None)
    if summary is not None:
        return {"summary": _truncate(_safe_str(summary), 500)}
    return {"result": _truncate(_safe_str(result), 500)}


def _tool_output(result: Any) -> dict[str, Any]:
    # execute_function returns (is_exec_success, result_dict)
    if isinstance(result, tuple) and len(result) == 2:
        success, payload = result
        out: dict[str, Any] = {"success": bool(success)}
        if isinstance(payload, dict):
            content = payload.get("content")
            if content is not None:
                out["content"] = _truncate(_safe_str(content), 500)
        else:
            out["result"] = _truncate(_safe_str(payload), 500)
        return out
    if result is None:
        return {}
    return {"result": _truncate(_safe_str(result), 500)}


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        return ""


def _truncate(text: str, max_len: int = 300) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"
