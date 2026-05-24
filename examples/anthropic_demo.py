"""
Anthropic SDK demo — traces real Claude API calls through VaP.

Requires ANTHROPIC_API_KEY in your environment.

Start the server first:
    uvicorn vap.server:app --reload

Then run:
    python examples/anthropic_demo.py
"""

import os
import threading
import time
import uvicorn
import anthropic

import vap


def run_agent():
    time.sleep(0.5)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    vap.patch_anthropic(client)  # auto-traces all client.messages.create calls

    with vap.trace("Claude Research Agent") as run:
        with run.step("plan", kind="step") as step:
            step.set_input({"goal": "Summarize the state of AI in 2024"})

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{"role": "user", "content": "List 3 major AI developments in 2024. Be brief."}],
            )
            plan_text = response.content[0].text
            step.set_output({"plan": plan_text})

        with run.step("write_summary", kind="step") as step:
            step.set_input({"plan": plan_text})

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[
                    {"role": "user", "content": f"Based on these points:\n{plan_text}\n\nWrite a 2-paragraph summary."},
                ],
            )
            summary = response.content[0].text
            step.set_output({"summary": summary})

    print(f"\nRun complete. View at http://localhost:5173 → run id: {run.run_id}")
    print("\nSummary:\n", summary)


if __name__ == "__main__":
    server = threading.Thread(
        target=lambda: uvicorn.run(vap.app, host="0.0.0.0", port=8000, log_level="warning"),
        daemon=True,
    )
    server.start()
    run_agent()
    input("\nPress Enter to exit…")
