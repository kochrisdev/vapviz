"""
Anthropic SDK demo — traces real Claude API calls through VaP.

Every client.messages.create() call is automatically captured as a purple
LLM node showing model name, token usage, cost, and response text.

Requirements:
    pip install "vap[anthropic]"
    export ANTHROPIC_API_KEY=sk-ant-...

Run (server + agent in one process):
    python examples/anthropic_demo.py

Or start the server first:
    vap serve --db vap.db
    python examples/anthropic_demo.py --agent-only

Open http://localhost:8001 (or http://localhost:5173 for Vite dev server).
"""
import os
import sys
import time
import threading

import vap


# ── Agent logic ────────────────────────────────────────────────────────────────

def run_agent() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set.\n"
            "Export it with: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    try:
        import anthropic
    except ImportError:
        raise SystemExit('Anthropic SDK not installed. Run: pip install "vap[anthropic]"')

    client = anthropic.Anthropic(api_key=api_key)
    vap.patch_anthropic(client)   # auto-traces every client.messages.create call

    model = "claude-3-5-haiku-20241022"   # fast, cheap, great for demos

    with vap.trace("Claude Research Agent") as run:

        # Step 1: use Claude to generate a research plan
        with run.step("plan", kind="step") as step:
            step.set_input({"goal": "Summarise the state of AI in 2024"})

            response = client.messages.create(
                model=model,
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": "List 3 major AI developments in 2024. Be very brief (1 sentence each).",
                }],
            )
            plan_text = response.content[0].text
            step.set_output({"plan": plan_text[:200]})

        # Step 2: expand each point into a short paragraph
        with run.step("expand", kind="step") as step:
            step.set_input({"points": 3})

            response = client.messages.create(
                model=model,
                max_tokens=400,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Based on these AI developments:\n{plan_text}\n\n"
                        "Write one short paragraph (2-3 sentences) about each."
                    ),
                }],
            )
            expanded = response.content[0].text
            step.set_output({"text": expanded[:300]})

        # Step 3: write a final executive summary
        with run.step("write_summary", kind="step") as step:
            step.set_input({"source": "expanded points"})

            response = client.messages.create(
                model=model,
                max_tokens=200,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Based on:\n{expanded}\n\n"
                        "Write a single 2-sentence executive summary for a non-technical audience."
                    ),
                }],
            )
            summary = response.content[0].text
            step.set_output({"summary": summary})

    print(f"\n[vap] Run complete  run_id={run.run_id}")
    print(f"[vap] View at http://localhost:8001")
    print(f"\n── Summary ─────────────────────────────")
    print(summary)


# ── Entry points ───────────────────────────────────────────────────────────────

def main_with_server() -> None:
    import uvicorn

    vap.configure(db="vap.db")
    server_app = vap.create_app()

    t = threading.Thread(
        target=lambda: uvicorn.run(server_app, host="0.0.0.0", port=8001, log_level="warning"),
        daemon=True,
    )
    t.start()
    time.sleep(1.0)

    run_agent()
    input("\nPress Enter to exit…")


def main_agent_only() -> None:
    vap.configure(db="vap.db")
    run_agent()


if __name__ == "__main__":
    if "--agent-only" in sys.argv:
        main_agent_only()
    else:
        main_with_server()
