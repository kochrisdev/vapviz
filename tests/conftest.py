"""Shared pytest fixtures for the vapviz test suite."""
from __future__ import annotations

import asyncio
import pytest

from vapviz.store import MemoryStore
from vapviz.tracer import Tracer, _current_step


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: real-LLM test that hits OpenRouter (paid, slow). Auto-applied "
        "to every tests/*_integration.py file. The fast/free gate runs "
        "`-m 'not integration'`; a plain `pytest` still runs everything.",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-mark every test in a *_integration.py file as `integration`."""
    for item in items:
        if item.path.name.endswith("_integration.py"):
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def store() -> MemoryStore:
    """Fresh in-memory store for each test."""
    return MemoryStore()


@pytest.fixture
def tracer(store: MemoryStore) -> Tracer:
    """Tracer wired to an isolated store."""
    return Tracer(store=store)


@pytest.fixture(autouse=True)
def _clean_current_step():
    """Ensure _current_step is None before and after every test.

    Prevents cross-test contamination when a test calls RunContext._start()
    (which sets _current_step) without a matching _end() call.
    """
    yield
    if _current_step.get() is not None:
        _current_step.set(None)


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()
