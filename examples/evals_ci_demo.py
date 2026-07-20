"""
Eval-suite / CI-gate demo.

Traces two runs (one clean, one over budget & off-topic), then applies an eval
suite the same way the `vapviz eval` CLI does — and reports the pass/fail the CI
gate would exit on. Runs with **no API key** (costs are attached manually,
exactly as the integrations do for real LLM calls).

Run:
    python examples/evals_ci_demo.py
"""
import vapviz
from vapviz import EvalSuite, run_suite
from vapviz.store import MemoryStore


def run_agent(tracer, label, *, cost, text):
    with tracer.trace(label) as run:
        with run.step("think", kind="llm") as step:
            step.set_input({"model": "gpt-4o"})
            step.set_output({"usage": {"input_tokens": 1000, "output_tokens": 200},
                             "cost_usd": cost, "text": text})
    return run


def main() -> None:
    store = MemoryStore()
    tracer = vapviz.Tracer(store=store)

    good = run_agent(tracer, "support agent", cost=0.01, text="I've created a ticket for you.")
    bad = run_agent(tracer, "support agent", cost=0.09, text="Not sure, sorry.")

    # The same declarative checks you'd put in examples/eval_suite.yaml.
    suite = EvalSuite(
        name="support-agent",
        checks=[
            {"type": "max_cost", "value": 0.02},
            {"type": "no_errors"},
            {"type": "output_contains", "value": "ticket"},
        ],
    )

    graphs = [store.get_graph(good.run_id), store.get_graph(bad.run_id)]
    report = run_suite(suite, graphs)

    print(report.summary())
    print(f"\nCI would exit with: {0 if report.passed else 1}")
    # In CI this is: vapviz eval --suite examples/eval_suite.yaml --db vapviz.db


if __name__ == "__main__":
    main()
