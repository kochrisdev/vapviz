"""Tests for run search & tagging — vap/search.py, store tags, and the endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vap.backends.sqlite import SqliteStore
from vap.events import NodeStatus
from vap.search import run_matches
from vap.server import create_app
from vap.store import MemoryStore
from vap.tracer import Tracer


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _build(store, label, *, tools=(), llm_text=None, error=False, run_id=None):
    tracer = Tracer(store=store)
    with tracer.trace(label, run_id=run_id) as run:
        for t in tools:
            with run.step(t, kind="tool") as s:
                s.set_input({"q": f"query for {t}"})
                s.set_output({"result": f"{t} done"})
        if llm_text is not None:
            with run.step("ask", kind="llm") as s:
                s.set_input({"model": "gpt-4o"})
                s.set_output({"text": llm_text})
        if error:
            try:
                with run.step("boom", kind="tool"):
                    raise ValueError("kaboom")
            except ValueError:
                pass
    return run


# ---------------------------------------------------------------------------
# run_matches (pure)
# ---------------------------------------------------------------------------

class TestRunMatches:
    def test_query_matches_run_label(self):
        store = MemoryStore()
        run = _build(store, "Weather Agent")
        g = store.get_graph(run.run_id)
        assert run_matches(g, query="weather")
        assert not run_matches(g, query="banana")

    def test_query_matches_node_output(self):
        store = MemoryStore()
        run = _build(store, "Agent", llm_text="the capital of France is Paris")
        g = store.get_graph(run.run_id)
        assert run_matches(g, query="paris")          # case-insensitive, in output
        assert run_matches(g, query="capital")

    def test_query_matches_tool_input(self):
        store = MemoryStore()
        run = _build(store, "Agent", tools=["search_web"])
        g = store.get_graph(run.run_id)
        assert run_matches(g, query="query for search_web")

    def test_status_filter(self):
        store = MemoryStore()
        ok = store.get_graph(_build(store, "ok run").run_id)
        # A run whose error propagates out of the trace ends with status "error".
        tracer = Tracer(store=store)
        bad_run = None
        try:
            with tracer.trace("bad run") as bad_run:
                raise ValueError("boom")
        except ValueError:
            pass
        bad = store.get_graph(bad_run.run_id)
        assert run_matches(ok, status="success")
        assert not run_matches(ok, status="error")
        assert run_matches(bad, status="error")

    def test_kind_filter(self):
        store = MemoryStore()
        g = store.get_graph(_build(store, "Agent", llm_text="hi").run_id)
        assert run_matches(g, kind="llm")
        assert not run_matches(g, kind="tool")

    def test_tool_filter(self):
        store = MemoryStore()
        g = store.get_graph(_build(store, "Agent", tools=["search_web", "calculator"]).run_id)
        assert run_matches(g, tool="search")
        assert not run_matches(g, tool="translate")

    def test_filters_combine(self):
        store = MemoryStore()
        g = store.get_graph(_build(store, "Agent", tools=["search_web"], llm_text="paris").run_id)
        assert run_matches(g, query="paris", status="success", kind="tool")
        assert not run_matches(g, query="paris", status="error")

    def test_empty_query_matches_all(self):
        store = MemoryStore()
        g = store.get_graph(_build(store, "Agent").run_id)
        assert run_matches(g)


# ---------------------------------------------------------------------------
# Store tags
# ---------------------------------------------------------------------------

class TestStoreTags:
    def test_set_and_get_tags_memory(self):
        store = MemoryStore()
        run = _build(store, "Agent")
        store.set_tags(run.run_id, ["prod", "v2"])
        assert store.get_tags(run.run_id) == ["prod", "v2"]
        assert store.get_run(run.run_id).tags == ["prod", "v2"]

    def test_tags_normalised(self):
        store = MemoryStore()
        run = _build(store, "Agent")
        assert store.set_tags(run.run_id, [" prod ", "prod", "", "v2"]) == ["prod", "v2"]

    def test_clearing_tags(self):
        store = MemoryStore()
        run = _build(store, "Agent")
        store.set_tags(run.run_id, ["x"])
        store.set_tags(run.run_id, [])
        assert store.get_tags(run.run_id) == []

    def test_delete_run_removes_tags(self):
        store = MemoryStore()
        run = _build(store, "Agent")
        store.set_tags(run.run_id, ["x"])
        store.delete_run(run.run_id)
        assert store.get_tags(run.run_id) == []

    def test_tags_persist_in_sqlite(self, tmp_path):
        db = str(tmp_path / "t.db")
        store = SqliteStore(db)
        run = _build(store, "Agent")
        store.set_tags(run.run_id, ["prod", "rag"])
        store.close()

        reopened = SqliteStore(db)
        assert reopened.get_tags(run.run_id) == ["prod", "rag"]
        assert reopened.get_run(run.run_id).tags == ["prod", "rag"]
        reopened.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client():
    store = MemoryStore()
    app = create_app(store=store)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, store


class TestEndpoints:
    def test_search_by_query(self, app_client):
        client, store = app_client
        _build(store, "Weather agent", llm_text="sunny in Paris")
        _build(store, "Math agent", llm_text="the answer is 42")
        r = client.get("/search", params={"q": "paris"})
        assert r.status_code == 200
        labels = [x["label"] for x in r.json()]
        assert labels == ["Weather agent"]

    def test_search_by_tool(self, app_client):
        client, store = app_client
        _build(store, "A", tools=["search_web"])
        _build(store, "B", tools=["calculator"])
        r = client.get("/search", params={"tool": "search"})
        assert [x["label"] for x in r.json()] == ["A"]

    def test_search_by_tag(self, app_client):
        client, store = app_client
        run = _build(store, "Tagged")
        _build(store, "Untagged")
        store.set_tags(run.run_id, ["prod"])
        r = client.get("/search", params={"tag": "prod"})
        assert [x["label"] for x in r.json()] == ["Tagged"]

    def test_put_and_get_tags_endpoint(self, app_client):
        client, store = app_client
        run = _build(store, "Agent")
        put = client.put(f"/runs/{run.run_id}/tags", json={"tags": ["a", "b", "a"]})
        assert put.status_code == 200
        assert put.json() == ["a", "b"]
        assert client.get(f"/runs/{run.run_id}/tags").json() == ["a", "b"]
        # tags also surface in the run list
        listed = next(x for x in client.get("/runs").json() if x["run_id"] == run.run_id)
        assert listed["tags"] == ["a", "b"]

    def test_tags_endpoint_unknown_run(self, app_client):
        client, _ = app_client
        assert client.put("/runs/nope/tags", json={"tags": ["x"]}).status_code == 404
