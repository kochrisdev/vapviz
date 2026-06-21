"""Tests for the FastAPI server endpoints (vapviz/server.py)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vapviz.events import EventType, NodeKind
from vapviz.server import create_app
from vapviz.store import MemoryStore

import time
import uuid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client():
    """Fresh app + store per test."""
    store = MemoryStore()
    app = create_app(store=store)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, store


def _seed_run(store: MemoryStore, label="Test Run") -> str:
    """Insert a minimal completed run into the store, return run_id."""
    from vapviz.events import VapEvent

    run_id = uuid.uuid4().hex[:12]
    root_id = uuid.uuid4().hex[:12]

    def ev(type, node_id, node_kind, node_label, parent_id=None, data=None):
        return VapEvent(
            id=uuid.uuid4().hex[:12],
            run_id=run_id,
            timestamp=time.time(),
            type=type,
            node_id=node_id,
            node_kind=node_kind,
            node_label=node_label,
            parent_id=parent_id,
            data=data or {},
        )

    store.add_event(ev(EventType.AGENT_START, root_id, NodeKind.AGENT, label, data={"label": label}))
    child_id = uuid.uuid4().hex[:12]
    store.add_event(ev(EventType.STEP_START, child_id, NodeKind.STEP, "work", parent_id=root_id))
    store.add_event(ev(EventType.STEP_END, child_id, NodeKind.STEP, "work", parent_id=root_id,
                       data={"input": {}, "output": {"ok": True}}))
    store.add_event(ev(EventType.AGENT_END, root_id, NodeKind.AGENT, label))
    return run_id


# ---------------------------------------------------------------------------
# GET /runs
# ---------------------------------------------------------------------------

class TestListRuns:
    def test_empty(self, app_client):
        client, _ = app_client
        r = client.get("/runs")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_runs(self, app_client):
        client, store = app_client
        _seed_run(store, "Run A")
        _seed_run(store, "Run B")
        r = client.get("/runs")
        assert r.status_code == 200
        labels = {item["label"] for item in r.json()}
        assert labels == {"Run A", "Run B"}

    def test_response_shape(self, app_client):
        client, store = app_client
        _seed_run(store)
        item = client.get("/runs").json()[0]
        for field in ("run_id", "label", "status", "started_at", "node_count", "event_count"):
            assert field in item


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------

class TestGetRun:
    def test_returns_summary(self, app_client):
        client, store = app_client
        run_id = _seed_run(store, "My Run")
        r = client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == run_id
        assert data["label"] == "My Run"

    def test_404_for_missing_run(self, app_client):
        client, _ = app_client
        r = client.get("/runs/doesnotexist")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/graph
# ---------------------------------------------------------------------------

class TestGetGraph:
    def test_returns_graph(self, app_client):
        client, store = app_client
        run_id = _seed_run(store)
        r = client.get(f"/runs/{run_id}/graph")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == run_id
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

    def test_404_for_missing_run(self, app_client):
        client, _ = app_client
        r = client.get("/runs/missing/graph")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/events  (remote ingest)
# ---------------------------------------------------------------------------

class TestIngestEvent:
    def test_ingest_valid_event(self, app_client):
        client, store = app_client
        run_id = uuid.uuid4().hex[:12]
        payload = {
            "id": uuid.uuid4().hex[:12],
            "run_id": run_id,
            "timestamp": time.time(),
            "type": "agent_start",
            "node_id": uuid.uuid4().hex[:12],
            "node_kind": "agent",
            "node_label": "Remote Agent",
            "parent_id": None,
            "data": {"label": "Remote Agent"},
            "schema_version": 1,
        }
        r = client.post(f"/runs/{run_id}/events", json=payload)
        assert r.status_code == 202
        assert store.get_run(run_id) is not None

    def test_run_id_mismatch_returns_400(self, app_client):
        client, _ = app_client
        payload = {
            "id": uuid.uuid4().hex[:12],
            "run_id": "aaaa",
            "timestamp": time.time(),
            "type": "agent_start",
            "node_id": uuid.uuid4().hex[:12],
            "node_kind": "agent",
            "node_label": "X",
            "parent_id": None,
            "data": {},
            "schema_version": 1,
        }
        r = client.post("/runs/bbbb/events", json=payload)
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /runs/{run_id}
# ---------------------------------------------------------------------------

class TestDeleteRun:
    def test_delete_existing_run(self, app_client):
        client, store = app_client
        run_id = _seed_run(store)
        r = client.delete(f"/runs/{run_id}")
        assert r.status_code == 204
        assert store.get_run(run_id) is None

    def test_delete_missing_run_404(self, app_client):
        client, _ = app_client
        r = client.delete("/runs/doesnotexist")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /runs
# ---------------------------------------------------------------------------

class TestClearRuns:
    def test_clears_all_runs(self, app_client):
        client, store = app_client
        _seed_run(store)
        _seed_run(store)
        r = client.delete("/runs")
        assert r.status_code == 204
        assert store.list_runs() == []


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/export
# ---------------------------------------------------------------------------

class TestExportRun:
    def test_export_returns_json_attachment(self, app_client):
        client, store = app_client
        run_id = _seed_run(store, "Export Run")
        r = client.get(f"/runs/{run_id}/export")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]
        assert "attachment" in r.headers.get("content-disposition", "")
        assert f"{run_id}.json" in r.headers.get("content-disposition", "")
        data = r.json()
        assert data["run_id"] == run_id
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 2

    def test_export_404_for_missing_run(self, app_client):
        client, _ = app_client
        r = client.get("/runs/doesnotexist/export")
        assert r.status_code == 404

    def test_export_json_is_valid_run_graph(self, app_client):
        """The exported JSON round-trips back to a RunGraph model."""
        from vapviz.events import RunGraph
        client, store = app_client
        run_id = _seed_run(store)
        r = client.get(f"/runs/{run_id}/export")
        graph = RunGraph.model_validate(r.json())
        assert graph.run_id == run_id


# ---------------------------------------------------------------------------
# GET /runs/compare
# ---------------------------------------------------------------------------

class TestCompareRuns:
    def test_compare_returns_both_graphs(self, app_client):
        client, store = app_client
        run_a = _seed_run(store, "Run A")
        run_b = _seed_run(store, "Run B")
        r = client.get(f"/runs/compare?a={run_a}&b={run_b}")
        assert r.status_code == 200
        data = r.json()
        assert "a" in data and "b" in data
        assert data["a"]["run_id"] == run_a
        assert data["b"]["run_id"] == run_b

    def test_compare_graphs_contain_nodes(self, app_client):
        client, store = app_client
        run_a = _seed_run(store, "Run A")
        run_b = _seed_run(store, "Run B")
        r = client.get(f"/runs/compare?a={run_a}&b={run_b}")
        data = r.json()
        assert len(data["a"]["nodes"]) == 2
        assert len(data["b"]["nodes"]) == 2

    def test_compare_404_when_a_missing(self, app_client):
        client, store = app_client
        run_b = _seed_run(store, "Run B")
        r = client.get(f"/runs/compare?a=notexist&b={run_b}")
        assert r.status_code == 404
        assert "notexist" in r.json()["detail"]

    def test_compare_404_when_b_missing(self, app_client):
        client, store = app_client
        run_a = _seed_run(store, "Run A")
        r = client.get(f"/runs/compare?a={run_a}&b=notexist")
        assert r.status_code == 404
        assert "notexist" in r.json()["detail"]

    def test_compare_requires_both_params(self, app_client):
        client, _ = app_client
        r = client.get("/runs/compare?a=only_a")
        assert r.status_code == 422  # FastAPI validation error
