"""Tests for vapviz/evalsuite.py — eval suites, run_suite, load_runs, and the CLI gate."""
from __future__ import annotations

import json
import uuid

import pytest

from vapviz.evals import _check_from_spec
from vapviz.evalsuite import (
    EvalSuite,
    SuiteReport,
    load_runs,
    load_suite,
    run_suite,
)
from vapviz.events import GraphNode, NodeKind, NodeStatus, RunGraph


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _graph(run_id, *, cost, text, duration_s=1.0, error=False):
    llm = GraphNode(
        id=uuid.uuid4().hex[:12], kind=NodeKind.LLM, label="llm/m",
        status=NodeStatus.ERROR if error else NodeStatus.SUCCESS,
        data={"input": {"model": "m"},
              "output": {"usage": {"input_tokens": 10, "output_tokens": 10},
                         "cost_usd": cost, "text": text}},
    )
    root = GraphNode(id="r", kind=NodeKind.AGENT, label="agent",
                     status=NodeStatus.SUCCESS, started_at=100.0, ended_at=100.0 + duration_s)
    return RunGraph(run_id=run_id, label="support", status=NodeStatus.SUCCESS,
                    nodes=[root, llm], started_at=100.0, ended_at=100.0 + duration_s)


CHECKS = [
    {"type": "max_cost", "value": 0.02},
    {"type": "no_errors"},
    {"type": "output_contains", "value": "ticket"},
]


# ---------------------------------------------------------------------------
# Suite loading
# ---------------------------------------------------------------------------

class TestLoadSuite:
    def test_load_json(self, tmp_path):
        p = tmp_path / "suite.json"
        p.write_text(json.dumps({"name": "s", "checks": CHECKS}), encoding="utf-8")
        suite = load_suite(p)
        assert suite.name == "s"
        assert len(suite.checks) == 3
        assert len(suite.build_checks()) == 3      # all specs materialise

    def test_load_yaml(self, tmp_path):
        pytest.importorskip("yaml")
        p = tmp_path / "suite.yaml"
        p.write_text(
            "name: yaml-suite\nchecks:\n  - type: max_cost\n    value: 0.02\n  - type: no_errors\n",
            encoding="utf-8",
        )
        suite = load_suite(p)
        assert suite.name == "yaml-suite"
        assert [c["type"] for c in suite.checks] == ["max_cost", "no_errors"]

    def test_malformed_check_fails_fast(self):
        suite = EvalSuite(name="bad", checks=[{"type": "nope"}])
        with pytest.raises(ValueError):
            suite.build_checks()

    def test_non_mapping_rejected(self, tmp_path):
        p = tmp_path / "suite.json"
        p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(ValueError):
            load_suite(p)


# ---------------------------------------------------------------------------
# run_suite
# ---------------------------------------------------------------------------

class TestRunSuite:
    def test_all_pass(self):
        suite = EvalSuite(name="s", checks=CHECKS)
        g = _graph("ok", cost=0.01, text="created a ticket")
        report = run_suite(suite, [g])
        assert report.passed
        assert report.total == 1 and report.passed_count == 1 and report.failed_count == 0

    def test_one_failure_fails_suite(self):
        suite = EvalSuite(name="s", checks=CHECKS)
        good = _graph("ok", cost=0.01, text="here is your ticket")
        bad = _graph("bad", cost=0.09, text="no idea")
        report = run_suite(suite, [good, bad])
        assert not report.passed
        assert report.passed_count == 1 and report.failed_count == 1
        failing = next(r for r in report.runs if r.run_id == "bad")
        names = {c.name for c in failing.result.checks if not c.passed}
        assert any("max_cost" in n for n in names)

    def test_empty_run_set_is_failure(self):
        # A mis-pointed CI job that evaluates nothing must NOT pass.
        report = run_suite(EvalSuite(name="s", checks=CHECKS), [])
        assert not report.passed
        assert report.total == 0

    def test_markdown_and_summary(self):
        report = run_suite(EvalSuite(name="s", checks=CHECKS),
                           [_graph("ok", cost=0.01, text="ticket")])
        assert "vapviz eval" in report.to_markdown()
        assert "PASSED" in report.summary()


# ---------------------------------------------------------------------------
# load_runs
# ---------------------------------------------------------------------------

class TestLoadRuns:
    def test_run_file(self, tmp_path):
        g = _graph("f1", cost=0.01, text="ticket")
        p = tmp_path / "vapviz-f1.json"
        p.write_text(g.model_dump_json(), encoding="utf-8")
        runs = load_runs(run_file=str(p))
        assert len(runs) == 1 and runs[0].run_id == "f1"

    def test_runs_dir(self, tmp_path):
        for i in range(3):
            g = _graph(f"r{i}", cost=0.01, text="ticket")
            (tmp_path / f"vapviz-r{i}.json").write_text(g.model_dump_json(), encoding="utf-8")
        runs = load_runs(runs_dir=str(tmp_path))
        assert {r.run_id for r in runs} == {"r0", "r1", "r2"}

    def test_runs_dir_empty_errors(self, tmp_path):
        with pytest.raises(ValueError):
            load_runs(runs_dir=str(tmp_path))

    def test_requires_exactly_one_source(self):
        with pytest.raises(ValueError):
            load_runs()
        with pytest.raises(ValueError):
            load_runs(run_file="a.json", runs_dir="b/")

    def test_db_with_filters(self, tmp_path):
        import vapviz
        from vapviz.backends.sqlite import SqliteStore

        db = str(tmp_path / "runs.db")
        store = SqliteStore(db)
        tracer = vapviz.Tracer(store=store)
        for cost, label in [(0.01, "alpha"), (0.09, "beta")]:
            with tracer.trace(label) as run:
                with run.step("think", kind="llm") as step:
                    step.set_output({"usage": {"input_tokens": 5, "output_tokens": 5},
                                     "cost_usd": cost, "text": "ticket"})

        assert len(load_runs(db=db)) == 2
        assert len(load_runs(db=db, latest=True)) == 1
        alpha = load_runs(db=db, label="alpha")
        assert len(alpha) == 1 and alpha[0].label == "alpha"


# ---------------------------------------------------------------------------
# CLI gate — exit codes
# ---------------------------------------------------------------------------

class TestCliGate:
    def _run_cli(self, argv):
        import vapviz.cli as cli

        parser_ns = self._parse(argv)
        return cli._eval(parser_ns)

    def _parse(self, argv):
        # Build the same Namespace the parser would, without invoking sys.exit.
        import argparse

        ns = argparse.Namespace(
            suite=None, db=None, run=None, runs_dir=None, run_id=None,
            label=None, tag=None, latest=False, json=False, github_summary=False,
        )
        for k, v in argv.items():
            setattr(ns, k, v)
        return ns

    def test_pass_exits_0(self, tmp_path, capsys):
        suite = tmp_path / "s.json"
        suite.write_text(json.dumps({"name": "s", "checks": CHECKS}), encoding="utf-8")
        g = _graph("ok", cost=0.01, text="ticket")
        run = tmp_path / "run.json"
        run.write_text(g.model_dump_json(), encoding="utf-8")
        code = self._run_cli({"suite": str(suite), "run": str(run)})
        assert code == 0
        assert "PASSED" in capsys.readouterr().out

    def test_fail_exits_1(self, tmp_path):
        suite = tmp_path / "s.json"
        suite.write_text(json.dumps({"name": "s", "checks": CHECKS}), encoding="utf-8")
        g = _graph("bad", cost=0.09, text="no idea")
        run = tmp_path / "run.json"
        run.write_text(g.model_dump_json(), encoding="utf-8")
        assert self._run_cli({"suite": str(suite), "run": str(run)}) == 1

    def test_bad_source_exits_2(self, tmp_path):
        suite = tmp_path / "s.json"
        suite.write_text(json.dumps({"name": "s", "checks": CHECKS}), encoding="utf-8")
        assert self._run_cli({"suite": str(suite), "run": str(tmp_path / "missing.json")}) == 2

    def test_github_summary_written(self, tmp_path, monkeypatch):
        suite = tmp_path / "s.json"
        suite.write_text(json.dumps({"name": "s", "checks": CHECKS}), encoding="utf-8")
        g = _graph("ok", cost=0.01, text="ticket")
        run = tmp_path / "run.json"
        run.write_text(g.model_dump_json(), encoding="utf-8")
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        code = self._run_cli({"suite": str(suite), "run": str(run), "github_summary": True})
        assert code == 0
        assert "vapviz eval" in summary.read_text(encoding="utf-8")
