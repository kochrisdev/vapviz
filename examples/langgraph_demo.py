"""
LangGraph demo — traces a simple ReAct agent with VapCallbackHandler.

Requirements:
    pip install "vap[langchain]" langgraph langchain-openai
    export OPENAI_API_KEY=sk-...

Start the VaP server first (separate terminal):
    vap serve --db vap.db

Then run:
    python examples/langgraph_demo.py

Or run everything in one process:
    python examples/langgraph_demo.py --server
"""
import sys
import time
import threading

import vap


def run_agent() -> None:
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.tools import tool
        from langgraph.prebuilt import create_react_agent
    except ImportError:
        raise SystemExit(
            "LangGraph dependencies not installed.\n"
            'Run: pip install "vap[langchain]" langgraph langchain-openai'
        )

    from vap.integrations.langchain import VapCallbackHandler

    # ------------------------------------------------------------------
    # Define tools
    # ------------------------------------------------------------------

    @tool
    def search_web(query: str) -> str:
        """Search the web for information about a query."""
        time.sleep(0.1)  # simulate latency
        return f"Search results for '{query}': Found 3 relevant articles about AI trends."

    @tool
    def calculate(expression: str) -> str:
        """Evaluate a mathematical expression."""
        try:
            result = eval(expression, {"__builtins__": {}})  # noqa: S307
            return str(result)
        except Exception as e:
            return f"Error: {e}"

    # ------------------------------------------------------------------
    # Build the agent
    # ------------------------------------------------------------------

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    tools = [search_web, calculate]
    agent = create_react_agent(llm, tools)

    # ------------------------------------------------------------------
    # Run with VaP tracing
    # ------------------------------------------------------------------

    with vap.trace("LangGraph ReAct Agent") as run:
        handler = VapCallbackHandler(run)

        result = agent.invoke(
            {"messages": [{"role": "user", "content":
                "Search for recent AI agent news and then calculate 42 * 7."}]},
            config={"callbacks": [handler]},
        )

        # The final message content
        final_msg = result["messages"][-1].content
        print(f"[agent] Response: {final_msg[:200]}")

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
