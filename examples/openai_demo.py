"""
OpenAI SDK demo — traces chat.completions.create calls automatically.

Every client.chat.completions.create() call becomes a purple LLM node
showing model name, token usage, USD cost, and response text.

Requirements:
    pip install "vap[openai]"
    export OPENAI_API_KEY=sk-...

Run (server + agent in one process):
    python examples/openai_demo.py

Or start the server first:
    vap serve --db vap.db
    python examples/openai_demo.py --agent-only

Open http://localhost:8001 (or http://localhost:5173 for Vite dev server).
"""
import os
import sys
import time
import threading

import vap


# ── Agent logic ────────────────────────────────────────────────────────────────

def run_agent() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit(
            "OPENAI_API_KEY is not set.\n"
            "Export it with: export OPENAI_API_KEY=sk-..."
        )

    try:
        import openai
    except ImportError:
        raise SystemExit('OpenAI SDK not installed. Run: pip install "vap[openai]"')

    client = openai.OpenAI()
    vap.patch_openai(client)   # auto-traces every chat.completions.create call

    model = "gpt-4o-mini"     # fast, cheap, great for demos

    with vap.trace("OpenAI Research Agent") as run:

        # Step 1: planning (no LLM — just bookkeeping)
        with run.step("plan", kind="step") as step:
            step.set_input({"goal": "Summarise recent advances in AI agents"})
            time.sleep(0.02)
            topics = ["agent architectures", "tool use in LLMs", "multi-agent systems"]
            step.set_output({"topics": topics})

        # Step 2–4: one LLM call per topic, automatically traced
        summaries: list[str] = []
        for topic in topics:
            with run.step(f"research/{topic.replace(' ', '_')}", kind="step") as step:
                step.set_input({"topic": topic})
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=120,
                    messages=[
                        {"role": "system", "content": "You are a concise technical writer."},
                        {"role": "user", "content": f"Write 2 sentences about: {topic}"},
                    ],
                )
                text = response.choices[0].message.content or ""
                summaries.append(text)
                step.set_output({"text": text[:120]})

        # Step 5: synthesise with one final LLM call
        with run.step("synthesize", kind="step") as step:
            combined = "\n".join(f"- {s}" for s in summaries)
            step.set_input({"source_count": len(summaries)})
            response = client.chat.completions.create(
                model=model,
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": f"Distil these points into one sentence:\n{combined}",
                }],
            )
            conclusion = response.choices[0].message.content or ""
            step.set_output({"conclusion": conclusion})

    print(f"\n[vap] Run complete  run_id={run.run_id}")
    print("[vap] View at http://localhost:8001")
    print(f"\n── Conclusion ──────────────────────────")
    print(conclusion)


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
