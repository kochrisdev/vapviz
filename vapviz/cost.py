"""
Token cost estimation for common LLM models.

Prices are in USD per 1 000 tokens (input, output).
Sources: OpenAI pricing page and Anthropic pricing page (May 2025).

Usage::

    from vapviz.cost import calculate_cost

    cost = calculate_cost("gpt-4o", input_tokens=500, output_tokens=200)
    # -> 0.003250  (USD)
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Pricing table
# (input_usd_per_1k, output_usd_per_1k)
# ---------------------------------------------------------------------------

PRICING: dict[str, tuple[float, float]] = {
    # ── OpenAI ──────────────────────────────────────────────────────────────
    "gpt-4o":                       (0.002_50,  0.010_00),
    "gpt-4o-2024-11-20":            (0.002_50,  0.010_00),
    "gpt-4o-2024-08-06":            (0.002_50,  0.010_00),
    "gpt-4o-mini":                  (0.000_150, 0.000_600),
    "gpt-4o-mini-2024-07-18":       (0.000_150, 0.000_600),
    "gpt-4-turbo":                  (0.010_00,  0.030_00),
    "gpt-4-turbo-2024-04-09":       (0.010_00,  0.030_00),
    "gpt-4":                        (0.030_00,  0.060_00),
    "gpt-4-0613":                   (0.030_00,  0.060_00),
    "gpt-3.5-turbo":                (0.000_500, 0.001_500),
    "gpt-3.5-turbo-0125":           (0.000_500, 0.001_500),
    "o1":                           (0.015_00,  0.060_00),
    "o1-2024-12-17":                (0.015_00,  0.060_00),
    "o1-mini":                      (0.003_00,  0.012_00),
    "o1-mini-2024-09-12":           (0.003_00,  0.012_00),
    "o3-mini":                      (0.001_10,  0.004_40),
    "o3-mini-2025-01-31":           (0.001_10,  0.004_40),
    "o4-mini":                      (0.001_10,  0.004_40),

    # ── Anthropic ────────────────────────────────────────────────────────────
    # Claude 4 family
    "claude-opus-4-5":              (0.015_00,  0.075_00),
    "claude-sonnet-4-5":            (0.003_00,  0.015_00),
    # Claude 3.x family
    "claude-3-5-sonnet-20241022":   (0.003_00,  0.015_00),
    "claude-3-5-sonnet-20240620":   (0.003_00,  0.015_00),
    "claude-3-5-haiku-20241022":    (0.000_800, 0.004_00),
    "claude-3-opus-20240229":       (0.015_00,  0.075_00),
    "claude-3-sonnet-20240229":     (0.003_00,  0.015_00),
    "claude-3-haiku-20240307":      (0.000_250, 0.001_25),
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """
    Return estimated cost in USD for a single LLM call, or ``None`` if the
    model is not in the pricing table.

    Matching is attempted in order:
    1. Exact model name (after stripping any ``provider/`` prefix, e.g.
       ``"openrouter/openai/gpt-4o-mini"`` → ``"gpt-4o-mini"``)
    2. The pricing-table key is a prefix of *model* (e.g. ``"gpt-4o"``
       matches ``"gpt-4o-2024-11-20"``)
    3. *model* is a prefix of the pricing-table key (handles short aliases)
    Among prefix matches the **longest** key wins, so ``"gpt-4o-mini-…"``
    prices as ``gpt-4o-mini``, not ``gpt-4o``.

    Args:
        model:         Model identifier as returned by the API (e.g. ``"gpt-4o"``).
        input_tokens:  Prompt / input token count.
        output_tokens: Completion / output token count.

    Returns:
        Cost in USD as a ``float``, or ``None`` if the model is unknown.
    """
    # LiteLLM / OpenRouter prefix the provider(s) onto the model id; the
    # pricing table keys never contain "/", so price by the bare name.
    model = model.rsplit("/", 1)[-1]

    pricing = PRICING.get(model)

    if pricing is None:
        # Prefix matching — the longest key is the most specific match.
        matches = [k for k in PRICING if model.startswith(k) or k.startswith(model)]
        if matches:
            pricing = PRICING[max(matches, key=len)]

    if pricing is None:
        return None

    input_cost_per_1k, output_cost_per_1k = pricing
    return (input_tokens * input_cost_per_1k / 1_000) + (output_tokens * output_cost_per_1k / 1_000)


def format_cost(cost_usd: float) -> str:
    """
    Format a cost value for display.

    Returns a human-readable string:
    - ``< $0.0001``  → ``"<$0.0001"``
    - ``< $0.01``    → ``"$0.000123"`` (6 decimal places)
    - otherwise      → ``"$0.0123"``   (4 decimal places)
    """
    if cost_usd < 0.0001:
        return "<$0.0001"
    if cost_usd < 0.01:
        return f"${cost_usd:.6f}"
    return f"${cost_usd:.4f}"
