"""
LangGraph demo — traces a ReAct agent with VapCallbackHandler.

VapCallbackHandler wires into LangChain's callback system, so every
chain invocation, tool call, and LLM round-trip appears as a correctly
nested node in the VaP graph — no manual instrumentation needed.

Requirements:
    pip install "vap[langchain]" langgraph langchain-openai
    export OPENAI_API_KEY=sk-...

Run (server + agent in one process):
    python examples/langgraph_demo.py

Or start the server first:
    vap serve --db vap.db
    python examples/langgraph_demo.py --agent-only

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
        from langchain_openai import ChatOpenAI
        from langchain_core.tools import tool
        # LangChain v1 renamed this to langchain.agents.create_agent;
        # langgraph.prebuilt.create_react_agent is deprecated (removed in
        # LangGraph V2). Prefer the new API, fall back to the old one.
        try:
            from langchain.agents import create_agent as build_agent
        except ImportError:
            from langgraph.prebuilt import create_react_agent as build_agent
    except ImportError:
        raise SystemExit(
            "LangGraph dependencies not installed.\n"
            'Run: pip install "vap[langchain]" langchain langgraph langchain-openai'
        )

    from vap.integrations.langchain import VapCallbackHandler

    # ── Define tools ──────────────────────────────────────────────────────

    @tool
    def search_web(query: str) -> str:
        """Search the web for recent information about a topic."""
        time.sleep(0.1)  # simulate latency
        return (
            f"Search results for '{query}': "
            "Found 3 articles. Key finding: significant progress in 2024."
        )

    @tool
    def calculate(expression: str) -> str:
        """Evaluate a Python arithmetic expression and return the result."""
        try:
            result = eval(expression, {"__builtins__": {}})  # noqa: S307
            return str(result)
        except Exception as exc:
            return f"Error evaluating '{expression}': {exc}"

    @tool
    def summarize_findings(findings: str) -> str:
        """Condense a set of research findings into a one-paragraph summary."""
        time.sleep(0.05)
        return f"Summary: {findings[:120]}... (condensed)"

    # ── Build the ReAct agent ─────────────────────────────────────────────

    llm   = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    tools = [search_web, calculate, summarize_findings]
    agent = build_agent(llm, tools)

    # ── Run with VaP tracing ──────────────────────────────────────────────

    with vap.trace("LangGraph ReAct Agent") as run:
        handler = VapCallbackHandler(run)

        result = agent.invoke(
            {
                "messages": [{
                    "role": "user",
                    "content": (
                        "Search for recent AI agent developments, "
                        "calculate 128 * 37, "
                        "then summarize your findings."
                    ),
                }]
            },
            config={"callbacks": [handler]},
        )

        final_msg = result["messages"][-1].content
        print(f"\n[agent] {final_msg[:300]}")

    print(f"\n[vap] Run complete  run_id={run.run_id}")
    print("[vap] View at http://localhost:8001")


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
