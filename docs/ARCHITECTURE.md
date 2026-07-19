# vapviz Architecture

This document describes the internal design of the Visualization Agentic Process framework — how events flow from user code through the Python tracer to the FastAPI server and ultimately to the React graph.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  User / Agent Code                                                  │
│                                                                     │
│   with vapviz.trace("My Agent") as run:           (sync)               │
│       with run.step("fetch", kind="tool") as step:                  │
│           step.set_input({...})                                     │
│           result = do_work()                                        │
│           step.set_output({...})                                    │
│                                                                     │
│   async with vapviz.atrace("Async Agent") as run: (async)              │
│       async with run.astep("fetch", kind="tool") as step:           │
│           step.set_input({...})                                     │
│           result = await do_work_async()                            │
│           step.set_output({...})                                    │
└──────────────────────────┬──────────────────────────────────────────┘
                           │  VapEvent objects (in-process)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  RunStore ABC  (vapviz/store.py)                                        │
│                                                                     │
│  MemoryStore   — thread-safe in-memory dict (default)               │
│  SqliteStore   — WAL-mode SQLite, survives restarts                  │
│                                                                     │
│  Both implementations:                                              │
│  • Build RunGraph (nodes + edges) incrementally on each event       │
│  • Hold asyncio.Queue per SSE subscriber                            │
│  • Use loop.call_soon_threadsafe() for thread→asyncio hand-off      │
│                                                                     │
│  vapviz/cost.py    — pricing table, calculate_cost(), format_cost()    │
│  (used by integrations to attach cost_usd to llm_response events)  │
│  vapviz/metrics.py — compute_metrics(): cross-run aggregation          │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  asyncio.Queue (per subscriber)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI Server  (vapviz/server.py)                                    │
│                                                                     │
│  GET    /runs                  → list[RunSummary]                   │
│  GET    /metrics               → Metrics (cross-run analytics)      │
│  GET    /runs/compare?a=&b=    → {a: RunGraph, b: RunGraph}         │
│  GET    /runs/{id}             → RunSummary                         │
│  GET    /runs/{id}/graph       → RunGraph snapshot                  │
│  GET    /runs/{id}/export      → RunGraph JSON file download        │
│  GET    /runs/{id}/events      → SSE stream (replay + live)         │
│  POST   /runs/{id}/events      → remote event ingest                │
│  GET    /runs/{id}/control     → control latch (desired + acked)    │
│  POST   /runs/{id}/control     → pause / resume / stop a live run   │
│  DELETE /runs                  → clear all runs                     │
│  DELETE /runs/{id}             → delete one run                     │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  Server-Sent Events  (EventSource API)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  React UI  (ui/src/)                                                │
│                                                                     │
│  useRunStream(runId)           SSE hook -> applyEvent() in Zustand  │
│  runStore.ts                   Builds nodes/edges from event stream  │
│  AgentGraph.tsx                ReactFlow DAG with dagre layout       │
│  LogsView.tsx                  Full-width filterable event log       │
│  NodeDetail.tsx                Selected-node inspector               │
│  Dashboard.tsx                 Cross-run analytics (GET /metrics)    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Event Model

Every observable action in an agent run is represented as a `VapEvent`:

```python
class VapEvent(BaseModel):
    id: str                   # 12-char hex, unique per event
    run_id: str               # groups all events for one run
    timestamp: float          # Unix epoch (seconds, float)
    type: EventType           # see table below
    node_id: str              # which graph node this event belongs to
    node_kind: NodeKind       # agent | step | tool | llm
    node_label: str           # human-readable name
    parent_id: str | None     # parent node_id (None = root)
    data: dict[str, Any]      # arbitrary payload (input, output, error, etc.)
    schema_version: int = 1   # bumped on breaking schema changes
```

`schema_version` enables forward-compatible migrations when the event schema evolves — stored events are tagged with the version they were written under.

### Event types and lifecycle

Each node kind has a symmetric open/close pair:

| Open event | Close event | Node kind |
|---|---|---|
| `agent_start` | `agent_end` | `agent` |
| `step_start` | `step_end` | `step` |
| `tool_call` | `tool_result` | `tool` |
| `llm_call` | `llm_response` | `llm` |
| — | `error` | any (replaces close) |

Two event types are freestanding — they don't open/close a node:

- `state_update` — updates metadata on the nearest parent node (currently inert in the graph reducers).
- `control` — an inert audit marker emitted by the server when a user pauses/resumes/stops a run (see [Control channel](#control-channel-pause--resume--stop)). It appears in the timeline (Logs) but produces **no** graph change in either reducer — a parity fixture (`control_inert.json`) asserts both reducers ignore it identically.

### Graph construction

The store builds a `RunGraph` incrementally as events arrive via the shared pure function `_apply_event_to_graph(graph, event)`:

- **Open event** → add `GraphNode` with `status: running`; if `parent_id` exists, add a `GraphEdge`
- **Close event** → update the matching node's terminal `status`, set `ended_at`, merge `data`. Status is derived by `_terminal_status(data)`: `error` in the data → `error`; else `stopped: true` in the data → `stopped` (the run was halted by user control — see [Control channel](#control-channel-pause--resume--stop)); else `success`. `error` always wins — a crash is a crash even if a stop was pending.
- **`agent_end`** → also updates the top-level `RunGraph.status` and `RunGraph.ended_at` (same `_terminal_status` rule)

This logic is extracted into a standalone pure function so both `MemoryStore` and `SqliteStore` share identical graph-building behaviour without inheritance.

---

## Python Package Internals

### Tracer (`vapviz/tracer.py`)

The tracer uses Python's `contextvars.ContextVar` to track the currently active `StepContext` without requiring users to pass context objects manually.

**How nesting works:**

```
ContextVar: _current_step = None

trace("Agent"):
  _current_step = root_ctx        # token_0 saved

  step("phase_1"):
    parent = _current_step.get()  # -> root_ctx
    _current_step = phase1_ctx    # token_1 saved
    edge: root -> phase1

    step("sub_task"):
      parent = _current_step.get()  # -> phase1_ctx
      _current_step = sub_ctx       # token_2 saved
      edge: phase1 -> sub

      yield  <- user code runs here

      _current_step.reset(token_2)  # -> back to phase1_ctx

    _current_step.reset(token_1)  # -> back to root_ctx

  _current_step.reset(token_0)  # -> None
```

`ContextVar.reset(token)` is used instead of `set(None)` so that async tasks and threads each have their own isolated context chain — two concurrent runs never interfere.

**Async tracer:**

`atrace` and `astep` are mirrors of `trace` and `step` built with `asynccontextmanager`:

```python
@asynccontextmanager
async def atrace(self, label: str) -> AsyncIterator[RunContext]:
    run = RunContext(label=label, store=self._store)
    run._start()
    error = None
    try:
        yield run
    except Exception as exc:
        error = exc
        raise
    finally:
        run._end(error=error)
```

Because `ContextVar` already propagates correctly through asyncio tasks (each `asyncio.Task` inherits a copy of the context at creation time), concurrent `astep` calls in `asyncio.gather` each see their own parent chain — no user intervention required.

**Dynamic store lookup:**

`Tracer._store` is a `@property` that reads `vapviz.store.default_store` at call time rather than capturing it at construction time. This means `vapviz.configure(db=...)` takes effect for all subsequent traces on the default tracer without requiring any re-import.

**Exception handling:**

If the body of a `with run.step()` block raises:
1. The `except` block emits an `error` event (sets node to `error` state)
2. The exception is re-raised
3. The `finally` block resets the `ContextVar` token (always runs)
4. The `if not error:` guard skips the normal close event (already marked error)

This ensures the graph always reaches a terminal state even when agents fail mid-run.

---

### Store (`vapviz/store.py`)

`RunStore` is an abstract base class. All store operations are defined as abstract methods:

```python
class RunStore(ABC):
    @abstractmethod
    def add_event(self, event: VapEvent) -> None: ...
    @abstractmethod
    def get_events(self, run_id: str) -> list[VapEvent]: ...
    @abstractmethod
    def get_graph(self, run_id: str) -> RunGraph | None: ...
    @abstractmethod
    def get_run(self, run_id: str) -> RunSummary | None: ...
    @abstractmethod
    def list_runs(self) -> list[RunSummary]: ...
    @abstractmethod
    def delete_run(self, run_id: str) -> None: ...
    @abstractmethod
    def clear(self) -> None: ...
    @abstractmethod
    def subscribe(self, run_id: str) -> asyncio.Queue: ...
    @abstractmethod
    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None: ...
    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None: ...  # default no-op
```

**`MemoryStore`** is the default implementation — everything lives in process memory.

**Thread-safety model (both stores):**

```
Tracer thread (sync)          asyncio event loop (server)
      │                               │
      │  add_event(event)             │
      │  acquire Lock                 │
      │  append to list               │
      │  update graph                 │
      │  release Lock                 │
      │                               │
      │  loop.call_soon_threadsafe(   │
      │    q.put_nowait, event        │──► asyncio.Queue
      │  )                            │         │
      │                               │         ▼
      │                               │   SSE generator
      │                               │   yields to browser
```

- `threading.Lock` protects all reads/writes to the event lists and graphs
- `asyncio.Queue` (one per SSE subscriber) is the hand-off point between threads
- `loop.call_soon_threadsafe` schedules `q.put_nowait` on the asyncio loop thread-safely

The loop reference is injected at server startup via `store.set_loop(asyncio.get_running_loop())` inside the FastAPI `lifespan` handler.

---

### SQLite Backend (`vapviz/backends/sqlite.py`)

`SqliteStore` persists events to a SQLite database file and replays them into an in-memory graph cache on startup.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS events (
    id        TEXT PRIMARY KEY,
    run_id    TEXT NOT NULL,
    timestamp REAL NOT NULL,
    data      TEXT NOT NULL    -- full VapEvent JSON
);
CREATE INDEX IF NOT EXISTS idx_events_run_id   ON events (run_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp);
```

**Key design choices:**

- `PRAGMA journal_mode=WAL` — allows concurrent reads from FastAPI while the tracer writes, with no read blocking writes
- `PRAGMA synchronous=NORMAL` — one fsync per WAL checkpoint instead of per write; survives OS crashes, risks at most one checkpoint of data on power loss
- `INSERT OR IGNORE` — prevents duplicate events if `add_event` is called twice with the same event ID (e.g. retry logic)
- Startup replay: `_load_from_db()` reads all persisted events ordered by `timestamp` and feeds them through `_apply_event_to_graph` to rebuild the in-memory graph cache
- `close()` method — called by the server's lifespan `finally` block to cleanly close the SQLite connection on shutdown

---

### Server (`vapviz/server.py`)

The FastAPI app is a thin façade over the store. The lifespan handler wires up the asyncio loop and cleans up on shutdown:

```python
@asynccontextmanager
async def lifespan(app):
    _store.set_loop(asyncio.get_running_loop())
    yield
    if hasattr(_store, "close"):
        _store.close()
```

The most interesting endpoint is the SSE stream:

```python
async def generator():
    # Phase 1: replay history (handles late-connecting browsers)
    for event in store.get_events(run_id):
        yield {"data": event.model_dump_json(), "event": event.type.value}

    # Phase 2: live stream from asyncio.Queue
    q = store.subscribe(run_id)
    try:
        while True:
            event = await asyncio.wait_for(q.get(), timeout=30)
            yield {"data": ..., "event": event.type.value}
    except asyncio.TimeoutError:
        yield {"data": "{}", "event": "ping"}   # keep-alive
    finally:
        store.unsubscribe(run_id, q)            # clean up on disconnect
```

The two-phase design means:
- A browser opened after a run completes still sees the full history
- A browser opened mid-run sees history first, then transitions seamlessly to live events
- Disconnecting subscribers are cleaned up via the `finally` block

---

### Cost Module (`vapviz/cost.py`)

`vapviz/cost.py` is a self-contained pricing utility — no external dependencies, no I/O.

**Pricing table:**

```python
PRICING: dict[str, tuple[float, float]] = {
    # (input_usd_per_1k, output_usd_per_1k)
    "gpt-4o":                  (0.00250,  0.01000),
    "gpt-4o-mini":             (0.00015,  0.00060),
    "o1":                      (0.01500,  0.06000),
    "o3-mini":                 (0.00110,  0.00440),
    "o4-mini":                 (0.00110,  0.00440),
    "claude-3-5-sonnet-20241022": (0.00300, 0.01500),
    "claude-3-haiku-20240307": (0.00025,  0.00125),
    # ... 20+ models total
}
```

**Matching strategy** (in order):
1. Exact model name
2. Pricing-table key is a prefix of the model string — e.g. `"gpt-4o"` matches `"gpt-4o-2099-01-01"`
3. Model string is a prefix of a pricing-table key — handles short aliases

This means new versioned variants (e.g. `"gpt-4o-2025-03-15"`) automatically resolve to the base model's pricing without any table update.

**`calculate_cost(model, input_tokens, output_tokens) -> float | None`**

Returns USD cost rounded to 8 decimal places, or `None` for unknown models. The integrations use this function: if `None` is returned, no `cost_usd` key is added to the node's output data.

**`format_cost(cost_usd) -> str`**

Display helper used by both the Python server (not currently exposed) and the React UI components:

| Cost range | Format | Example |
|---|---|---|
| `< $0.0001` | `"<$0.0001"` | very cheap calls |
| `< $0.01` | `"$0.000123"` | 6 decimal places |
| `≥ $0.01` | `"$0.0123"` | 4 decimal places |

---

### Metrics Module (`vapviz/metrics.py`)

Like `cost.py`, this is a pure, dependency-free aggregation layer — no I/O, no store coupling. `compute_metrics(graphs: list[RunGraph]) -> Metrics` is a single pass over the supplied graphs:

```
for each RunGraph:
    tally status (success / error / running)
    add (ended_at − started_at) to the duration total
    bucket the run's day for cost_over_time
    for each node:
        increment by_kind[node.kind]
        if node.kind == llm:
            model  = node.data["input"]["model"]  (fallback: strip "llm/" label prefix)
            usage  = node.data["output"]["usage"]    -> token totals + per-model tally
            cost   = node.data["output"]["cost_usd"] -> cost totals + per-model tally + daily bucket
derive: success_rate, avg_cost_usd, avg_duration_ms
sort by_model by (cost, calls) desc; emit cost_over_time chronologically
```

**Key design points:**

- **Reads the shared node-data shape, not events.** Every integration (`patch_*`, `VapCallbackHandler`, `VapCrewAIListener`) and the raw tracer write `input.model`, `output.usage`, and `output.cost_usd` the same way, so metrics need no integration-specific code.
- **Averages are denominator-aware.** `avg_cost_usd` divides by the number of runs that actually contributed cost (not `run_count`), and `avg_duration_ms` divides by completed runs with a measurable duration — both are `None` rather than `0` when the denominator is empty, so the UI can render "—".
- **`success_rate` excludes running runs** — it is `success / (success + error)`, so an in-flight run never drags the rate down.
- **Response models** (`Metrics`, `ModelStat`, `TokenTotals`, `KindCounts`, `DailyCost`) are pydantic, so FastAPI validates and serialises them directly and the TypeScript interfaces mirror them 1:1.

The `GET /metrics` route fetches `store.get_graph()` for every `store.list_runs()` entry and passes the list straight to `compute_metrics()` — the route holds no logic of its own.

---

### Budgets Module (`vapviz/budgets.py`)

Another pure layer over the graph, turning metrics into guardrails. `check_budget(graph, budget)`
measures a single run's cost, duration, and token totals (the same way `metrics.py` does) and emits a
`Violation` for every limit the run exceeds, returning a `BudgetReport` (`status`, the measured
values, and the `violations` list).

`enable_budget_alerts(budget, on_alert=…)` uses the **same store-wrapping pattern as the OTel
exporter**: it overrides `add_event` on the instance so that when an `agent_end` event lands, the run
is fetched and checked; on a violation it calls `on_alert(report)` (default: a `vapviz.budgets` logger
warning). The check runs on the agent's thread but is cheap (a single graph pass) and best-effort —
any failure is swallowed so alerting can't break the run. `BudgetAlertHandle.disable()` deletes the
instance override, reverting to the class method.

This keeps budgets composable: the same `add_event` override pattern powers OTel export and budget
alerts independently, and `GET /runs/{id}/budget` exposes a stateless, query-param-driven check for
the UI or ad-hoc use.

---

### Evals Module (`vapviz/evals.py`)

Where budgets are *passive guardrails*, evals are *active assertions* — vapviz as a regression-testing
tool for agents. A `Check` is just a named function `RunGraph -> (passed, detail[, score])`, wrapped
so a throwing check is recorded as a failure rather than crashing the run. `eval_run` applies a list
of checks and aggregates: `passed` is the AND of all checks, `score` is the mean of their 0–1 scores.

Built-in checks reuse the same per-run measures as budgets (`_run_cost`, `_run_duration_ms`,
`_run_tokens`), so "cost ≤ $0.02" means the same thing in a budget alert and an eval. `output_contains`
scans node outputs (optionally a named node). `custom` and `judge` accept user predicates — vapviz never
calls an LLM itself for judging, keeping evals provider-agnostic and unit-testable offline.

Two surfaces wrap the same core: the Python `eval_run(run, [...])` (drop into pytest/CI, accepts a
`RunContext` or `RunGraph`) and a declarative `run_checks(graph, specs)` that builds checks from JSON
specs — the latter backs `POST /runs/{id}/eval` so any language or the UI can score a run.

---

### Search & Tags (`vapviz/search.py` + store)

**Search** is a pure predicate, `run_matches(graph, query=, status=, kind=, tool=)`: it builds a text
"haystack" per node (label + JSON-stringified input/output/error) and AND-combines the supplied
filters. `GET /search` walks `list_runs()`, applies `tag` filtering at the summary level (tags aren't
in the graph), fetches each graph, and keeps the matches. It's linear over stored runs — fine for the
single-node scale vapviz targets; a larger deployment would push this into the store/DB.

**Tags** are the first piece of *mutable* per-run state in a system that's otherwise append-only
events. They live beside the event log rather than in it: the `RunStore` ABC provides concrete
`get_tags`/`set_tags` over a `self._tags` dict (so `MemoryStore` gets them for free), and `SqliteStore`
overrides `set_tags` to persist to a `tags(run_id, tag)` table and loads them on startup. `RunSummary`
gained a `tags` field, populated by reading `self._tags` **directly inside the already-held lock** —
calling `get_tags()` there would re-enter the non-reentrant `Lock` and deadlock. `delete_run`/`clear`
drop tags alongside events.

On the client, `RunList` runs the content search against `/search` (debounced) and renders tag chips
(click to filter); `TagEditor` in the run header does optimistic `PUT /runs/{id}/tags` writes that the
3-second run poll reconciles.

---

### Configuration (`vapviz/__init__.py`)

`vapviz.configure(db=...)` is the public API for switching the module-level store:

```python
def configure(db: str | None = None) -> None:
    import sys
    import vapviz.store as _sm

    new_store = SqliteStore(db) if db is not None else MemoryStore()
    _sm.default_store = new_store
    # Also update the binding on this module so vapviz.default_store stays current
    sys.modules[__name__].default_store = new_store
```

The `sys.modules[__name__]` trick is needed because Python's import machinery creates a binding in `vapviz.__init__` at import time (`from .store import default_store`). Simply reassigning `_sm.default_store` would leave the `vapviz.default_store` name pointing at the old object. Writing through `sys.modules` updates both bindings atomically from the caller's perspective.

Every consumer of the default store resolves it **at call time** for the same reason: `Tracer._store` is a property, and `create_app()` reads `vapviz.store.default_store` when it is called (fixed 2026-07-18 — it previously froze an import-time copy, so `configure(db=...)` → `create_app()` silently served an empty `MemoryStore`). The one deliberate exception is the prebuilt `vapviz.app` at the bottom of `server.py`: it is constructed at import, so it snapshots whatever store exists then. If you use `configure`, build your own app with `create_app()` afterwards rather than reusing `vapviz.app`.

---

## Control channel (Pause / Resume / Stop)

Everything above describes a **one-directional** system: the agent talks, vapviz listens and draws. The control channel (`vapviz/control.py`) is the **return lane** — the only place data flows *back* from the UI toward the agent. It lets a user pause, resume, or stop a live **in-process** run (agent and server sharing one Python process, as in `run_dev.py`).

**The one hard constraint that shapes the whole design:** vapviz observes; it does not drive. The agent's code runs in *its own* call stack — vapviz only sees it when the agent passes through the tracer's context managers. So control must be **cooperative**: the tracer checks a per-run "mailbox" at the top of every `step`/`astep` (the turnstiles the agent already walks through) and obeys what it finds. It is a polite halt at the next checkpoint, never a force-kill. An agent stuck inside one long tool call won't react until it next enters a step, and an agent with no sub-steps has no checkpoints at all — both are documented limits, surfaced honestly in the UI as "pausing…" / "stopping…".

```
   ┌────────── existing one-way event lane (unchanged) ──────────┐
   │  agent → Tracer → RunStore → SSE → UI  (VapEvent history)   │
   └──────────────────────────────────────────────────────────────┘

   ┌────────── the return lane ───────────────────────────────────┐
   │  UI  ──POST /runs/{id}/control {action}──►  RunStore         │
   │        (Pause/Resume/Stop buttons)         (control latch)   │
   │                                                  │           │
   │  UI  ◄─GET /runs/{id}/control (poll ~1s)──  desired + acked  │
   │        (renders "pausing…/paused/stopping…")     ▲           │
   │                                                  │           │
   │  Tracer checkpoint at each step/astep enter ─────┘           │
   │        reads latch → parks, or raises VapStopped             │
   └───────────────────────────────────────────────────────────────┘
```

**The latch (`RunControl`)** is a tiny per-run record with two fields whose *difference* is the point: `desired` (what the user asked for, written by the server) and `acked` (what the agent has actually done, written by the tracer at a checkpoint). The gap between them is the honest cooperative lag the UI renders — `desired=paused, acked=running` is "pausing…"; when they agree it's "paused".

**Where the latch lives — a side channel, deliberately.** `desired`/`acked` is mutable, ephemeral state (a request about what to do *next*), a poor fit for the append-only event log. So it sits in the store as plain in-memory state guarded by the existing `self._lock`, exactly like tags: concrete methods `get_control` / `set_desired` / `set_ack` on the `RunStore` ABC, backed by a `self._control` dict in both `MemoryStore` and `SqliteStore`. It is **never fed to the graph reducers and never persisted** — even for SQLite, on purpose: a restarted server has no live agent left to control, so there is nothing meaningful to restore (and no DB migration needed).

**Exactly two things do ride the event lane** (and therefore pay the dual-logic tax — see the parity-test note below):

1. **The inert `control` audit event.** Each successful control action makes the server emit a `control` event (`data: {action: "pause"|"resume"|"stop"}`) through the normal `add_event` path, so "⏸ Paused by user" appears live in the Logs timeline and persists with the run. Both reducers ignore it completely (like `state_update`); the `control_inert.json` parity fixture enforces that.
2. **The first-class `stopped` status.** A user-stopped run terminates with `agent_end` carrying `data={stopped: true, error_type: "VapStopped"}` and **no `error` key** — so both reducers derive the terminal status `stopped` (not a success, not a crash) via the shared `_terminal_status` rule, and every status-keyed surface (badges, run list, building rooms, metrics) renders it as its own neutral state. The `stopped_run.json` parity fixture enforces agreement.

**Tracer checkpoints.** `_check_control` (sync) and `_acheck_control` (async) run as the *first* line of `step`/`astep`, before the child node's start event — so a pause parks the agent cleanly *between* steps (never mid-tool-call), and a stop raises before the next step ever appears. The two variants exist because parking must not freeze the wrong thing:

- **Sync agent** (own thread): blocks on a per-run `threading.Event` with a `CONTROL_POLL` (0.1 s) timeout. `set_desired` `.set()`s the event so resume is effectively instant; the timeout is only a safety re-poll bounding worst-case latency if a wake is ever missed. The server's asyncio loop keeps serving throughout — only the agent's thread is parked.
- **Async agent** (sharing the server's event loop): `await asyncio.sleep(CONTROL_POLL)` in a loop, yielding so the very Resume request that will unpause it can be served.

**Stop = a real exception.** When `desired == "stopped"`, the checkpoint raises `VapStopped(run_id)` (exported as `vapviz.VapStopped`). Each open `step`/`astep` catches it, closes its node with `stopped: true` (not an error), and re-raises; `trace`/`atrace` end the run as stopped and re-raise again so the agent's own code genuinely unwinds and halts. An author who wants a graceful shutdown can `except vapviz.VapStopped:` at their top level.

**Server endpoints.** `GET /runs/{id}/control` returns the latch (+ `ended: true` when the run is terminal — the UI hides the bar). `POST /runs/{id}/control` validates the action (`pause`/`resume`/`stop`, 422 otherwise), no-ops with `ended: true` on already-terminal runs, maps the action to a desired state, and emits the audit event.

**UI.** `RunControlBar.tsx` (Theater tab, live runs only) polls `GET /control` every 1 s and posts actions; the branchy state table lives in the pure, unit-tested `lib/runControl.ts` (`controlUiState(desired, acked, runStatus)` → banner + buttons). This latch-side UI state is **not** part of the dual-logic rule — only the `stopped` status and the `control` event type are.

**Current scope and deferred layers:** this is Layer 1 — lifecycle control of in-process agents. Deferred by design: message injection / task prompting (Layer 2, plus a `vapviz.checkpoint()` escape hatch for step-less long loops), retry/re-run (Layer 3), and cross-process control for remote-ingest agents, whose tracers cannot see the server's in-memory latch (Layer 4).

---

## React UI Internals

### State management (`runStore.ts`)

The Zustand store is the client-side equivalent of `RunStore`. It receives raw `VapEvent` objects from the SSE hook and applies the same open/close logic to build `nodes` and `edges` arrays:

```
SSE event arrives
       │
       ▼
applyEvent(event)
  ├── START type -> push new GraphNode (status: running), maybe push GraphEdge
  ├── END type   -> update matching node (status: success/error, ended_at, data)
  └── ERROR type -> update matching node (status: error)
       │
       ▼
  Recompute total_cost_usd
  (sum node.data.output.cost_usd across all nodes in this run)
       │
       ▼
Zustand subscribers re-render
  ├── AgentGraph  (nodes + edges -> ReactFlow; LLM nodes show cost_usd)
  ├── LogsView (filterable events list)
  └── RunList (run summary; total_cost_usd shown in purple when non-null)
```

The store also holds a `view: "runs" | "dashboard"` flag (with `setView`). `App.tsx` renders the `Dashboard` component when `view === "dashboard"`; `selectRun` always resets `view` to `"runs"` so picking a run from the dashboard returns to the graph.

**Cost aggregation in `runStore.ts`:**

After every `applyEvent` call, `total_cost_usd` is recomputed by summing `node.data.output.cost_usd` across all nodes in the run. The result is stored in `RunSummary.total_cost_usd` — `null` if no LLM node has a cost entry (e.g. the model is unknown), otherwise the running sum as a `number`. This is a pure client-side recalculation with no extra network round-trip.

### Run comparison (`RunComparison.tsx`)

`RunComparison` is rendered instead of the normal graph view whenever `compareRunId` is non-null in the Zustand store.

**Data flow:**
1. The component `fetch`es `/runs/compare?a={runIdA}&b={runIdB}` on mount, receiving both `RunGraph` objects in one request.
2. Client-side diff is computed by comparing node labels between the two graphs:
   - **common** — nodes whose `label` appears in both graphs
   - **only A / only B** — nodes unique to each run
3. Duration Δ and cost Δ are computed from graph-level metadata.
4. Two `ReactFlowProvider` / `AgentGraph` pairs render side by side, each with a coloured label strip (sky-blue for A, amber for B).

**UX flow in RunList:**
- A hover-revealed `⊕` (GitCompare) icon appears on every non-selected run row.
- Clicking it sets `compareRunId` in the store → `App.tsx` switches to `RunComparison`.
- An amber "Comparison mode active" banner appears at the bottom of the sidebar.
- The `✕` icon on the active comparison run clears `compareRunId`; so does selecting any new primary run.

---

### Export (`ExportMenu.tsx`)

The `ExportMenu` dropdown lives in the run header and offers two actions:

**JSON download:**
- Calls `GET /runs/{id}/export` which returns the `RunGraph` as `application/json` with `Content-Disposition: attachment`.
- The browser triggers an automatic file download (`vapviz-{run_id}.json`).

**PNG download:**
- Dynamically imports `html2canvas` (loaded only on demand to avoid bundle bloat).
- Captures the graph container `<div>` (the `ref` is wired in `App.tsx`) including the ReactFlow viewport.
- Converts the canvas to a PNG blob and triggers a download.

---

### Analytics dashboard (`Dashboard.tsx`)

`Dashboard` is rendered instead of the graph/comparison views whenever `view === "dashboard"` in the Zustand store (toggled by the `BarChart3` button in the `RunList` header).

**Data flow:**
1. On mount it `fetch`es `/metrics` and re-polls every 5 s (mirroring `RunList`'s run polling), holding the result in local component state — it does not touch the run-event store.
2. The `Metrics` payload drives four blocks: a row of stat cards (runs, success rate, total/avg cost, avg duration, LLM calls, tokens), a cost-over-time bar chart, a by-model table, and a nodes-by-kind breakdown.

**Rendering notes:**
- Charts are dependency-free — CSS flex bars, not a charting library — to keep the bundle lean. Bars use `height: %` of an `h-full` flex column; the column **must** carry `h-full` because the row uses `items-end`, which otherwise collapses children to content height.
- All formatting (cost tiers, `k`/`M` token abbreviation, `ms`/`s`/`m` durations, percentage) lives in local helpers, matching the colour conventions used elsewhere (purple for cost, kind colours for the breakdown bars).

---

### Graph rendering (`AgentGraph.tsx`)

ReactFlow renders the DAG. Layout is computed by **dagre** on every re-render (via `useMemo`):

```
GraphNode[] + GraphEdge[]
       │
       ▼ useMemo
dagre.graphlib.Graph
  .setGraph({ rankdir: "TB", nodesep: 40, ranksep: 60 })
  .layout()
       │
       ▼
ReactFlow Node[] with { position: { x, y } }
       │
       ▼
<ReactFlow nodes={...} edges={...} nodeTypes={{ vapviz: VapNode }} />
```

`VapNode` is a custom node component that:
- Sets background colour by `node.kind` (indigo / sky / emerald / purple)
- Sets border colour by `node.status` (amber for running, green for success, red for error)
- Animates a pulsing dot when `status === "running"`
- Shows duration in ms when both `started_at` and `ended_at` are present
- Shows a purple cost label below the duration for `llm` nodes when `data.output.cost_usd` is present

### Trace replay (`ReplayBar.tsx` + `lib/replay.ts`)

Replay reuses the fact that a run *is* its event log. `buildGraphAt(events, n)` is a pure reducer that
replays the first `n` events into `{nodes, edges}` using the same START/END/ERROR rules as the store
and `runStore`. When replay is active, `App` computes this partial graph (memoised on `n`) and hands
it to `AgentGraph` instead of the live `state.nodes/edges` — so the existing graph component renders
the run "as of" any point with no changes of its own. `ReplayBar` owns the scrubber: a range input
bound to `n`, play/pause (a timer that advances `n`), and step buttons. Replay state lives in `App`
(`replayIndex: number | null`, `null` = live) and resets when the selected run changes. dagre re-lays
out as nodes appear, so the graph visibly fills in as you scrub or play.

### SSE hook (`useRunStream.ts`)

```typescript
useEffect(() => {
    const es = new EventSource(`/runs/${runId}/events`);

    // Register a handler for each named SSE event type
    ["agent_start", "step_start", "tool_call", "llm_call", ...].forEach(type => {
        es.addEventListener(type, (e) => applyEvent(JSON.parse(e.data)));
    });

    return () => es.close();   // clean up on unmount or runId change
}, [runId]);
```

Named SSE events (`event: tool_call\ndata: {...}`) are used instead of the default `message` event so each handler only receives the events it cares about.

### Theater & Building (`OfficeStage.tsx`, `TheaterView.tsx`, `BuildingView.tsx`, `lib/{sprites,officeArt,officeScene,theater,building}.ts`)

The Theater is a watchable renderer over the *same* derived graph the other views use — **UI-only, no
backend change** (the Python touches are additive metadata only: the `langgraph_node` marker below,
and the `app_id` run identity the Building groups by).

- **`lib/sprites.ts` — the art-as-data sprite engine.** A sprite is hand-authored TEXT: a palette
  (char key → color, some keys flagged recolorable) plus a char-grid (one key per pixel). The 12×16
  worker (4-frame walk cycle) is rasterized to an offscreen canvas via `ImageData` and blitted with
  integer-scale nearest-neighbor. An FNV-1a hash of the agent's name picks a deterministic **colorway**
  (skin/hair/shirt/pants), so one authored sprite becomes many distinct coworkers who keep their look
  across runs. Owned art: hand-authored, zero AI, zero third-party packs (provenance in
  `ui/src/lib/ASSETS.md`).
- **`lib/officeArt.ts` — the room.** Furniture (LLM desk, SEARCH shelves, FETCH racks, DATA cabinet,
  PRINT table, home desks, plus lounge/dinner-nook decor), floor/wall tiles, and the **locked room
  layout** (station geometry + stand-points, decor placements, the home-desk row). `homeSpots(n)`
  places the cast's home desks: up to 6 in the locked front row, larger casts wrap into an additive
  overflow back row on the open floor so desks never overlap (unit-tested). `bakeGround()`
  renders the static room once per scale/cast into an offscreen canvas; `drawDecorAnim()` overlays
  the two live props (flickering TV, bubbling water cooler) each frame. The diorama's warm palette is
  fixed sprite data — deliberately not theme tokens.
- **`lib/officeScene.ts` — graph → office wiring** (pure, tested). `stationForCall` routes a running
  call to its station: LLM-kind → the LLM desk; tool calls keyword-match their label (normalized
  snake_case → words) to SEARCH / FETCH / PRINT / DATA, with a deterministic hash fallback so unknown
  tools still spread out. `callsByAgent` attributes every llm/tool call to the nearest cast actor up
  the parent chain (same ownership rule as `buildScene`'s subtree walk), yielding each agent's
  running + most-recent call. Also owns the playful per-station dialogue lines.
- **`OfficeStage.tsx` — the canvas renderer** behind both the Theater tab and the Floor's zones.
  Picks an integer device-pixel scale from the container (ResizeObserver), bakes the ground, and runs
  a rAF loop: workers glide toward their target (home desk ↔ station) at **duration-adaptive speed**
  (each trip takes ~0.55 s regardless of distance, so arrival beats any real call), legs cycle while
  moving, the active station glows, and name tags + speech bubbles draw in canvas. Driven purely by
  the `nodes` prop → identical for live SSE and replay. Honors `prefers-reduced-motion` (no walk/decor
  animation). A `compact` prop renders the same room for the Floor's small tiled run-zones: station
  label chips and speech bubbles are dropped (unreadable at zone scale), name-tag chrome keeps a
  legible minimum size via a floored chrome unit, and the glow / walk / ✓ ! cues carry the signal.
  Tiling-friendly by construction: canvas text widths are cached across frames/instances, and an
  IntersectionObserver pauses the rAF loop for any stage scrolled out of view (browsers only pause
  rAF for hidden tabs, not offscreen elements).
- **`lib/theater.ts` — the scene model.** `buildScene(nodes)` is a pure reduction: pick the cast, then
  decide each agent's `state` (idle/thinking/working/done/error) and which desk it's `at` (`llm`/`tool`/
  `home`). Cast detection, by signal strength: `agent/` label prefix (CrewAI/Pydantic AI) → `langgraph_node`
  marker minus generic wrappers (LangGraph workers) → agent-kind root → first node. Re-entered nodes
  (LangGraph revisits `supervisor`/`math_expert`) are **grouped by name** into one character. "Linger":
  while an agent is still active it stays at the desk of its most recently started call instead of bouncing
  home between back-to-back calls; desks only glow for a *running* call.
- **`TheaterView.tsx`** — the per-run view: a thin wrapper that hands the run's `shownNodes` (live or
  replayed) to a full-size `OfficeStage`. Added as a 4th run tab in `App` (Story/Theater/Graph/Logs);
  a tab on every run; the existing `ReplayBar` drives playback.
- **`lib/building.ts` — the Office Building reducer** (pure, tested — like `officeScene`/`buildScene`,
  it re-presents derived data and is NOT part of the dual-logic parity rule). `appKey(run) =
  run.app_id ?? run.label` is THE grouping key, shared by the building and the sidebar so they can
  never disagree. `groupApps(runs)` folds the `/runs` roster into apps and picks each app's
  **current run** (any running run wins, most-recently-started first; else newest).
  `buildBuilding(runs, prev, dismissed)` then places apps deterministically, in order: **stay put**
  (a surviving app keeps its exact `{floor, room}` from `prev`) → **failures stay + surface to the
  lounge** (an app whose current run failed keeps its room — the room turns red — AND is listed in
  `Building.lounge`; a dismissed failed run — keyed by run id — removes the app from the building
  until its next run) → **seat new apps on the top floor** → **descend under pressure** (a full top
  floor sends its earliest app down: oldest *finished* preferred, else the earliest-started running
  app, which stays live below; the cascade appends floors at the bottom — never sideways; trailing
  empty floors are trimmed). Floors are fixed at `ROOMS_PER_FLOOR = 6`.
- **`BuildingView.tsx`** — the global monitor (`view: "floor"`, sidebar 🎭), replacing the retired
  `FloorView.tsx`. It **polls** `/runs` (+ `/runs/{id}/graph` per visible room, finished graphs
  cached) every ~1.5 s rather than opening many SSE streams — frontend-only, fine for local-scale
  concurrency — and feeds each tick through `buildBuilding` (seeded with the previous tick for room
  stickiness). Renders the **visual building** (Phase 4b): a CSS shell (roof + `VAPVIZ` sign, floor
  slabs, lobby) whose floors are a **2×3 grid** of `compact` `OfficeStage` rooms around a central
  **Walk Way**, plus a **Door/Stairs** column (a floor's Stairs sit directly above the next floor's
  Door). The top floor's east side hosts the shared **Lounge** (`LoungeStage.tsx` over the
  hand-authored break-room diorama in `lib/loungeArt.ts`); floors below show a solid east wall +
  windows. A failed app's room stays put and turns red (`.vt-room--error`) while the app is listed
  in the lounge with one recolored worker idling at a distinct break-room spot (coffee / vending /
  cooler / table / plant / pacing): click its card to inspect the failed run, or **Dismiss** it
  (persisted in `localStorage["vapviz.dismissed"]` as failed run ids, pruned on load against the
  live roster). Transitions animate on the **walk overlay** (`lib/walkOverlay.ts` — a sprite canvas
  above the room grid): a descent walks room → Walk Way → Stairs (*vanish*) → Door below → room
  (nobody is ever drawn on the stairs), and a failure walks room → lounge; rooms the overlay didn't
  animate fall back to the FLIP glide, and `prefers-reduced-motion` snaps everything (no walkers, no
  FLIP). **Floor life (Phase 4c, honest-only since 4d):** the same overlay also runs a *persistent*
  layer — `WalkEngine.reconcileFloorLife(busy)`, called each poll from `BuildingView` with a fresh
  `snapshot(el)` (capturing per-room `roomdoor:<appKey>` anchors; each room has an invisible
  `.vt-room-door` anchor on its Walk-Way edge). It keeps one honest `Resident` (state machine
  `in → mill → out`) per **running** room — recolored by `appKey`, milling on that floor's Walk-Way
  lane, walking back through the door when the room finishes — and nothing else: an idle floor has
  an empty corridor (the 4c decorative ambient stroller was deleted in 4d). Residents keep the rAF
  loop alive, so the engine is stopped explicitly on unmount (`clearAll`); reduced-motion spawns no
  floor life. **Floor environment (Phase 4d):** each floor also renders an environment canvas
  *under* the rooms (`lib/floorArt.ts` + `components/FloorEnv.tsx`): from measured DOM rects it
  draws corridor stone tiles, shared wall runs with a door threshold per room, a runner rug +
  ceiling lights, props (plants, cooler, notice board, wall art, clock), the Door/Stairs alcove
  icons and east-wall windows — the DOM room tiles lost their CSS card chrome and carry wall-signage
  nameplates (`.vt-plate`: DOM text + status LED) instead. UI-only, exempt from the dual-logic rule. The lobby doubles as a live **directory board** (apps working · in the lounge · cost
  today). Clicking a room selects the app's current run. Desks inside a room are assigned by
  **sorted agent name** (in `OfficeStage.computeGoals`), so an agent keeps its seat across ticks and
  re-runs. *(The interim SVG stage — `AgentStage.tsx` + `lib/avatar.ts` — was retired when the Floor
  moved to the sprite office; the run-keyed `FloorView` was retired when the Building landed.)*

---

## Anthropic SDK Integration (`integrations/anthropic_sdk.py`)

`patch_anthropic(client)` auto-detects whether the client is `anthropic.Anthropic` (sync) or `anthropic.AsyncAnthropic` (async) and applies the appropriate wrapper to `client.messages.create`.

**Sync path:** replaces `client.messages.create` with a regular function that wraps the call in a `StepContext`.

**Async path:** replaces `client.messages.create` with an `async def` that `await`s the original coroutine.

Both paths:
1. Check `_current_step` — if no active vapviz trace context, call the original immediately (zero overhead outside a trace)
2. Create a `StepContext` with `kind=llm`, parented to the current step
3. Emit `llm_call` with model name, message count, and tool names
4. Call the original `messages.create`
5. Call `calculate_cost(model, input_tokens, output_tokens)` and attach `cost_usd` to the output if the model is recognised
6. Emit `llm_response` with response text, `stop_reason`, token usage, and optional `cost_usd`
7. On exception: emit `error` and re-raise

Because Python module imports are cached, the `ContextVar` imported inside the wrapper is the same object as the one used by the tracer — so parent tracking works correctly across the patched call.

---

## OpenAI SDK Integration (`integrations/openai_sdk.py`)

`patch_openai(client)` follows the same dual-path pattern as the Anthropic integration, wrapping `client.chat.completions.create`.

Auto-detection uses `isinstance(client, openai.AsyncOpenAI)` to choose the async wrapper; falls back to the sync wrapper otherwise.

Both paths:
1. Check `_current_step` — no-op if outside a vapviz trace
2. Create a `StepContext` with `kind=llm`
3. Emit `llm_call` with model, messages, and tool names
4. Call the original `chat.completions.create`
5. Call `calculate_cost(model, prompt_tokens, completion_tokens)` and attach `cost_usd` if the model is in the pricing table
6. Emit `llm_response` with `choices[0].message.content`, `finish_reason`, token usage, and optional `cost_usd`
7. On exception: emit `error` and re-raise

---

## LangGraph / LangChain Integration (`integrations/langchain.py`)

`VapCallbackHandler` implements LangChain's `BaseCallbackHandler` interface. It translates LangChain's UUID-based run tracking into vapviz's `StepContext` tree.

**UUID → vapviz mapping:**

LangChain passes a UUID `run_id` and an optional `parent_run_id` into every callback. `VapCallbackHandler` maintains an internal `_contexts: dict[UUID, StepContext]` map and looks up the parent context in that map. If `parent_run_id` is absent (top-level chain), it falls back to the `RunContext`'s root `StepContext`.

**Callback → vapviz node mapping:**

| LangChain callback | vapviz `kind` | Events emitted |
|---|---|---|
| `on_chain_start` / `on_chain_end` | `step` | `step_start` / `step_end` |
| `on_tool_start` / `on_tool_end` | `tool` | `tool_call` / `tool_result` |
| `on_chat_model_start` / `on_llm_start` | `llm` | `llm_call` |
| `on_llm_end` | `llm` | `llm_response` |
| `on_chain_error` / `on_tool_error` / `on_llm_error` | any | `error` |

**Tool input parsing:**

`on_tool_start` passes tool input as a string. The handler attempts `json.loads(input_str)` first; if that fails it stores `{"input": input_str}`.

**LLM response extraction:**

`on_llm_end` receives a LangChain `LLMResult`. The handler extracts the first generation text and, if present, token usage from `LLMResult.llm_output`.

**LangGraph node marker (Theater):**

`on_chain_start` already labels a node from `metadata["langgraph_node"]` when present (so multi-agent
graphs read as `supervisor` / `math_expert` rather than anonymous `chain`s — U4/LG3). It now also carries
that name through to the node's `data` via `set_meta(langgraph_node=...)`. This is purely additive metadata
(it rides into `node.data` through the normal `_emit` → event `data` path, so **no change to the
event→graph reduction or its dual TS mirror**), and it lets the Theater's cast detection
(`lib/theater.ts`) reliably distinguish a real graph agent from an anonymous sub-step.

Raises `ImportError` at instantiation time if `langchain-core` is not installed.

---

## CrewAI Integration (`integrations/crewai_listener.py`)

`VapCrewAIListener` uses a fundamentally different pattern from the SDK patches. Rather than monkey-patching method calls, it subclasses CrewAI's `BaseEventListener` and subscribes to the framework's internal event bus.

### Event bus mechanics

CrewAI exposes a process-wide singleton bus (`crewai_event_bus`). Calling `BaseEventListener.__init__()` invokes `setup_listeners()`, which registers handlers via `@bus.on(EventClass)` decorators. The bus dispatches events through a `ThreadPoolExecutor` — each `emit(source, event)` call submits all matching handlers to the pool and returns a `Future` that resolves when every handler finishes.

Two critical constraints follow from this design:

- **Handlers cannot be deregistered.** Once a listener is instantiated its handlers persist for the process lifetime. Creating multiple listeners (e.g. one per test) accumulates handlers; all of them fire on every subsequent event.
- **A stalled handler blocks the emitting thread.** Because `future.result()` waits for _all_ handlers to complete, a deadlocked handler in any registered listener freezes the caller.

### Initialisation order

All state is initialised **before** `super().__init__()` is called:

```python
def __init__(self, run=None):
    self._provided_run = run
    self._lock = threading.Lock()
    self._crew_roots: dict[str, StepContext] = {}
    self._task_nodes: dict[str, StepContext] = {}
    # ... other dicts ...
    super().__init__()   # calls setup_listeners() — must come last
```

`super().__init__()` triggers `setup_listeners()` immediately, and the registered handlers close over `self`. If any state were uninitialised at that point an in-flight event could race the constructor.

### Parent tracking without ContextVar

The SDK integrations (OpenAI, Anthropic, LangChain) rely on the `_current_step` `ContextVar` for automatic parent tracking because they run on the same thread or asyncio task as the user code.

CrewAI's `ThreadPoolExecutor` threads have no vapviz `ContextVar` context — they are bare OS threads with no connection to the tracer's context chain. The listener therefore maintains **explicit parent-tracking dictionaries** guarded by a single `threading.Lock`:

| Dict | Key | Value | Purpose |
|---|---|---|---|
| `_crew_roots` | `kickoff_started_event_id` | `StepContext` | Crew root node per `kickoff()` |
| `_task_nodes` | `task_name` | `StepContext` | Open task nodes |
| `_task_event_to_name` | `started_event_id` | `task_name` | Maps end events back to their task |
| `_agent_exec_nodes` | `started_event_id` | `StepContext` | Open agent-execution nodes |
| `_agent_by_id` | `agent_id` | `StepContext` | Most recent open exec node per agent |
| `_tool_nodes` | `started_event_id` | `StepContext` | Open tool-call nodes |
| `_llm_nodes` | `call_id` | `StepContext` | Open LLM-call nodes |

The lifecycle of each map entry mirrors the event lifecycle: start-event → insert; end/error event → pop and close the node.

### Deadlock avoidance

`_get_crew_root()` acquires `self._lock` to read `_current_crew_event_id` and `_crew_roots`. It must never be called while `self._lock` is already held. In `_on_agent_exec_start`, the fallback to the crew root must be split into two separate critical sections:

```python
# WRONG — deadlocks when task_name is None: _get_crew_root() tries to
# acquire self._lock which the outer `with` block already holds.
with self._lock:
    parent_ctx = (
        self._task_nodes.get(task_name) if task_name else None
    ) or self._get_crew_root()

# CORRECT — release the lock before calling _get_crew_root()
with self._lock:
    parent_ctx = self._task_nodes.get(task_name) if task_name else None
if parent_ctx is None:
    parent_ctx = self._get_crew_root()   # acquires its own lock internally
```

Because `threading.Lock` is not reentrant, a single deadlocked handler stalls one thread in the `ThreadPoolExecutor`. With accumulated listeners (as seen in repeated test runs where handlers cannot be deregistered), this could exhaust the pool and block every subsequent `emit()` call.

### Task name derivation

`AgentExecutionStartedEvent` does not carry an explicit `task_name` field — it carries a `task` object. The listener derives the canonical name with the same three-step chain used by `_on_task_start`:

```
event.task_name  →  task.name  →  _first_words(task.description, 6)
```

Using identical derivation logic guarantees the key stored in `_task_nodes` by `_on_task_start` matches the key looked up in `_on_agent_exec_start`, so agent nodes are correctly parented to the matching task node.

### Auto vs manual mode

| | Auto mode | Manual mode |
|---|---|---|
| Constructor | `VapCrewAIListener()` | `VapCrewAIListener(run=run)` |
| Run creation | New `RunContext` per `kickoff()` | Provided `RunContext` is used |
| Store | `vapviz.store.default_store` | `run._store` |
| Crew node kind | `agent` (becomes the run root) | `step` (child of run root) |
| Run lifecycle | Listener opens and closes the run | Caller's `with vapviz.trace(...)` controls it |

Manual mode also provides **test isolation**: each test creates its own `MemoryStore` + `RunContext` + `VapCrewAIListener(run=run)`. Because `_get_store()` returns `run._store`, all events from that listener write only to that store — other accumulated listener instances write to their own stores and never contaminate the assertions.

### Event flow diagram

```
crew.kickoff(inputs={...})
       │
       ▼
CrewAI event bus (crewai_event_bus)
       │  ThreadPoolExecutor.submit(handler, source, event)
       ▼
VapCrewAIListener handlers
  _on_crew_start    → create RunContext or step node; populate _crew_roots
  _on_task_start    → create task/ step node; populate _task_nodes
  _on_agent_exec_start → create agent/ step node; populate _agent_by_id
  _on_tool_start    → create tool node; populate _tool_nodes
  _on_llm_start     → create llm/ node; populate _llm_nodes
  _on_llm_end       → pop from _llm_nodes; attach usage + cost_usd
  _on_tool_end      → pop from _tool_nodes
  _on_agent_exec_end → pop from _agent_exec_nodes + _agent_by_id
  _on_task_end      → pop from _task_nodes
  _on_crew_end      → pop from _crew_roots; close run (auto) or step (manual)
       │
       │  ctx._emit(EventType.*)  [same as all other integrations]
       ▼
RunStore.add_event(VapEvent)
       │
       ▼
FastAPI SSE → React UI
```

---

## Pydantic AI Integration (`integrations/pydantic_ai.py`)

Pydantic AI has no global event bus, so `VapPydanticAI` takes a different tack from the
other integrations: it **monkey-patches `Agent.run` / `Agent.run_sync`** and reconstructs
the graph from the run's message history *after* the call returns. This trades live
streaming for a complete, accurate snapshot (per-request usage and cost, tool args and
results) with no dependency on Pydantic AI's streaming internals.

### Wrapping and the re-entrancy guard

Both `run` (async) and `run_sync` (sync) are wrapped so either entry point is traced.
Because `run_sync` delegates to `run` internally, naively wrapping both would record the
same run twice. A `ContextVar` (`_recording`) guards against this: the outer wrapper sets
it, and any nested wrapped call sees it set and passes straight through to the original.
The ContextVar (rather than a plain flag) keeps the guard correct across the asyncio task
that `run_sync` spawns.

`_wrap()` always recovers the pristine original (stashed on the wrapper as
`_vap_pydantic_ai_original`) before re-wrapping, so patching twice never stacks wrappers,
and `detach()` restores the saved originals.

### Graph reconstruction from `result.all_messages()`

After the wrapped call returns, `_record()` walks the message history once:

```
agent node (kind=agent in auto mode / step "agent/<name>" in manual mode)
  for each ModelResponse:
      llm node "llm/<model_name>"
        usage  → input/output tokens          (RequestUsage on the response)
        cost   → calculate_cost(model_name)    (aggregated onto the agent node)
        record each ToolCallPart by tool_call_id → (tool_name, args, this llm node)
  for each ModelRequest with a ToolReturnPart:
      tool node, parent = the llm node that issued the matching tool_call_id
        input  = the call's args, output = the return content
```

Events are emitted with **explicit timestamps** taken from the message objects
(`ModelResponse.timestamp`, `ToolReturnPart.timestamp`) rather than `time.time()`, so the
graph reflects real wall-clock ordering. A small `_emit()` helper constructs `VapEvent`s
directly (the public `StepContext._emit` always stamps "now", which would collapse a
post-hoc reconstruction to a single instant). Tracing is best-effort: `_record` is wrapped
so a failure never breaks the user's agent run.

### Auto vs manual mode

| | Manual mode (`VapPydanticAI(run)`) | Auto mode (`VapPydanticAI()`) |
|---|---|---|
| Store / run id | the provided run's | `default_store`, fresh id per call |
| Agent node | `step` `agent/<name>` under the run root | `agent` node *is* the run root |
| Lifecycle | nests inside an existing `vapviz.trace()` | one vapviz run per `agent.run()` |

---

## LlamaIndex Integration (`integrations/llamaindex.py`)

LlamaIndex ships its own instrumentation system — a dispatcher with **span handlers** (function
enter/exit/error) and **event handlers** (granular typed events). `VapLlamaIndex` is a span
handler, because LlamaIndex's span tree is already shaped exactly like a vapviz graph: every
instrumented method call is a span with an `id_` and a `parent_span_id`.

### Span handler, not monkey-patching

`VapLlamaIndex` subclasses `BaseSpanHandler` and registers on the **root** dispatcher
(`get_dispatcher().add_span_handler(self)`), so it sees spans from every sub-dispatcher.
The base class is a pydantic model; private state (`_provided_run`, `_spans`, `_lock`) is set
explicitly in `__init__` rather than via `PrivateAttr` factories, which aren't reliably applied
when the base's `__init__` is overridden.

Three callbacks drive everything:

```
new_span(id_, bound_args, instance, parent_span_id)   → open a node
prepare_to_exit_span(id_, ..., result)                → close it (success)
prepare_to_drop_span(id_, ..., err)                   → close it (error)
```

Each is wrapped so a tracing failure can never break the traced call. `_spans` maps a
LlamaIndex `id_` to the vapviz `(store, run_id, node_id, parent_id, kind)` it created, so a child
span resolves its parent by looking up `parent_span_id`. Timings come from `time.time()` at open
and close — these are **live, real durations** (unlike the post-hoc Pydantic AI reconstruction).

### Parent resolution and the two modes

For each span, the parent is resolved in order:

1. `parent_span_id` is a span we've already seen → same run, parent = that node.
2. No tracked parent, **manual mode** (a run was provided) → parent = the run's root node.
3. No tracked parent, **auto mode** → this span *becomes* a new run's `agent` root.

Manual mode is the recommended pattern: one `vapviz.trace()` block captures an entire RAG workflow
as a single run. Auto mode makes each top-level instrumented call its own run (LlamaIndex emits
several root spans — indexing, then querying — so a workflow yields several runs).

### Kind classification and labels

The span `id_` is `"<qualname>-<uuid>"`; stripping the trailing UUID (a fixed 5 hyphen-groups)
yields the node label, e.g. `RetrieverQueryEngine.query`. Kind is inferred from the bound
`instance`'s class plus the method name: classes ending in `LLM` (or LLM methods like
`chat`/`complete`/`predict`) → `llm`; classes ending in `Retriever` or a `retrieve` call, and
classes containing `Embedding` → `tool`; everything else → `step`. Using `endswith` rather than a
substring keeps the orchestrators honest — `RetrieverQueryEngine` is a `step`, while
`VectorIndexRetriever` is a `tool`.

---

## AutoGen Integration (`integrations/autogen.py`)

AutoGen's classic API (`ConversableAgent`, shipped today as `ag2` / `pyautogen`) has no event bus or
instrumentation dispatcher, so `VapAutoGen` monkey-patches three methods on `ConversableAgent` and
reconstructs the conversation from the call flow:

```
initiate_chat   → the chat (step "chat/<recipient>", or the run's agent root in auto mode)
generate_reply  → one agent turn (step "agent/<name>")
execute_function→ a tool/function call (tool)
```

### A thread-local node stack

The defining problem is *nesting*: tool calls happen inside an agent's `generate_reply`, and chats
can nest (a tool may start another `initiate_chat`). AutoGen runs a conversation synchronously, so a
**thread-local stack** of open node frames captures the structure exactly:

- `_begin(kind, label)` resolves the parent as the current stack top → else the provided run's root
  (manual) → else a fresh run root (auto), emits the start event, and pushes a frame.
- `_end(...)` pops the frame and emits the end (or `error`) event.

Each wrapper is `try/finally` around the original call, so frames are always popped — even when a
reply raises. Because turns push and pop around the whole `generate_reply`, sequential turns end up
as **siblings under the chat**, while a tool's `execute_function` (running inside a turn) finds that
turn on top of the stack and nests beneath it. Timings come from `time.time()` at begin/end, so
they're real. Tracing is best-effort: a failure in `_begin`/`_end` is swallowed so it can't break the
conversation.

### Modes and patch safety

Manual mode nests the whole conversation under one `vapviz.trace()`; auto mode turns each top-level
`initiate_chat` into its own run (its chat node becomes the run's `agent` root). `_wrap` always
recovers the pristine original (stashed on the wrapper) before re-wrapping, so patching twice never
stacks wrappers or double-counts, and `detach()` restores the originals.

---

## OpenTelemetry Export (`integrations/otel.py`)

This is an **export sink**, not a framework integration: it reads completed vapviz runs and
reproduces them as OpenTelemetry traces, so vapviz can feed an existing observability stack
(Jaeger, Grafana Tempo, Datadog) in parallel with its own UI.

### Reconstruction, not interception

Rather than emit spans live as events arrive, `enable_otel_export()` wraps the store's
`add_event` and waits for a run's `agent_end` event, then converts the whole `RunGraph` to
spans in one pass (`build_spans`). This mirrors the Pydantic AI integration's "reconstruct
from the finished structure" approach and keeps the mapping trivial: the graph is already
complete, so parent/child links, timings, and aggregates are all known.

```
store.add_event(event)
       │  (original call runs first — UI/SSE unaffected)
       ▼
event.type == AGENT_END ?
       │ yes
       ▼
build_spans(store.get_graph(run_id), tracer)
   roots = nodes with no parent (or parent absent from graph)
   for each node, depth-first:
       span = tracer.start_span(label, context=parent_ctx, start_time=ns(started_at))
       set gen_ai.* / vapviz.* attributes; set OK/ERROR status
       recurse into children with set_span_in_context(span)
       span.end(end_time=ns(ended_at))
```

Each run becomes its own trace because every root span is started with no parent context.
Timestamps are converted from epoch-seconds floats to integer nanoseconds.

### Wiring and threading

`enable_otel_export` resolves a `TracerProvider` three ways: an explicit `tracer_provider`,
a new provider built around an OTLP exporter when an `endpoint` is given (the exporter is
imported lazily so the gRPC/HTTP deps are only needed when actually used), or the global
provider when both are omitted (so vapviz slots into an already-configured OpenTelemetry stack).

Auto-export runs inside `add_event`, i.e. on the agent's own thread. Using a
`BatchSpanProcessor` keeps that non-blocking — `start_span`/`end` just enqueue; a background
thread does the network export. Export is best-effort: any failure in `build_spans` is
swallowed so it can never break the traced agent. `OtelExportHandle.disable()` removes the
instance-level `add_event` override (reverting to the class method); `.shutdown()` also
flushes the provider.

### Attribute mapping

Spans follow OpenTelemetry's GenAI semantic conventions where they apply
(`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`) and use a
`vapviz.*` namespace for the rest (`vapviz.node.kind`, `vapviz.node.status`, `vapviz.run_id`,
`vapviz.cost_usd`, and bounded `vapviz.input` / `vapviz.output` snapshots).

---

## Extension Guide

### Adding a new node kind

1. **`vapviz/events.py`** — add a value to `NodeKind`
2. **`vapviz/tracer.py`** — add the start/end `EventType` mappings in the `_start_event` / `_end_event` helpers
3. **`ui/src/components/AgentGraph.tsx`** — add a colour entry to `KIND_BG`
4. **`ui/src/types/events.ts`** — add the string literal to the `NodeKind` union

### Adding a new event type or node status

Both are **dual-logic** touches — the Python and TypeScript halves must move together, and the parity test enforces it:

1. **`vapviz/events.py`** ↔ **`ui/src/types/events.ts`** — add the `EventType` / `NodeStatus` value to both.
2. **Both reducers** — `_apply_event_to_graph` (`vapviz/store.py`) ↔ `applyEventToGraph` (`ui/src/store/runStore.ts`): implement identical behaviour, including "deliberately inert" (an event that changes nothing, like `state_update` / `control`, still needs a fixture proving both sides ignore it). The replay scrubber's `buildGraphAt` (`ui/src/lib/replay.ts`) is a third, nodes-only copy of the reduction — the parity test replays the fixtures through it too.
3. **A parity fixture** — drop a JSON case in `tests/fixtures/reducer_parity/`; both test halves pick it up automatically.
3a. **The SSE listener list** — `ui/src/hooks/useRunStream.ts` registers a listener per event type (unlistened SSE named events are dropped silently); its list is `satisfies Record<EventType, …>`, so the compiler flags the omission.
4. **For a new status:** every `Record<NodeStatus, …>` map in the UI (StatusBadge, BuildingView's dot map, AgentGraph borders, …) — the TS compiler lists them for you — plus `vapviz/metrics.py` (which counts runs by status) and the status clauses in `vapviz/summary.py` ↔ `ui/src/lib/summary.ts`.

The `stopped` status added with the control channel is the worked example of this checklist. Note the boundary: the control **latch** (`RunControl`, `lib/runControl.ts`) is a side channel and UI state respectively — *not* part of the dual-logic rule; only what rides the event lane is.

### Adding a new integration

Two patterns are available depending on how the target framework exposes its hooks.

**Pattern A — monkey-patch** (OpenAI, Anthropic style): intercept a specific method on a client object. Best when the framework provides a single callable to wrap and the call is made on the same thread as the vapviz trace context.

**Pattern B — event-bus listener** (CrewAI style): subclass the framework's listener base class and register handlers. Best when the framework has its own internal event system and dispatches callbacks from background threads that have no vapviz `ContextVar` context. Use explicit parent-tracking dicts instead of relying on `ContextVar`.

**Pattern A example** — follows `anthropic_sdk.py`:

```python
from ..tracer import _current_step, _uid, NodeKind, StepContext
from ..events import EventType

def patch_myframework(client):
    original = client.some_method

    def patched(*args, **kwargs):
        current = _current_step.get()
        if current is None:
            return original(*args, **kwargs)

        ctx = StepContext(
            run_id=current.run_id,
            node_id=_uid(),
            node_kind=NodeKind.TOOL,
            label="my_framework/method",
            parent_id=current.node_id,
            store=current._store,
        )
        ctx._emit(EventType.TOOL_CALL)
        token = _current_step.set(ctx)
        try:
            result = original(*args, **kwargs)
            ctx.set_output({"result": str(result)})
            ctx._emit(EventType.TOOL_RESULT, {"input": ctx._input, "output": ctx._output})
            return result
        except Exception as exc:
            ctx._emit(EventType.ERROR, {"error": str(exc)})
            raise
        finally:
            _current_step.reset(token)

    client.some_method = patched
```

For an async integration, use `async def patched` and `await original(...)` — otherwise the structure is identical.

**Pattern B example** — event-bus listener with explicit parent tracking:

```python
import threading
from ..tracer import _uid, NodeKind, StepContext, RunContext
from ..events import EventType

class VapMyFrameworkListener(MyFrameworkBaseListener):
    def __init__(self, run=None):
        self._provided_run = run
        self._lock = threading.Lock()
        self._open_nodes: dict[str, StepContext] = {}  # started_event_id -> ctx
        super().__init__()  # triggers setup_listeners() — must come LAST

    def _get_store(self):
        if self._provided_run is not None:
            return self._provided_run._store
        import vapviz.store as _sm
        return _sm.default_store

    def setup_listeners(self, bus):

        @bus.on(SomeStartEvent)
        def on_start(source, event):
            run_id = self._provided_run.run_id if self._provided_run else ...
            ctx = StepContext(
                run_id=run_id,
                node_id=_uid(),
                node_kind=NodeKind.STEP,
                label=f"step/{event.name}",
                parent_id=...,           # look up from explicit tracking dict
                store=self._get_store(),
            )
            ctx._emit(EventType.STEP_START)
            with self._lock:
                self._open_nodes[event.event_id] = ctx

        @bus.on(SomeEndEvent)
        def on_end(source, event):
            started_id = getattr(event, "started_event_id", None)
            with self._lock:
                ctx = self._open_nodes.pop(started_id, None)
            if ctx is None:
                return
            ctx.set_output({"result": event.output})
            ctx._emit(EventType.STEP_END, {"input": ctx._input, "output": ctx._output})
```

Key rules for Pattern B:
- Initialise all state before `super().__init__()`
- Never call a method that acquires `self._lock` while already inside `with self._lock:`
- Do not rely on `_current_step` `ContextVar` — the bus handler runs on a background thread with no vapviz context chain

### Implementing a custom store backend

Subclass `RunStore` and implement all abstract methods. The minimum required surface:

```python
from vapviz.store import RunStore, _apply_event_to_graph
from vapviz.events import VapEvent, RunGraph, RunSummary
import asyncio, threading

class MyStore(RunStore):
    def __init__(self):
        self._lock = threading.Lock()
        self._graphs: dict[str, RunGraph] = {}
        self._events: dict[str, list[VapEvent]] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop):
        self._loop = loop

    def add_event(self, event: VapEvent) -> None:
        with self._lock:
            self._events.setdefault(event.run_id, []).append(event)
            graph = self._graphs.setdefault(event.run_id, RunGraph(run_id=event.run_id))
            _apply_event_to_graph(graph, event)
        # Fan out to SSE subscribers
        for q in self._subscribers.get(event.run_id, []):
            if self._loop:
                self._loop.call_soon_threadsafe(q.put_nowait, event)

    # ... implement remaining abstract methods
```

Pass your store to `create_app()` and `Tracer()`:

```python
store = MyStore()
app   = vapviz.create_app(store=store)
tracer = vapviz.Tracer(store=store)
```

---

## Design Decisions

### Why `ContextVar` instead of explicit parent passing?

Users shouldn't have to thread a context object through every function call. `ContextVar` provides automatic propagation through the call stack, including across `asyncio.Task` boundaries — so concurrent async agent steps each see their own correct parent without any user intervention. Each `asyncio.Task` inherits a snapshot of the context at creation time, making concurrent fan-out safe by construction.

### Why SSE instead of WebSockets?

SSE is unidirectional (server → client), which is exactly the access pattern needed. It works over plain HTTP/1.1, requires no special server infrastructure, and the browser's `EventSource` API reconnects automatically on network interruption. WebSockets would add bidirectional complexity with no benefit for this use case.

### Why in-process store by default?

Running the tracer and server in the same process via `default_store` eliminates all serialisation overhead on the hot path — emitting an event is a lock-acquire + list-append. The remote ingest endpoint (`POST /runs/{id}/events`) exists for multi-process deployments without changing any user-facing API.

### Why SQLite with WAL mode?

SQLite's Write-Ahead Logging mode allows concurrent readers and a single writer without blocking each other. This is ideal for vapviz's access pattern: the tracer writes one event at a time (often from a non-asyncio thread), while FastAPI serves multiple concurrent SSE readers. WAL mode with `synchronous=NORMAL` gives a good safety/throughput balance — events are not lost on an OS crash, and throughput is limited by fsync-per-checkpoint rather than fsync-per-write.

### Why `sys.modules[__name__]` in `configure()`?

Python's import system creates a binding in `vapviz.__init__` at import time:

```python
from .store import default_store  # creates vapviz.default_store = <MemoryStore>
```

Later, `vapviz.store.default_store = new_store` updates the variable in the `store` module but leaves the `vapviz.default_store` name (created by the `from ... import` statement) still pointing at the old object. Writing through `sys.modules[__name__].default_store = new_store` updates the attribute on the `vapviz` module object directly, keeping both names in sync.

### Why dagre for layout?

Dagre is the de-facto standard for directed acyclic graph layout in the JavaScript ecosystem, with good TypeScript types and reliable results for tree-shaped agent graphs. The layout is recomputed on every render change — acceptable for graphs with < ~200 nodes; a future optimisation would be incremental layout using `elk.js`.
