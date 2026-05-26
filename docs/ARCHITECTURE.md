# VaP Architecture

This document describes the internal design of the Visualization Agentic Process framework — how events flow from user code through the Python tracer to the FastAPI server and ultimately to the React graph.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  User / Agent Code                                                  │
│                                                                     │
│   with vap.trace("My Agent") as run:           (sync)               │
│       with run.step("fetch", kind="tool") as step:                  │
│           step.set_input({...})                                     │
│           result = do_work()                                        │
│           step.set_output({...})                                    │
│                                                                     │
│   async with vap.atrace("Async Agent") as run: (async)              │
│       async with run.astep("fetch", kind="tool") as step:           │
│           step.set_input({...})                                     │
│           result = await do_work_async()                            │
│           step.set_output({...})                                    │
└──────────────────────────┬──────────────────────────────────────────┘
                           │  VapEvent objects (in-process)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  RunStore ABC  (vap/store.py)                                        │
│                                                                     │
│  MemoryStore   — thread-safe in-memory dict (default)               │
│  SqliteStore   — WAL-mode SQLite, survives restarts                  │
│                                                                     │
│  Both implementations:                                              │
│  • Build RunGraph (nodes + edges) incrementally on each event       │
│  • Hold asyncio.Queue per SSE subscriber                            │
│  • Use loop.call_soon_threadsafe() for thread→asyncio hand-off      │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  asyncio.Queue (per subscriber)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI Server  (vap/server.py)                                    │
│                                                                     │
│  GET    /runs                  → list[RunSummary]                   │
│  GET    /runs/{id}             → RunSummary                         │
│  GET    /runs/{id}/graph       → RunGraph snapshot                  │
│  GET    /runs/{id}/events      → SSE stream (replay + live)         │
│  POST   /runs/{id}/events      → remote event ingest                │
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
│  EventTimeline.tsx             Chronological event log               │
│  NodeDetail.tsx                Selected-node inspector               │
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

The `state_update` event is freestanding — it doesn't open/close a node, it updates metadata on the nearest parent node.

### Graph construction

The store builds a `RunGraph` incrementally as events arrive via the shared pure function `_apply_event_to_graph(graph, event)`:

- **Open event** → add `GraphNode` with `status: running`; if `parent_id` exists, add a `GraphEdge`
- **Close event** → update the matching node's `status` to `success` or `error`, set `ended_at`, merge `data`
- **`agent_end`** → also updates the top-level `RunGraph.status` and `RunGraph.ended_at`

This logic is extracted into a standalone pure function so both `MemoryStore` and `SqliteStore` share identical graph-building behaviour without inheritance.

---

## Python Package Internals

### Tracer (`vap/tracer.py`)

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

`Tracer._store` is a `@property` that reads `vap.store.default_store` at call time rather than capturing it at construction time. This means `vap.configure(db=...)` takes effect for all subsequent traces on the default tracer without requiring any re-import.

**Exception handling:**

If the body of a `with run.step()` block raises:
1. The `except` block emits an `error` event (sets node to `error` state)
2. The exception is re-raised
3. The `finally` block resets the `ContextVar` token (always runs)
4. The `if not error:` guard skips the normal close event (already marked error)

This ensures the graph always reaches a terminal state even when agents fail mid-run.

---

### Store (`vap/store.py`)

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

### SQLite Backend (`vap/backends/sqlite.py`)

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

### Server (`vap/server.py`)

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

### Configuration (`vap/__init__.py`)

`vap.configure(db=...)` is the public API for switching the module-level store:

```python
def configure(db: str | None = None) -> None:
    import sys
    import vap.store as _sm

    new_store = SqliteStore(db) if db is not None else MemoryStore()
    _sm.default_store = new_store
    # Also update the binding on this module so vap.default_store stays current
    sys.modules[__name__].default_store = new_store
```

The `sys.modules[__name__]` trick is needed because Python's import machinery creates a binding in `vap.__init__` at import time (`from .store import default_store`). Simply reassigning `_sm.default_store` would leave the `vap.default_store` name pointing at the old object. Writing through `sys.modules` updates both bindings atomically from the caller's perspective.

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
Zustand subscribers re-render
  ├── AgentGraph  (nodes + edges -> ReactFlow)
  ├── EventTimeline (events list)
  └── RunList (run summary)
```

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
<ReactFlow nodes={...} edges={...} nodeTypes={{ vap: VapNode }} />
```

`VapNode` is a custom node component that:
- Sets background colour by `node.kind` (indigo / sky / emerald / purple)
- Sets border colour by `node.status` (amber for running, green for success, red for error)
- Animates a pulsing dot when `status === "running"`
- Shows duration in ms when both `started_at` and `ended_at` are present

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

---

## Anthropic SDK Integration (`integrations/anthropic_sdk.py`)

`patch_anthropic(client)` auto-detects whether the client is `anthropic.Anthropic` (sync) or `anthropic.AsyncAnthropic` (async) and applies the appropriate wrapper to `client.messages.create`.

**Sync path:** replaces `client.messages.create` with a regular function that wraps the call in a `StepContext`.

**Async path:** replaces `client.messages.create` with an `async def` that `await`s the original coroutine.

Both paths:
1. Check `_current_step` — if no active VaP trace context, call the original immediately (zero overhead outside a trace)
2. Create a `StepContext` with `kind=llm`, parented to the current step
3. Emit `llm_call` with model name, message count, and tool names
4. Call the original `messages.create`
5. Emit `llm_response` with response text, `stop_reason`, and token usage
6. On exception: emit `error` and re-raise

Because Python module imports are cached, the `ContextVar` imported inside the wrapper is the same object as the one used by the tracer — so parent tracking works correctly across the patched call.

---

## Extension Guide

### Adding a new node kind

1. **`vap/events.py`** — add a value to `NodeKind`
2. **`vap/tracer.py`** — add the start/end `EventType` mappings in the `_start_event` / `_end_event` helpers
3. **`ui/src/components/AgentGraph.tsx`** — add a colour entry to `KIND_BG`
4. **`ui/src/types/events.ts`** — add the string literal to the `NodeKind` union

### Adding a new integration

Create `vap/integrations/<framework>.py` following the pattern in `anthropic_sdk.py`:

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

### Implementing a custom store backend

Subclass `RunStore` and implement all abstract methods. The minimum required surface:

```python
from vap.store import RunStore, _apply_event_to_graph
from vap.events import VapEvent, RunGraph, RunSummary
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
app   = vap.create_app(store=store)
tracer = vap.Tracer(store=store)
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

SQLite's Write-Ahead Logging mode allows concurrent readers and a single writer without blocking each other. This is ideal for VaP's access pattern: the tracer writes one event at a time (often from a non-asyncio thread), while FastAPI serves multiple concurrent SSE readers. WAL mode with `synchronous=NORMAL` gives a good safety/throughput balance — events are not lost on an OS crash, and throughput is limited by fsync-per-checkpoint rather than fsync-per-write.

### Why `sys.modules[__name__]` in `configure()`?

Python's import system creates a binding in `vap.__init__` at import time:

```python
from .store import default_store  # creates vap.default_store = <MemoryStore>
```

Later, `vap.store.default_store = new_store` updates the variable in the `store` module but leaves the `vap.default_store` name (created by the `from ... import` statement) still pointing at the old object. Writing through `sys.modules[__name__].default_store = new_store` updates the attribute on the `vap` module object directly, keeping both names in sync.

### Why dagre for layout?

Dagre is the de-facto standard for directed acyclic graph layout in the JavaScript ecosystem, with good TypeScript types and reliable results for tree-shaped agent graphs. The layout is recomputed on every render change — acceptable for graphs with < ~200 nodes; a future optimisation would be incremental layout using `elk.js`.
