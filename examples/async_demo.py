"""
Async demo — shows vap.atrace() and run.astep() with asyncio.

Demonstrates concurrent fan-out tool calls using asyncio.gather — each
parallel task automatically inherits the correct parent context via
Python's ContextVar.

Run (server + agent in one process):
    python examples/async_demo.py

Or start the server first and run just the agent:
    vap serve --db vap.db
    python examples/async_demo.py --agent-only

Open http://localhost:8001 (or http://localhost:5173 for Vite dev server).
"""
import asyncio
import sys
import time
import threading

import vap


# ── Agent logic ────────────────────────────────────────────────────────────────

async def _fetch_url(run: vap.RunContext, url: str) -> str:
    """Simulate an async HTTP fetch as a traced tool call."""
    async with run.astep(f"fetch/{url.split('/')[-1]}", kind="tool") as step:
        step.set_input({"url": url})
        await asyncio.sleep(0.12)          # simulate network latency
        content = f"Content fetched from {url} ({len(url) * 10} bytes)"
        step.set_output({"bytes": len(url) * 10, "ok": True})
        return content


async def run_agent() -> None:
    async with vap.atrace("Async Research Agent") as run:

        # Phase 1: plan
        async with run.astep("plan", kind="step") as step:
            step.set_input({"goal": "Research async AI frameworks"})
            await asyncio.sleep(0.05)
            urls = [
                "https://example.com/react-agents",
                "https://example.com/async-llm-patterns",
                "https://example.com/concurrent-tool-use",
            ]
            step.set_output({"urls": urls})

        # Phase 2: concurrent fetch (all three start at the same time)
        async with run.astep("fetch_articles", kind="step") as parent:
            parent.set_input({"url_count": len(urls)})
            articles = await asyncio.gather(*[_fetch_url(run, u) for u in urls])
            parent.set_output({"fetched": len(articles)})

        # Phase 3: analyse each article sequentially
        analyses = []
        async with run.astep("analyse", kind="step") as parent:
            parent.set_input({"articles": len(articles)})
            for i, article in enumerate(articles, 1):
                async with run.astep(f"analyse_article_{i}", kind="step") as step:
                    step.set_input({"length": len(article)})
                    await asyncio.sleep(0.06)
                    analysis = f"Analysis of article {i}: positive findings."
                    step.set_output({"result": analysis, "sentiment": "positive"})
                    analyses.append(analysis)
            parent.set_output({"analyses": len(analyses)})

        # Phase 4: synthesise
        async with run.astep("synthesize", kind="step") as step:
            step.set_input({"source_count": len(analyses)})
            await asyncio.sleep(0.08)
            step.set_output({
                "conclusion": "Async AI frameworks show improved throughput and lower latency.",
                "confidence": 0.87,
            })

    print(f"\n[vap] Run complete  run_id={run.run_id}")
    print("[vap] View at http://localhost:8001")


# ── Entry points ───────────────────────────────────────────────────────────────

async def main_with_server() -> None:
    import uvicorn

    vap.configure(db="vap.db")
    server_app = vap.create_app()

    t = threading.Thread(
        target=lambda: uvicorn.run(server_app, host="0.0.0.0", port=8001, log_level="warning"),
        daemon=True,
    )
    t.start()
    await asyncio.sleep(1.0)

    await run_agent()
    print("[vap] Press Ctrl-C to stop.")
    await asyncio.sleep(999_999)


async def main_agent_only() -> None:
    vap.configure(db="vap.db")
    await run_agent()


if __name__ == "__main__":
    if "--agent-only" in sys.argv:
        asyncio.run(main_agent_only())
    else:
        asyncio.run(main_with_server())
