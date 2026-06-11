"""Shared pytest fixtures for the VaP test suite."""
from __future__ import annotations

import asyncio
import pytest

from vap.store import MemoryStore
from vap.tracer import Tracer, _current_step


@pytest.fixture(autouse=True)
def _reset_current_step():
    """Keep the parent-tracking ContextVar from leaking between tests.

    Tests that drive RunContext/StepContext directly (e.g. the CrewAI
    listener tests) may leave ``_current_step`` set, which breaks later
    tests that expect a clean context.
    """
    yield
    _current_step.set(None)


@pytest.fixture
def store() -> MemoryStore:
    """Fresh in-memory store for each test."""
    return MemoryStore()


@pytest.fixture
def tracer(store: MemoryStore) -> Tracer:
    """Tracer wired to an isolated store."""
    return Tracer(store=store)


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()
