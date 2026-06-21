"""Tests for vapviz/integrations/openai_sdk.py — uses MagicMock, no real API key."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vapviz.events import EventType
from vapviz.integrations.openai_sdk import patch_openai, _extract_output
from vapviz.store import MemoryStore
from vapviz.tracer import Tracer


# ---------------------------------------------------------------------------
# Helpers — fake OpenAI response objects
# ---------------------------------------------------------------------------

def _make_sync_client():
    """Minimal mock that looks like openai.OpenAI."""
    client = MagicMock()
    # Ensure isinstance check fails so _patch_sync path is taken
    with patch("vapviz.integrations.openai_sdk.__import__", side_effect=ImportError):
        pass
    return client


def _fake_response(text="Hello!", finish_reason="stop",
                   prompt_tokens=10, completion_tokens=5):
    """Fake ChatCompletion response."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    resp.choices[0].finish_reason = finish_reason
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    return resp


# ---------------------------------------------------------------------------
# _extract_output
# ---------------------------------------------------------------------------

class TestExtractOutput:
    def test_extracts_text(self):
        out = _extract_output(_fake_response(text="Hi there"))
        assert out["text"] == "Hi there"

    def test_extracts_finish_reason(self):
        out = _extract_output(_fake_response(finish_reason="stop"))
        assert out["finish_reason"] == "stop"

    def test_extracts_usage(self):
        out = _extract_output(_fake_response(prompt_tokens=7, completion_tokens=3))
        assert out["usage"]["input_tokens"] == 7
        assert out["usage"]["output_tokens"] == 3

    def test_handles_none_content(self):
        resp = _fake_response()
        resp.choices[0].message.content = None
        out = _extract_output(resp)
        assert "text" not in out

    def test_handles_missing_choices(self):
        resp = MagicMock()
        resp.choices = []
        resp.usage = None
        out = _extract_output(resp)
        assert out == {}


# ---------------------------------------------------------------------------
# Sync patching
# ---------------------------------------------------------------------------

class TestSyncPatch:
    def _make_client_and_tracer(self):
        store = MemoryStore()
        tracer = Tracer(store=store)

        client = MagicMock()
        client.chat.completions.create.return_value = _fake_response("Answer")
        # Force sync path by making isinstance(client, AsyncOpenAI) fail
        with patch("vapviz.integrations.openai_sdk.patch_openai", wraps=patch_openai):
            pass

        # Manually call _patch_sync to avoid the ImportError check
        from vapviz.integrations.openai_sdk import _patch_sync
        _patch_sync(client)
        return client, tracer, store

    def test_events_emitted_inside_trace(self):
        client, tracer, store = self._make_client_and_tracer()

        with tracer.trace("test") as run:
            with run.step("chat", kind="step"):
                client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": "hi"}],
                )

        types = [e.type.value for e in store.get_events(run.run_id)]
        assert "llm_call" in types
        assert "llm_response" in types

    def test_llm_node_has_correct_label(self):
        client, tracer, store = self._make_client_and_tracer()

        with tracer.trace("test") as run:
            with run.step("chat", kind="step"):
                client.chat.completions.create(
                    model="gpt-4o",
                    messages=[],
                )

        graph = store.get_graph(run.run_id)
        llm_node = next((n for n in graph.nodes if n.kind.value == "llm"), None)
        assert llm_node is not None
        assert "gpt-4o" in llm_node.label

    def test_no_events_outside_trace(self):
        store = MemoryStore()
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_response()

        from vapviz.integrations.openai_sdk import _patch_sync
        _patch_sync(client)
        # Call outside any trace — original should be called, no events stored
        client.chat.completions.create(model="gpt-4o", messages=[])
        assert store.list_runs() == []

    def test_error_emits_error_event(self):
        store = MemoryStore()
        tracer = Tracer(store=store)
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("API down")

        from vapviz.integrations.openai_sdk import _patch_sync
        _patch_sync(client)

        with pytest.raises(RuntimeError, match="API down"):
            with tracer.trace("test") as run:
                with run.step("chat", kind="step"):
                    client.chat.completions.create(model="gpt-4o", messages=[])

        types = [e.type.value for e in store.get_events(run.run_id)]
        assert "error" in types
        assert "llm_response" not in types

    def test_output_data_in_response_event(self):
        client, tracer, store = self._make_client_and_tracer()

        with tracer.trace("test") as run:
            with run.step("chat", kind="step"):
                client.chat.completions.create(model="gpt-4o", messages=[])

        resp_event = next(
            e for e in store.get_events(run.run_id) if e.type == EventType.LLM_RESPONSE
        )
        assert resp_event.data["output"]["text"] == "Answer"


# ---------------------------------------------------------------------------
# Async patching
# ---------------------------------------------------------------------------

class TestAsyncPatch:
    def _make_async_client_and_tracer(self):
        store = MemoryStore()
        tracer = Tracer(store=store)

        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_fake_response("Async answer"))

        from vapviz.integrations.openai_sdk import _patch_async
        _patch_async(client)
        return client, tracer, store

    def test_async_events_emitted(self):
        client, tracer, store = self._make_async_client_and_tracer()

        async def _inner():
            async with tracer.atrace("test") as run:
                async with run.astep("chat", kind="step"):
                    await client.chat.completions.create(model="gpt-4o-mini", messages=[])
            return run

        run = asyncio.run(_inner())
        types = [e.type.value for e in store.get_events(run.run_id)]
        assert "llm_call" in types
        assert "llm_response" in types

    def test_async_no_events_outside_trace(self):
        store = MemoryStore()
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_fake_response())

        from vapviz.integrations.openai_sdk import _patch_async
        _patch_async(client)

        async def _inner():
            await client.chat.completions.create(model="gpt-4o", messages=[])

        asyncio.run(_inner())
        assert store.list_runs() == []

    def test_async_error_emits_error_event(self):
        store = MemoryStore()
        tracer = Tracer(store=store)
        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=RuntimeError("timeout"))

        from vapviz.integrations.openai_sdk import _patch_async
        _patch_async(client)

        async def _inner():
            async with tracer.atrace("test") as run:
                async with run.astep("chat", kind="step"):
                    await client.chat.completions.create(model="gpt-4o", messages=[])

        with pytest.raises(RuntimeError):
            asyncio.run(_inner())

        run_id = store.list_runs()[0].run_id
        types = [e.type.value for e in store.get_events(run_id)]
        assert "error" in types
