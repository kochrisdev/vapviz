"""
Eval suites & CI gating for vapviz.

An **eval suite** is a declarative bundle of checks (the same specs
:func:`vapviz.evals.run_checks` understands) plus a way to point at the runs to
evaluate. :func:`run_suite` applies the suite to a set of run graphs and returns
a :class:`SuiteReport`; the ``vapviz eval`` CLI turns a failing report into a
non-zero exit code, so agent regressions can **fail a CI build**.

A suite file (YAML or JSON)::

    name: support-agent
    description: Guardrails for the support agent
    checks:
      - type: max_cost
        value: 0.02
      - type: max_latency
        value: 3.0
      - type: no_errors
      - type: output_contains
        value: ticket

Runs come from a persisted SQLite store (``--db runs.db``), an exported run file
(``--run vapviz-<id>.json``, the format of ``GET /runs/{id}/export``), or a
directory of such files (``--runs-dir``). See :func:`load_runs`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .evals import EvalResult, eval_run
from .evals import _check_from_spec  # declarative spec -> Check
from .events import RunGraph


# ---------------------------------------------------------------------------
# Suite model
# ---------------------------------------------------------------------------

class EvalSuite(BaseModel):
    """A named bundle of declarative checks applied to one or more runs."""

    name: str = "eval-suite"
    description: str = ""
    checks: list[dict] = Field(default_factory=list)

    def build_checks(self):
        """Materialise the declarative specs into :class:`vapviz.evals.Check` objects.

        Raises ``ValueError`` if a spec is malformed (surfaced early, before any run
        is evaluated, so a broken suite fails fast rather than per-run).
        """
        return [_check_from_spec(spec) for spec in self.checks]


class RunEval(BaseModel):
    """The result of evaluating one run against the suite."""

    run_id: str
    label: str = ""
    result: EvalResult


class SuiteReport(BaseModel):
    """The outcome of running a suite over a set of runs."""

    suite: str
    passed: bool
    total: int = 0
    passed_count: int = 0
    failed_count: int = 0
    runs: list[RunEval] = Field(default_factory=list)

    def summary(self) -> str:
        """A plain-text report suitable for a terminal / CI log."""
        head = (
            f"{'PASSED' if self.passed else 'FAILED'}  suite '{self.suite}': "
            f"{self.passed_count}/{self.total} runs passed"
        )
        lines = [head]
        for r in self.runs:
            mark = "PASS" if r.result.passed else "FAIL"
            label = f" {r.label}" if r.label else ""
            lines.append(f"  [{mark}] {r.run_id}{label}  ({r.result.score:.0%})")
            if not r.result.passed:
                for c in r.result.checks:
                    if not c.passed:
                        lines.append(f"         - {c.name}: {c.detail}")
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """A Markdown report for a GitHub Actions step summary."""
        status = "✅ passed" if self.passed else "❌ failed"
        out = [
            f"## vapviz eval — `{self.suite}` {status}",
            "",
            f"**{self.passed_count}/{self.total}** runs passed.",
            "",
            "| Run | Label | Result | Score | Failing checks |",
            "| --- | --- | --- | --- | --- |",
        ]
        for r in self.runs:
            mark = "✅" if r.result.passed else "❌"
            fails = ", ".join(c.name for c in r.result.checks if not c.passed) or "—"
            out.append(
                f"| `{r.run_id}` | {r.label or '—'} | {mark} | {r.result.score:.0%} | {fails} |"
            )
        return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Loading suites
# ---------------------------------------------------------------------------

def load_suite(path: str | os.PathLike) -> EvalSuite:
    """Load an :class:`EvalSuite` from a YAML or JSON file.

    ``.json`` is parsed with the stdlib; ``.yaml`` / ``.yml`` need PyYAML
    (``pip install pyyaml``) and raise a clear error if it is missing.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()

    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise ImportError(
                f"reading a YAML suite ({p.name}) requires PyYAML — install it with "
                "`pip install pyyaml`, or use a .json suite file"
            ) from exc
        data = yaml.safe_load(text) or {}
    elif suffix == ".json":
        data = json.loads(text)
    else:
        # Be forgiving: try JSON, then YAML if available.
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                import yaml
            except ImportError as exc:  # pragma: no cover
                raise ValueError(
                    f"could not parse suite {p.name} as JSON and PyYAML is not installed"
                ) from exc
            data = yaml.safe_load(text) or {}

    if not isinstance(data, dict):
        raise ValueError(f"suite {p.name} must be a mapping with a 'checks' list")
    return EvalSuite.model_validate(data)


# ---------------------------------------------------------------------------
# Loading runs
# ---------------------------------------------------------------------------

def _load_graph_file(path: Path) -> RunGraph:
    return RunGraph.model_validate_json(path.read_text(encoding="utf-8"))


def load_runs(
    *,
    db: Optional[str] = None,
    run_file: Optional[str] = None,
    runs_dir: Optional[str] = None,
    run_id: Optional[str] = None,
    label: Optional[str] = None,
    tag: Optional[str] = None,
    latest: bool = False,
) -> list[RunGraph]:
    """Collect the run graphs to evaluate from one source.

    Exactly one *source* must be given:

    * ``db`` — path to a SQLite store written by ``vapviz serve --db`` /
      ``vapviz.configure(db=...)``.
    * ``run_file`` — a single exported run JSON file (``GET /runs/{id}/export``).
    * ``runs_dir`` — a directory of exported run JSON files (``*.json``).

    For ``db``, the *filters* narrow which runs are returned: ``run_id`` (one
    run), ``label`` (exact label match), ``tag`` (runs carrying that tag), and/or
    ``latest`` (only the most recent match). With no filter, every run is
    returned. Filters are ignored for file sources.
    """
    sources = [s for s in (db, run_file, runs_dir) if s]
    if len(sources) != 1:
        raise ValueError("provide exactly one of: db, run_file, runs_dir")

    if run_file:
        return [_load_graph_file(Path(run_file))]

    if runs_dir:
        files = sorted(Path(runs_dir).glob("*.json"))
        if not files:
            raise ValueError(f"no *.json run files found in {runs_dir}")
        return [_load_graph_file(f) for f in files]

    # db source
    from .backends.sqlite import SqliteStore

    store = SqliteStore(db)
    summaries = store.list_runs()  # newest first

    if run_id is not None:
        summaries = [s for s in summaries if s.run_id == run_id]
    if label is not None:
        summaries = [s for s in summaries if s.label == label]
    if tag is not None:
        summaries = [s for s in summaries if tag in (store.get_tags(s.run_id) or [])]
    if latest:
        summaries = summaries[:1]

    graphs: list[RunGraph] = []
    for s in summaries:
        g = store.get_graph(s.run_id)
        if g is not None:
            graphs.append(g)
    return graphs


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_suite(suite: EvalSuite, graphs: list[RunGraph]) -> SuiteReport:
    """Apply *suite* to every graph in *graphs* and return a :class:`SuiteReport`.

    The report ``passed`` only if **every** run passed **and** at least one run was
    evaluated — an empty run set is treated as a failure so a mis-pointed CI job
    can't pass by evaluating nothing.
    """
    checks = suite.build_checks()  # fail fast on a malformed suite

    runs: list[RunEval] = []
    for g in graphs:
        result = eval_run(g, checks)
        runs.append(RunEval(run_id=g.run_id, label=g.label or "", result=result))

    passed_count = sum(1 for r in runs if r.result.passed)
    failed_count = len(runs) - passed_count
    all_passed = bool(runs) and failed_count == 0

    return SuiteReport(
        suite=suite.name,
        passed=all_passed,
        total=len(runs),
        passed_count=passed_count,
        failed_count=failed_count,
        runs=runs,
    )
