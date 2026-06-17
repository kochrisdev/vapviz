"""
Budgets & alerting demo.

Defines a cost/latency budget and runs two agents — one within budget, one that
blows past it — so you can see the alert fire. Runs with **no API key** (costs
are attached manually, exactly as the integrations do for real LLM calls).

Run:
    python examples/budgets_demo.py
"""
import logging
import time

import vap
from vap.budgets import Budget, check_budget, enable_budget_alerts
from vap.store import MemoryStore

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def run_agent(tracer, label, *, cost, work_s):
    """Trace one agent whose single LLM call has a known cost and duration."""
    with tracer.trace(label) as run:
        with run.step("think", kind="llm") as step:
            step.set_input({"model": "gpt-4o"})
            time.sleep(work_s)
            step.set_output({
                "usage": {"input_tokens": 1000, "output_tokens": 200},
                "cost_usd": cost,
            })
    return run


def main() -> None:
    store = MemoryStore()
    tracer = vap.Tracer(store=store)

    budget = Budget(max_cost_usd=0.02, max_duration_ms=500)
    print(f"\nBudget: max ${budget.max_cost_usd} / run, max {budget.max_duration_ms:.0f} ms / run\n")

    # Auto-alert on every completed run (logs a warning when a limit is exceeded).
    handle = enable_budget_alerts(budget, store=store)

    print("Run A — cheap & fast (within budget):")
    a = run_agent(tracer, "Cheap agent", cost=0.004, work_s=0.05)

    print("Run B - expensive & slow (over budget) -> expect a warning:")
    b = run_agent(tracer, "Expensive agent", cost=0.05, work_s=0.7)

    handle.disable()

    print("\nReports:")
    for run in (a, b):
        report = check_budget(store.get_graph(run.run_id), budget)
        tag = "OK  " if report.status == "ok" else "OVER"
        detail = "; ".join(
            f"{v.metric}={v.actual} (limit {v.limit}, +{v.pct_over:.0f}%)" for v in report.violations
        ) or "within all limits"
        print(f"  [{tag}] {run.label:18} ${report.cost_usd:.4f} / {report.duration_ms:.0f} ms — {detail}")


if __name__ == "__main__":
    main()
