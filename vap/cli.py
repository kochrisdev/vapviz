from __future__ import annotations

import argparse
import sys


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    if args.db:
        from vap.backends.sqlite import SqliteStore
        from vap.server import create_app
        import vap.store as _sm

        store = SqliteStore(args.db)
        _sm.default_store = store          # in-process tracers pick this up
        app = create_app(store=store)
        print(f"[vap] Using SQLite store: {args.db}")
    else:
        from vap.server import app
        print("[vap] Using in-memory store (runs will be lost on restart)")
        print("[vap] Pass --db <path> to persist runs to SQLite")

    print(f"[vap] Server starting on http://{args.host}:{args.port}")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vap",
        description="VaP — Visualization Agentic Process",
    )
    sub = parser.add_subparsers(dest="command")

    # ── vap serve ──────────────────────────────────────────────────────
    serve = sub.add_parser("serve", help="Start the VaP server")
    serve.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    serve.add_argument("--port", type=int, default=8001, help="Bind port (default: 8001)")
    serve.add_argument("--db", default=None, metavar="PATH",
                       help="SQLite database path for persistence (default: in-memory)")
    serve.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    serve.add_argument("--log-level", default="warning",
                       choices=["debug", "info", "warning", "error", "critical"])

    args = parser.parse_args()

    if args.command == "serve":
        _serve(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
