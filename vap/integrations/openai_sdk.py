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
        "max_tokens": kwargs.get("max_tokens"),
        "tools": [
            # OpenAI tools are {"type": "function", "function": {"name": ...}}
            t.get("function", {}).get("name") if isinstance(t, dict) else str(t)
            for t in kwargs.get("tools", [])
        ],
    })
    return ctx


def _extract_output(result: Any) -> dict[str, Any]:
    """Pull text, finish_reason, and token usage from an OpenAI ChatCompletion."""
    output: dict[str, Any] = {}
    if hasattr(result, "choices") and result.choices:
        choice = result.choices[0]
        if hasattr(choice, "message") and hasattr(choice.message, "content"):
            if choice.message.content is not None:
                output["text"] = choice.message.content
        if hasattr(choice, "finish_reason") and choice.finish_reason:
            output["finish_reason"] = choice.finish_reason
    if hasattr(result, "usage") and result.usage:
        output["usage"] = {
            "input_tokens": result.usage.prompt_tokens,
            "output_tokens": result.usage.completion_tokens,
        }
    return output


def _patch_sync(client: Any) -> None:
    original = client.chat.completions.create

    def patched(*args: Any, **kwargs: Any) -> Any:
        ctx = _make_llm_ctx(kwargs)
        if ctx is None:
            return original(*args, **kwargs)
        ctx._emit(EventType.LLM_CALL)
        token = _current_step.set(ctx)
        try:
            result = original(*args, **kwargs)
            ctx.set_output(_extract_output(result))
            ctx._emit(EventType.LLM_RESPONSE, {"input": ctx._input, "output": ctx._output})
            return result
        except Exception as exc:
            ctx._emit(EventType.ERROR, {"error": str(exc), "error_type": type(exc).__name__})
            raise
        finally:
            _current_step.reset(token)

    client.chat.completions.create = patched


def _patch_async(client: Any) -> None:
    original = client.chat.completions.create

    async def patched(*args: Any, **kwargs: Any) -> Any:
        ctx = _make_llm_ctx(kwargs)
        if ctx is None:
            return await original(*args, **kwargs)
        ctx._emit(EventType.LLM_CALL)
        token = _current_step.set(ctx)
        try:
            result = await original(*args, **kwargs)
            ctx.set_output(_extract_output(result))
            ctx._emit(EventType.LLM_RESPONSE, {"input": ctx._input, "output": ctx._output})
            return result
        except Exception as exc:
            ctx._emit(EventType.ERROR, {"error": str(exc), "error_type": type(exc).__name__})
            raise
        finally:
            _current_step.reset(token)

    client.chat.completions.create = patched


def patch_openai(client: Any) -> None:
    """
    Auto-instrument an OpenAI client so every ``chat.completions.create`` call
    is traced as an LLM node under the current VaP step.

    Handles both sync (``openai.OpenAI``) and async (``openai.AsyncOpenAI``)
    clients automatically.

    Requires the ``openai`` package: ``pip install "vap[openai]"``

    Usage::

        import openai, vap

        client = openai.OpenAI()
        vap.patch_openai(client)                    # sync

        async_client = openai.AsyncOpenAI()
        vap.patch_openai(async_client)              # async — same call

    Each ``chat.completions.create`` call becomes a purple **llm** node
    showing model name, messages, token usage, and the response text.
    """
    try:
        import openai as _openai
        if isinstance(client, _openai.AsyncOpenAI):
            _patch_async(client)
            return
    except ImportError:
        pass
    _patch_sync(client)
