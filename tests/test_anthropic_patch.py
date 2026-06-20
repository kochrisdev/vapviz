"""Tests for vap/integrations/anthropic_sdk.py — uses MagicMock, no real API key."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from vap.events import EventType
from vap.integrations.anthropic_sdk import _extract_output, _patch_async, _patch_sync
from vap.store import MemoryStore
from vap.tracer import Tracer


# ---------------------------------------------------------------------------
# Helpers — fake Anthropic message objects
# ---------------------------------------------------------------------------

def _fake_message(text="Hello!", stop_reason="end_turn",
                  input_tokens=10, output_tokens=5):
    """Fake anthropic Message response (content is a list of blocks with .text)."""
    msg = MagicMock()
    block = MagicMock()
    block.text = text
    msg.content = [block]
    msg.stop_reason = stop_reason
    msg.usage.input_tokens = input_tokens
    msg.usage.output_tokens = output_tokens
    return msg


def _client_with(message):
    """A mock that looks like anthropic.Anthropic with messages.create."""
    client = MagicMock()
    client.messages.create.return_value = message
    return client


# ---------------------------------------------------------------------------
# _extract_output
# ---------------------------------------------------------------------------

class TestExtractOutput:
    def test_extracts_text(self):
        out = _extract_output(_fake_message(text="Hi there"))
        assert out["text"] == "Hi there"

    def test_joins_multiple_content_blocks(self):
        msg = _fake_message()
        b1, b2 = MagicMock(), MagicMock()
        b1.text, b2.text = "part one", "part two"
        msg.content = [b1, b2]
        out = _extract_output(msg)
        assert out["text"] == "part one\npart two"

    def test_extracts_stop_reason(self):
        out = _extract_output(_fake_message(stop_reason="max_tokens"))
        assert out["stop_reason"] == "max_tokens"

    def test_extracts_usage(self):
        out = _extract_output(_fake_message(input_tokens=7, output_tokens=3))
        assert out["usage"] == {"input_tokens": 7, "output_tokens": 3}

    def test_cost_attached_for_known_model(self):
        out = _extract_output(_fake_message(input_tokens=1000, output_tokens=500),
                              model="claude-3-5-sonnet-20241022")
        assert "cost_usd" in out and out["cost_usd"] > 0

    def test_no_cost_for_unknown_model(self):
        out = _extract_output(_fake_message(), model="some-unknown-model")
        assert "cost_usd" not in out


# ---------------------------------------------------------------------------
# Sync patching
# ---------------------------------------------------------------------------

class TestSyncPatch:
    def _setup(self, message=None):
        store = MemoryStore()
        tracer = Tracer(store=store)
        client = _client_with(message or _fake_message("Answer"))
        _patch_sync(client)
        return client, tracer, store

    def test_events_emitted_inside_trace(self):
        client, tracer, store = self._setup()
        with tracer.trace("test") as run:
            with run.step("chat", kind="step"):
                client.messages.create(model="claude-3-5-sonnet-20241022",
                                        messages=[{"role": "user", "content": "hi"}])
        types = [e.type.value for e in store.get_events(run.run_id)]
        assert "llm_call" in types and "llm_response" in types

    def test_llm_node_label_has_model(self):
        client, tracer, store = self._setup()
        with tracer.trace("test") as run:
            with run.step("chat", kind="step"):
                client.messages.create(model="claude-3-5-haiku-20241022", messages=[])
        graph = store.get_graph(run.run_id)
        llm = next((n for n in graph.nodes if n.kind.value == "llm"), None)
        assert llm is not None and "claude-3-5-haiku-20241022" in llm.label

    def test_output_and_cost_in_response_event(self):
        client, tracer, store = self._setup(
            _fake_message("Answer", input_tokens=1000, output_tokens=500)
        )
        with tracer.trace("test") as run:
            with run.step("chat", kind="step"):
                client.messages.create(model="claude-3-5-sonnet-20241022", messages=[])
        resp = next(e for e in store.get_events(run.run_id) if e.type == EventType.LLM_RESPONSE)
        assert resp.data["output"]["text"] == "Answer"
        assert resp.data["output"]["cost_usd"] > 0

    def test_no_events_outside_trace(self):
        store = MemoryStore()
        Tracer(store=store)
        client = _client_with(_fake_message())
        _patch_sync(client)
        client.messages.create(model="claude-3-5-sonnet-20241022", messages=[])
        assert store.list_runs() == []

    def test_error_emits_error_event(self):
        store = MemoryStore()
        tracer = Tracer(store=store)
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("API down")
        _patch_sync(client)
        with pytest.raises(RuntimeError, match="API down"):
            with tracer.trace("test") as run:
                with run.step("chat", kind="step"):
                    client.messages.create(model="claude-3-5-sonnet-20241022", messages=[])
        types = [e.type.value for e in store.get_events(run.run_id)]
        assert "error" in types and "llm_response" not in types


# ---------------------------------------------------------------------------
# Async patching
# ---------------------------------------------------------------------------

class TestAsyncPatch:
    def _setup(self, message=None):
        store = MemoryStore()
        tracer = Tracer(store=store)
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=message or _fake_message("Async answer"))
        _patch_async(client)
        return client, tracer, store

    def test_async_events_emitted(self):
        client, tracer, store = self._setup()

        async def _inner():
            async with tracer.atrace("test") as run:
                async with run.astep("chat", kind="step"):
                    await client.messages.create(model="claude-3-5-haiku-20241022", messages=[])
            return run

        run = asyncio.run(_inner())
        types = [e.type.value for e in store.get_events(run.run_id)]
        assert "llm_call" in types and "llm_response" in types

    def test_async_error_emits_error_event(self):
        store = MemoryStore()
        tracer = Tracer(store=store)
        client = MagicMock()
        client.messages.create = AsyncMock(side_effect=RuntimeError("timeout"))
        _patch_async(client)

        async def _inner():
            async with tracer.atrace("test") as run:
                async with run.astep("chat", kind="step"):
                    await client.messages.create(model="claude-3-5-sonnet-20241022", messages=[])

        with pytest.raises(RuntimeError):
            asyncio.run(_inner())
        run_id = store.list_runs()[0].run_id
        types = [e.type.value for e in store.get_events(run_id)]
        assert "error" in types
