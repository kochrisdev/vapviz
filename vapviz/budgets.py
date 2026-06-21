"""
Cost & latency budgets for vapviz.

Turn the metrics vapviz already captures into **guardrails**: define a budget
(max cost, duration, and/or tokens) and check a run against it. ``check_budget``
is a pure function; ``enable_budget_alerts`` wraps a store so every completed run
is checked automatically and an alert fires when a limit is exceeded.

Programmatic check::

    import vapviz
    from vapviz.budgets import Budget, check_budget

    graph = store.get_graph(run_id)
    report = check_budget(graph, Budget(max_cost_usd=0.02, max_duration_ms=3000))
    if report.status == "exceeded":
        for v in report.violations:
            print(f"{v.metric}: {v.actual} > {v.limit} (+{v.pct_over:.0f}%)")

Automatic alerting on every run::

    import vapviz
    from vapviz.budgets import Budget, enable_budget_alerts

    vapviz.configure(db="vapviz.db")
    enable_budget_alerts(Budget(max_cost_usd=0.05, max_duration_ms=5000))
    # over-budget runs now log a warning (or call your on_alert callback)
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request
from typing import Any, Callable, Optional, Union

from pydantic import BaseModel, Field

from .events import EventType, NodeKind, RunGraph

logger = logging.getLogger("vapviz.budgets")

# An alert sink: called with a BudgetReport when a run exceeds its budget.
AlertChannel = Callable[["BudgetReport"], None]


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
# Per-run measures (consistent with vapviz.metrics)
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
    logger.warning("vapviz budget exceeded for run %s: %s", report.run_id, parts)


def enable_budget_alerts(
    budget: Budget,
    *,
    store=None,
    on_alert: Optional[Union[AlertChannel, list[AlertChannel]]] = None,
) -> BudgetAlertHandle:
    """Check every completed run against *budget* and alert on violations.

    Wraps the store's ``add_event`` so that when a run's ``agent_end`` event is
    recorded, the run is checked. On a violation, each alert channel is called.
    Returns a handle with ``disable()``.

    Parameters
    ----------
    budget:
        The limits to enforce.
    store:
        Store to watch. Defaults to ``vapviz.store.default_store``.
    on_alert:
        A single channel or a list of channels — each a callable invoked with the
        :class:`BudgetReport` when a run exceeds the budget. Use the built-in
        :func:`webhook_alert`, :func:`slack_alert`, :func:`otel_alert`, or your
        own callback. Defaults to logging a warning on the ``vapviz.budgets``
        logger. Channels are best-effort: an exception in one never breaks the
        run or the other channels.
    """
    import vapviz.store as _sm

    target = store if store is not None else _sm.default_store
    original = target.add_event

    if on_alert is None:
        channels: list[AlertChannel] = [_default_alert]
    elif callable(on_alert):
        channels = [on_alert]
    else:
        channels = list(on_alert)

    def wrapped(event) -> None:
        original(event)
        if event.type == EventType.AGENT_END:
            try:
                graph = target.get_graph(event.run_id)
                if graph is None:
                    return
                report = check_budget(graph, budget)
                if report.status != "exceeded":
                    return
                for channel in channels:
                    try:
                        channel(report)
                    except Exception:  # noqa: BLE001 - one channel must not break others
                        logger.warning("vapviz budget alert channel failed", exc_info=True)
            except Exception:  # noqa: BLE001 - alerting is best-effort
                pass

    target.add_event = wrapped
    return BudgetAlertHandle(target, original)


# ---------------------------------------------------------------------------
# Built-in alert channels
# ---------------------------------------------------------------------------

def _summary(report: BudgetReport) -> str:
    return ", ".join(
        f"{v.metric} {v.actual} > {v.limit} (+{v.pct_over:.0f}%)" for v in report.violations
    )


def _deliver(url: str, payload: dict, headers: Optional[dict], timeout: float) -> None:
    """POST *payload* as JSON to *url* in a daemon thread (never blocks the run)."""
    def _post() -> None:
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers={"Content-Type": "application/json", **(headers or {})},
            )
            urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - user-supplied URL
        except Exception:  # noqa: BLE001 - alerting is best-effort
            logger.warning("vapviz budget alert POST to %s failed", url, exc_info=True)

    threading.Thread(target=_post, daemon=True).start()


def webhook_alert(url: str, *, headers: Optional[dict] = None, timeout: float = 5.0) -> AlertChannel:
    """Alert channel that POSTs the :class:`BudgetReport` as JSON to *url*."""
    def _send(report: BudgetReport) -> None:
        _deliver(url, report.model_dump(), headers, timeout)
    return _send


def slack_alert(webhook_url: str, *, timeout: float = 5.0) -> AlertChannel:
    """Alert channel that posts a formatted message to a Slack incoming webhook."""
    def _send(report: BudgetReport) -> None:
        text = f":warning: *vapviz budget exceeded* for run `{report.run_id}`\n{_summary(report)}"
        _deliver(webhook_url, {"text": text}, None, timeout)
    return _send


def otel_alert(*, tracer_provider=None, service_name: str = "vapviz") -> AlertChannel:
    """Alert channel that emits an OpenTelemetry span (``vapviz.budget_exceeded``).

    Requires ``pip install "vapviz[otel]"``.
    """
    try:
        from opentelemetry import trace as _otel_trace
        from opentelemetry.trace import Status, StatusCode
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            'otel_alert requires opentelemetry. Install it with: pip install "vapviz[otel]"'
        ) from exc

    provider = tracer_provider if tracer_provider is not None else _otel_trace.get_tracer_provider()
    tracer = provider.get_tracer(service_name)

    def _send(report: BudgetReport) -> None:
        span = tracer.start_span("vapviz.budget_exceeded")
        span.set_attribute("vapviz.run_id", report.run_id)
        span.set_attribute("vapviz.cost_usd", report.cost_usd)
        if report.duration_ms is not None:
            span.set_attribute("vapviz.duration_ms", report.duration_ms)
        span.set_attribute("vapviz.total_tokens", report.total_tokens)
        span.set_attribute("vapviz.violations", [v.metric for v in report.violations])
        span.set_status(Status(StatusCode.ERROR, _summary(report)))
        span.end()
    return _send
