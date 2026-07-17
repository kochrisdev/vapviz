"""
Live run control demo — pause / resume / stop a running agent. No API key needed.

Starts the vapviz server in a background thread, then runs a slow synthetic
agent (~2 minutes of small steps) IN THIS PROCESS so you can control it live:

  * from the UI: open the run, go to the Theater tab, use the Agent control bar
    (Pause / Resume / Stop), or
  * from a terminal, with the curl commands this script prints.

Control is COOPERATIVE — the tracer obeys at each step boundary, so "pausing…"
lands when the current step finishes, and Stop raises vapviz.VapStopped inside
the agent (caught below for a graceful goodbye). The run ends with the neutral
⏹ "stopped" status — not a success, not a failure.

Run:
    python examples/control_demo.py

Open http://localhost:8001 to watch (UI built) or
     http://localhost:5173 if running the Vite dev server separately.
"""
import threading
import time

import uvicorn

import vapviz


N_BATCHES = 240          # ~2 minutes of work — plenty of time to play
STEP_SECONDS = 0.5


def run_agent() -> None:
    try:
        with vapviz.trace("Slow Batch Agent", app_id="control-demo") as run:
            print(f"\n[vapviz] Run started  run_id={run.run_id}")
            print("[vapviz] Control it from the Theater tab at http://localhost:8001")
            print("[vapviz] …or from another terminal:")
            base = f"http://localhost:8001/runs/{run.run_id}/control"
            print(f"    curl -X POST {base} -H 'Content-Type: application/json' -d '{{\"action\": \"pause\"}}'")
            print(f"    curl -X POST {base} -H 'Content-Type: application/json' -d '{{\"action\": \"resume\"}}'")
            print(f"    curl -X POST {base} -H 'Content-Type: application/json' -d '{{\"action\": \"stop\"}}'")
            print(f"    curl {base}    # see desired vs acked (the cooperative lag)\n")

            for i in range(1, N_BATCHES + 1):
                # Each step entry is a control checkpoint: pause parks here,
                # stop raises VapStopped here.
                with run.step(f"process_batch_{i:03d}", kind="step") as step:
                    step.set_input({"batch": i, "of": N_BATCHES})
                    time.sleep(STEP_SECONDS)
                    step.set_output({"processed": i * 10})
                if i % 20 == 0:
                    print(f"[agent] {i}/{N_BATCHES} batches done")

        print("\n[vapviz] Run finished on its own (nobody stopped it).")

    except vapviz.VapStopped:
        # The Stop button (or curl) fired: the tracer already closed the open
        # nodes and ended the run with status "stopped"; this except is our
        # chance to clean up gracefully instead of unwinding to the top.
        print("\n[agent] Stopped from the UI — cleaning up and exiting gracefully.")


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
