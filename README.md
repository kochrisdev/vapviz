# VaP — Visualization Agentic Process

A lightweight Python + React framework for **tracing and visualizing AI agent pipelines** in real time.

Instrument your agent with a single context manager. Every step, tool call, and LLM invocation appears instantly as a live interactive graph in the browser — with inputs, outputs, durations, and error states.

![VaP demo screenshot](docs/screenshot.png)

---

## Features

- **Zero-boilerplate tracing** — `with vap.trace("my agent")` is all you need
- **Async-native** — `async with vap.atrace(...)` / `run.astep(...)` for full asyncio support
- **Automatic nesting** — `ContextVar`-based parent tracking; deeply nested steps wire up correctly without any manual IDs
- **Anthropic SDK auto-instrumentation** — one call to `vap.patch_anthropic(client)` traces every `messages.create` call automatically (sync **and** async clients)
- **OpenAI SDK auto-instrumentation** — `vap.patch_openai(client)` traces every `chat.completions.create` call (sync **and** async)
- **LangGraph / LangChain integration** — `VapCallbackHandler` captures all chain, tool, and LLM calls from any LangChain-compatible framework
- **CrewAI integration** — `VapCrewAIListener` hooks into CrewAI's native event bus to trace Crews, Tasks, Agents, Tools, and LLM calls automatically
- **Persistent storage** — `vap.configure(db="vap.db")` switches from in-memory to SQLite with zero code changes
- **CLI** — `vap serve --db vap.db` starts the server from the command line
- **Live streaming** — events flow from tracer → FastAPI → SSE → React in real time; the graph updates as the agent runs
- **Interactive graph** — ReactFlow DAG with dagre auto-layout, zoom/pan, minimap
- **Node detail panel** — click any node to inspect its inputs, outputs, token usage, duration, and errors
- **Event timeline** — chronological log of all 10 event types with millisecond timestamps
- **Remote ingest** — push events via HTTP from any process or language (`POST /runs/{id}/events`)
- **Run comparison** — diff any two runs side by side: node diff (only A / only B / common), duration Δ, and cost Δ
- **Export** — download any run as JSON (`GET /runs/{id}/export`) or PNG (html2canvas capture)

---

## Tutorial

New to VaP? The **[step-by-step tutorial](docs/TUTORIAL.md)** walks you from installation to a
fully instrumented agent — covering tracing, async, error handling, cost tracking, OpenAI/Anthropic
auto-instrumentation, LangGraph, CrewAI, remote ingest, run comparison, and export.

---

## Deployment

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for full production deployment instructions, including Docker, Nginx, Railway, Render, Fly.io, health checks, and security hardening.

---

## Quick Start

### 1. Python backend

```bash
# Clone and install
git clone https://github.com/kochrisdev/vap.git
cd vap
pip install -e .                  # core only
pip install -e ".[all]"           # + Anthropic, OpenAI, LangChain, CrewAI integrations
```

### 2. React UI

```bash
cd ui
npm install
npm run dev        # -> http://localhost:5173
```

### 3. Start the server

```bash
# In-memory (resets on restart):
vap serve

# Persistent SQLite (survives restarts):
vap serve --db vap.db
```

Open **http://localhost:5173** to see the live graph UI.

---

## Core API

### Synchronous tracing

```python
import vap

with vap.trace("My Agent") as run:
    with run.step("fetch_data", kind="tool") as step:
        step.set_input({"url": "https://api.example.com/data"})
        data = fetch()
        step.set_output({"rows": len(data)})

    with run.step("analyze", kind="step") as step:
        step.set_input({"rows": len(data)})
        result = analyze(data)
        step.set_output({"summary": result})
```

### Async tracing

```python
import asyncio
import vap

async def run_agent():
    async with vap.atrace("Async Agent") as run:
        async with run.astep("plan", kind="step") as step:
            step.set_input({"goal": "research"})
            await asyncio.sleep(0.1)
            step.set_output({"urls": 3})

        # Concurrent tool calls
        results = await asyncio.gather(
            fetch_with_step(run, "https://example.com/a"),
            fetch_with_step(run, "https://example.com/b"),
        )

asyncio.run(run_agent())
```

Both `trace`/`atrace` and `step`/`astep` are interchangeable in terms of what gets recorded — use whichever matches your code's execution model.

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

### Cost utilities

VaP ships a built-in pricing table covering 20+ OpenAI and Anthropic models. Use the utility directly or let the SDK patches attach cost automatically:

```python
import vap

# Returns USD cost as a float, or None for unknown models
cost = vap.calculate_cost("gpt-4o", input_tokens=1000, output_tokens=500)
# -> 0.0075

# Format for display
vap.format_cost(cost)          # -> "$0.0075"
vap.format_cost(0.000005)      # -> "<$0.0001"
```

When `patch_openai` or `patch_anthropic` is active, cost is calculated automatically and stored as `cost_usd` in every `llm` node's output data. The per-run total appears in the sidebar, and each LLM node shows its individual cost in the graph.

### Error handling

Unhandled exceptions are caught, recorded on the node as `status: error`, and re-raised — the run continues to propagate normally:

```python
with vap.trace("Risky Agent") as run:
    with run.step("might_fail", kind="tool") as step:
        result = risky_operation()   # if this raises, node -> error, exception re-raised
```

---

## Persistence

By default VaP uses an in-memory store — fast, no setup required, but runs are lost when the process exits.

### SQLite persistence

```python
import vap

# Call once at startup, before any trace() calls
vap.configure(db="vap.db")

with vap.trace("My Agent") as run:
    ...
```

Or use the CLI:

```bash
vap serve --db vap.db
```

Runs are replayed from the database on startup, so you can view historical traces after restarting the server.

---

## CLI

```
vap serve [OPTIONS]

Options:
  --host TEXT       Bind host (default: 0.0.0.0)
  --port INT        Bind port (default: 8001)
  --db PATH         SQLite database path for persistence (default: in-memory)
  --reload          Enable auto-reload for development
  --log-level TEXT  Uvicorn log level (default: warning)
```

---

## SDK Integrations

### Anthropic

Works with both sync and async Anthropic clients:

```python
import anthropic, vap

client = anthropic.Anthropic()
vap.patch_anthropic(client)                     # sync

async_client = anthropic.AsyncAnthropic()
vap.patch_anthropic(async_client)               # async — same call
```

```bash
pip install "vap[anthropic]"
```

### OpenAI

```python
import openai, vap

client = openai.OpenAI()
vap.patch_openai(client)                        # sync

async_client = openai.AsyncOpenAI()
vap.patch_openai(async_client)                  # async — same call
```

```bash
pip install "vap[openai]"
```

Each `chat.completions.create` call becomes a purple **llm** node showing model name, messages, token usage (`input_tokens`, `output_tokens`), response text, and estimated USD cost for known models.

### LangGraph / LangChain

Pass `VapCallbackHandler` to any LangChain-compatible graph or chain:

```python
from vap.integrations.langchain import VapCallbackHandler

with vap.trace("LangGraph Agent") as run:
    handler = VapCallbackHandler(run)
    result = graph.invoke(
        {"messages": [HumanMessage(content="Research AI trends")]},
        config={"callbacks": [handler]},
    )
```

```bash
pip install "vap[langchain]" langgraph langchain-openai
```

Every chain invocation, tool call, and LLM call appears as a correctly nested node in the graph — no manual instrumentation needed.

### CrewAI

Register `VapCrewAIListener` once before calling `crew.kickoff()`:

```python
import vap
from vap.integrations.crewai_listener import VapCrewAIListener

vap.configure(db="vap.db")
VapCrewAIListener()          # auto mode — one new VaP run per kickoff()

result = crew.kickoff(inputs={"topic": "AI agents"})
```

Or attach to an existing run (**manual mode**) to embed the crew inside a larger pipeline trace:

```python
with vap.trace("Full Pipeline") as run:
    with run.step("pre_process", kind="step") as step: ...

    VapCrewAIListener(run=run)   # tasks appear as children of this run
    crew.kickoff(inputs={...})

    with run.step("post_process", kind="step") as step: ...
```

```bash
pip install "vap[crewai]"
```

Every Task, Agent execution, Tool call, and LLM round-trip is captured automatically via
CrewAI's native event bus — no `verbose=True` noise, no monkey-patching.

---

## REST API

The FastAPI server (`http://localhost:8001`) exposes:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/runs` | List all runs (summary) |
| `GET` | `/runs/{id}` | Single run summary |
| `GET` | `/runs/{id}/graph` | Full graph snapshot (nodes + edges) |
| `GET` | `/runs/{id}/export` | Download run graph as a JSON file attachment |
| `GET` | `/runs/{id}/events` | **SSE stream** — replays history then pushes live |
| `GET` | `/runs/compare?a={id}&b={id}` | Return two run graphs for comparison |
| `POST` | `/runs/{id}/events` | Ingest an event from a remote process |
| `DELETE` | `/runs` | Clear all runs from store |
| `DELETE` | `/runs/{id}` | Delete a single run |

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
├── __init__.py               Public API: trace, atrace, configure, patch_anthropic
├── events.py                 Pydantic models — VapEvent, GraphNode, RunGraph
├── store.py                  RunStore ABC + MemoryStore + thread-safe pub/sub
├── tracer.py                 trace/atrace context managers, ContextVar nesting
├── server.py                 FastAPI app — REST + SSE endpoints
├── cli.py                    vap serve command
├── cost.py                   Token cost — 20+ model pricing table, calculate_cost()
├── backends/
│   ├── __init__.py
│   └── sqlite.py             SqliteStore — WAL-mode SQLite persistence
└── integrations/
    ├── anthropic_sdk.py      patch_anthropic() — sync + async client support
    ├── openai_sdk.py         patch_openai() — sync + async client support
    ├── langchain.py          VapCallbackHandler — LangGraph / LangChain integration
    └── crewai_listener.py    VapCrewAIListener — CrewAI event bus integration

ui/src/                       Vite + React + TypeScript
├── App.tsx                   Root layout — sidebar / graph / timeline / detail panel
├── components/
│   ├── AgentGraph.tsx        ReactFlow DAG with dagre auto-layout
│   ├── EventTimeline.tsx     Chronological event log
│   ├── ExportMenu.tsx        Export dropdown (JSON download + PNG capture)
│   ├── NodeDetail.tsx        Selected-node inspector
│   ├── RunComparison.tsx     Side-by-side diff of two runs
│   └── RunList.tsx           Sidebar run list with compare button
├── hooks/
│   └── useRunStream.ts       SSE hook — subscribes to /runs/{id}/events
├── store/
│   └── runStore.ts           Zustand store — builds graph state from events
└── types/
    └── events.ts             TypeScript mirror of Python event models

examples/
├── simple_demo.py            Multi-step fake agent — no API key needed
├── async_demo.py             Async agent with concurrent steps (asyncio.gather)
├── error_handling_demo.py    Three error scenarios — leaf, nested, partial failure
├── cost_tracking_demo.py     Simulated LLM cost overlay — no API key needed
├── remote_ingest_demo.py     HTTP POST ingest from a separate process (stdlib only)
├── anthropic_demo.py         Real Claude API calls with auto-tracing
├── openai_demo.py            OpenAI chat.completions with auto-tracing
├── langgraph_demo.py         LangGraph ReAct agent with VapCallbackHandler
└── crewai_demo.py            CrewAI multi-agent crew with VapCrewAIListener

docs/
├── TUTORIAL.md               Step-by-step learning guide (start here)
├── ARCHITECTURE.md           Internal design — event flow, store, React state machine
├── DEVELOPER_REFERENCE.md    Complete Python API, CLI, REST, SSE, TypeScript types
└── DEPLOYMENT.md             Docker, Nginx, cloud platforms, security

tests/
├── conftest.py               Shared fixtures
├── test_tracer.py            Sync/async tracing, nesting, ContextVar, errors
├── test_store.py             MemoryStore, SqliteStore, graph mutation
├── test_server.py            REST endpoints
├── test_openai_patch.py      OpenAI integration (mock, no API key)
├── test_langchain.py         LangChain handler (skipped if langchain-core absent)
├── test_cost.py              Pricing table, calculate_cost(), integration cost output
└── test_crewai_listener.py   CrewAI listener (skipped if crewai absent)

run_dev.py                    One-command dev entry point (server + demo agent)
pyproject.toml                Python package metadata + dependencies
```

---

## Running the Examples

### Simple demo (no API key)

```bash
python examples/simple_demo.py
```

Starts the server on `:8001` in a background thread, runs a simulated research agent, then waits for Enter.

### Async demo (no API key)

```bash
python examples/async_demo.py

# Or push to an already-running server:
vap serve --db vap.db
python examples/async_demo.py --agent-only
```

Demonstrates `atrace`, `astep`, and `asyncio.gather` for concurrent fan-out tool calls.

### Error handling demo (no API key)

```bash
python examples/error_handling_demo.py
```

Runs three separate traces that each demonstrate a different failure mode:
- **Leaf failure** — a tool raises `ConnectionError`; the caller catches it, a fallback step continues
- **Nested failure** — a child step raises `ValueError` which propagates to mark the parent node red too
- **Partial failure** — one of three parallel fetches fails while the others succeed; a downstream merge step still runs

Failed nodes appear red in the graph; successfully-completed nodes stay green.

### Cost tracking demo (no API key)

```bash
python examples/cost_tracking_demo.py
```

Simulates three LLM pipelines (gpt-4o-mini, gpt-4o, mixed-model) using `vap.calculate_cost()` to attach
`cost_usd` to each node. Shows per-node cost labels (purple) in the graph and per-run totals in the
sidebar. Select two runs and click ⊕ to compare costs side by side.

### Remote ingest demo (no API key, no vap import in agent)

```bash
python examples/remote_ingest_demo.py

# Or push to an already-running server:
vap serve --db vap.db
python examples/remote_ingest_demo.py --agent-only --server-url http://localhost:8001
```

Demonstrates the HTTP ingest pattern: the "agent" process uses only `urllib.request` (no `vap` import)
and POSTs `VapEvent` JSON payloads directly to `POST /runs/{run_id}/events`. Useful for polyglot
architectures where the agent runs in a different language or on a separate machine.

### Anthropic demo

```bash
pip install "vap[anthropic]"
export ANTHROPIC_API_KEY=sk-ant-...
python examples/anthropic_demo.py
```

### OpenAI demo

```bash
pip install "vap[openai]"
export OPENAI_API_KEY=sk-...
python examples/openai_demo.py
```

Runs three `gpt-4o-mini` calls and traces each as a nested `llm` node.

### LangGraph demo

```bash
pip install "vap[langchain]" langgraph langchain-openai
export OPENAI_API_KEY=sk-...
python examples/langgraph_demo.py
```

Runs a ReAct agent with three tools (`search_web`, `calculate`, `summarize_findings`). Every chain step, tool call, and LLM round-trip is traced automatically via `VapCallbackHandler`.

### CrewAI demo

```bash
pip install "vap[crewai]"
export OPENAI_API_KEY=sk-...
python examples/crewai_demo.py
```

Runs two traces:
1. **Auto mode** — a two-agent sequential crew (researcher → writer). `VapCrewAIListener()` is registered once and auto-creates a VaP run per `kickoff()`.
2. **Manual mode** — the same crew embedded inside a larger `vap.trace()` pipeline with pre/post-processing steps on either side.

---

## Configuration Reference

```python
import vap

# Use SQLite persistence (call once at startup)
vap.configure(db="vap.db")

# Use in-memory store (default)
vap.configure()

# Custom store passed directly
from vap import Tracer, MemoryStore
store = MemoryStore()
tracer = Tracer(store=store)

with tracer.trace("isolated run") as run:
    ...
```

---

## Roadmap

### v0.2.0 — Phase 1 (complete)
- [x] **Persistent storage** — SQLite backend with WAL mode, replay on startup
- [x] **Async tracer** — `atrace` / `astep` with `asynccontextmanager`
- [x] **CLI** — `vap serve --db <path>`
- [x] **Async Anthropic** — `patch_anthropic` detects `AsyncAnthropic` automatically
- [x] **Single-run REST** — `GET /runs/{id}`, `DELETE /runs/{id}`

### v0.3.0 — Phase 2 (complete)
- [x] **OpenAI SDK integration** — `patch_openai(client)` for sync + async clients
- [x] **LangGraph / LangChain integration** — `VapCallbackHandler` for any LangChain-compatible framework
- [x] **Test suite** — 90 tests covering tracer, stores, server, and integrations

### v0.4.0 — Phase 3 (complete)
- [x] **Token cost overlay** — per-node USD cost on every LLM call, total cost per run in sidebar
- [x] **Pricing table** — 20+ OpenAI and Anthropic models with prefix-match fallback
- [x] **`vap.calculate_cost(model, input_tokens, output_tokens)`** — public cost utility

### v0.5.0 — Phase 4 (complete)
- [x] **Run comparison** — diff two runs side by side; stats header (duration Δ, cost Δ, node diff), side-by-side ReactFlow graphs
- [x] **Export** — download run as JSON (`GET /runs/{id}/export`) or PNG (html2canvas capture of the graph canvas)
- [x] **`GET /runs/compare?a={id}&b={id}`** — server endpoint returning both graphs in one request
- [x] **Compare mode in sidebar** — hover any run to see the ⊕ compare button; amber highlight + banner when active

### v0.6.0 — Phase 5 (complete)
- [x] **CrewAI integration** — `VapCrewAIListener` hooks into CrewAI's native `BaseEventListener` event bus; traces Crews, Tasks, Agent executions, Tool calls, and LLM round-trips automatically
- [x] **Auto + manual mode** — auto mode creates a new VaP run per `kickoff()`; manual mode attaches the crew as a sub-section of an existing `vap.trace()` pipeline
- [x] **LLM cost on CrewAI nodes** — `cost_usd` auto-attached via LiteLLM usage dict; `pip install "vap[crewai]"`
- [x] **19-test suite** — `tests/test_crewai_listener.py` covers crew lifecycle, task/agent/tool/LLM nodes, cost tracking, and import guard

---

## Dependencies

### Python
| Package | Role |
|---|---|
| `fastapi` | REST + SSE server |
| `uvicorn` | ASGI server |
| `pydantic` | Event schema validation |
| `sse-starlette` | Server-Sent Events support |
| `anthropic` *(optional)* | Anthropic SDK integration (`pip install "vap[anthropic]"`) |
| `openai` *(optional)* | OpenAI SDK integration (`pip install "vap[openai]"`) |
| `langchain-core` *(optional)* | LangGraph/LangChain integration (`pip install "vap[langchain]"`) |
| `crewai` *(optional)* | CrewAI integration (`pip install "vap[crewai]"`) |

`sqlite3` is part of the Python standard library — no extra install needed for persistence.

### UI
| Package | Role |
|---|---|
| `@xyflow/react` | Graph canvas (ReactFlow v12) |
| `dagre` | Automatic DAG layout |
| `html2canvas` | PNG snapshot of the graph canvas |
| `zustand` | Client-side state management |
| `tailwindcss` | Utility CSS |
| `lucide-react` | Icons |

---

## License

MIT
