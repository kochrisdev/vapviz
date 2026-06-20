"""
Cost & latency budgets for VaP.

Turn the metrics VaP already captures into **guardrails**: define a budget
(max cost, duration, and/or tokens) and check a run against it. ``check_budget``
is a pure function; ``enable_budget_alerts`` wraps a store so every completed run
is checked automatically and an alert fires when a limit is exceeded.

Programmatic check::

    import vap
    from vap.budgets import Budget, check_budget

    graph = store.get_graph(run_id)
    report = check_budget(graph, Budget(max_cost_usd=0.02, max_duration_ms=3000))
    if report.status == "exceeded":
        for v in report.violations:
            print(f"{v.metric}: {v.actual} > {v.limit} (+{v.pct_over:.0f}%)")

Automatic alerting on every run::

    import vap
    from vap.budgets import Budget, enable_budget_alerts

    vap.configure(db="vap.db")
    enable_budget_alerts(Budget(max_cost_usd=0.05, max_duration_ms=5000))
    # over-budget runs now log a warning (or call your on_alert callback)
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from .events import EventType, NodeKind, RunGraph

logger = logging.getLogger("vap.budgets")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Budget(BaseModel):
    """A set of optional per-run limits. Any limit left as ``None`` is ignored."""

    max_cost_usd: Optional[float] = None
    max_duration_ms: Optional[float] = None
    max_total_tokens: Optional[int] = None


class Violation(BaseModel):
    metric: str            # "cost_usd" | "duration_ms" | "total_tokens"
    limit: float
    actual: float
    pct_over: float        # how far past the limit, as a percentage


class BudgetReport(BaseModel):
    run_id: str
    status: str            # "ok" | "exceeded"
    cost_usd: float = 0.0
    duration_ms: Optional[float] = None
    total_tokens: int = 0
    violations: list[Violation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-run measures (consistent with vap.metrics)
# ---------------------------------------------------------------------------

def _run_cost(graph: RunGraph) -> float:
    total = 0.0
    for node in graph.nodes:
        output = node.data.get("output") if isinstance(node.data, dict) else None
        if isinstance(output, dict):
            cost = output.get("cost_usd")
            if isinstance(cost, (int, float)):
                total += cost
    return round(total, 8)


def _run_tokens(graph: RunGraph) -> int:
    total = 0
    for node in graph.nodes:
        if node.kind != NodeKind.LLM:
            continue
        output = node.data.get("output") if isinstance(node.data, dict) else None
        usage = output.get("usage") if isinstance(output, dict) else None
        if isinstance(usage, dict):
            total += int(usage.get("input_tokens") or 0)
            total += int(usage.get("output_tokens") or 0)
    return total


def _run_duration_ms(graph: RunGraph) -> Optional[float]:
    if graph.ended_at is None or graph.started_at is None:
        return None
    return round((graph.ended_at - graph.started_at) * 1000.0, 2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_budget(graph: RunGraph, budget: Budget) -> BudgetReport:
    """Check a single run graph against *budget* and return a report."""
    cost = _run_cost(graph)
    tokens = _run_tokens(graph)
    duration = _run_duration_ms(graph)

    violations: list[Violation] = []

    def _add(metric: str, limit: Optional[float], actual: Optional[float]) -> None:
        if limit is None or actual is None:
            return
        if actual > limit:
            pct = ((actual - limit) / limit * 100.0) if limit else float("inf")
            violations.append(Violation(metric=metric, limit=float(limit),
                                        actual=float(actual), pct_over=round(pct, 2)))

    _add("cost_usd", budget.max_cost_usd, cost)
    _add("duration_ms", budget.max_duration_ms, duration)
    _add("total_tokens", budget.max_total_tokens, tokens)

    return BudgetReport(
        run_id=graph.run_id,
        status="exceeded" if violations else "ok",
        cost_usd=cost,
        duration_ms=duration,
        total_tokens=tokens,
        violations=violations,
    )


class BudgetAlertHandle:
    """Returned by :func:`enable_budget_alerts`. Call :meth:`disable` to stop."""

    def __init__(self, store, original_add_event) -> None:
        self._store = store
        self._original = original_add_event

    def disable(self) -> None:
        try:
            del self._store.add_event
        except AttributeError:
            self._store.add_event = self._original


def _default_alert(report: BudgetReport) -> None:
    parts = ", ".join(
        f"{v.metric} {v.actual} > {v.limit} (+{v.pct_over:.0f}%)" for v in report.violations
    )
    logger.warning("VaP budget exceeded for run %s: %s", report.run_id, parts)


def enable_budget_alerts(
    budget: Budget,
    *,
    store=None,
    on_alert: Optional[Callable[[BudgetReport], None]] = None,
) -> BudgetAlertHandle:
    """Check every completed run against *budget* and alert on violations.

    Wraps the store's ``add_event`` so that when a run's ``agent_end`` event is
    recorded, the run is checked. On a violation, *on_alert* is called (or a
    warning is logged by default). Returns a handle with ``disable()``.

    Parameters
    ----------
    budget:
        The limits to enforce.
    store:
        Store to watch. Defaults to ``vap.store.default_store``.
    on_alert:
        Callback invoked with the :class:`BudgetReport` when a run exceeds the
        budget. Defaults to logging a warning on the ``vap.budgets`` logger.
    """
    import vap.store as _sm

    target = store if store is not None else _sm.default_store
    original = target.add_event
    alert = on_alert or _default_alert

    def wrapped(event) -> None:
        original(event)
        if event.type == EventType.AGENT_END:
            try:
                graph = target.get_graph(event.run_id)
                if graph is not None:
                    report = check_budget(graph, budget)
                    if report.status == "exceeded":
                        alert(report)
            except Exception:  # noqa: BLE001 - alerting is best-effort
                pass

    target.add_event = wrapped
    return BudgetAlertHandle(target, original)
