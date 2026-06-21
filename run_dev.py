"""
Dev entry point: starts the vapviz server AND runs a demo agent in one process.
The server keeps running until you kill this script (Ctrl+C).

Usage:
    python run_dev.py
"""

import threading
import time
import uvicorn

import vapviz


def demo_agent() -> None:
    time.sleep(1.2)  # let uvicorn finish binding

    print("\n[vapviz] Running demo agent…")
    with vapviz.trace("Research Agent Demo") as run:
        with run.step("search_web", kind="tool") as step:
            step.set_input({"query": "renewable energy 2024"})
            time.sleep(0.25)
            step.set_output({"results": ["Solar breakthrough", "Wind expansion", "Grid storage"], "count": 3})

        with run.step("summarize_results", kind="step") as parent:
            parent.set_input({"results_count": 3})

            with run.step("fetch_article_1", kind="tool") as step:
                step.set_input({"url": "https://example.com/solar"})
                time.sleep(0.1)
                step.set_output({"text": "Solar panels hit 40% efficiency…"})

            with run.step("fetch_article_2", kind="tool") as step:
                step.set_input({"url": "https://example.com/wind"})
                time.sleep(0.1)
                step.set_output({"text": "Offshore wind capacity doubled…"})

            with run.step("write_summary", kind="step") as step:
                step.set_input({"articles": 2})
                time.sleep(0.15)
                step.set_output({"summary": "Renewable energy made major strides in 2024."})

            parent.set_output({"summary_ready": True})

        with run.step("format_report", kind="step") as step:
            step.set_input({"summary": "Renewable energy…"})
            time.sleep(0.08)
            step.set_output({"report": "Final report: 3 paragraphs, 450 words."})

    print(f"[vapviz] Demo run complete  ->  run_id={run.run_id}")
    print("[vapviz] Open http://localhost:5173 and select the run in the sidebar.\n")


if __name__ == "__main__":
    t = threading.Thread(target=demo_agent, daemon=True)
    t.start()

    print("[vapviz] Server starting on http://localhost:8001 …")
    uvicorn.run(vapviz.app, host="0.0.0.0", port=8001, log_level="warning")
