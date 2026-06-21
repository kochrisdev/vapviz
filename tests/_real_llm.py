"""
Shared helpers for the real-LLM integration tests (tests/test_*_integration.py).

These run actual agents for each framework against OpenRouter (OpenAI-compatible)
and assert on the graph vapviz records, using a real SqliteStore so persistence-
only bugs surface. Everything is gated: the test modules skip cleanly when
OPENROUTER_API_KEY is absent or the framework isn't installed.

Not a test module (leading underscore) — pytest won't collect it.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    p = REPO / "scratch" / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL = os.environ.get("VAP_MODEL", "openai/gpt-4o-mini")
BASE_URL = "https://openrouter.ai/api/v1"


def openrouter_client(async_: bool = False):
    """An OpenAI SDK client pointed at OpenRouter."""
    import openai
    cls = openai.AsyncOpenAI if async_ else openai.OpenAI
    return cls(base_url=BASE_URL, api_key=KEY)


def node_cost(node) -> float | None:
    out = (node.data or {}).get("output", {})
    return out.get("cost_usd") if isinstance(out, dict) else None


def summary(store, run_id: str):
    return next(r for r in store.list_runs() if r.run_id == run_id)


def llm_cost_sum(graph) -> float:
    """Sum cost_usd over LLM-kind nodes only (the correct run total)."""
    total = 0.0
    for n in graph.nodes:
        if n.kind.value == "llm":
            c = node_cost(n)
            if c:
                total += c
    return total
