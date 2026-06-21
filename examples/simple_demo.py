"""
Simple demo — runs a fake multi-step research agent with no API key needed.

Starts the vapviz server in a background thread and runs a simulated pipeline
with nested steps, tool calls, and a sub-agent to show off the graph layout.

Run:
    python examples/simple_demo.py

Or start the server separately first and run just the agent:
    vapviz serve --db vapviz.db
    python examples/simple_demo.py --agent-only

Open http://localhost:8001 to see the live graph (UI built) or
     http://localhost:5173 if running the Vite dev server separately.
"""
import sys
import time
import threading
import uvicorn

import vapviz


# ── Agent logic ────────────────────────────────────────────────────────────────

def run_agent() -> None:
    with vapviz.trace("Research Agent") as run:

        # Tool: search the web
        with run.step("search_web", kind="tool") as step:
            step.set_input({"query": "climate change solutions 2024"})
            time.sleep(0.2)
            results = [
                {"title": "Solar energy breakthrough", "url": "https://example.com/solar"},
                {"title": "Carbon capture update",      "url": "https://example.com/carbon"},
            ]
            step.set_output({"results": results, "count": len(results)})

        # Step: summarise each result
        with run.step("summarize", kind="step") as step:
            step.set_input({"articles": len(results)})
            time.sleep(0.15)
            step.set_output({"summary": "Key findings: solar and carbon capture leading the way."})

        # Step: synthesise a report (contains nested sub-steps)
        with run.step("synthesize_report", kind="step") as report_step:
            report_step.set_input({"sources": len(results)})

            with run.step("format_citations", kind="tool") as step:
                step.set_input({"items": results})
                time.sleep(0.05)
                step.set_output({"citations": "[1] Solar... [2] Carbon..."})

            with run.step("write_conclusion", kind="step") as step:
                step.set_input({"draft": "..."})
                time.sleep(0.1)
                step.set_output({"text": "Renewable energy shows strong commercial promise."})

            with run.step("quality_check", kind="tool") as step:
                step.set_input({"report_length": 500})
                time.sleep(0.05)
                step.set_output({"passed": True, "score": 0.92})

            report_step.set_output({"report": "Final report assembled.", "word_count": 500})

    print(f"\n[vapviz] Run complete  run_id={run.run_id}")
    print(f"[vapviz] View at http://localhost:8001  (or http://localhost:5173 for Vite dev server)")


# ── Entry points ───────────────────────────────────────────────────────────────

def main_with_server() -> None:
    """Start the vapviz server in-process, then run the agent."""
    vapviz.configure(db="vapviz.db")
    server_app = vapviz.create_app()

    t = threading.Thread(
        target=lambda: uvicorn.run(server_app, host="0.0.0.0", port=8001, log_level="warning"),
        daemon=True,
    )
    t.start()
    time.sleep(1.0)   # wait for uvicorn to bind

    run_agent()
    input("\nPress Enter to exit…")


def main_agent_only() -> None:
    """Just run the agent; assumes `vapviz serve` is already running."""
    vapviz.configure(db="vapviz.db")
    run_agent()


if __name__ == "__main__":
    if "--agent-only" in sys.argv:
        main_agent_only()
    else:
        main_with_server()
