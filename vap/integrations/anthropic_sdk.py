from __future__ import annotations

from typing import Any

from ..tracer import get_current_step


def patch_anthropic(client: Any) -> None:
    """
    Monkey-patches an Anthropic client so every messages.create call is
    automatically traced as an LLM node under the current VaP step.

    Usage:
        import anthropic
        import vap

        client = anthropic.Anthropic()
        vap.patch_anthropic(client)

        with vap.trace("my_agent"):
            # This call is now traced automatically
            response = client.messages.create(model="claude-opus-4-7", ...)
    """
    original_create = client.messages.create

    def patched_create(*args: Any, **kwargs: Any) -> Any:
        current = get_current_step()
        if current is None:
            return original_create(*args, **kwargs)

        from ..tracer import _current_step, _uid, _now, NodeKind, StepContext
        from ..events import EventType

        model = kwargs.get("model", "unknown")
        label = f"llm/{model}"
        node_id = _uid()

        ctx = StepContext(
            run_id=current.run_id,
            node_id=node_id,
            node_kind=NodeKind.LLM,
            label=label,
            parent_id=current.node_id,
            store=current._store,
        )
        ctx.set_input({
            "model": model,
            "messages": kwargs.get("messages", []),
            "system": kwargs.get("system"),
            "max_tokens": kwargs.get("max_tokens"),
            "tools": [t.get("name") if isinstance(t, dict) else str(t) for t in kwargs.get("tools", [])],
        })
        ctx._emit(EventType.LLM_CALL)
        token = _current_step.set(ctx)

        try:
            result = original_create(*args, **kwargs)
            usage = None
            if hasattr(result, "usage") and result.usage:
                usage = {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                }
            output_text = None
            if hasattr(result, "content") and result.content:
                blocks = [
                    b.text if hasattr(b, "text") else str(b)
                    for b in result.content
                ]
                output_text = "\n".join(blocks)

            ctx.set_output({"text": output_text, "usage": usage, "stop_reason": getattr(result, "stop_reason", None)})
            ctx._emit(EventType.LLM_RESPONSE, {"input": ctx._input, "output": ctx._output})
            return result
        except Exception as exc:
            ctx._emit(EventType.ERROR, {"error": str(exc), "error_type": type(exc).__name__})
            raise
        finally:
            _current_step.reset(token)

    client.messages.create = patched_create
