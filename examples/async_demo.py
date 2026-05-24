"""
Async demo — shows vap.atrace() and run.astep() with asyncio.

Start the VaP server first (separate terminal):
    vap serve --db vap.db

Then run:
    python examples/async_demo.py

Or run everything in one process (server + agent):
    python examples/async_demo.py --server
"""
import asyncio
import sys
import time

import vap


async def fetch_article(url: str, run: vap.Tracer) -> str:
    """Simulates an async HTTP call."""
    await asyncio.sleep(0.1)
    return f"Article content from {url}"


async def run_agent() -> None:
    async with vap.atrace("Async Research Agent") as run:

        # Concurrent tool calls using asyncio.gather
        async with run.astep("plan", kind="step") as step:
            step.set_input({"goal": "Research async AI frameworks"})
            await asyncio.sleep(0.05)
            step.set_output({"urls": ["https://example.com/a", "https://example.com/b"]})

        # Fan-out: two fetch tasks running concurrently
        async with run.astep("fetch_articles", kind="step") as parent:
            parent.set_input({"urls": 2})

            results = await asyncio.gather(
                _fetch_with_step(run, "https://example.com/a"),
                _fetch_with_step(run, "https://example.com/b"),
            )
            parent.set_output({"articles": len(results)})

        # Synthesize
        async with run.astep("synthesize", kind="step") as step:
            step.set_input({"articles": 2})
            await asyncio.sleep(0.08)
            step.set_output({"summary": "Async frameworks show improved throughput."})

    print(f"[vap] Run complete -> run_id={run.run_id}")


async def _fetch_with_step(run, url: str) -> str:
    async with run.astep(f"fetch:{url.split('/')[-1]}", kind="tool") as step:
        step.set_input({"url": url})
        await asyncio.sleep(0.1)
        content = f"Content from {url}"
        step.set_output({"length": len(content)})
        return content


async def main_with_server() -> None:
    """Start server + run agent in a single process."""
    import threading
    import uvicorn

    vap.configure(db="vap.db")
    server_app = vap.create_app()

    def run_server():
        uvicorn.run(server_app, host="0.0.0.0", port=8001, log_level="warning")

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    await asyncio.sleep(1.5)  # let uvicorn bind

    await run_agent()
    print("[vap] Open http://localhost:5173 to see the trace.")
    await asyncio.sleep(999_999)  # keep server alive


async def main_agent_only() -> None:
    """Just run the agent; assumes server is already running."""
    vap.configure(db="vap.db")
    await run_agent()


if __name__ == "__main__":
    if "--server" in sys.argv:
        asyncio.run(main_with_server())
    else:
        asyncio.run(main_agent_only())
