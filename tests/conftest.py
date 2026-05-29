"""Shared pytest fixtures for the VaP test suite."""
from __future__ import annotations

import asyncio
import pytest

from vap.store import MemoryStore
from vap.tracer import Tracer


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
