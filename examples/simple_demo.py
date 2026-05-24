"""
Simple demo — runs a fake multi-step agent and streams it to the VaP server.

Start the server first:
    uvicorn vap.server:app --reload

Then run this script:
    python examples/simple_demo.py
"""

import time
import threading
import uvicorn

import vap


def fake_agent():
    """Simulates a research agent with tool calls and sub-steps."""
    time.sleep(0.5)  # let server boot

    with vap.trace("Research Agent") as run:
        with run.step("search_web", kind="tool") as step:
            step.set_input({"query": "climate change solutions 2024"})
            time.sleep(0.2)
            results = [
                {"title": "Solar energy breakthrough", "url": "..."},
                {"title": "Carbon capture update", "url": "..."},
            ]
            step.set_output({"results": results, "count": len(results)})

        with run.step("summarize", kind="step") as step:
            step.set_input({"text": "Long article text..."})
            time.sleep(0.15)
            step.set_output({"summary": "Key findings: solar and carbon capture leading."})

        with run.step("synthesize_report", kind="step") as parent_step:
            parent_step.set_input({"sources": 2})

            with run.step("format_citations", kind="tool") as step:
                step.set_input({"items": results})
                time.sleep(0.05)
                step.set_output({"citations": "[1] Solar... [2] Carbon..."})

            with run.step("write_conclusion", kind="step") as step:
                step.set_input({"draft": "..."})
                time.sleep(0.1)
                step.set_output({"text": "In conclusion, renewable energy shows promise."})

            parent_step.set_output({"report": "Final report assembled."})

    print(f"Run complete. View at http://localhost:5173 → run id: {run.run_id}")


if __name__ == "__main__":
    server = threading.Thread(
        target=lambda: uvicorn.run(vap.app, host="0.0.0.0", port=8000, log_level="warning"),
        daemon=True,
    )
    server.start()
    fake_agent()
    input("Press Enter to exit…")
