# VaP — Visualization Agentic Process

A lightweight Python + React framework for **tracing and visualizing AI agent pipelines** in real time.

Instrument your agent with a single context manager. Every step, tool call, and LLM invocation appears instantly as a live interactive graph in the browser — with inputs, outputs, durations, and error states.

![VaP demo screenshot](docs/screenshot.png)

---

## Features

- **Zero-boilerplate tracing** — `with vap.trace("my agent")` is all you need
- **Automatic nesting** — `ContextVar`-based parent tracking; deeply nested steps wire up correctly without any manual IDs
- **Anthropic SDK auto-instrumentation** — one call to `vap.patch_anthropic(client)` traces every `messages.create` call automatically
- **Live streaming** — events flow from tracer → FastAPI → SSE → React in real time; the graph updates as the agent runs
- **Interactive graph** — ReactFlow DAG with dagre auto-layout, zoom/pan, minimap
- **Node detail panel** — click any node to inspect its inputs, outputs, token usage, duration, and errors
- **Event timeline** — chronological log of all 10 event types with millisecond timestamps
- **Remote ingest** — push events via HTTP from any process or language (`POST /runs/{id}/events`)

---

## Quick Start

### 1. Python backend

```bash
# Clone and install
git clone https://github.com/kochrisdev/vap.git
cd vap
pip install -e .
```

### 2. React UI

```bash
cd ui
npm install
npm run dev        # → http://localhost:5173
```

### 3. Start the dev server + run a demo

```bash
# From the project root (separate terminal from the UI)
python run_dev.py  # starts FastAPI on :8001 and runs a demo agent
```

Open **http://localhost:5173**, click "Research Agent Demo" in the sidebar.

---

## Core API

### Tracing a run

```python
import vap

with vap.trace("My Agent") as run:
    # Every block inside becomes a node in the graph
    with run.step("fetch_data", kind="tool") as step:
        step.set_input({"url": "https://api.example.com/data"})
        data = fetch()
        step.set_output({"rows": len(data)})

    with run.step("analyze", kind="step") as step:
        step.set_input({"rows": len(data)})
        result = analyze(data)
        step.set_output({"summary": result})
```

### Node kinds

| `kind=` | Graph colour | Emits events |
|---|---|---|
| `"agent"` | Indigo | `agent_start` / `agent_end` |
| `"step"` | Sky blue | `step_start` / `step_end` |
| `"tool"` | Emerald | `tool_call` / `tool_result` |
| `"llm"` | Purple | `llm_call` / `llm_response` |

### Nesting

Steps nest automatically — no parent IDs needed:

```python
with vap.trace("Pipeline") as run:
    with run.step("phase_1", kind="step"):          # depth 1
        with run.step("sub_task_a", kind="tool"):   # depth 2 — auto-parented
            ...
        with run.step("sub_task_b", kind="tool"):   # depth 2 — auto-parented
            ...
```

### Error handling

Unhandled exceptions are caught, recorded on the node as `status: error`, and re-raised — the run continues to propagate normally:

```python
with vap.trace("Risky Agent") as run:
    with run.step("might_fail", kind="tool") as step:
        result = risky_operation()   # if this raises, node → error, exception re-raised
```

---

## Anthropic SDK Integration

```python
import anthropic
import vap

client = anthropic.Anthropic()
vap.patch_anthropic(client)        # one-time setup

with vap.trace("Claude Agent") as run:
    with run.step("research", kind="step"):
        # This call is traced automatically as an LLM node
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": "Summarize AI trends in 2024."}],
        )
```

Each `messages.create` call becomes a purple **llm** node showing:
- Model name and token usage (`input_tokens`, `output_tokens`)
- Full input messages (truncated in UI)
- Response text and `stop_reason`

---

## REST API

The FastAPI server (`http://localhost:8001`) exposes:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/runs` | List all runs (summary) |
| `GET` | `/runs/{id}/graph` | Full graph snapshot (nodes + edges) |
| `GET` | `/runs/{id}/events` | **SSE stream** — replays history then pushes live |
| `POST` | `/runs/{id}/events` | Ingest an event from a remote process |
| `DELETE` | `/runs` | Clear all runs from memory |

Interactive docs: **http://localhost:8001/docs**

### SSE event types

The stream emits named SSE events matching the `type` field of each `VapEvent`:

```
agent_start  agent_end
step_start   step_end
tool_call    tool_result
llm_call     llm_response
state_update
error
```

---

## Project Structure

```
vap/                          Python package
├── __init__.py               Public API: trace, patch_anthropic, app
├── events.py                 Pydantic models — VapEvent, GraphNode, RunGraph
├── store.py                  Thread-safe in-memory store + asyncio pub/sub
├── tracer.py                 trace() context manager, StepContext, ContextVar nesting
├── server.py                 FastAPI app — REST + SSE endpoints
└── integrations/
    └── anthropic_sdk.py      patch_anthropic() — wraps messages.create

ui/src/                       Vite + React + TypeScript
├── App.tsx                   Root layout — sidebar / graph / timeline / detail panel
├── components/
│   ├── AgentGraph.tsx        ReactFlow DAG with dagre auto-layout
│   ├── EventTimeline.tsx     Chronological event log
│   ├── NodeDetail.tsx        Selected-node inspector
│   └── RunList.tsx           Sidebar run list (polls /runs every 3s)
├── hooks/
│   └── useRunStream.ts       SSE hook — subscribes to /runs/{id}/events
├── store/
│   └── runStore.ts           Zustand store — builds graph state from events
└── types/
    └── events.ts             TypeScript mirror of Python event models

examples/
├── simple_demo.py            Multi-step fake agent — no API key needed
└── anthropic_demo.py         Real Claude API calls with auto-tracing

run_dev.py                    One-command dev entry point (server + demo agent)
pyproject.toml                Python package metadata + dependencies
```

---

## Running the Examples

### Simple demo (no API key)

```bash
python examples/simple_demo.py
```

Starts the server on `:8000` in a background thread, runs a simulated research agent, then waits for Enter.

### Anthropic demo

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python examples/anthropic_demo.py
```

Runs two real Claude API calls and traces them through VaP.

---

## Custom Tracer Instance

If you need multiple isolated stores (e.g. in tests):

```python
from vap import Tracer, RunStore

store = RunStore()
tracer = Tracer(store=store)

with tracer.trace("isolated run") as run:
    ...
```

---

## Roadmap

- [ ] **Persistent storage** — SQLite / PostgreSQL backend
- [ ] **LangGraph integration** — automatic callback handler
- [ ] **Async tracer** — `async with` support for async agent frameworks
- [ ] **Token cost overlay** — per-node cost estimation
- [ ] **Run comparison** — diff two runs side by side
- [ ] **Export** — download run as JSON / PNG

---

## Dependencies

### Python
| Package | Role |
|---|---|
| `fastapi` | REST + SSE server |
| `uvicorn` | ASGI server |
| `pydantic` | Event schema validation |
| `sse-starlette` | Server-Sent Events support |
| `anthropic` | Optional — Anthropic SDK integration |

### UI
| Package | Role |
|---|---|
| `@xyflow/react` | Graph canvas (ReactFlow v12) |
| `dagre` | Automatic DAG layout |
| `zustand` | Client-side state management |
| `tailwindcss` | Utility CSS |
| `lucide-react` | Icons |

---

## License

MIT
