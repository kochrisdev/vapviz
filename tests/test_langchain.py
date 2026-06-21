"""
Tests for vapviz/integrations/langchain.py — uses minimal stubs so langchain-core
is not required to run the suite.  When langchain-core IS installed the tests
exercise the real BaseCallbackHandler inheritance.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from vapviz.events import EventType, NodeKind, NodeStatus
from vapviz.integrations.langchain import (
    VapCallbackHandler,
    _extract_name,
    _extract_llm_result,
    _safe_dict,
    _LANGCHAIN_AVAILABLE,
)
from vapviz.store import MemoryStore
from vapviz.tracer import Tracer


# ---------------------------------------------------------------------------
# Skip guard — mark tests that require langchain-core
# ---------------------------------------------------------------------------

requires_langchain = pytest.mark.skipif(
    not _LANGCHAIN_AVAILABLE,
    reason="langchain-core not installed",
)


# ---------------------------------------------------------------------------
# Helper: build a tracer+store and enter a trace so _root_ctx exists
# ---------------------------------------------------------------------------

class _TraceHandle:
    """Context-manager helper that gives us an active RunContext + store."""
    def __init__(self):
        self.store = MemoryStore()
        self.tracer = Tracer(store=self.store)
        self._cm = None
        self.run = None

    def __enter__(self):
        self._cm = self.tracer.trace("test")
        self.run = self._cm.__enter__()
        return self

    def __exit__(self, *args):
        self._cm.__exit__(*args)


# ---------------------------------------------------------------------------
# Private helper functions (no langchain dependency needed)
# ---------------------------------------------------------------------------

class TestExtractName:
    def test_uses_name_key(self):
        assert _extract_name({"name": "MyChain"}) == "MyChain"

    def test_uses_last_id_element(self):
        assert _extract_name({"id": ["langchain", "chat_models", "ChatOpenAI"]}) == "ChatOpenAI"

    def test_returns_none_for_empty(self):
        assert _extract_name(None) is None
        assert _extract_name({}) is None


class TestSafeDict:
    def test_returns_dict_value_equal(self):
        # Now deep-coerces to a JSON-safe equivalent (not necessarily the same object).
        d = {"a": 1}
        assert _safe_dict(d) == d

    def test_stringifies_non_dict(self):
        result = _safe_dict("hello")
        assert result == {"value": "hello"}

    def test_stringifies_list(self):
        result = _safe_dict([1, 2, 3])
        assert "value" in result

    def test_coerces_non_serializable_objects(self):
        # LG2 regression: nested non-JSON objects (e.g. LangChain messages) must
        # not raise — they're coerced so on_chain_end can emit STEP_END.
        import json

        class Msg:
            def model_dump(self):
                return {"content": "hi"}

        result = _safe_dict({"messages": [Msg()]})
        json.dumps(result)  # must not raise
        assert result == {"messages": [{"content": "hi"}]}


class TestExtractLlmResult:
    def _make_result(self, text="Hi", prompt_tokens=5, completion_tokens=3):
        result = MagicMock()
        gen = MagicMock()
        gen.text = text
        result.generations = [[gen]]
        result.llm_output = {
            "token_usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        }
        return result

    def test_extracts_text(self):
        out = _extract_llm_result(self._make_result(text="Hello"))
        assert out["text"] == "Hello"

    def test_extracts_usage(self):
        out = _extract_llm_result(self._make_result(prompt_tokens=7, completion_tokens=4))
        assert out["usage"]["input_tokens"] == 7
        assert out["usage"]["output_tokens"] == 4

    def test_handles_empty_generations(self):
        result = MagicMock()
        result.generations = []
        result.llm_output = None
        out = _extract_llm_result(result)
        assert out == {}

    def test_extracts_from_message_content(self):
        result = MagicMock()
        gen = MagicMock()
        gen.text = None
        gen.message.content = "From message"
        result.generations = [[gen]]
        result.llm_output = None
        out = _extract_llm_result(result)
        assert out["text"] == "From message"


# ---------------------------------------------------------------------------
# VapCallbackHandler — requires langchain-core (or stubs that satisfy isinstance)
# ---------------------------------------------------------------------------

@requires_langchain
class TestVapCallbackHandlerChain:
    def test_chain_start_creates_step_node(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_chain_start(
                {"name": "MyChain"}, {"input": "test"},
                run_id=run_uuid, parent_run_id=None,
            )
            ctx = handler._contexts.get(run_uuid)
            assert ctx is not None
            assert ctx.node_kind == NodeKind.STEP

    def test_chain_label_prefers_langgraph_node(self):
        # LG3/U4: multi-agent readability — the node name comes from metadata.
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_chain_start(
                {"name": "RunnableSequence"}, {},
                run_id=run_uuid, parent_run_id=None,
                metadata={"langgraph_node": "math_expert"},
            )
            assert handler._contexts[run_uuid].label == "math_expert"

    def test_chain_label_falls_back_when_no_langgraph_node(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_chain_start(
                {"name": "MyChain"}, {}, run_id=run_uuid, metadata={},
            )
            assert handler._contexts[run_uuid].label == "MyChain"

    def test_chain_end_removes_context_and_emits_step_end(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_chain_start({"name": "X"}, {}, run_id=run_uuid)
            handler.on_chain_end({"result": "ok"}, run_id=run_uuid)
            assert run_uuid not in handler._contexts
            types = [e.type.value for e in h.store.get_events(h.run.run_id)]
            assert "step_end" in types

    def test_chain_error_emits_error_event(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_chain_start({"name": "X"}, {}, run_id=run_uuid)
            handler.on_chain_error(ValueError("boom"), run_id=run_uuid)
            assert run_uuid not in handler._contexts
            types = [e.type.value for e in h.store.get_events(h.run.run_id)]
            assert "error" in types

    def test_nested_chains_have_correct_parents(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            parent_uuid = uuid4()
            child_uuid = uuid4()
            handler.on_chain_start({"name": "Parent"}, {}, run_id=parent_uuid)
            handler.on_chain_start({"name": "Child"}, {}, run_id=child_uuid,
                                   parent_run_id=parent_uuid)

            graph = h.store.get_graph(h.run.run_id)
            # While trace is still running (no step_end yet) nodes have run state
            parent_ctx = handler._contexts[parent_uuid]
            child_ctx = handler._contexts[child_uuid]
            assert child_ctx.parent_id == parent_ctx.node_id

    def test_top_level_chain_parented_to_run_root(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_chain_start({"name": "TopLevel"}, {}, run_id=run_uuid)
            ctx = handler._contexts[run_uuid]
            assert ctx.parent_id == h.run._root_ctx.node_id


@requires_langchain
class TestVapCallbackHandlerTool:
    def test_tool_start_creates_tool_node(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_tool_start({"name": "search"}, '{"query": "hello"}', run_id=run_uuid)
            ctx = handler._contexts.get(run_uuid)
            assert ctx is not None
            assert ctx.node_kind == NodeKind.TOOL
            assert ctx.label == "search"

    def test_tool_end_emits_tool_result(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_tool_start({"name": "search"}, "query", run_id=run_uuid)
            handler.on_tool_end("result text", run_id=run_uuid)
            types = [e.type.value for e in h.store.get_events(h.run.run_id)]
            assert "tool_result" in types

    def test_tool_input_parsed_as_json(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_tool_start({"name": "calc"}, '{"expr": "1+1"}', run_id=run_uuid)
            ctx = handler._contexts[run_uuid]
            assert ctx._input == {"expr": "1+1"}

    def test_tool_input_string_fallback(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_tool_start({"name": "calc"}, "not json", run_id=run_uuid)
            ctx = handler._contexts[run_uuid]
            assert ctx._input == {"input": "not json"}

    def test_tool_error_emits_error_event(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_tool_start({"name": "bad_tool"}, "", run_id=run_uuid)
            handler.on_tool_error(RuntimeError("failed"), run_id=run_uuid)
            types = [e.type.value for e in h.store.get_events(h.run.run_id)]
            assert "error" in types


@requires_langchain
class TestVapCallbackHandlerLLM:
    def _make_llm_result(self, text="Response"):
        result = MagicMock()
        gen = MagicMock()
        gen.text = text
        result.generations = [[gen]]
        result.llm_output = {
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 5}
        }
        return result

    def test_chat_model_start_creates_llm_node(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            msg = MagicMock()
            msg.model_dump.return_value = {"role": "user", "content": "hi"}
            handler.on_chat_model_start(
                {"name": "ChatOpenAI"}, [[msg]], run_id=run_uuid,
            )
            ctx = handler._contexts.get(run_uuid)
            assert ctx is not None
            assert ctx.node_kind == NodeKind.LLM
            assert "ChatOpenAI" in ctx.label

    def test_llm_end_emits_llm_response(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_llm_start({"name": "LLM"}, ["prompt"], run_id=run_uuid)
            handler.on_llm_end(self._make_llm_result("Hi"), run_id=run_uuid)
            types = [e.type.value for e in h.store.get_events(h.run.run_id)]
            assert "llm_response" in types

    def test_llm_response_contains_text(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_llm_start({"name": "LLM"}, ["prompt"], run_id=run_uuid)
            handler.on_llm_end(self._make_llm_result("The answer"), run_id=run_uuid)
            resp_event = next(
                e for e in h.store.get_events(h.run.run_id)
                if e.type == EventType.LLM_RESPONSE
            )
            assert resp_event.data["output"]["text"] == "The answer"

    def test_llm_error_emits_error_event(self):
        with _TraceHandle() as h:
            handler = VapCallbackHandler(h.run)
            run_uuid = uuid4()
            handler.on_llm_start({"name": "LLM"}, ["prompt"], run_id=run_uuid)
            handler.on_llm_error(RuntimeError("rate limited"), run_id=run_uuid)
            types = [e.type.value for e in h.store.get_events(h.run.run_id)]
            assert "error" in types
