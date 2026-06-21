"""
Pydantic AI demo — traces an agent run with VapPydanticAI.

VapPydanticAI wraps ``Agent.run`` / ``Agent.run_sync`` so every model request
(with token usage and cost) and every tool call (with its arguments and result)
appears as a correctly nested node in the vapviz graph — no changes to your agent
code.

This demo uses Pydantic AI's built-in ``TestModel`` so it runs with **no API key
and no network** — perfect for trying vapviz out. To use a real model instead, set
an API key and pass e.g. ``"openai:gpt-4o-mini"`` as the agent's model.

Requirements:
    pip install "vapviz[pydantic-ai]"

Run (server + agent in one process):
    python examples/pydantic_ai_demo.py

Or start the server first:
    vapviz serve --db vapviz.db
    python examples/pydantic_ai_demo.py --agent-only

Open http://localhost:8001 to see the graph.

What you'll see
---------------
Two traces:

1. "Weather agent" (auto mode) — a fresh vapviz run per agent.run_sync():
   - agent root
       ├─ llm/test           (first model request → calls tools)
       │     ├─ get_weather  (tool)
       │     └─ get_forecast (tool)
       └─ llm/test           (final model response)

2. "Trip planner" (manual mode) — the agent embedded in a larger vapviz pipeline:
   - load_preferences   (regular vapviz step)
   - agent/trip-planner
       └─ llm/test → temperature (tool)
   - format_itinerary   (regular vapviz step)
"""
import sys
import threading
import time

import vapviz


# ── Tools ────────────────────────────────────────────────────────────────────

def _build_agent(name: str):
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    agent = Agent(TestModel(), name=name, system_prompt="You are a helpful assistant.")

    @agent.tool_plain
    def get_weather(city: str) -> str:
        """Return the current weather for a city."""
        return f"{city}: 21°C, partly cloudy"

    @agent.tool_plain
    def get_forecast(city: str, days: int) -> str:
        """Return a multi-day forecast for a city."""
        return f"{city}: sunny for the next {days} days"

    @agent.tool_plain
    def temperature(city: str) -> int:
        """Return the temperature in Celsius for a city."""
        return 21

    return agent


# ── Demos ──────────────────────────────────────────────────────────────────────

def run_demo_1_auto() -> None:
    """Auto mode — VapPydanticAI() patches once; each run becomes its own vapviz run."""
    agent = _build_agent("weather-agent")
    result = agent.run_sync("What's the weather and 3-day forecast for Paris?")
    print(f"[demo 1] output: {result.output!r}")


def run_demo_2_manual() -> None:
    """Manual mode — the agent run nests inside a larger vapviz.trace() pipeline."""
    agent = _build_agent("trip-planner")

    with vapviz.trace("Trip planner") as run:
        with run.step("load_preferences", kind="step") as step:
            step.set_input({"user": "demo"})
            step.set_output({"prefers": "warm cities"})

        from vapviz.integrations.pydantic_ai import VapPydanticAI

        listener = VapPydanticAI(run)
        result = agent.run_sync("Is Lisbon warm enough for a beach trip?")
        listener.detach()

        with run.step("format_itinerary", kind="step") as step:
            step.set_input({"answer": str(result.output)[:80]})
            step.set_output({"itinerary": "Day 1: beach, Day 2: old town"})

    print(f"[demo 2] output: {result.output!r}")


def _check_deps() -> None:
    try:
        import pydantic_ai  # noqa: F401
    except ImportError:
        raise SystemExit(
            "pydantic-ai is not installed.\n"
            'Run: pip install "vapviz[pydantic-ai]"'
        )


def run_agent() -> None:
    _check_deps()

    from vapviz.integrations.pydantic_ai import VapPydanticAI

    print("\n── Demo 1: Weather agent (auto mode) ──────────────────────────")
    listener = VapPydanticAI()        # auto mode: one vapviz run per agent.run_sync()
    run_demo_1_auto()
    listener.detach()

    print("\n── Demo 2: Trip planner inside a pipeline (manual mode) ───────")
    run_demo_2_manual()

    print("\n[vapviz] Both runs complete. View at http://localhost:8001")


# ── Entry points ───────────────────────────────────────────────────────────────

def main_with_server() -> None:
    import uvicorn

    vapviz.configure(db="vapviz.db")
    server_app = vapviz.create_app()

    t = threading.Thread(
        target=lambda: uvicorn.run(server_app, host="0.0.0.0", port=8001, log_level="warning"),
        daemon=True,
    )
    t.start()
    time.sleep(1.0)

    run_agent()
    input("\nPress Enter to exit…")


def main_agent_only() -> None:
    vapviz.configure(db="vapviz.db")
    run_agent()


if __name__ == "__main__":
    if "--agent-only" in sys.argv:
        main_agent_only()
    else:
        main_with_server()
