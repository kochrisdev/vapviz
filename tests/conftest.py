"""Shared pytest fixtures for the VaP test suite."""
from __future__ import annotations

import asyncio
import pytest

from vap.store import MemoryStore
from vap.tracer import Tracer, _current_step


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
