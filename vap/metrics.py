"""
Cross-run analytics for VaP.

``compute_metrics`` is a pure function that takes a list of ``RunGraph``
snapshots and returns aggregate statistics used by the ``/metrics`` endpoint
and the dashboard UI: run counts, success rate, total/average cost and
duration, token totals, a per-model breakdown, a per-kind node count, and a
daily cost-over-time series.

It reads the same node-data shape every integration produces:

* LLM node label  ──  ``llm/{model}``
* ``node.data["input"]["model"]``           ── model name
* ``node.data["output"]["usage"]``          ── ``{input_tokens, output_tokens}``
* ``node.data["output"]["cost_usd"]``       ── float
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from .events import NodeKind, NodeStatus, RunGraph


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class TokenTotals(BaseModel):
    input: int = 0
    output: int = 0


class ModelStat(BaseModel):
    model: str
    calls: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


class KindCounts(BaseModel):
    agent: int = 0
    step: int = 0
    tool: int = 0
    llm: int = 0


class DailyCost(BaseModel):
    date: str               # YYYY-MM-DD (UTC)
    cost_usd: float = 0.0
    run_count: int = 0


class Metrics(BaseModel):
    run_count: int = 0
    success_count: int = 0
    error_count: int = 0
    running_count: int = 0
    success_rate: Optional[float] = None        # over completed runs, 0..1

    total_cost_usd: float = 0.0
    avg_cost_usd: Optional[float] = None         # per run that has any cost

    total_duration_ms: float = 0.0
    avg_duration_ms: Optional[float] = None      # per completed run

    total_nodes: int = 0
    total_llm_calls: int = 0
    total_tokens: TokenTotals = Field(default_factory=TokenTotals)

    by_model: list[ModelStat] = Field(default_factory=list)
    by_kind: KindCounts = Field(default_factory=KindCounts)
    cost_over_time: list[DailyCost] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _model_of(node) -> str:
    """Best-effort model name for an LLM node."""
    data = node.data or {}
    inp = data.get("input")
    if isinstance(inp, dict):
        model = inp.get("model")
        if model:
            return str(model)
    # Fallback: strip the "llm/" label prefix
    if node.label.startswith("llm/"):
        return node.label[4:]
    return node.label or "unknown"


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_metrics(graphs: list[RunGraph]) -> Metrics:
    """Aggregate a list of run graphs into a :class:`Metrics` snapshot."""
    m = Metrics(run_count=len(graphs))

    model_acc: dict[str, ModelStat] = {}
    daily_cost: dict[str, float] = defaultdict(float)
    daily_runs: dict[str, int] = defaultdict(int)
    cost_run_count = 0       # runs that contributed any cost
    duration_run_count = 0   # completed runs with a measurable duration

    for g in graphs:
        # ── run status ─────────────────────────────────────────────
        if g.status == NodeStatus.SUCCESS:
            m.success_count += 1
        elif g.status == NodeStatus.ERROR:
            m.error_count += 1
        else:
            m.running_count += 1

        # ── duration ───────────────────────────────────────────────
        if g.ended_at is not None and g.started_at is not None:
            dur_ms = (g.ended_at - g.started_at) * 1000.0
            if dur_ms >= 0:
                m.total_duration_ms += dur_ms
                duration_run_count += 1

        # ── per-run accumulators ───────────────────────────────────
        run_cost = 0.0
        day = _day(g.started_at)
        daily_runs[day] += 1

        for node in g.nodes:
            m.total_nodes += 1

            kind = node.kind
            if kind == NodeKind.AGENT:
                m.by_kind.agent += 1
            elif kind == NodeKind.STEP:
                m.by_kind.step += 1
            elif kind == NodeKind.TOOL:
                m.by_kind.tool += 1
            elif kind == NodeKind.LLM:
                m.by_kind.llm += 1

            if kind != NodeKind.LLM:
                continue

            m.total_llm_calls += 1
            output = node.data.get("output") if isinstance(node.data, dict) else None
            output = output if isinstance(output, dict) else {}

            model = _model_of(node)
            stat = model_acc.get(model)
            if stat is None:
                stat = ModelStat(model=model)
                model_acc[model] = stat
            stat.calls += 1

            usage = output.get("usage")
            if isinstance(usage, dict):
                in_tok = int(usage.get("input_tokens") or 0)
                out_tok = int(usage.get("output_tokens") or 0)
                m.total_tokens.input += in_tok
                m.total_tokens.output += out_tok
                stat.input_tokens += in_tok
                stat.output_tokens += out_tok

            cost = output.get("cost_usd")
            if isinstance(cost, (int, float)):
                m.total_cost_usd += cost
                stat.cost_usd += cost
                run_cost += cost

        if run_cost > 0:
            cost_run_count += 1
            daily_cost[day] += run_cost

    # ── derived aggregates ─────────────────────────────────────────
    completed = m.success_count + m.error_count
    if completed:
        m.success_rate = round(m.success_count / completed, 4)
    if cost_run_count:
        m.avg_cost_usd = round(m.total_cost_usd / cost_run_count, 8)
    if duration_run_count:
        m.avg_duration_ms = round(m.total_duration_ms / duration_run_count, 2)

    m.total_cost_usd = round(m.total_cost_usd, 8)
    m.total_duration_ms = round(m.total_duration_ms, 2)

    # by_model — sort by cost desc, then calls desc
    m.by_model = sorted(
        (
            ModelStat(
                model=s.model,
                calls=s.calls,
                cost_usd=round(s.cost_usd, 8),
                input_tokens=s.input_tokens,
                output_tokens=s.output_tokens,
            )
            for s in model_acc.values()
        ),
        key=lambda s: (s.cost_usd, s.calls),
        reverse=True,
    )

    # cost_over_time — chronological, one bucket per day that has a run
    m.cost_over_time = [
        DailyCost(date=d, cost_usd=round(daily_cost.get(d, 0.0), 8), run_count=daily_runs[d])
        for d in sorted(daily_runs.keys())
    ]

    return m
