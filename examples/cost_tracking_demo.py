"""
Cost tracking demo — demonstrates the token cost overlay without an API key.

Simulates several LLM calls with realistic token counts, manually attaching
cost_usd to each node's output using vap.calculate_cost(). Shows:
  - Per-node cost on LLM nodes in the graph (purple label)
  - Per-run total cost in the sidebar
  - Cost comparison between models using the run comparison feature
  - vap.calculate_cost() and vap.format_cost() utilities directly

No API key needed — all LLM responses are simulated.

Run (server + agent in one process):
    python examples/cost_tracking_demo.py

Or start the server first:
    vap serve --db vap.db
    python examples/cost_tracking_demo.py --agent-only

Open http://localhost:8001 to see cost labels on every LLM node.
Try the comparison feature to see cost differences between runs.
"""
import sys
import time
import threading

import vap


# ── Helpers ────────────────────────────────────────────────────────────────────

def simulate_llm(
    run: vap.RunContext,
    label: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    response_text: str,
) -> str:
    """Simulate an LLM call: emit a traced llm node with cost attached."""
    with run.step(label, kind="llm") as step:
        step.set_input({
            "model": model,
            "input_tokens": input_tokens,
        })
        time.sleep(0.05)   # simulate API latency

        cost = vap.calculate_cost(model, input_tokens, output_tokens)
        output: dict = {
            "text": response_text,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
        if cost is not None:
            output["cost_usd"] = round(cost, 8)

        step.set_output(output)
        return response_text


# ── Agent runs ─────────────────────────────────────────────────────────────────

def run_gpt4o_mini_agent() -> None:
    """Simulated pipeline using gpt-4o-mini (cheap, fast)."""
    with vap.trace("Pipeline — gpt-4o-mini") as run:

        with run.step("plan", kind="step") as step:
            step.set_input({"goal": "Analyse customer reviews"})
            time.sleep(0.03)
            step.set_output({"tasks": ["extract_themes", "score_sentiment", "summarise"]})

        simulate_llm(run, "llm/extract_themes", "gpt-4o-mini",
                     input_tokens=800, output_tokens=300,
                     response_text="Themes: quality, price, delivery speed.")

        simulate_llm(run, "llm/score_sentiment", "gpt-4o-mini",
                     input_tokens=600, output_tokens=150,
                     response_text="Sentiment score: 0.72 (positive).")

        simulate_llm(run, "llm/summarise", "gpt-4o-mini",
                     input_tokens=500, output_tokens=120,
                     response_text="Customers value quality and fast delivery.")

        with run.step("store_results", kind="tool") as step:
            step.set_input({"destination": "reports/q4.json"})
            time.sleep(0.02)
            step.set_output({"written": True})

    print(f"[vap] gpt-4o-mini run  run_id={run.run_id}")


def run_gpt4o_agent() -> None:
    """Same pipeline with gpt-4o — more capable but ~17× more expensive."""
    with vap.trace("Pipeline — gpt-4o") as run:

        with run.step("plan", kind="step") as step:
            step.set_input({"goal": "Analyse customer reviews"})
            time.sleep(0.03)
            step.set_output({"tasks": ["extract_themes", "score_sentiment", "summarise"]})

        simulate_llm(run, "llm/extract_themes", "gpt-4o",
                     input_tokens=800, output_tokens=300,
                     response_text="Themes: quality, price, delivery speed, packaging.")

        simulate_llm(run, "llm/score_sentiment", "gpt-4o",
                     input_tokens=600, output_tokens=150,
                     response_text="Sentiment: 0.74. Notable: price complaints in Q3.")

        simulate_llm(run, "llm/summarise", "gpt-4o",
                     input_tokens=500, output_tokens=120,
                     response_text="Quality and delivery drive satisfaction; price is emerging concern.")

        with run.step("store_results", kind="tool") as step:
            step.set_input({"destination": "reports/q4.json"})
            time.sleep(0.02)
            step.set_output({"written": True})

    print(f"[vap] gpt-4o run       run_id={run.run_id}")


def run_mixed_model_agent() -> None:
    """Use a cheap model for routing and an expensive model only when needed."""
    with vap.trace("Pipeline — Mixed Models") as run:

        with run.step("ingest", kind="step") as step:
            step.set_input({"reviews": 1000})
            time.sleep(0.04)
            step.set_output({"batches": 4})

        # Cheap model filters and routes each batch
        for i in range(1, 4):
            simulate_llm(run, f"llm/filter_batch_{i}", "gpt-4o-mini",
                         input_tokens=400, output_tokens=80,
                         response_text=f"Batch {i}: 18 relevant, 7 spam.")

        # Expensive model for the final synthesis only
        simulate_llm(run, "llm/deep_analysis", "gpt-4o",
                     input_tokens=1200, output_tokens=400,
                     response_text="Deep analysis: three emerging themes in premium segment.")

        with run.step("report", kind="step") as step:
            step.set_input({"themes": 3})
            time.sleep(0.03)
            step.set_output({"status": "done"})

    print(f"[vap] mixed-model run  run_id={run.run_id}")


def show_cost_utilities() -> None:
    """Print the cost utility functions directly for reference."""
    print("\n── vap.calculate_cost() examples ──────────────────────────────")
    examples = [
        ("gpt-4o-mini",             1_000, 500),
        ("gpt-4o",                  1_000, 500),
        ("claude-3-5-haiku-20241022", 1_000, 500),
        ("claude-3-5-sonnet-20241022", 1_000, 500),
        ("o1",                      1_000, 500),
        ("my-private-model",        1_000, 500),
    ]
    for model, inp, out in examples:
        cost = vap.calculate_cost(model, inp, out)
        label = vap.format_cost(cost) if cost is not None else "unknown model"
        print(f"  {model:<38} {inp:>6} in / {out:>4} out  →  {label}")


def run_agent() -> None:
    show_cost_utilities()

    print("\n── Running three pipeline variants ────────────────────────────")
    run_gpt4o_mini_agent()
    run_gpt4o_agent()
    run_mixed_model_agent()

    print("\n[vap] All runs complete. View at http://localhost:8001")
    print("[vap] Tip: select two runs and click ⊕ to compare costs side by side.")


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
