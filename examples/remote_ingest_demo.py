"""
Remote ingest demo — pushes events from a separate process via HTTP POST.

This example shows how to trace an agent that runs in a completely separate
process (or even a different machine / language) by posting VapEvent JSON
payloads to POST /runs/{run_id}/events.

The vapviz package does NOT need to be imported in the agent process — only
an HTTP client is required. This script uses stdlib urllib.request so it
works with no extra dependencies.

Architecture:
    Agent process  ──POST /runs/{id}/events──►  vapviz Server  ──SSE──►  Browser

Run (starts server + agent in one process):
    python examples/remote_ingest_demo.py

Or push to an already-running server:
    vapviz serve --db vapviz.db
    python examples/remote_ingest_demo.py --agent-only --server-url http://localhost:8001

Open http://localhost:8001 to see the run appear in real time.
"""
import json
import sys
import time
import threading
import urllib.request
import uuid


# ── HTTP helper (no extra deps) ────────────────────────────────────────────────

def post_event(server: str, run_id: str, event: dict) -> None:
    """POST a single VapEvent dict to the vapviz server."""
    body = json.dumps(event).encode()
    req  = urllib.request.Request(
        f"{server}/runs/{run_id}/events",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5)


def uid() -> str:
    return uuid.uuid4().hex[:12]


# ── Remote agent (uses only stdlib — no vapviz import needed) ────────────────────

def run_remote_agent(server: str) -> str:
    """
    Simulate a data-processing pipeline by posting events manually.

    Returns the run_id so the caller can print the trace URL.
    """
    run_id  = uid()
    root_id = uid()
    ts      = time.time

    print(f"[remote] Starting run  run_id={run_id}")

    # ── Open the agent run ────────────────────────────────────────────────
    post_event(server, run_id, {
        "id": uid(), "run_id": run_id, "timestamp": ts(),
        "type": "agent_start", "node_id": root_id,
        "node_kind": "agent", "node_label": "Remote Data Pipeline",
        "parent_id": None, "data": {"label": "Remote Data Pipeline"},
        "schema_version": 1,
    })

    # ── Step: ingest ──────────────────────────────────────────────────────
    ingest_id = uid()
    post_event(server, run_id, {
        "id": uid(), "run_id": run_id, "timestamp": ts(),
        "type": "step_start", "node_id": ingest_id,
        "node_kind": "step", "node_label": "ingest",
        "parent_id": root_id, "data": {"input": {"source": "s3://bucket/data.parquet"}},
        "schema_version": 1,
    })
    time.sleep(0.15)
    post_event(server, run_id, {
        "id": uid(), "run_id": run_id, "timestamp": ts(),
        "type": "step_end", "node_id": ingest_id,
        "node_kind": "step", "node_label": "ingest",
        "parent_id": root_id,
        "data": {"input": {"source": "s3://bucket/data.parquet"},
                 "output": {"rows": 50_000, "bytes": 4_200_000}},
        "schema_version": 1,
    })
    print("[remote] ingest done")

    # ── Tool calls: validate + clean (sequential) ─────────────────────────
    for name, result in [
        ("validate", {"passed": True,  "errors": 0}),
        ("clean",    {"rows_dropped": 12, "rows_remaining": 49_988}),
    ]:
        node_id = uid()
        post_event(server, run_id, {
            "id": uid(), "run_id": run_id, "timestamp": ts(),
            "type": "tool_call", "node_id": node_id,
            "node_kind": "tool", "node_label": name,
            "parent_id": root_id, "data": {"input": {"rows": 50_000}},
            "schema_version": 1,
        })
        time.sleep(0.10)
        post_event(server, run_id, {
            "id": uid(), "run_id": run_id, "timestamp": ts(),
            "type": "tool_result", "node_id": node_id,
            "node_kind": "tool", "node_label": name,
            "parent_id": root_id, "data": {"output": result},
            "schema_version": 1,
        })
        print(f"[remote] {name} done: {result}")

    # ── Step: transform ───────────────────────────────────────────────────
    transform_id = uid()
    post_event(server, run_id, {
        "id": uid(), "run_id": run_id, "timestamp": ts(),
        "type": "step_start", "node_id": transform_id,
        "node_kind": "step", "node_label": "transform",
        "parent_id": root_id, "data": {"input": {"format": "parquet → csv"}},
        "schema_version": 1,
    })

    # Nested tool: write output
    write_id = uid()
    post_event(server, run_id, {
        "id": uid(), "run_id": run_id, "timestamp": ts(),
        "type": "tool_call", "node_id": write_id,
        "node_kind": "tool", "node_label": "write_output",
        "parent_id": transform_id, "data": {"input": {"dest": "s3://bucket/out.csv"}},
        "schema_version": 1,
    })
    time.sleep(0.12)
    post_event(server, run_id, {
        "id": uid(), "run_id": run_id, "timestamp": ts(),
        "type": "tool_result", "node_id": write_id,
        "node_kind": "tool", "node_label": "write_output",
        "parent_id": transform_id,
        "data": {"output": {"written_rows": 49_988, "size_mb": 8.1}},
        "schema_version": 1,
    })

    time.sleep(0.05)
    post_event(server, run_id, {
        "id": uid(), "run_id": run_id, "timestamp": ts(),
        "type": "step_end", "node_id": transform_id,
        "node_kind": "step", "node_label": "transform",
        "parent_id": root_id,
        "data": {"output": {"status": "ok", "rows": 49_988}},
        "schema_version": 1,
    })
    print("[remote] transform done")

    # ── Close the agent run ───────────────────────────────────────────────
    post_event(server, run_id, {
        "id": uid(), "run_id": run_id, "timestamp": ts(),
        "type": "agent_end", "node_id": root_id,
        "node_kind": "agent", "node_label": "Remote Data Pipeline",
        "parent_id": None, "data": {"output": {"status": "success"}},
        "schema_version": 1,
    })
    print("[remote] run complete")
    return run_id


# ── Entry points ───────────────────────────────────────────────────────────────

def main_with_server() -> None:
    import vapviz
    import uvicorn

    vapviz.configure(db="vapviz.db")
    server_app = vapviz.create_app()

    t = threading.Thread(
        target=lambda: uvicorn.run(server_app, host="0.0.0.0", port=8001, log_level="warning"),
        daemon=True,
    )
    t.start()
    time.sleep(1.0)

    server_url = "http://localhost:8001"
    run_id = run_remote_agent(server_url)
    print(f"\n[vapviz] View at {server_url}  run_id={run_id}")
    input("\nPress Enter to exit…")


def main_agent_only() -> None:
    # Parse --server-url from CLI args
    server_url = "http://localhost:8001"
    for i, arg in enumerate(sys.argv):
        if arg == "--server-url" and i + 1 < len(sys.argv):
            server_url = sys.argv[i + 1]

    run_id = run_remote_agent(server_url)
    print(f"\n[vapviz] View at {server_url}  run_id={run_id}")


if __name__ == "__main__":
    if "--agent-only" in sys.argv:
        main_agent_only()
    else:
        main_with_server()
