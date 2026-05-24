# VaP Architecture

This document describes the internal design of the Visualization Agentic Process framework — how events flow from user code through the Python tracer to the FastAPI server and ultimately to the React graph.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  User / Agent Code                                                  │
│                                                                     │
│   with vap.trace("My Agent") as run:                                │
│       with run.step("fetch", kind="tool") as step:                  │
│           step.set_input({...})                                     │
│           result = do_work()                                        │
│           step.set_output({...})                                    │
└──────────────────────────┬──────────────────────────────────────────┘
                           │  VapEvent objects (sync, in-process)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  RunStore  (vap/store.py)                                           │
│                                                                     │
│  • Thread-safe dict of run_id → [VapEvent]                          │
│  • Builds RunGraph (nodes + edges) incrementally on each event      │
│  • Holds asyncio.Queue per SSE subscriber                           │
│  • Uses loop.call_soon_threadsafe() to cross thread→asyncio boundary│
└──────────────────────────┬───────────────────────────────────────────┘
                           │  asyncio.Queue (per subscriber)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI Server  (vap/server.py)                                    │
│                                                                     │
│  GET  /runs                    → list[RunSummary]                   │
│  GET  /runs/{id}/graph         → RunGraph snapshot                  │
│  GET  /runs/{id}/events        → SSE stream (replay + live)         │
│  POST /runs/{id}/events        → remote event ingest                │
│  DEL  /runs                    → clear store                        │
└──────────────────────────┬───────────────────────────────────────────┘
                           │  Server-Sent Events  (EventSource API)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  React UI  (ui/src/)                                                │
│                                                                     │
│  useRunStream(runId)           SSE hook → applyEvent() in Zustand   │
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
```

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

The `RunStore` builds a `RunGraph` incrementally as events arrive:

- **Open event** → add `GraphNode` with `status: running`; if `parent_id` exists and parent is already in the graph, add a `GraphEdge`
- **Close event** → update the matching node's `status` to `success` or `error`, set `ended_at`, merge `data`
- **`agent_end`** → also updates the top-level `RunGraph.status` and `RunGraph.ended_at`

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
    parent = _current_step.get()  # → root_ctx
    _current_step = phase1_ctx    # token_1 saved
    edge: root → phase1

    step("sub_task"):
      parent = _current_step.get()  # → phase1_ctx
      _current_step = sub_ctx       # token_2 saved
      edge: phase1 → sub

      yield  ← user code runs here

      _current_step.reset(token_2)  # → back to phase1_ctx

    _current_step.reset(token_1)  # → back to root_ctx

  _current_step.reset(token_0)  # → None
```

`ContextVar.reset(token)` is used instead of `set(None)` so that async tasks and threads each have their own isolated context chain — two concurrent runs never interfere.

**Exception handling:**

If the body of a `with run.step()` block raises:
1. The `except` block emits an `error` event (sets node to `error` state)
2. The exception is re-raised
3. The `finally` block resets the `ContextVar` token (always runs)
4. The `if not error:` guard skips the normal close event (already marked error)

This ensures the graph always reaches a terminal state even when agents fail mid-run.

### Store (`vap/store.py`)

The store is the single source of truth shared between the sync tracer thread and the async FastAPI server.

**Thread-safety model:**

```
Tracer thread (sync)          asyncio event loop (server)
      │                               │
      │  add_event(event)             │
      │  ┌─ acquire Lock             │
      │  │  append to list           │
      │  │  update graph             │
      │  └─ release Lock             │
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

### Server (`vap/server.py`)

The FastAPI app is a thin façade over the store. The most interesting endpoint is the SSE stream:

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

## React UI Internals

### State management (`runStore.ts`)

The Zustand store is the client-side equivalent of `RunStore`. It receives raw `VapEvent` objects from the SSE hook and applies the same open/close logic to build `nodes` and `edges` arrays:

```
SSE event arrives
       │
       ▼
applyEvent(event)
  ├── START type → push new GraphNode (status: running), maybe push GraphEdge
  ├── END type   → update matching node (status: success/error, ended_at, data)
  └── ERROR type → update matching node (status: error)
       │
       ▼
Zustand subscribers re-render
  ├── AgentGraph  (nodes + edges → ReactFlow)
  ├── EventTimeline (events list)
  └── RunList (run summary)
```

The store also maintains a `runs` array (the sidebar list) which is updated in-place as events arrive for already-known runs, or prepended for new runs.

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

`patch_anthropic(client)` replaces `client.messages.create` with a wrapper that:

1. Checks `_current_step` — if there's no active VaP trace context, calls the original and returns immediately (zero overhead outside a trace)
2. Creates a `StepContext` with `kind=llm`, parented to the current step
3. Emits `llm_call` with model name, message count, and tool names
4. Calls the original `messages.create`
5. Emits `llm_response` with response text, `stop_reason`, and token usage
6. On exception: emits `error` and re-raises

Because Python module imports are cached, the `ContextVar` imported inside the wrapper is the same object as the one used by the tracer — so parent tracking works correctly.

---

## Extension Guide

### Adding a new node kind

1. **`vap/events.py`** — add a value to `NodeKind`
2. **`vap/tracer.py`** — add the start/end `EventType` mappings in `step()` (the two dicts)
3. **`ui/src/components/AgentGraph.tsx`** — add a colour entry to `KIND_BG`
4. **`ui/src/types/events.ts`** — add the string literal to the `NodeKind` union

### Adding a new integration

Create `vap/integrations/<framework>.py` following the pattern in `anthropic_sdk.py`:

```python
from ..tracer import get_current_step, _current_step, _uid, NodeKind, StepContext
from ..events import EventType

def patch_myframework(client):
    original = client.some_method

    def patched(*args, **kwargs):
        current = get_current_step()
        if current is None:
            return original(*args, **kwargs)

        ctx = StepContext(
            run_id=current.run_id,
            node_id=_uid(),
            node_kind=NodeKind.TOOL,   # or LLM, STEP
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

### Using a custom store

The `RunStore` interface is simple: if you want persistent storage (e.g. SQLite), subclass `RunStore` and override `add_event`, `get_events`, `get_graph`, and `list_runs`. Pass your custom store to `create_app()` and `Tracer()`:

```python
store = MyPersistentStore("sqlite:///vap.db")
app   = vap.create_app(store=store)
tracer = vap.Tracer(store=store)

with tracer.trace("persistent run") as run:
    ...
```

---

## Design Decisions

### Why `ContextVar` instead of explicit parent passing?

Users shouldn't have to thread a context object through every function call. `ContextVar` provides automatic propagation through the call stack, including across `asyncio.Task` boundaries — so concurrent async agent steps each see their own correct parent without any user intervention.

### Why SSE instead of WebSockets?

SSE is unidirectional (server → client), which is exactly the access pattern needed. It works over plain HTTP/1.1, requires no special server infrastructure, and the browser's `EventSource` API reconnects automatically on network interruption. WebSockets would add bidirectional complexity with no benefit for this use case.

### Why in-process store by default?

Running the tracer and server in the same process via `default_store` eliminates all serialisation overhead on the hot path — emitting an event is a lock-acquire + list-append. The remote ingest endpoint (`POST /runs/{id}/events`) exists for multi-process deployments without changing any user-facing API.

### Why dagre for layout?

Dagre is the de-facto standard for directed acyclic graph layout in the JavaScript ecosystem, with good TypeScript types and reliable results for tree-shaped agent graphs. The layout is recomputed on every render change — acceptable for graphs with < ~200 nodes; a future optimisation would be incremental layout using `elk.js`.
