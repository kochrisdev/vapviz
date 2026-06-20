"""
Agent evals & scoring demo.

Shows VaP used as a *regression test for agents*: trace a run, then assert it
meets cost / latency / correctness checks. Runs with **no API key**.

This is exactly the pattern you'd put in a pytest test or a CI step — swap the
fake agent for your real one and keep the `eval_run(...)` assertions.

Run:
    python examples/evals_demo.py
"""
import time

import vap
from vap.evals import eval_run, max_cost, max_latency, no_errors, output_contains, judge
from vap.store import MemoryStore


def run_support_agent(tracer, question: str):
    """A stand-in agent: one LLM call that 'answers' the question."""
    with tracer.trace("support agent") as run:
        with run.step("answer", kind="llm") as step:
            step.set_input({"model": "gpt-4o-mini", "question": question})
            time.sleep(0.05)
            step.set_output({
                "text": "To reset your password, open Settings and click 'Reset password'.",
                "usage": {"input_tokens": 320, "output_tokens": 60},
                "cost_usd": 0.0013,
            })
    return run


def looks_helpful(graph) -> tuple:
    """A trivial stand-in for an LLM-as-judge scorer (you'd call a model here)."""
    text = ""
    for node in graph.nodes:
        out = node.data.get("output") if isinstance(node.data, dict) else None
        if isinstance(out, dict) and isinstance(out.get("text"), str):
            text = out["text"]
    score = 1.0 if "reset" in text.lower() else 0.3
    return score >= 0.5, f"helpfulness score {score}", score


def main() -> None:
    store = MemoryStore()
    tracer = vap.Tracer(store=store)

    run = run_support_agent(tracer, "How do I reset my password?")

    result = eval_run(run, [
        max_cost(0.01),
        max_latency(2.0),
        no_errors(),
        output_contains("reset password"),
        judge("helpfulness", looks_helpful),
    ])

    print()
    print(result.summary())
    print()
    print(f"overall: {'PASS' if result.passed else 'FAIL'}  score={result.score:.0%}")

    # In a test you'd simply assert:
    assert result.passed, result.summary()


if __name__ == "__main__":
    main()
