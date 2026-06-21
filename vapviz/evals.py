"""
Agent evals & scoring for vapviz.

Turn a traced run into a set of pass/fail assertions — *regression testing for
agents*. Define checks (cost, latency, tokens, error-free, output contains, or
your own / an LLM judge), run them against a run graph, and get an ``EvalResult``
with a per-check breakdown and an overall score.

In a test or CI::

    import vapviz
    from vapviz.evals import eval_run, max_cost, max_latency, no_errors, output_contains

    with vapviz.trace("support agent") as run:
        ...

    result = eval_run(run, [
        max_cost(0.02),
        max_latency(3.0),
        no_errors(),
        output_contains("ticket"),
    ])
    assert result.passed, result.summary()

Declarative checks (JSON-friendly, used by ``POST /runs/{id}/eval``)::

    from vapviz.evals import run_checks
    result = run_checks(graph, [
        {"type": "max_cost", "value": 0.02},
        {"type": "output_contains", "value": "ticket"},
    ])
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Union

from pydantic import BaseModel, Field

from .budgets import _run_cost, _run_duration_ms, _run_tokens
from .events import NodeStatus, RunGraph
from .tracer import RunContext


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

class CheckResult(BaseModel):
    name: str
    passed: bool
    score: float = 0.0          # 0..1
    detail: str = ""


class EvalResult(BaseModel):
    run_id: str
    passed: bool                # all checks passed
    score: float = 0.0          # mean of check scores, 0..1
    checks: list[CheckResult] = Field(default_factory=list)

    def summary(self) -> str:
        lines = [f"{'PASS' if c.passed else 'FAIL'}  {c.name} — {c.detail}" for c in self.checks]
        head = f"{'PASSED' if self.passed else 'FAILED'} ({self.score:.0%})"
        return head + "\n" + "\n".join("  " + l for l in lines)


# ---------------------------------------------------------------------------
# Check — a named assertion over a RunGraph
# ---------------------------------------------------------------------------

# A check function returns (passed, detail) or (passed, detail, score).
_CheckFn = Callable[[RunGraph], Union[tuple, "tuple[bool, str]"]]


class Check:
    """A named assertion. ``evaluate`` returns a :class:`CheckResult`."""

    def __init__(self, name: str, fn: _CheckFn) -> None:
        self.name = name
        self._fn = fn

    def evaluate(self, graph: RunGraph) -> CheckResult:
        try:
            out = self._fn(graph)
        except Exception as exc:  # noqa: BLE001 - a throwing check is a failed check
            return CheckResult(name=self.name, passed=False, score=0.0,
                               detail=f"check raised {type(exc).__name__}: {exc}")
        if len(out) == 3:
            passed, detail, score = out
        else:
            passed, detail = out
            score = 1.0 if passed else 0.0
        return CheckResult(name=self.name, passed=bool(passed), score=float(score), detail=str(detail))


# ---------------------------------------------------------------------------
# Built-in checks
# ---------------------------------------------------------------------------

def max_cost(usd: float) -> Check:
    def fn(g: RunGraph):
        c = _run_cost(g)
        return c <= usd, f"cost ${c} (limit ${usd})"
    return Check(f"max_cost<=${usd}", fn)


def max_latency(seconds: float) -> Check:
    def fn(g: RunGraph):
        ms = _run_duration_ms(g)
        if ms is None:
            return False, "run has no measured duration"
        return ms <= seconds * 1000.0, f"{ms:.0f} ms (limit {seconds * 1000:.0f} ms)"
    return Check(f"max_latency<={seconds}s", fn)


def max_tokens(n: int) -> Check:
    def fn(g: RunGraph):
        t = _run_tokens(g)
        return t <= n, f"{t} tokens (limit {n})"
    return Check(f"max_tokens<={n}", fn)


def no_errors() -> Check:
    def fn(g: RunGraph):
        bad = [node.label for node in g.nodes if node.status == NodeStatus.ERROR]
        return (len(bad) == 0,
                "no error nodes" if not bad else f"{len(bad)} error node(s): {', '.join(bad[:5])}")
    return Check("no_errors", fn)


def output_contains(text: str, *, node_label: Optional[str] = None, case_sensitive: bool = False) -> Check:
    needle = text if case_sensitive else text.lower()

    def fn(g: RunGraph):
        for node in g.nodes:
            if node_label is not None and node.label != node_label:
                continue
            output = node.data.get("output") if isinstance(node.data, dict) else None
            if output is None:
                continue
            hay = _stringify(output)
            if not case_sensitive:
                hay = hay.lower()
            if needle in hay:
                return True, f"found in node '{node.label}'"
        where = f"node '{node_label}'" if node_label else "any node output"
        return False, f"'{text}' not found in {where}"
    label = f"output_contains('{text}')" + (f"@{node_label}" if node_label else "")
    return Check(label, fn)


def custom(name: str, fn: Callable[[RunGraph], Any]) -> Check:
    """Wrap an arbitrary predicate. ``fn`` may return a bool, ``(bool, detail)``, or ``(bool, detail, score)``."""
    def adapt(g: RunGraph):
        out = fn(g)
        if isinstance(out, tuple):
            return out
        return bool(out), ""
    return Check(name, adapt)


def judge(name: str, fn: Callable[[RunGraph], Any]) -> Check:
    """An LLM-as-judge (or any scoring) check.

    ``fn(graph)`` should return ``(passed, detail, score)`` — vapviz does not call an
    LLM itself; you supply the judging function so it stays provider-agnostic and
    testable.
    """
    return Check(name, fn)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _as_graph(run_or_graph: Union[RunGraph, RunContext]) -> RunGraph:
    if isinstance(run_or_graph, RunGraph):
        return run_or_graph
    if isinstance(run_or_graph, RunContext):
        graph = run_or_graph._store.get_graph(run_or_graph.run_id)
        if graph is None:
            raise ValueError(f"no graph for run {run_or_graph.run_id}")
        return graph
    raise TypeError("eval_run expects a RunGraph or a RunContext")


def eval_run(run_or_graph: Union[RunGraph, RunContext], checks: list[Check]) -> EvalResult:
    """Run *checks* against a run and return an :class:`EvalResult`.

    Accepts a ``RunGraph`` or a ``RunContext`` (from ``vapviz.trace()``).
    """
    graph = _as_graph(run_or_graph)
    results = [c.evaluate(graph) for c in checks]
    passed = all(r.passed for r in results)
    score = round(sum(r.score for r in results) / len(results), 4) if results else 1.0
    return EvalResult(run_id=graph.run_id, passed=passed, score=score, checks=results)


# ---------------------------------------------------------------------------
# Declarative checks (JSON-friendly, for the REST endpoint)
# ---------------------------------------------------------------------------

def _check_from_spec(spec: dict) -> Check:
    t = spec.get("type")
    if t == "max_cost":
        return max_cost(float(spec["value"]))
    if t == "max_latency":
        return max_latency(float(spec["value"]))
    if t == "max_tokens":
        return max_tokens(int(spec["value"]))
    if t == "no_errors":
        return no_errors()
    if t == "output_contains":
        return output_contains(str(spec["value"]), node_label=spec.get("node_label"),
                               case_sensitive=bool(spec.get("case_sensitive", False)))
    raise ValueError(f"unknown check type: {t!r}")


def run_checks(run_or_graph: Union[RunGraph, RunContext], specs: list[dict]) -> EvalResult:
    """Build checks from declarative specs and run them. Used by ``POST /runs/{id}/eval``."""
    return eval_run(run_or_graph, [_check_from_spec(s) for s in specs])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        import json

        return json.dumps(value, default=str)
    except Exception:  # noqa: BLE001
        return str(value)
