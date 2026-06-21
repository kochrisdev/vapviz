"""
Error handling demo — shows how exceptions are captured as error nodes.

No API key needed.

This demo illustrates three error scenarios:
  1. A leaf step that raises an exception — the node turns red, the
     exception propagates to the caller, which handles it gracefully.
  2. A nested failure — a parent step that contains a failing child; the
     parent is also marked as error when the exception propagates.
  3. A run that partially succeeds — some steps complete fine while one
     fails; the graph shows a mix of green and red nodes.

Run (server + agent in one process):
    python examples/error_handling_demo.py

Or start the server first:
    vapviz serve --db vapviz.db
    python examples/error_handling_demo.py --agent-only

Open http://localhost:8001 to see the graph with error states highlighted.
"""
import sys
import time
import threading

import vapviz


# ── Agent logic ────────────────────────────────────────────────────────────────

def run_scenario_1_leaf_error(run: vapviz.RunContext) -> None:
    """A single tool call that raises. The node turns red; caller catches."""
    with run.step("fetch_data", kind="tool") as step:
        step.set_input({"url": "https://api.example.com/data"})
        time.sleep(0.1)
        raise ConnectionError("API timeout after 10 s")
        # The step context manager catches the exception, records it on
        # the node as status=error, then re-raises it.


def run_scenario_2_nested_error(run: vapviz.RunContext) -> None:
    """A parent step whose child fails — both turn red."""
    with run.step("process_pipeline", kind="step") as parent:
        parent.set_input({"items": 5})

        with run.step("validate", kind="tool") as step:
            step.set_input({"schema": "v2"})
            time.sleep(0.05)
            step.set_output({"valid": True})

        with run.step("transform", kind="step") as step:
            step.set_input({"format": "parquet"})
            time.sleep(0.08)
            raise ValueError("Unsupported schema version: 1 (expected 2)")


def run_scenario_3_partial_failure(run: vapviz.RunContext) -> None:
    """Three parallel tasks; one fails while the others succeed."""
    sources = ["database", "cache", "api"]

    for source in sources:
        try:
            with run.step(f"fetch/{source}", kind="tool") as step:
                step.set_input({"source": source})
                time.sleep(0.07)

                if source == "cache":
                    raise RuntimeError("Cache miss — key not found")

                step.set_output({"rows": 42, "source": source})

        except RuntimeError as exc:
            # Caller handles the error; the failed node is already recorded
            print(f"  [warn] fetch/{source} failed: {exc}")

    # Downstream step still runs (uses data from successful fetches)
    with run.step("merge_results", kind="step") as step:
        step.set_input({"successful_sources": 2})
        time.sleep(0.06)
        step.set_output({"merged_rows": 84, "skipped": ["cache"]})


def run_agent() -> None:
    # ── Scenario 1: leaf error ────────────────────────────────────────────
    with vapviz.trace("Error Demo — Leaf Failure") as run:
        with run.step("setup", kind="step") as step:
            step.set_input({"config": "prod"})
            time.sleep(0.05)
            step.set_output({"ready": True})

        try:
            run_scenario_1_leaf_error(run)
        except ConnectionError as exc:
            print(f"  [handled] {exc}")

        # Subsequent steps still run after a handled error
        with run.step("fallback", kind="step") as step:
            step.set_input({"strategy": "use_cache"})
            time.sleep(0.06)
            step.set_output({"data": "cached_result", "fresh": False})

    print(f"[vapviz] Scenario 1 complete  run_id={run.run_id}")

    # ── Scenario 2: nested error ──────────────────────────────────────────
    with vapviz.trace("Error Demo — Nested Failure") as run:
        with run.step("ingest", kind="step") as step:
            step.set_input({"files": 3})
            time.sleep(0.04)
            step.set_output({"loaded": 3})

        try:
            run_scenario_2_nested_error(run)
        except ValueError as exc:
            print(f"  [handled] {exc}")

        # Recovery step
        with run.step("recover", kind="step") as step:
            step.set_input({"action": "revert_to_v1_schema"})
            time.sleep(0.05)
            step.set_output({"status": "recovered"})

    print(f"[vapviz] Scenario 2 complete  run_id={run.run_id}")

    # ── Scenario 3: partial failure ───────────────────────────────────────
    with vapviz.trace("Error Demo — Partial Failure") as run:
        with run.step("init", kind="step") as step:
            step.set_input({"sources": 3})
            time.sleep(0.03)
            step.set_output({"ok": True})

        run_scenario_3_partial_failure(run)

        with run.step("report", kind="step") as step:
            step.set_input({"data": "merged"})
            time.sleep(0.04)
            step.set_output({"status": "partial_success", "rows": 84})

    print(f"[vapviz] Scenario 3 complete  run_id={run.run_id}")
    print("\n[vapviz] View at http://localhost:8001 — look for red nodes in each run!")


# ── Entry points ───────────────────────────────────────────────────────────────

def main_with_server() -> None:
    import uvicorn

    vapviz.configure(db="vapviz.db")
    server_app = vapviz.create_app()

    t = threading.Thread(
        target=lambda: uvicorn.run(server_app, host="0.0.0.0", port=8001, log_level="warning"),
        daemon=True,
    )
    t.start()
    time.sleep(1.0)

    run_agent()
    input("\nPress Enter to exit…")


def main_agent_only() -> None:
    vapviz.configure(db="vapviz.db")
    run_agent()


if __name__ == "__main__":
    if "--agent-only" in sys.argv:
        main_agent_only()
    else:
        main_with_server()
