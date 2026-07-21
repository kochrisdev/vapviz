"""
Message injection demo — send a message into a live agent. No API key needed.

This is Layer 2 of vapviz's agent control. Layer 1 (see examples/control_demo.py) lets you
Pause / Resume / Stop a running agent from the outside. Layer 2 lets you talk to it: the agent
asks a question with vapviz.take_input() and genuinely waits — mid-Python-function — until a
message arrives, either from the UI's control bar or a POST to /runs/{id}/input. It also
demonstrates vapviz.checkpoint(): a manual control checkpoint for a loop that has no
per-iteration run.step() of its own.

To keep this runnable end-to-end with no human required, a background thread plays the part of
"the person answering" — it waits a couple of seconds (so you can watch the run genuinely sit in
"waiting for your input" first) and then sends a real message over HTTP, the same request the
UI's control bar makes. Want to answer it yourself instead?

  1. Delete/comment out the `send_message_soon(...)` call in run_agent() below.
  2. Run this script.
  3. Open http://localhost:8001, select the run, open the Theater tab, and type your own
     message into the Agent control bar — or run the printed curl command from a terminal.

Run:
    python examples/input_demo.py
"""
import json
import threading
import time
import urllib.request

import uvicorn

import vapviz


SERVER = "http://localhost:8001"


def post_message(run_id: str, message: str) -> None:
    """POST /runs/{id}/input — the same request the UI's control bar sends."""
    body = json.dumps({"message": message}).encode()
    req = urllib.request.Request(
        f"{SERVER}/runs/{run_id}/input",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5)


def send_message_soon(run_id: str, message: str, delay: float = 2.0) -> None:
    """Stand in for a human: wait a bit, then actually send the message over HTTP —
    so vapviz.take_input() below has something real to receive."""

    def _worker() -> None:
        time.sleep(delay)
        print(f"[human] sending: {message!r}")
        post_message(run_id, message)

    threading.Thread(target=_worker, daemon=True).start()


def run_agent() -> None:
    with vapviz.trace("Message Demo Agent", app_id="input-demo") as run:
        print(f"\n[vapviz] Run started  run_id={run.run_id}")
        print("[vapviz] Watch it live at http://localhost:8001 (Theater tab)")
        print(f"    curl -X POST {SERVER}/runs/{run.run_id}/input \\")
        print("         -H 'Content-Type: application/json' -d '{\"message\": \"hello!\"}'\n")

        with run.step("draft", kind="step") as step:
            print("[agent] Drafting a first pass…")
            time.sleep(0.3)
            step.set_output({"draft": "Here is a first draft."})

        # A background "human" sends a message in a couple of seconds, so this demo
        # finishes on its own. In real use, this is wherever a person actually types
        # into the UI — delete this line to try it fully live instead.
        send_message_soon(run.run_id, "Make it shorter and friendlier.")

        with run.step("await_feedback", kind="step") as step:
            print("[agent] Asking for feedback via vapviz.take_input() — and genuinely waiting…")
            feedback = vapviz.take_input()          # <- blocks here until a message arrives
            print(f"[agent] Got feedback: {feedback!r}")
            step.set_output({"feedback": feedback})

        with run.step("revise", kind="step") as step:
            print("[agent] Revising with that feedback…")
            time.sleep(0.2)
            step.set_output({"final": f"(revised per: {feedback})"})

        # --- vapviz.checkpoint(): a loop with no per-iteration step ---------------
        with run.step("batch_cleanup", kind="step") as step:
            print("[agent] Running a step-less loop guarded by vapviz.checkpoint()…")
            for i in range(5):
                vapviz.checkpoint()      # obeys Pause/Stop here too, even with no run.step()
                time.sleep(0.1)
            step.set_output({"items_processed": 5})

        print("\n[vapviz] Run finished.")


def main() -> None:
    server_app = vapviz.create_app()   # in-memory store — nothing left on disk

    t = threading.Thread(
        target=lambda: uvicorn.run(server_app, host="0.0.0.0", port=8001, log_level="warning"),
        daemon=True,
    )
    t.start()
    time.sleep(1.0)   # wait for uvicorn to bind

    run_agent()
    input("\nPress Enter to exit…")


if __name__ == "__main__":
    main()
