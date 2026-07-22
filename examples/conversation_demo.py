"""
Two-way conversation demo — the agent talks *back*. No API key needed.

This is Layer 2b of vapviz's agent control. Layer 2 (see examples/input_demo.py) let you send a
message *into* a running agent. Layer 2b lets the agent hold a real back-and-forth with you:

  * vapviz.ask("Which region?")  -> posts a question you SEE, then waits for your reply
  * vapviz.say("Got it — …")     -> posts a statement you see, without waiting

Open the run in the Theater tab and you'll see a chat panel docked beside the office scene, with
the agent's questions/statements and your replies as bubbles.

To keep this runnable end-to-end with no human required, a background thread plays "the person
answering" — it waits for the agent to actually ask (polling GET /runs/{id}/control until
`waiting_for_input` is true, and reading back the `question` the agent posted), then sends a real
answer over HTTP, the same request the UI's chat panel makes. Want to answer it yourself?

  1. Delete/comment out the `answer_when_asked(...)` call in run_agent() below.
  2. Run this script, open http://localhost:8001, select the run, open the Theater tab, and type
     your answer into the chat panel — or POST it to /runs/{id}/input yourself.

Run:
    python examples/conversation_demo.py
"""
import json
import threading
import time
import urllib.request

import uvicorn

import vapviz


SERVER = "http://localhost:8001"


def _get_control(run_id: str) -> dict:
    with urllib.request.urlopen(f"{SERVER}/runs/{run_id}/control", timeout=5) as r:
        return json.load(r)


def post_message(run_id: str, message: str) -> None:
    """POST /runs/{id}/input — the same request the UI's chat panel sends."""
    body = json.dumps({"message": message}).encode()
    req = urllib.request.Request(
        f"{SERVER}/runs/{run_id}/input",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5)


def answer_when_asked(run_id: str, answer: str) -> None:
    """Stand in for a human: wait until the agent actually asks (so you can watch it sit in
    'waiting for your input' first), read the question it posted, then send a real reply."""

    def _worker() -> None:
        for _ in range(120):
            c = _get_control(run_id)
            if c.get("waiting_for_input"):
                print(f"[human] agent asked: {c.get('question')!r} → answering {answer!r}")
                post_message(run_id, answer)
                return
            time.sleep(0.25)

    threading.Thread(target=_worker, daemon=True).start()


def run_agent() -> None:
    with vapviz.trace("Deploy Agent", app_id="conversation-demo") as run:
        print(f"\n[vapviz] Run started  run_id={run.run_id}")
        print("[vapviz] Watch it live at http://localhost:8001 (Theater tab → chat panel)\n")

        with run.step("plan", kind="step") as step:
            print("[agent] Planning the deploy…")
            time.sleep(0.3)
            step.set_output({"ready": True})

        # A background "human" answers once the agent asks — delete to try it fully live.
        answer_when_asked(run.run_id, "us-west")

        with run.step("choose_region", kind="step") as step:
            print("[agent] Asking which region via vapviz.ask() — and genuinely waiting…")
            region = vapviz.ask("Which region should I deploy to?")   # <- shows the question, waits
            print(f"[agent] Got: {region!r}")
            vapviz.say(f"Got it — deploying to {region}.")             # <- confirm; no waiting
            step.set_output({"region": region})

        with run.step("deploy", kind="step") as step:
            print("[agent] Deploying…")
            time.sleep(0.5)
            vapviz.say("Deploy complete.")
            step.set_output({"deployed_to": region})

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
