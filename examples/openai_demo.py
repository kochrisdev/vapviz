"""
OpenAI SDK demo — traces chat.completions.create calls automatically.

Requirements:
    pip install "vap[openai]"
    export OPENAI_API_KEY=sk-...

Start the VaP server first (separate terminal):
    vap serve --db vap.db

Then run:
    python examples/openai_demo.py

Or run everything in one process (server + agent):
    python examples/openai_demo.py --server
"""
import sys
import time
import threading

import vap
from vap.integrations.openai_sdk import patch_openai


def run_agent() -> None:
    try:
        import openai
    except ImportError:
        raise SystemExit('OpenAI SDK not installed. Run: pip install "vap[openai]"')

    client = openai.OpenAI()
    patch_openai(client)

    with vap.trace("OpenAI Research Agent") as run:
        # Step 1: plan
        with run.step("plan", kind="step") as step:
            step.set_input({"goal": "Summarize recent advances in AI agents"})
            time.sleep(0.05)
            step.set_output({"queries": ["AI agent architectures", "tool use in LLMs"]})

        # Step 2: first LLM call — automatically traced as an llm node
        with run.step("research_architectures", kind="step") as step:
            step.set_input({"query": "AI agent architectures"})
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=200,
                messages=[
                    {"role": "system", "content": "You are a concise research assistant."},
                    {"role": "user", "content": "Briefly summarize modern AI agent architectures."},
                ],
            )
            summary = response.choices[0].message.content
            step.set_output({"summary": summary[:120] + "..."})

        # Step 3: second LLM call
        with run.step("research_tool_use", kind="step") as step:
            step.set_input({"query": "tool use in LLMs"})
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=200,
                messages=[
                    {"role": "system", "content": "You are a concise research assistant."},
                    {"role": "user", "content": "Briefly explain how LLMs use external tools."},
                ],
            )
            summary = response.choices[0].message.content
            step.set_output({"summary": summary[:120] + "..."})

        # Step 4: synthesize with a third LLM call
        with run.step("synthesize", kind="step") as step:
            step.set_input({"sources": 2})
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=150,
                messages=[
                    {"role": "user", "content": "Combine these ideas into one sentence: "
                     "modern AI agents use architectures like ReAct and tool calling."},
                ],
            )
            step.set_output({"conclusion": response.choices[0].message.content})

    print(f"[vap] Run complete -> run_id={run.run_id}")
    print("[vap] Open http://localhost:5173 to see the trace.")


def main_with_server() -> None:
    import uvicorn

    vap.configure(db="vap.db")
    server_app = vap.create_app()

    def run_server():
        uvicorn.run(server_app, host="0.0.0.0", port=8001, log_level="warning")

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(1.5)

    run_agent()
    input("Press Enter to exit...")


def main_agent_only() -> None:
    vap.configure(db="vap.db")
    run_agent()


if __name__ == "__main__":
    if "--server" in sys.argv:
        main_with_server()
    else:
        main_agent_only()
