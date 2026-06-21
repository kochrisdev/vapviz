from __future__ import annotations

from typing import Any

from ..tracer import _current_step, _uid, NodeKind, StepContext
from ..events import EventType


def _make_llm_ctx(kwargs: dict[str, Any]) -> StepContext | None:
    """Return a StepContext for an LLM call, or None if no trace is active."""
    current = _current_step.get()
    if current is None:
        return None
    model = kwargs.get("model", "unknown")
    ctx = StepContext(
        run_id=current.run_id,
        node_id=_uid(),
        node_kind=NodeKind.LLM,
        label=f"llm/{model}",
        parent_id=current.node_id,
        store=current._store,
    )
    ctx.set_input({
        "model": model,
        "messages": kwargs.get("messages", []),
        "system": kwargs.get("system"),
        "max_tokens": kwargs.get("max_tokens"),
        "tools": [
            t.get("name") if isinstance(t, dict) else str(t)
            for t in kwargs.get("tools", [])
        ],
    })
    return ctx


def _extract_output(result: Any, model: str = "") -> dict[str, Any]:
    """Pull text, stop_reason, token usage, and cost from an Anthropic message response."""
    from ..cost import calculate_cost

    output: dict[str, Any] = {}
    if hasattr(result, "content") and result.content:
        output["text"] = "\n".join(
            b.text if hasattr(b, "text") else str(b) for b in result.content
        )
    if hasattr(result, "stop_reason"):
        output["stop_reason"] = result.stop_reason
    if hasattr(result, "usage") and result.usage:
        input_tokens = result.usage.input_tokens
        output_tokens = result.usage.output_tokens
        output["usage"] = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        cost = calculate_cost(model, input_tokens, output_tokens)
        if cost is not None:
            output["cost_usd"] = round(cost, 8)
    return output


def _patch_sync(client: Any) -> None:
    original = client.messages.create

    def patched(*args: Any, **kwargs: Any) -> Any:
        ctx = _make_llm_ctx(kwargs)
        if ctx is None:
            return original(*args, **kwargs)
        ctx._emit(EventType.LLM_CALL)
        token = _current_step.set(ctx)
        try:
            result = original(*args, **kwargs)
            ctx.set_output(_extract_output(result, model=kwargs.get("model", "")))
            ctx._emit(EventType.LLM_RESPONSE, {"input": ctx._input, "output": ctx._output})
            return result
        except Exception as exc:
            ctx._emit(EventType.ERROR, {"error": str(exc), "error_type": type(exc).__name__})
            raise
        finally:
            _current_step.reset(token)

    client.messages.create = patched


def _patch_async(client: Any) -> None:
    original = client.messages.create

    async def patched(*args: Any, **kwargs: Any) -> Any:
        ctx = _make_llm_ctx(kwargs)
        if ctx is None:
            return await original(*args, **kwargs)
        ctx._emit(EventType.LLM_CALL)
        token = _current_step.set(ctx)
        try:
            result = await original(*args, **kwargs)
            ctx.set_output(_extract_output(result, model=kwargs.get("model", "")))
            ctx._emit(EventType.LLM_RESPONSE, {"input": ctx._input, "output": ctx._output})
            return result
        except Exception as exc:
            ctx._emit(EventType.ERROR, {"error": str(exc), "error_type": type(exc).__name__})
            raise
        finally:
            _current_step.reset(token)

    client.messages.create = patched


def patch_anthropic(client: Any) -> None:
    """
    Auto-instrument an Anthropic client so every ``messages.create`` call is
    traced as an LLM node under the current vapviz step.

    Handles both sync (``anthropic.Anthropic``) and async
    (``anthropic.AsyncAnthropic``) clients automatically.

    Usage::

        import anthropic, vapviz

        client = anthropic.Anthropic()
        vapviz.patch_anthropic(client)           # sync

        async_client = anthropic.AsyncAnthropic()
        vapviz.patch_anthropic(async_client)     # async — same call
    """
    try:
        import anthropic as _anthropic
        if isinstance(client, _anthropic.AsyncAnthropic):
            _patch_async(client)
            return
    except ImportError:
        pass
    _patch_sync(client)
