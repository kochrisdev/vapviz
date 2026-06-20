"""
AutoGen (AG2) demo — traces a multi-agent conversation with VapAutoGen.

VapAutoGen wraps ``ConversableAgent`` so a chat shows up as a VaP graph: the chat
as a root, each agent turn as a child node, and any tool/function call nested
under the turn that made it.

This demo uses offline agents (``llm_config=False`` with registered reply
functions), so it runs with **no API key and no network**. To use real LLMs,
give the agents an ``llm_config`` with your provider/key and drop the
``register_reply`` calls.

Requirements:
    pip install "vap[autogen]"

Run (server + chat in one process):
    python examples/autogen_demo.py

Or start the server first:
    vap serve --db vap.db
    python examples/autogen_demo.py --agent-only

Open http://localhost:8001 to see the graph.
"""
import sys
import threading
import time

import vap


def _check_deps() -> None:
    try:
        import autogen  # noqa: F401
    except ImportError:
        raise SystemExit(
            "autogen (ag2) is not installed.\n"
            'Run: pip install "vap[autogen]"'
        )


def run_agent() -> None:
    _check_deps()

    from autogen import ConversableAgent

    from vap.integrations.autogen import VapAutoGen

    # A tiny scripted "researcher → writer" conversation, fully offline.
    researcher = ConversableAgent(
        "researcher", llm_config=False, human_input_mode="NEVER",
        max_consecutive_auto_reply=2,
    )
    writer = ConversableAgent(
        "writer", llm_config=False, human_input_mode="NEVER",
        max_consecutive_auto_reply=2,
    )

    researcher.register_reply(
        [ConversableAgent, None],
        lambda self, messages=None, sender=None, config=None: (
            True, "Findings: solar +40% efficiency; offshore wind doubled; grid storage maturing.",
        ),
    )
    writer.register_reply(
        [ConversableAgent, None],
        lambda self, messages=None, sender=None, config=None: (
            True, "Summary: renewable energy made major strides this year across solar, wind, and storage.",
        ),
    )

    print("\n── Two-agent conversation traced under one VaP run ────────────")
    with vap.trace("Research conversation") as run:
        listener = VapAutoGen(run)
        writer.initiate_chat(
            researcher,
            message="Summarize the top renewable-energy developments.",
            max_turns=2,
        )
        listener.detach()

    print(f"\n[vap] Conversation complete (run_id={run.run_id}). View at http://localhost:8001")


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
