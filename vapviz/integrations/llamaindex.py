"""
vapviz tracing integration for LlamaIndex.

Registers a span handler on LlamaIndex's instrumentation dispatcher so that every
instrumented call — query engines, retrievers, embeddings, response synthesizers,
LLM calls — is reproduced as a vapviz node. The span tree (each span's
``parent_span_id``) maps directly onto vapviz's node hierarchy, and node timings are
real (spans are captured live as they open and close).

Two usage modes
---------------

**Manual mode** — attach LlamaIndex activity to an existing ``vapviz.trace()`` so a
whole RAG workflow becomes one run (recommended)::

    import vapviz
    from vapviz.integrations.llamaindex import VapLlamaIndex

    with vapviz.trace("RAG query") as run:
        VapLlamaIndex(run)
        index = VectorStoreIndex.from_documents(docs)
        response = index.as_query_engine().query("...")

**Auto mode** — each top-level instrumented call becomes its own vapviz run::

    import vapviz
    from vapviz.integrations.llamaindex import VapLlamaIndex

    vapviz.configure(db="vapviz.db")
    VapLlamaIndex()
    response = query_engine.query("...")

Call ``.detach()`` to remove the handler from the dispatcher.

Requirements
------------
    pip install "vapviz[llamaindex]"
"""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

from pydantic import PrivateAttr

from ..events import EventType, NodeKind, VapEvent
from ..tracer import RunContext, _uid

try:
    from llama_index.core.instrumentation import get_dispatcher
    from llama_index.core.instrumentation.span_handlers import BaseSpanHandler

    _LLAMAINDEX_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the dep
    _LLAMAINDEX_AVAILABLE = False

    class BaseSpanHandler:  # type: ignore[no-redef]
        """Stub so the module imports without llama-index-core installed."""


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


# ---------------------------------------------------------------------------
# VapLlamaIndex
# ---------------------------------------------------------------------------


class VapLlamaIndex(BaseSpanHandler):  # type: ignore[misc]
    """
    vapviz span handler for LlamaIndex.

    Parameters
    ----------
    run:
        Optional ``RunContext`` from ``vapviz.trace()``. When provided (manual
        mode), every LlamaIndex span is attached under that run. When omitted
        (auto mode), each top-level span (one with no instrumented parent)
        starts its own vapviz run in ``vapviz.store.default_store``.
    register:
        Register on LlamaIndex's root dispatcher immediately (default ``True``).
    """

    _provided_run: Any = PrivateAttr(default=None)
    _spans: dict = PrivateAttr(default_factory=dict)
    _lock: Any = PrivateAttr(default_factory=threading.Lock)

    def __init__(self, run: Optional[RunContext] = None, *, register: bool = True, **kwargs: Any) -> None:
        if not _LLAMAINDEX_AVAILABLE:
            raise ImportError(
                "llama-index-core is required for VapLlamaIndex. "
                'Install it with: pip install "vapviz[llamaindex]"'
            )
        super().__init__(**kwargs)
        # Set private attrs explicitly — pydantic's PrivateAttr default_factory
        # is not reliably applied when __init__ is overridden on this base.
        self._provided_run = run
        self._spans = {}
        self._lock = threading.Lock()
        if register:
            self.register()

    @classmethod
    def class_name(cls) -> str:  # noqa: D401 - required by BaseSpanHandler
        return "VapLlamaIndex"

    # ------------------------------------------------------------------
    # Register / detach
    # ------------------------------------------------------------------

    def register(self) -> None:
        get_dispatcher().add_span_handler(self)

    def detach(self) -> None:
        """Remove this handler from the root dispatcher."""
        try:
            get_dispatcher().span_handlers.remove(self)
        except (ValueError, Exception):  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Span lifecycle (called by the dispatcher)
    # ------------------------------------------------------------------

    def new_span(self, id_, bound_args, instance=None, parent_span_id=None, tags=None, **kwargs):  # noqa: ANN001
        try:
            self._open(id_, bound_args, instance, parent_span_id)
        except Exception:  # noqa: BLE001 - tracing must never break the call
            pass
        return None

    def prepare_to_exit_span(self, id_, bound_args, instance=None, result=None, **kwargs):  # noqa: ANN001
        try:
            self._close(id_, result=result, error=None)
        except Exception:  # noqa: BLE001
            pass
        return None

    def prepare_to_drop_span(self, id_, bound_args, instance=None, err=None, **kwargs):  # noqa: ANN001
        try:
            self._close(id_, result=None, error=err)
        except Exception:  # noqa: BLE001
            pass
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _open(self, id_, bound_args, instance, parent_span_id) -> None:
        label = _label(id_)
        kind = _classify(instance, label)
        ts = time.time()

        with self._lock:
            parent = self._spans.get(parent_span_id) if parent_span_id else None

            if parent is not None:
                store = parent["store"]
                run_id = parent["run_id"]
                parent_node_id = parent["node_id"]
                is_run_root = False
            elif self._provided_run is not None:
                # Manual mode: attach under the provided run's root.
                store = self._provided_run._store
                run_id = self._provided_run.run_id
                parent_node_id = self._provided_run._root_node_id
                is_run_root = False
            else:
                # Auto mode: this top-level span becomes its own run's root.
                import vapviz.store as _sm

                store = _sm.default_store
                run_id = _uid()
                parent_node_id = None
                is_run_root = True
                kind = NodeKind.AGENT

            node_id = _uid()
            self._spans[id_] = {
                "store": store,
                "run_id": run_id,
                "node_id": node_id,
                "kind": kind,
                "label": label,
                "parent_id": parent_node_id,
                "is_run_root": is_run_root,
                "model": _model_name(instance) if kind == NodeKind.LLM else None,
            }

        data: dict[str, Any] = {}
        if is_run_root:
            data["label"] = label
        inp = _args_snapshot(bound_args)
        if inp:
            data["input"] = inp

        _emit(store, run_id, _START_EVENT[kind], node_id, kind, label, parent_node_id, ts, data)

    def _close(self, id_, result, error) -> None:
        ts = time.time()
        with self._lock:
            rec = self._spans.pop(id_, None)
        if rec is None:
            return

        kind = rec["kind"]
        if error is not None:
            data = {"error": _truncate(_safe_str(error)), "error_type": type(error).__name__}
            if rec["is_run_root"]:
                _emit(rec["store"], rec["run_id"], EventType.AGENT_END, rec["node_id"], kind,
                      rec["label"], rec["parent_id"], ts, data)
            else:
                _emit(rec["store"], rec["run_id"], EventType.ERROR, rec["node_id"], kind,
                      rec["label"], rec["parent_id"], ts, data)
            return

        out = {"result": _truncate(_safe_str(result))} if result is not None else {}
        if kind == NodeKind.LLM and result is not None:
            out.update(_extract_usage_and_cost(result, rec.get("model")))
        _emit(rec["store"], rec["run_id"], _END_EVENT[kind], rec["node_id"], kind,
              rec["label"], rec["parent_id"], ts, {"output": out} if out else {})


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


def _model_name(instance: Any) -> str:
    """Best-effort model id from a LlamaIndex LLM instance (e.g. ``gpt-4o-mini``)."""
    return _safe_str(getattr(instance, "model", None) or getattr(instance, "model_name", None))


def _extract_usage_and_cost(result: Any, model: Optional[str]) -> dict[str, Any]:
    """Read token usage from a LlamaIndex LLM response and price it.

    Mirrors ``langchain.py::_extract_llm_result``. LlamaIndex Chat/Completion
    responses expose the raw provider payload on ``.raw`` (an OpenAI
    ``ChatCompletion`` with ``.usage``, or a dict) and sometimes echo token
    counts in ``.additional_kwargs``.
    """
    from ..cost import calculate_cost

    in_tok = out_tok = 0

    raw = getattr(result, "raw", None)
    usage = None
    if raw is not None:
        usage = getattr(raw, "usage", None)
        if usage is None and isinstance(raw, dict):
            usage = raw.get("usage")
    if usage is not None:
        get = usage.get if isinstance(usage, dict) else (lambda k: getattr(usage, k, None))
        in_tok = get("prompt_tokens") or get("input_tokens") or 0
        out_tok = get("completion_tokens") or get("output_tokens") or 0

    if not (in_tok or out_tok):
        ak = getattr(result, "additional_kwargs", None)
        if isinstance(ak, dict):
            in_tok = ak.get("prompt_tokens") or ak.get("input_tokens") or 0
            out_tok = ak.get("completion_tokens") or ak.get("output_tokens") or 0

    in_tok = int(in_tok or 0)
    out_tok = int(out_tok or 0)
    if not (in_tok or out_tok):
        return {}

    out: dict[str, Any] = {"usage": {"input_tokens": in_tok, "output_tokens": out_tok}}
    cost = calculate_cost(model or "", in_tok, out_tok)
    if cost is not None:
        out["cost_usd"] = round(cost, 8)
    return out


def _label(id_: str) -> str:
    """LlamaIndex span ids are ``"<qualname>-<uuid>"``; recover the qualname."""
    parts = id_.rsplit("-", 5)          # uuid is 5 hyphen-separated groups
    return parts[0] if len(parts) == 6 else id_


_LLM_METHODS = {
    "chat", "complete", "predict", "achat", "acomplete", "apredict",
    "stream_chat", "stream_complete", "astream_chat", "astream_complete",
}


def _classify(instance: Any, label: str) -> NodeKind:
    cls = type(instance).__name__ if instance is not None else ""
    method = label.rsplit(".", 1)[-1].lstrip("_")
    if cls.endswith("LLM") or "LLM" in cls or method in _LLM_METHODS:
        return NodeKind.LLM
    if cls.endswith("Retriever") or method == "retrieve":
        return NodeKind.TOOL
    if "Embedding" in cls:
        return NodeKind.TOOL
    return NodeKind.STEP


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


def _args_snapshot(bound_args: Any) -> dict[str, Any]:
    """A small, bounded snapshot of call arguments (minus ``self``)."""
    arguments = getattr(bound_args, "arguments", None)
    if not isinstance(arguments, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in list(arguments.items())[:8]:
        if key in ("self", "cls"):
            continue
        out[key] = _truncate(_safe_str(value), 200)
    return out
