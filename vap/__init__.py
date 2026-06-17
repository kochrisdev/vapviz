from .tracer import trace, atrace, get_current_step, Tracer
from .store import default_store, RunStore, MemoryStore
from .server import create_app, app
from .integrations.anthropic_sdk import patch_anthropic
from .integrations.openai_sdk import patch_openai
from .backends.sqlite import SqliteStore
from .cost import calculate_cost, format_cost
from .metrics import compute_metrics, Metrics
from .budgets import Budget, BudgetReport, check_budget, enable_budget_alerts
from .evals import (
    Check,
    CheckResult,
    EvalResult,
    eval_run,
    run_checks,
    max_cost,
    max_latency,
    max_tokens,
    no_errors,
    output_contains,
    custom,
    judge,
)


def configure(db: str | None = None) -> None:
    """
    Configure the module-level VaP store backend.

    Call this once before any ``trace()`` / ``atrace()`` calls.

    Args:
        db: Path to a SQLite database file. Runs are persisted across
            server restarts. If *None*, the default in-memory store is used.

    Example::

        import vap
        vap.configure(db="vap.db")          # persist to SQLite

        with vap.trace("My agent") as run:
            ...
    """
    import sys
    import vap.store as _sm

    new_store: RunStore = SqliteStore(db) if db is not None else MemoryStore()
    _sm.default_store = new_store
    # Also update the binding on this module so vap.default_store stays current
    sys.modules[__name__].default_store = new_store


__all__ = [
    # Tracing
    "trace",
    "atrace",
    "get_current_step",
    "Tracer",
    # Store
    "default_store",
    "RunStore",
    "MemoryStore",
    "SqliteStore",
    # Server
    "create_app",
    "app",
    # Integrations
    "patch_anthropic",
    "patch_openai",
    # Cost
    "calculate_cost",
    "format_cost",
    # Metrics
    "compute_metrics",
    "Metrics",
    # Budgets
    "Budget",
    "BudgetReport",
    "check_budget",
    "enable_budget_alerts",
    # Evals
    "Check",
    "CheckResult",
    "EvalResult",
    "eval_run",
    "run_checks",
    "max_cost",
    "max_latency",
    "max_tokens",
    "no_errors",
    "output_contains",
    "custom",
    "judge",
    # Configuration
    "configure",
]
