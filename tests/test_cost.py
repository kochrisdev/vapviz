"""Tests for vapviz/cost.py — pricing table and cost calculation."""
from __future__ import annotations

import pytest
from vapviz.cost import calculate_cost, format_cost, PRICING


class TestCalculateCost:
    def test_exact_match_openai(self):
        cost = calculate_cost("gpt-4o", 1000, 500)
        # input: 1000 * 0.0025/1000 = 0.0025
        # output: 500 * 0.010/1000  = 0.005
        assert cost == pytest.approx(0.0025 + 0.005, rel=1e-6)

    def test_exact_match_anthropic(self):
        cost = calculate_cost("claude-3-haiku-20240307", 2000, 1000)
        # input: 2000 * 0.00025/1000 = 0.0005
        # output: 1000 * 0.00125/1000 = 0.00125
        assert cost == pytest.approx(0.0005 + 0.00125, rel=1e-6)

    def test_gpt4o_mini_pricing(self):
        cost = calculate_cost("gpt-4o-mini", 10_000, 5_000)
        # input: 10000 * 0.000150/1000 = 0.0015
        # output: 5000 * 0.000600/1000 = 0.003
        assert cost == pytest.approx(0.0015 + 0.003, rel=1e-6)

    def test_unknown_model_returns_none(self):
        assert calculate_cost("some-unknown-model-xyz", 1000, 500) is None

    def test_zero_tokens(self):
        cost = calculate_cost("gpt-4o", 0, 0)
        assert cost == 0.0

    def test_prefix_match_versioned_model(self):
        # "gpt-4o" is a prefix of an unknown versioned variant
        cost = calculate_cost("gpt-4o-2099-01-01", 1000, 1000)
        assert cost is not None  # prefix matched to "gpt-4o"

    def test_longest_prefix_wins_for_mini_variants(self):
        # Regression (M1): unknown "gpt-4o-mini-*" versions must price as
        # gpt-4o-mini, not as the shorter (and ~17x pricier) gpt-4o prefix.
        cost = calculate_cost("gpt-4o-mini-2099-01-01", 1000, 1000)
        assert cost == pytest.approx(0.000150 + 0.000600, rel=1e-6)

    def test_longest_prefix_wins_for_o1_mini(self):
        # Regression (M1): "o1-mini-*" must price as o1-mini, not o1.
        cost = calculate_cost("o1-mini-2099", 1000, 1000)
        assert cost == pytest.approx(0.003 + 0.012, rel=1e-6)

    def test_provider_prefix_stripped(self):
        # Regression (L2): LiteLLM/OpenRouter-style ids carry a provider
        # prefix; the bare model name must still match the pricing table.
        cost = calculate_cost("openai/gpt-4o-mini", 1000, 1000)
        assert cost == pytest.approx(0.000150 + 0.000600, rel=1e-6)

    def test_double_provider_prefix_stripped(self):
        cost = calculate_cost("openrouter/openai/gpt-4o-mini", 1000, 1000)
        assert cost == pytest.approx(0.000150 + 0.000600, rel=1e-6)

    def test_provider_prefixed_unknown_model_returns_none(self):
        assert calculate_cost("openai/some-unknown-model-xyz", 1000, 500) is None

    def test_all_known_models_return_float(self):
        for model in PRICING:
            cost = calculate_cost(model, 1000, 500)
            assert isinstance(cost, float), f"Expected float for {model}"
            assert cost > 0

    def test_cost_is_rounded_to_8_places(self):
        # The function rounds to 8 decimal places
        cost = calculate_cost("gpt-4o-mini", 1, 1)
        assert cost is not None
        # Verify it's not an absurdly long float
        assert len(str(cost).split(".")[-1]) <= 10

    def test_input_only_cost(self):
        cost_input_only = calculate_cost("gpt-4o", 1000, 0)
        cost_output_only = calculate_cost("gpt-4o", 0, 1000)
        assert cost_input_only is not None
        assert cost_output_only is not None
        # Output is more expensive for gpt-4o
        assert cost_output_only > cost_input_only


class TestFormatCost:
    def test_tiny_cost(self):
        assert format_cost(0.00001) == "<$0.0001"

    def test_small_cost(self):
        result = format_cost(0.001234)
        assert result == "$0.001234"
        assert result.startswith("$")

    def test_larger_cost(self):
        result = format_cost(0.05)
        assert result == "$0.0500"

    def test_zero(self):
        assert format_cost(0.0) == "<$0.0001"

    def test_exact_threshold(self):
        # 0.0001 is not < 0.0001
        result = format_cost(0.0001)
        assert result != "<$0.0001"
        assert "$" in result


class TestCostInStore:
    """Integration: cost flows from integration output into RunSummary."""

    def test_total_cost_none_when_no_llm_nodes(self):
        from vapviz.store import MemoryStore
        from vapviz.tracer import Tracer

        store = MemoryStore()
        tracer = Tracer(store=store)
        with tracer.trace("no-llm") as run:
            with run.step("step", kind="step"):
                pass

        summary = store.get_run(run.run_id)
        assert summary.total_cost_usd is None

    def test_total_cost_aggregated_from_llm_nodes(self):
        from vapviz.store import MemoryStore, _total_cost
        from vapviz.events import RunGraph, NodeStatus, GraphNode, NodeKind

        graph = RunGraph(run_id="r1", label="test", status=NodeStatus.SUCCESS, started_at=1.0)
        # Simulate two LLM nodes with cost in their data
        graph.nodes.append(GraphNode(
            id="n1", kind=NodeKind.LLM, label="llm/gpt-4o", status=NodeStatus.SUCCESS,
            data={"output": {"cost_usd": 0.01}},
        ))
        graph.nodes.append(GraphNode(
            id="n2", kind=NodeKind.LLM, label="llm/gpt-4o", status=NodeStatus.SUCCESS,
            data={"output": {"cost_usd": 0.005}},
        ))

        total = _total_cost(graph)
        assert total == pytest.approx(0.015, rel=1e-6)

    def test_total_cost_skips_nodes_without_cost(self):
        from vapviz.store import _total_cost
        from vapviz.events import RunGraph, NodeStatus, GraphNode, NodeKind

        graph = RunGraph(run_id="r1", label="test", status=NodeStatus.SUCCESS, started_at=1.0)
        graph.nodes.append(GraphNode(
            id="n1", kind=NodeKind.STEP, label="step", status=NodeStatus.SUCCESS,
            data={"output": {"rows": 10}},  # no cost_usd
        ))
        graph.nodes.append(GraphNode(
            id="n2", kind=NodeKind.LLM, label="llm/unknown", status=NodeStatus.SUCCESS,
            data={"output": {}},  # no cost_usd (unknown model)
        ))

        assert _total_cost(graph) is None


class TestCostInIntegrations:
    """Integration: patch_openai/_anthropic add cost_usd to output."""

    def test_openai_output_includes_cost_for_known_model(self):
        from unittest.mock import MagicMock
        from vapviz.integrations.openai_sdk import _extract_output

        result = MagicMock()
        result.choices = [MagicMock()]
        result.choices[0].message.content = "Hello"
        result.choices[0].finish_reason = "stop"
        result.usage.prompt_tokens = 100
        result.usage.completion_tokens = 50

        out = _extract_output(result, model="gpt-4o-mini")
        assert "cost_usd" in out
        assert out["cost_usd"] > 0

    def test_openai_output_no_cost_for_unknown_model(self):
        from unittest.mock import MagicMock
        from vapviz.integrations.openai_sdk import _extract_output

        result = MagicMock()
        result.choices = [MagicMock()]
        result.choices[0].message.content = "Hi"
        result.choices[0].finish_reason = "stop"
        result.usage.prompt_tokens = 100
        result.usage.completion_tokens = 50

        out = _extract_output(result, model="my-private-model")
        assert "cost_usd" not in out

    def test_anthropic_output_includes_cost(self):
        from unittest.mock import MagicMock
        from vapviz.integrations.anthropic_sdk import _extract_output

        result = MagicMock()
        result.content = [MagicMock(text="Hi")]
        result.stop_reason = "end_turn"
        result.usage.input_tokens = 200
        result.usage.output_tokens = 100

        out = _extract_output(result, model="claude-3-haiku-20240307")
        assert "cost_usd" in out
        assert out["cost_usd"] > 0
