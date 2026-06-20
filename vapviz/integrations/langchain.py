"""
vapviz callback handler for LangChain / LangGraph.

Traces every chain, tool, and LLM call as vapviz nodes under an existing
``RunContext``.  Works with LangChain >= 0.1 (``langchain-core``).

Usage::

    import vapviz
    from vapviz.integrations.langchain import VapCallbackHandler

    with vapviz.trace("LangGraph Agent") as run:
        handler = VapCallbackHandler(run)
        result = graph.invoke(
            {"messages": [HumanMessage(content="Hello")]},
            config={"callbacks": [handler]},
        )
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from ..tracer import _uid, NodeKind, StepContext
from ..events import EventType

try:
    from langchain_core.callbacks.base import BaseCallbackHandler as _BaseCallbackHandler
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    # Stub so the module can be imported without langchain installed.
    # VapCallbackHandler will raise ImportError at instantiation time.
    class _BaseCallbackHandler:  # type: ignore[no-redef]
        pass
    _LANGCHAIN_AVAILABLE = False


class VapCallbackHandler(_BaseCallbackHandler):  # type: ignore[misc]
    """
    LangChain/LangGraph callback handler that records all chain, tool, and
    LLM invocations as vapviz nodes under an existing ``RunContext``.

    Parameters
    ----------
    run:
        The ``RunContext`` yielded by ``vapviz.trace()`` or ``vapviz.atrace()``.

    Example::

        with vapviz.trace("LangGraph Agent") as run:
            handler = VapCallbackHandler(run)
            result = graph.invoke(inputs, config={"callbacks": [handler]})
    """

    def __init__(self, run: Any) -> None:
        if not _LANGCHAIN_AVAILABLE:
            raise ImportError(
                "langchain-core is required for VapCallbackHandler. "
                'Install it with: pip install "vapviz[langchain]"'
            )
        super().__init__()
        self._run = run
        # Maps LangChain run UUID -> vapviz StepContext
        self._contexts: dict[UUID, StepContext] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_parent_ctx(self, parent_run_id: Optional[UUID]) -> StepContext:
        """Return the vapviz context for parent_run_id, falling back to run root."""
        if parent_run_id and parent_run_id in self._contexts:
            return self._contexts[parent_run_id]
        return self._run._root_ctx

    def _make_ctx(
        self,
        label: str,
        kind: str,
        parent_run_id: Optional[UUID],
    ) -> StepContext:
        parent_ctx = self._get_parent_ctx(parent_run_id)
        return StepContext(
            run_id=self._run.run_id,
            node_id=_uid(),
            node_kind=NodeKind(kind),
            label=label,
            parent_id=parent_ctx.node_id,
            store=self._run._store,
        )

    # ------------------------------------------------------------------
    # Chain callbacks  →  step nodes
    # ------------------------------------------------------------------

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        # Prefer the LangGraph node name (e.g. "supervisor", "math_expert") so
        # multi-agent graphs are readable; LangChain only exposes it via metadata.
        # Without it every chain falls back to the anonymous label "chain" (U4/LG3).
        name = (metadata or {}).get("langgraph_node") or _extract_name(serialized) or "chain"
        ctx = self._make_ctx(name, "step", parent_run_id)
        ctx.set_input(_safe_dict(inputs))
        if tags:
            ctx.set_meta(tags=tags)
        ctx._emit(EventType.STEP_START)
        self._contexts[run_id] = ctx

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        ctx = self._contexts.pop(run_id, None)
        if ctx:
            ctx.set_output(_safe_dict(outputs))
            ctx._emit(EventType.STEP_END, {"input": ctx._input, "output": ctx._output})

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        ctx = self._contexts.pop(run_id, None)
        if ctx:
            ctx._emit(EventType.ERROR, {
                "error": str(error),
                "error_type": type(error).__name__,
            })

    # ------------------------------------------------------------------
    # Tool callbacks  →  tool nodes
    # ------------------------------------------------------------------

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        name = _extract_name(serialized) or "tool"
        ctx = self._make_ctx(name, "tool", parent_run_id)
        # Try to parse JSON inputs for richer display
        try:
            input_data = json.loads(input_str)
            if not isinstance(input_data, dict):
                input_data = {"input": input_str}
        except (json.JSONDecodeError, TypeError):
            input_data = {"input": input_str}
        ctx.set_input(input_data)
        ctx._emit(EventType.TOOL_CALL)
        self._contexts[run_id] = ctx

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        ctx = self._contexts.pop(run_id, None)
        if ctx:
            ctx.set_output({"output": str(output)})
            ctx._emit(EventType.TOOL_RESULT, {"input": ctx._input, "output": ctx._output})

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        ctx = self._contexts.pop(run_id, None)
        if ctx:
            ctx._emit(EventType.ERROR, {
                "error": str(error),
                "error_type": type(error).__name__,
            })

    # ------------------------------------------------------------------
    # Chat model callbacks  →  llm nodes
    # ------------------------------------------------------------------

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[Any]],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        model_name = _extract_name(serialized) or "llm"
        ctx = self._make_ctx(f"llm/{model_name}", "llm", parent_run_id)
        flat = []
        for batch in messages:
            for msg in batch:
                flat.append(_serialize_message(msg))
        ctx.set_input({"model": model_name, "messages": flat})
        ctx._emit(EventType.LLM_CALL)
        self._contexts[run_id] = ctx

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        """Fallback for non-chat LLMs."""
        model_name = _extract_name(serialized) or "llm"
        ctx = self._make_ctx(f"llm/{model_name}", "llm", parent_run_id)
        ctx.set_input({"model": model_name, "prompts": prompts})
        ctx._emit(EventType.LLM_CALL)
        self._contexts[run_id] = ctx

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        ctx = self._contexts.pop(run_id, None)
        if ctx:
            model = (ctx._input or {}).get("model", "") if isinstance(ctx._input, dict) else ""
            output = _extract_llm_result(response, model)
            ctx.set_output(output)
            ctx._emit(EventType.LLM_RESPONSE, {"input": ctx._input, "output": ctx._output})

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        ctx = self._contexts.pop(run_id, None)
        if ctx:
            ctx._emit(EventType.ERROR, {
                "error": str(error),
                "error_type": type(error).__name__,
            })


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_name(serialized: Optional[Dict[str, Any]]) -> Optional[str]:
    """Pull a human-readable name from a LangChain serialized component dict."""
    if not serialized:
        return None
    if "name" in serialized:
        return serialized["name"]
    # id is a list like ["langchain", "chat_models", "openai", "ChatOpenAI"]
    if "id" in serialized and isinstance(serialized["id"], list) and serialized["id"]:
        return serialized["id"][-1]
    return None


def _serialize_message(msg: Any) -> dict:
    """Convert a LangChain BaseMessage to a plain dict."""
    if hasattr(msg, "model_dump"):
        try:
            return msg.model_dump()
        except Exception:
            pass
    if hasattr(msg, "dict"):
        try:
            return msg.dict()
        except Exception:
            pass
    return {"content": str(msg)}


def _json_default(o: Any) -> Any:
    """JSON fallback for non-serializable values (e.g. LangChain message objects)."""
    if hasattr(o, "model_dump"):
        try:
            return o.model_dump()
        except Exception:
            pass
    if hasattr(o, "dict"):
        try:
            return o.dict()
        except Exception:
            pass
    return str(o)


def _safe_dict(value: Any) -> dict:
    """Coerce a value to a plain, JSON-serializable dict.

    LangGraph (``langchain.agents.create_agent``) nests raw message objects in
    chain inputs/outputs; without deep coercion ``on_chain_end`` raises
    ``TypeError: Object of type HumanMessage is not JSON serializable`` and the
    node never receives its end event (left stuck "running").
    """
    if not isinstance(value, dict):
        value = {"value": str(value)}
    return json.loads(json.dumps(value, default=_json_default))


def _extract_llm_result(response: Any, model: str = "") -> dict:
    """Extract text, token usage, and cost from a LangChain LLMResult."""
    from ..cost import calculate_cost

    output: dict[str, Any] = {}

    if hasattr(response, "generations") and response.generations:
        texts: list[str] = []
        for gen_list in response.generations:
            for gen in gen_list:
                if hasattr(gen, "text") and gen.text:
                    texts.append(gen.text)
                elif hasattr(gen, "message"):
                    msg = gen.message
                    content = getattr(msg, "content", "")
                    if isinstance(content, str):
                        texts.append(content)
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                texts.append(block.get("text", ""))
        if texts:
            output["text"] = "\n".join(t for t in texts if t)

    if hasattr(response, "llm_output") and response.llm_output:
        # The start-time label is the class name ("ChatOpenAI"); the real model
        # id (e.g. "openai/gpt-4o-mini") is on the result — prefer it for pricing.
        model = response.llm_output.get("model_name") or model
        usage = (
            response.llm_output.get("token_usage")
            or response.llm_output.get("usage")
            or {}
        )
        if usage:
            input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens", 0)
            output_tokens = usage.get("completion_tokens") or usage.get("output_tokens", 0)
            output["usage"] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
            cost = calculate_cost(model, input_tokens, output_tokens)
            if cost is not None:
                output["cost_usd"] = round(cost, 8)

    return output
