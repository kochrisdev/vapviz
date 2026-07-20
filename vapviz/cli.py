from __future__ import annotations

import argparse
import os
import sys


def _serve(args: argparse.Namespace) -> None:
    import uvicorn
    from vapviz.server import create_app
    import vapviz.store as _sm

    if args.db:
        from vapviz.backends.sqlite import SqliteStore
        store = SqliteStore(args.db)
        _sm.default_store = store          # in-process tracers pick this up
        print(f"[vapviz] Using SQLite store: {args.db}")
    else:
        from vapviz.store import MemoryStore
        store = MemoryStore()
        print("[vapviz] Using in-memory store (runs will be lost on restart)")
        print("[vapviz] Pass --db <path> to persist runs to SQLite")

    if args.static_dir:
        print(f"[vapviz] Serving UI from: {args.static_dir}")

    app = create_app(store=store, static_dir=args.static_dir)

    print(f"[vapviz] Server starting on http://{args.host}:{args.port}")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


def _eval(args: argparse.Namespace) -> int:
    """Run an eval suite and return a process exit code (0 = pass, 1 = fail).

    This is the CI gate: it exits non-zero when any run fails the suite (or when
    no runs were found), so it can guard a build.
    """
    from vapviz.evalsuite import load_runs, load_suite, run_suite

    try:
        suite = load_suite(args.suite)
        graphs = load_runs(
            db=args.db,
            run_file=args.run,
            runs_dir=args.runs_dir,
            run_id=args.run_id,
            label=args.label,
            tag=args.tag,
            latest=args.latest,
        )
    except (ValueError, ImportError, FileNotFoundError, OSError) as exc:
        print(f"[vapviz eval] error: {exc}", file=sys.stderr)
        return 2

    report = run_suite(suite, graphs)

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(report.summary())

    # Optionally append a Markdown summary to the GitHub Actions step summary.
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if args.github_summary and summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(report.to_markdown())
        except OSError:
            pass  # never fail the gate because the summary couldn't be written

    return 0 if report.passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vapviz",
        description="vapviz — Visualization Agentic Process",
    )
    sub = parser.add_subparsers(dest="command")

    # ── vapviz serve ──────────────────────────────────────────────────────
    serve = sub.add_parser("serve", help="Start the vapviz server")
    serve.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    serve.add_argument("--port", type=int, default=8001, help="Bind port (default: 8001)")
    serve.add_argument("--db", default=None, metavar="PATH",
                       help="SQLite database path for persistence (default: in-memory)")
    serve.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    serve.add_argument("--log-level", default="warning",
                       choices=["debug", "info", "warning", "error", "critical"])
    serve.add_argument("--static-dir", default=None, metavar="PATH",
                       help="Serve the built React UI from this directory (e.g. ui/dist)")

    # ── vapviz eval ───────────────────────────────────────────────────────
    ev = sub.add_parser(
        "eval",
        help="Run an eval suite against traced runs; exit non-zero on failure (CI gate)",
    )
    ev.add_argument("--suite", required=True, metavar="PATH",
                    help="Eval suite file (YAML or JSON)")
    src = ev.add_mutually_exclusive_group(required=True)
    src.add_argument("--db", default=None, metavar="PATH",
                     help="SQLite store to load runs from")
    src.add_argument("--run", default=None, metavar="PATH",
                     help="A single exported run JSON file")
    src.add_argument("--runs-dir", default=None, metavar="DIR",
                     help="A directory of exported run JSON files (*.json)")
    ev.add_argument("--run-id", default=None, help="Only evaluate this run id (with --db)")
    ev.add_argument("--label", default=None, help="Only evaluate runs with this label (with --db)")
    ev.add_argument("--tag", default=None, help="Only evaluate runs carrying this tag (with --db)")
    ev.add_argument("--latest", action="store_true",
                    help="Only evaluate the most recent matching run (with --db)")
    ev.add_argument("--json", action="store_true", help="Print the report as JSON")
    ev.add_argument("--github-summary", action="store_true",
                    help="Append a Markdown report to $GITHUB_STEP_SUMMARY")

    args = parser.parse_args()

    if args.command == "serve":
        _serve(args)
    elif args.command == "eval":
        sys.exit(_eval(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
