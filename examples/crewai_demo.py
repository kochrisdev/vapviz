"""
CrewAI demo — traces a multi-agent crew with VapCrewAIListener.

VapCrewAIListener hooks into CrewAI's native event bus, so every Task,
Agent execution, Tool call, and LLM round-trip appears as a correctly
nested node in the vapviz graph — no manual instrumentation needed.

Requirements:
    pip install "vapviz[crewai]"
    export OPENAI_API_KEY=sk-...

    # or use any LiteLLM-compatible model, e.g. Anthropic:
    pip install crewai anthropic
    export ANTHROPIC_API_KEY=sk-ant-...

Run (server + crew in one process):
    python examples/crewai_demo.py

Or start the server first:
    vapviz serve --db vapviz.db
    python examples/crewai_demo.py --agent-only

Open http://localhost:8001 to see the graph.

What you'll see
---------------
Two separate traces:

1. "Research Crew" — sequential crew (researcher → writer):
   - task/research  →  agent/Senior Researcher
       └─ llm/gpt-4o-mini  (research LLM calls)
   - task/write     →  agent/Content Writer
       └─ llm/gpt-4o-mini  (writing LLM calls)

2. "Mixed Pipeline" — CrewAI run embedded inside a larger vapviz trace:
   - pre_process    (regular vapviz step)
   - crew/Pipeline Crew
       └─ task/summarise  →  agent/Summariser
              └─ llm/gpt-4o-mini
   - post_process   (regular vapviz step)
"""
import os
import sys
import time
import threading

import vapviz


# ── Agent logic ────────────────────────────────────────────────────────────────

def _check_deps() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is not set.\n"
            "Export it with: export OPENAI_API_KEY=sk-..."
        )
    try:
        import crewai  # noqa: F401
    except ImportError:
        raise SystemExit(
            "CrewAI is not installed.\n"
            'Run: pip install "vapviz[crewai]"'
        )


def run_demo_1_sequential_crew() -> None:
    """
    Demo 1 — Auto mode.

    VapCrewAIListener is registered once at module level; each
    crew.kickoff() automatically creates its own vapviz run.
    """
    from crewai import Agent, Crew, Process, Task

    researcher = Agent(
        role="Senior Researcher",
        goal="Provide a concise, accurate summary of the given topic.",
        backstory=(
            "You are a meticulous researcher who distils complex information "
            "into clear, factual bullet points."
        ),
        verbose=False,
    )

    writer = Agent(
        role="Content Writer",
        goal="Turn research findings into a polished one-paragraph summary.",
        backstory=(
            "You are an expert technical writer who crafts clear, engaging "
            "summaries from raw research notes."
        ),
        verbose=False,
    )

    research_task = Task(
        description=(
            "Research '{topic}' and list the three most important recent "
            "developments in exactly three bullet points."
        ),
        expected_output="Three bullet points, each under 30 words.",
        agent=researcher,
    )

    write_task = Task(
        description=(
            "Using the research findings, write a single paragraph (max 80 words) "
            "summarising '{topic}' for a technical audience."
        ),
        expected_output="One paragraph, max 80 words.",
        agent=writer,
        context=[research_task],
    )

    crew = Crew(
        agents=[researcher, writer],
        tasks=[research_task, write_task],
        process=Process.sequential,
        verbose=False,
    )

    print("[demo 1] Running sequential crew…")
    result = crew.kickoff(inputs={"topic": "AI agent frameworks"})
    print(f"\n[demo 1] Result:\n{result.raw[:400]}")


def run_demo_2_manual_mode() -> None:
    """
    Demo 2 — Manual mode.

    The crew is a sub-section of a larger vapviz.trace() run, with regular
    pre/post-processing steps on either side.
    """
    from crewai import Agent, Crew, Process, Task
    from vapviz.integrations.crewai_listener import VapCrewAIListener

    summariser = Agent(
        role="Summariser",
        goal="Produce a one-sentence summary of the provided text.",
        backstory="You are an expert at boiling information down to its essence.",
        verbose=False,
    )

    summarise_task = Task(
        description=(
            "Summarise the following in one sentence (max 25 words):\n'{text}'"
        ),
        expected_output="One sentence, under 25 words.",
        agent=summariser,
    )

    crew = Crew(
        agents=[summariser],
        tasks=[summarise_task],
        process=Process.sequential,
        verbose=False,
    )

    with vapviz.trace("Mixed Pipeline") as run:

        # Pre-processing step (plain vapviz, no CrewAI)
        with run.step("pre_process", kind="step") as step:
            step.set_input({"source": "database", "rows": 500})
            time.sleep(0.05)
            text = (
                "Large language models have transformed natural language processing "
                "by enabling zero-shot and few-shot learning across diverse tasks."
            )
            step.set_output({"text": text, "chars": len(text)})

        # CrewAI phase — attach listener to the existing run
        listener = VapCrewAIListener(run=run)
        print("[demo 2] Running crew inside existing trace…")
        result = crew.kickoff(inputs={"text": text})

        # Post-processing step
        with run.step("post_process", kind="step") as step:
            step.set_input({"summary": result.raw})
            time.sleep(0.03)
            step.set_output({"status": "stored", "length": len(result.raw)})

    print(f"\n[demo 2] Summary: {result.raw}")


def run_agent() -> None:
    _check_deps()

    from vapviz.integrations.crewai_listener import VapCrewAIListener

    # Register the listener in auto mode once — it will auto-trace
    # every crew.kickoff() called from this point on.
    VapCrewAIListener()

    print("\n── Demo 1: Sequential crew (auto mode) ────────────────────────")
    run_demo_1_sequential_crew()

    print("\n── Demo 2: Crew inside a larger pipeline (manual mode) ─────────")
    run_demo_2_manual_mode()

    print("\n[vapviz] Both runs complete. View at http://localhost:8001")


# ── Entry points ───────────────────────────────────────────────────────────────

def main_with_server() -> None:
    import uvicorn

    # Order matters: configure(db=...) first, THEN create_app() — the app
    # resolves the default store when built. (Don't reuse the prebuilt
    # vapviz.app here; it was constructed at import with the in-memory store.)
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
