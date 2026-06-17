# VaP Developer Reference

Complete API reference for the Visualization Agentic Process framework — Python package, CLI, REST API, SSE protocol, and TypeScript types.

---

## Contents

1. [Python API](#python-api)
   - [Module-level functions](#module-level-functions)
   - [Tracer](#tracer)
   - [RunContext](#runcontext)
   - [StepContext](#stepcontext)
   - [Store classes](#store-classes)
   - [Event models](#event-models)
   - [Enums](#enums)
2. [CLI](#cli)
3. [REST API](#rest-api)
4. [SSE Stream Protocol](#sse-stream-protocol)
5. [Remote Ingest](#remote-ingest)
6. [TypeScript Types](#typescript-types)
7. [Changelog](#changelog)

---

## Python API

Install:

```bash
pip install -e .                    # core only
pip install -e ".[anthropic]"       # + Anthropic SDK integration
pip install -e ".[openai]"          # + OpenAI SDK integration
pip install -e ".[langchain]"       # + LangGraph/LangChain integration
pip install -e ".[crewai]"          # + CrewAI integration
pip install -e ".[all]"             # + all four integrations
pip install -e ".[dev]"             # + pytest, httpx, pytest-asyncio, all integrations
```

---

### Module-level functions

These are the primary entry points exported from the `vap` package.

---

#### `vap.configure(db=None)`

Configure the module-level store backend. Call once at startup before any `trace()` / `atrace()` calls.

```python
vap.configure(db: str | None = None) -> None
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `db` | `str \| None` | `None` | Path to a SQLite file. Pass `None` to use the in-memory store. |

**Effect:** replaces both `vap.store.default_store` and `vap.default_store` with the new store instance. Any `Tracer` created without an explicit `store=` argument will pick up the new store dynamically.

```python
import vap

# Persist runs to SQLite
vap.configure(db="runs.db")

# Reset to in-memory (e.g. in tests)
vap.configure()
```

---

#### `vap.trace(label, run_id=None)`

Synchronous context manager. Starts an agent run trace, yields a `RunContext`, and closes the run on exit.

```python
vap.trace(label: str, run_id: str | None = None) -> ContextManager[RunContext]
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `label` | `str` | required | Human-readable name shown in the UI sidebar. |
| `run_id` | `str \| None` | `None` | Custom run ID (12-char hex). Auto-generated if omitted. |

```python
with vap.trace("My Agent") as run:
    print(run.run_id)  # e.g. "a3f9c2e81b47"
    with run.step("fetch", kind="tool") as step:
        ...
```

Exceptions raised inside the block are recorded as an error on the root agent node and re-raised unchanged.

---

#### `vap.atrace(label, run_id=None)`

Async version of `trace`. Use inside `async def` functions with `async with`.

```python
vap.atrace(label: str, run_id: str | None = None) -> AsyncContextManager[RunContext]
```

Parameters are identical to `trace`.

```python
async with vap.atrace("Async Agent") as run:
    async with run.astep("plan", kind="step") as step:
        step.set_input({"goal": "research"})
        await asyncio.sleep(0.1)
        step.set_output({"urls": 3})
```

---

#### `vap.get_current_step()`

Returns the `StepContext` that is currently active in this thread / async task, or `None` if no trace is running.

```python
vap.get_current_step() -> StepContext | None
```

Useful for integrations that need to attach to the current trace context from a place where `run` is not in scope.

```python
def my_library_call():
    step = vap.get_current_step()
    if step:
        step.set_meta(library_version="1.2.3")
```

---

#### `vap.patch_openai(client)`

Instrument an OpenAI client so every `chat.completions.create` call is automatically traced as an `llm` node under the currently active VaP step.

```python
vap.patch_openai(client: Any) -> None
```

| Parameter | Type | Description |
|---|---|---|
| `client` | `openai.OpenAI \| openai.AsyncOpenAI` | The client instance to patch. |

Auto-detects sync vs. async clients and applies the correct wrapper.

```python
import openai, vap

# Sync
client = openai.OpenAI()
vap.patch_openai(client)

# Async
async_client = openai.AsyncOpenAI()
vap.patch_openai(async_client)
```

**What gets traced per `chat.completions.create` call:**

Input (`data` on the `llm_call` event):
- `model` — string
- `messages` — list of message dicts
- `max_tokens` — int or `None`
- `tools` — list of function names

Output (`data` on the `llm_response` event):
- `text` — `choices[0].message.content`
- `finish_reason` — `"stop"`, `"length"`, `"tool_calls"`, etc.
- `usage` — `{"input_tokens": int, "output_tokens": int}`
- `cost_usd` — estimated USD cost (omitted for unknown models)

Requires: `pip install "vap[openai]"`

---

#### `vap.patch_anthropic(client)`

Instrument an Anthropic client so every `messages.create` call is automatically traced as an `llm` node under the currently active VaP step.

```python
vap.patch_anthropic(client: Any) -> None
```

| Parameter | Type | Description |
|---|---|---|
| `client` | `anthropic.Anthropic \| anthropic.AsyncAnthropic` | The client instance to patch. |

Auto-detects sync vs. async clients and applies the correct wrapper.

```python
import anthropic, vap

# Sync
client = anthropic.Anthropic()
vap.patch_anthropic(client)

# Async
async_client = anthropic.AsyncAnthropic()
vap.patch_anthropic(async_client)
```

**What gets traced per `messages.create` call:**

Input (`data` on the `llm_call` event):
- `model` — string
- `messages` — list of message dicts
- `system` — system prompt string or `None`
- `max_tokens` — int or `None`
- `tools` — list of tool names

Output (`data` on the `llm_response` event):
- `text` — joined text content blocks
- `stop_reason` — `"end_turn"`, `"max_tokens"`, `"tool_use"`, etc.
- `usage` — `{"input_tokens": int, "output_tokens": int}`
- `cost_usd` — estimated USD cost (omitted for unknown models)

If called outside an active VaP trace context, the original `messages.create` is invoked directly with no overhead.

---

#### `vap.calculate_cost(model, input_tokens, output_tokens)`

Estimate the USD cost for a single LLM API call.

```python
vap.calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None
```

| Parameter | Type | Description |
|---|---|---|
| `model` | `str` | Model identifier as returned by the API (e.g. `"gpt-4o"`, `"claude-3-haiku-20240307"`). |
| `input_tokens` | `int` | Prompt / input token count. |
| `output_tokens` | `int` | Completion / output token count. |

**Returns:** Cost in USD as a `float` rounded to 8 decimal places, or `None` if the model is not in the pricing table.

Matching is attempted in order: exact name → pricing-table key is a prefix of `model` → `model` is a prefix of a pricing-table key. This makes versioned variants (e.g. `"gpt-4o-2025-03-15"`) resolve to the base model automatically.

```python
import vap

cost = vap.calculate_cost("gpt-4o", input_tokens=1000, output_tokens=500)
# -> 0.0075

cost = vap.calculate_cost("some-private-model", 100, 50)
# -> None
```

Available via `from vap.cost import calculate_cost` or directly as `vap.calculate_cost`.

---

#### `vap.format_cost(cost_usd)`

Format a USD cost value for human display.

```python
vap.format_cost(cost_usd: float) -> str
```

| Cost range | Output format | Example |
|---|---|---|
| `< $0.0001` | `"<$0.0001"` | tiny micro-calls |
| `< $0.01` | `"$0.000123"` | 6 decimal places |
| `≥ $0.01` | `"$0.0123"` | 4 decimal places |

```python
vap.format_cost(0.0075)    # -> "$0.007500"
vap.format_cost(0.000001)  # -> "<$0.0001"
vap.format_cost(0.05)      # -> "$0.0500"
```

---

#### `vap.compute_metrics(graphs)`

Aggregate a list of `RunGraph` snapshots into a single cross-run analytics object. This is the pure function behind the `GET /metrics` endpoint and the UI analytics dashboard — it reads only the node data every integration already produces, so no extra instrumentation is required.

```python
vap.compute_metrics(graphs: list[RunGraph]) -> Metrics
```

| Parameter | Type | Description |
|---|---|---|
| `graphs` | `list[RunGraph]` | Run-graph snapshots, e.g. `[store.get_graph(s.run_id) for s in store.list_runs()]`. |

**Returns:** a `Metrics` pydantic model:

| Field | Type | Description |
|---|---|---|
| `run_count` | `int` | Number of runs in the input. |
| `success_count` / `error_count` / `running_count` | `int` | Run counts by terminal status. |
| `success_rate` | `float \| None` | `success / (success + error)`, over **completed** runs only; `None` when none have finished. |
| `total_cost_usd` | `float` | Sum of every LLM node's `cost_usd`. |
| `avg_cost_usd` | `float \| None` | Mean cost per run that contributed any cost; `None` when no run did. |
| `total_duration_ms` / `avg_duration_ms` | `float` / `float \| None` | Wall-clock totals; the average is over completed runs with a measurable duration. |
| `total_nodes` | `int` | Node count across all graphs. |
| `total_llm_calls` | `int` | Number of `llm` nodes. |
| `total_tokens` | `TokenTotals` | `{input, output}` token sums. |
| `by_model` | `list[ModelStat]` | `{model, calls, cost_usd, input_tokens, output_tokens}` per model, sorted by cost then calls. |
| `by_kind` | `KindCounts` | `{agent, step, tool, llm}` node counts. |
| `cost_over_time` | `list[DailyCost]` | `{date, cost_usd, run_count}` per UTC day, chronological. |

The model name for each LLM node is taken from `node.data["input"]["model"]`, falling back to the `llm/` label prefix.

```python
import vap
from vap.backends.sqlite import SqliteStore

store = SqliteStore("vap.db")
graphs = [g for g in (store.get_graph(s.run_id) for s in store.list_runs()) if g]
metrics = vap.compute_metrics(graphs)

print(metrics.total_cost_usd, metrics.success_rate)
for m in metrics.by_model:
    print(m.model, m.calls, m.cost_usd)
```

Available as `vap.compute_metrics` / `vap.Metrics`, or `from vap.metrics import compute_metrics`.

---

#### `vap.Budget` / `vap.check_budget` / `vap.enable_budget_alerts`

Cost & latency guardrails. Import from `vap` or `vap.budgets`.

```python
class Budget(BaseModel):
    max_cost_usd: float | None = None
    max_duration_ms: float | None = None
    max_total_tokens: int | None = None
```

**`check_budget(graph: RunGraph, budget: Budget) -> BudgetReport`** — compute a run's cost, duration,
and token totals and compare against the limits. Returns a `BudgetReport`:

| Field | Description |
|---|---|
| `run_id` | the run |
| `status` | `"ok"` or `"exceeded"` |
| `cost_usd` / `duration_ms` / `total_tokens` | the measured values |
| `violations` | list of `{metric, limit, actual, pct_over}` — one per breached limit |

A limit left as `None` is ignored; a missing duration (a still-running run) skips the duration check.

**`enable_budget_alerts(budget, *, store=None, on_alert=None) -> BudgetAlertHandle`** — wraps the
store so every completed run (`agent_end`) is checked; on a violation it calls `on_alert(report)`
(default: logs a warning on the `vap.budgets` logger). `handle.disable()` restores the store.

```python
import vap
from vap.budgets import Budget, enable_budget_alerts

vap.configure(db="vap.db")
handle = enable_budget_alerts(
    Budget(max_cost_usd=0.05, max_duration_ms=5000),
    on_alert=lambda r: print("OVER BUDGET", r.run_id, r.violations),
)
```

---

#### `vap.eval_run` and checks

Run pass/fail assertions against a run — regression testing for agents. Import from `vap` or
`vap.evals`.

**`eval_run(run_or_graph, checks: list[Check]) -> EvalResult`** — accepts a `RunGraph` or a
`RunContext` (from `vap.trace()`). Returns an `EvalResult`:

| Field | Description |
|---|---|
| `run_id` | the run |
| `passed` | `True` only if **every** check passed |
| `score` | mean of the checks' 0–1 scores |
| `checks` | list of `{name, passed, score, detail}` |

`EvalResult.summary()` returns a printable multi-line report.

**Built-in checks** (each returns a `Check`):

| Check | Passes when |
|---|---|
| `max_cost(usd)` | run cost ≤ `usd` |
| `max_latency(seconds)` | run duration ≤ `seconds` |
| `max_tokens(n)` | total tokens ≤ `n` |
| `no_errors()` | no node has `error` status |
| `output_contains(text, node_label=None, case_sensitive=False)` | `text` appears in a node's output |
| `custom(name, fn)` | `fn(graph)` is truthy (may return `bool`, `(bool, detail)`, or `(bool, detail, score)`) |
| `judge(name, fn)` | `fn(graph)` returns `(passed, detail, score)` — an LLM-as-judge or any scorer you supply |

```python
import vap
from vap.evals import eval_run, max_cost, no_errors, output_contains

result = eval_run(run, [max_cost(0.02), no_errors(), output_contains("ticket")])
assert result.passed, result.summary()
```

**`run_checks(run_or_graph, specs: list[dict]) -> EvalResult`** — build checks from JSON-friendly
specs (`{"type": "max_cost", "value": 0.02}`, `{"type": "output_contains", "value": "ticket"}`,
`{"type": "no_errors"}`, …). Powers `POST /runs/{id}/eval`. Unknown types raise `ValueError`.

---

#### `vap.create_app(store=None)`

Create a new FastAPI application instance.

```python
vap.create_app(store: RunStore | None = None) -> FastAPI
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `store` | `RunStore \| None` | `None` | Store backend to use. Defaults to `vap.store.default_store`. |

Returns a `FastAPI` instance. Use with any ASGI server:

```python
import uvicorn, vap
from vap.backends.sqlite import SqliteStore

store = SqliteStore("runs.db")
app = vap.create_app(store=store)
uvicorn.run(app, host="0.0.0.0", port=8001)
```

The app wires `store.set_loop()` in its `lifespan` startup handler and calls `store.close()` (if present) on shutdown.

---

### Tracer

`vap.Tracer` is the class underlying the module-level `trace` / `atrace` functions. Use it when you need an isolated tracer with its own store (e.g. in tests).

```python
class vap.Tracer(store: RunStore | None = None)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `store` | `RunStore \| None` | `None` | Explicit store. If `None`, reads `vap.store.default_store` dynamically at call time. |

#### Methods

| Method | Returns | Description |
|---|---|---|
| `trace(label, run_id=None)` | `ContextManager[RunContext]` | Synchronous run trace. |
| `atrace(label, run_id=None)` | `AsyncContextManager[RunContext]` | Asynchronous run trace. |
| `get_current_step()` | `StepContext \| None` | Active step in current context. |

```python
from vap import Tracer, MemoryStore

store = MemoryStore()
tracer = Tracer(store=store)

with tracer.trace("isolated") as run:
    with run.step("task", kind="tool") as step:
        step.set_input({"x": 1})
        step.set_output({"y": 2})

summaries = store.list_runs()
```

---

### RunContext

Yielded by `trace()` / `atrace()`. Represents a single agent run.

```python
class RunContext:
    run_id: str     # 12-char hex, unique per run
    label: str      # display name
```

#### `run.step(label, kind="step")`

Open a synchronous child step.

```python
run.step(label: str, kind: str = "step") -> ContextManager[StepContext]
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `label` | `str` | required | Node label shown in the graph. |
| `kind` | `str` | `"step"` | Node kind — `"step"`, `"tool"`, `"llm"`, or `"agent"`. |

#### `run.astep(label, kind="step")`

Open an asynchronous child step.

```python
run.astep(label: str, kind: str = "step") -> AsyncContextManager[StepContext]
```

Parameters are identical to `step`.

**Example — concurrent async tool calls:**

```python
async def fetch(run, url):
    async with run.astep(f"fetch:{url}", kind="tool") as step:
        step.set_input({"url": url})
        data = await http_get(url)
        step.set_output({"bytes": len(data)})
        return data

async with vap.atrace("Research") as run:
    results = await asyncio.gather(
        fetch(run, "https://example.com/a"),
        fetch(run, "https://example.com/b"),
    )
```

ContextVar propagation (PEP 567) ensures each concurrent task sees its own parent automatically — no manual parent ID passing required.

---

### StepContext

Yielded by `run.step()` / `run.astep()`. Represents one node in the graph.

```python
class StepContext:
    run_id: str
    node_id: str
    node_kind: NodeKind
    label: str
    parent_id: str | None
```

#### `step.set_input(data)`

Record the inputs for this node. Stored in the `data` field of the close event.

```python
step.set_input(data: dict[str, Any]) -> None
```

#### `step.set_output(data)`

Record the outputs for this node.

```python
step.set_output(data: dict[str, Any]) -> None
```

#### `step.set_meta(**kwargs)`

Merge arbitrary metadata into the event data dict. Emitted on every subsequent event from this context.

```python
step.set_meta(**kwargs: Any) -> None
```

```python
with run.step("process", kind="tool") as step:
    step.set_input({"items": 100})
    step.set_meta(worker_id="w-3", queue="fast")
    result = process()
    step.set_output({"processed": len(result)})
```

---

### Store classes

#### `RunStore` (ABC)

Abstract base class for all store backends. Import from `vap.store`.

```python
from vap.store import RunStore
```

| Method | Signature | Description |
|---|---|---|
| `set_loop` | `(loop: asyncio.AbstractEventLoop) -> None` | Inject the asyncio loop. Default no-op. |
| `add_event` | `(event: VapEvent) -> None` | Persist and fan-out to subscribers. |
| `get_events` | `(run_id: str) -> list[VapEvent]` | All events in insertion order. |
| `get_graph` | `(run_id: str) -> RunGraph \| None` | Deep-copy graph snapshot. |
| `get_run` | `(run_id: str) -> RunSummary \| None` | Single run summary. |
| `list_runs` | `() -> list[RunSummary]` | All runs, newest first. |
| `delete_run` | `(run_id: str) -> None` | Remove one run and its events. |
| `clear` | `() -> None` | Remove all runs. |
| `subscribe` | `(run_id: str) -> asyncio.Queue` | Queue for live SSE events. |
| `unsubscribe` | `(run_id: str, q: asyncio.Queue) -> None` | Remove queue from subscriber list. |

---

#### `MemoryStore`

Default in-memory implementation. Thread-safe. Runs are lost when the process exits.

```python
from vap.store import MemoryStore

store = MemoryStore()
```

No constructor arguments.

---

#### `SqliteStore`

Persistent SQLite-backed store. Import from `vap.backends.sqlite` or `vap.SqliteStore`.

```python
from vap.backends.sqlite import SqliteStore

store = SqliteStore(db_path: str | Path)
```

| Parameter | Type | Description |
|---|---|---|
| `db_path` | `str \| Path` | Path to the SQLite file. Created automatically if it doesn't exist. |

Additional method not on the ABC:

| Method | Description |
|---|---|
| `close()` | Close the SQLite connection. Called automatically by the server on shutdown. |

**SQLite schema:**

```sql
CREATE TABLE events (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    type        TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    node_kind   TEXT NOT NULL,
    node_label  TEXT NOT NULL,
    parent_id   TEXT,
    data_json   TEXT NOT NULL DEFAULT '{}',
    schema_ver  INTEGER NOT NULL DEFAULT 1
);
-- Indexes on run_id and timestamp
```

---

### Event models

All models are Pydantic `BaseModel` subclasses. Import from `vap.events`.

---

#### `VapEvent`

The atomic unit of tracing. Every action emits one or two events (open + close).

| Field | Type | Description |
|---|---|---|
| `id` | `str` | 12-char hex, globally unique. |
| `run_id` | `str` | Groups all events belonging to one run. |
| `timestamp` | `float` | Unix epoch seconds (float). |
| `type` | `EventType` | Event type string — see [EventType](#eventtype). |
| `node_id` | `str` | Graph node this event belongs to. |
| `node_kind` | `NodeKind` | `agent` / `step` / `tool` / `llm`. |
| `node_label` | `str` | Human-readable node name. |
| `parent_id` | `str \| None` | Parent node ID; `None` for the root agent node. |
| `data` | `dict[str, Any]` | Arbitrary payload (inputs, outputs, errors, metadata). |
| `schema_version` | `int` | Always `1` in v0.2.0. Bumped on breaking schema changes. |

---

#### `GraphNode`

A node in the run graph, built incrementally from events.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Same as `VapEvent.node_id`. |
| `kind` | `NodeKind` | Node kind. |
| `label` | `str` | Display label. |
| `status` | `NodeStatus` | `pending` / `running` / `success` / `error`. |
| `parent_id` | `str \| None` | Parent node ID. |
| `started_at` | `float \| None` | Timestamp of the open event. |
| `ended_at` | `float \| None` | Timestamp of the close event. `None` if still running. |
| `data` | `dict[str, Any]` | Merged data from all events for this node. |

---

#### `GraphEdge`

A directed edge in the run graph.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | `"{source}→{target}"` |
| `source` | `str` | Parent node ID. |
| `target` | `str` | Child node ID. |
| `kind` | `str` | Always `"execution"` in v0.2.0. |

---

#### `RunSummary`

Lightweight summary of a run — used in the sidebar list.

| Field | Type | Description |
|---|---|---|
| `run_id` | `str` | Unique run identifier. |
| `label` | `str` | Display name. |
| `status` | `NodeStatus` | Current run status. |
| `started_at` | `float` | Unix epoch seconds. |
| `ended_at` | `float \| None` | `None` if still running. |
| `node_count` | `int` | Total graph nodes. |
| `event_count` | `int` | Total raw events. |
| `total_cost_usd` | `float \| None` | Sum of `cost_usd` from all LLM nodes. `None` if no LLM nodes have a known cost. |

---

#### `RunGraph`

Full graph snapshot for a run.

| Field | Type | Description |
|---|---|---|
| `run_id` | `str` | Unique run identifier. |
| `label` | `str` | Display name. |
| `status` | `NodeStatus` | Current run status. |
| `nodes` | `list[GraphNode]` | All graph nodes. |
| `edges` | `list[GraphEdge]` | All graph edges. |
| `started_at` | `float` | Unix epoch seconds. |
| `ended_at` | `float \| None` | `None` if still running. |

---

### Enums

All enums extend `str, Enum` — their `.value` is the wire string.

#### `EventType`

| Value | Wire string | Emitted by |
|---|---|---|
| `AGENT_START` | `"agent_start"` | `trace()` / `atrace()` enter |
| `AGENT_END` | `"agent_end"` | `trace()` / `atrace()` exit |
| `STEP_START` | `"step_start"` | `step()` / `astep()` enter (kind=step/agent) |
| `STEP_END` | `"step_end"` | `step()` / `astep()` exit (kind=step/agent) |
| `TOOL_CALL` | `"tool_call"` | `step()` enter with kind=tool |
| `TOOL_RESULT` | `"tool_result"` | `step()` exit with kind=tool |
| `LLM_CALL` | `"llm_call"` | `step()` enter with kind=llm; Anthropic patch enter |
| `LLM_RESPONSE` | `"llm_response"` | `step()` exit with kind=llm; Anthropic patch exit |
| `STATE_UPDATE` | `"state_update"` | Freestanding state metadata event |
| `ERROR` | `"error"` | Any unhandled exception inside a step block |

#### `NodeKind`

| Value | Wire string | Description |
|---|---|---|
| `AGENT` | `"agent"` | Root agent node (indigo in UI) |
| `STEP` | `"step"` | Generic processing step (sky blue) |
| `TOOL` | `"tool"` | Tool / function call (emerald) |
| `LLM` | `"llm"` | LLM API call (purple) |

#### `NodeStatus`

| Value | Wire string | Description |
|---|---|---|
| `PENDING` | `"pending"` | Created but open event not yet received |
| `RUNNING` | `"running"` | Open event received, no close yet |
| `SUCCESS` | `"success"` | Close event received without error |
| `ERROR` | `"error"` | Error event received |

---

---

### `VapCallbackHandler`

LangChain/LangGraph callback handler. Import from `vap.integrations.langchain`.

```python
from vap.integrations.langchain import VapCallbackHandler

VapCallbackHandler(run: RunContext)
```

| Parameter | Type | Description |
|---|---|---|
| `run` | `RunContext` | The active run context from `vap.trace()` or `vap.atrace()`. |

Raises `ImportError` at instantiation time if `langchain-core` is not installed.

**Usage:**

```python
from vap.integrations.langchain import VapCallbackHandler

with vap.trace("LangGraph Agent") as run:
    handler = VapCallbackHandler(run)
    result = graph.invoke(inputs, config={"callbacks": [handler]})
```

**Callbacks handled:**

| LangChain callback | VaP node kind | Open event | Close event |
|---|---|---|---|
| `on_chain_start` / `on_chain_end` | `step` | `step_start` | `step_end` |
| `on_tool_start` / `on_tool_end` | `tool` | `tool_call` | `tool_result` |
| `on_chat_model_start` / `on_llm_start` | `llm` | `llm_call` | — |
| `on_llm_end` | `llm` | — | `llm_response` |
| `on_chain_error` / `on_tool_error` / `on_llm_error` | any | — | `error` |

**Parent tracking:**

LangChain passes `run_id` (UUID) and `parent_run_id` (UUID) into each callback. `VapCallbackHandler` maps these to VaP `StepContext` objects so the graph nests correctly. Top-level chains with no `parent_run_id` are parented to the `RunContext` root node.

**Tool input parsing:**

`on_tool_start` receives `input_str` as a string. The handler attempts to parse it as JSON; if that fails it stores `{"input": input_str}`.

Requires: `pip install "vap[langchain]"`

---

### `VapCrewAIListener`

CrewAI event bus listener. Import from `vap.integrations.crewai_listener`.

```python
from vap.integrations.crewai_listener import VapCrewAIListener

VapCrewAIListener(run: RunContext | None = None)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `run` | `RunContext \| None` | `None` | Optional existing run context (manual mode). When `None`, a new VaP run is created automatically for each `crew.kickoff()` call (auto mode). |

Raises `ImportError` at instantiation time if `crewai` is not installed.

**Auto mode** — instantiate once at module level; every subsequent `crew.kickoff()` creates its own run:

```python
import vap
from vap.integrations.crewai_listener import VapCrewAIListener

vap.configure(db="vap.db")
VapCrewAIListener()           # register before any kickoff()

result = crew.kickoff(inputs={"topic": "AI"})
```

**Manual mode** — attach to an existing `RunContext` so the crew appears as a sub-section:

```python
with vap.trace("Full Pipeline") as run:
    VapCrewAIListener(run=run)
    result = crew.kickoff(inputs={...})
```

**Events captured and VaP node mapping:**

| CrewAI event | VaP node kind | Parent |
|---|---|---|
| `CrewKickoffStartedEvent` | `agent` (auto) or `step` (manual) | none / run root |
| `TaskStartedEvent` | `step` (`task/…`) | crew root |
| `AgentExecutionStartedEvent` | `step` (`agent/…`) | task node |
| `ToolUsageStartedEvent` | `tool` | agent execution node |
| `LLMCallStartedEvent` | `llm` (`llm/model-name`) | agent execution node |

**Cost tracking:**

`LLMCallCompletedEvent.usage` is a LiteLLM-style dict (`prompt_tokens`, `completion_tokens`).
The listener reads it, normalises the keys, and calls `vap.calculate_cost(model, input_tokens,
output_tokens)` automatically. `cost_usd` appears on the node when the model is in the pricing
table.

**`detach()`:**

```python
listener = VapCrewAIListener(run=run)
crew.kickoff(inputs={...})
listener.detach()   # flush any orphaned open nodes (rarely needed)
```

Requires: `pip install "vap[crewai]"`

---

### `VapPydanticAI`

Pydantic AI integration. Import from `vap.integrations.pydantic_ai`.

```python
from vap.integrations.pydantic_ai import VapPydanticAI

VapPydanticAI(run: RunContext | None = None, *, patch: bool = True)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `run` | `RunContext \| None` | `None` | Optional existing run context (manual mode). When `None`, a new VaP run is created for each `agent.run()` / `run_sync()` call (auto mode). |
| `patch` | `bool` | `True` | Patch `Agent` immediately. Set `False` to defer to `.patch()`. |

Raises `ImportError` at instantiation time if `pydantic-ai` is not installed.

It wraps `Agent.run` and `Agent.run_sync` (a re-entrancy guard prevents double-counting when `run_sync` delegates to `run`). After each run completes, the graph is reconstructed from `result.all_messages()`.

**Auto mode** — instantiate once; every subsequent agent run becomes its own VaP run:

```python
import vap
from vap.integrations.pydantic_ai import VapPydanticAI

vap.configure(db="vap.db")
VapPydanticAI()                       # patch before any agent.run()

result = agent.run_sync("What's the weather in Paris?")
```

**Manual mode** — attach to an existing `RunContext` so the agent nests inside a pipeline:

```python
with vap.trace("Trip planner") as run:
    VapPydanticAI(run)
    result = agent.run_sync("Is Lisbon warm?")
```

**Pydantic AI → VaP node mapping:**

| Source | VaP node kind | Parent |
|---|---|---|
| the agent run | `agent` (auto) or `step` (`agent/<name>`, manual) | none / run root |
| each `ModelResponse` | `llm` (`llm/<model_name>`) | agent node |
| each tool call (`ToolCallPart` → `ToolReturnPart`) | `tool` | the model request that called it |

**Cost & tokens:** each `ModelResponse` carries `usage` (input/output tokens) and `model_name`; the listener calls `vap.calculate_cost(model_name, …)` per request and aggregates totals onto the agent node. Node timings come from the messages' timestamps.

**`detach()`** restores the original `Agent` methods:

```python
listener = VapPydanticAI(run)
agent.run_sync("...")
listener.detach()
```

`patch_pydantic_ai(run=None)` is a convenience wrapper equivalent to `VapPydanticAI(run)`.

> **Scope:** the streaming methods (`run_stream` / `run_stream_events`) are not traced yet.

Requires: `pip install "vap[pydantic-ai]"`

---

### `VapLlamaIndex`

LlamaIndex integration. Import from `vap.integrations.llamaindex`. Registers a span handler on
LlamaIndex's instrumentation dispatcher; every instrumented span becomes a VaP node.

```python
from vap.integrations.llamaindex import VapLlamaIndex

VapLlamaIndex(run: RunContext | None = None, *, register: bool = True)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `run` | `RunContext \| None` | `None` | Existing run context (manual mode) — all spans attach under it. When `None` (auto mode), each top-level span starts its own VaP run. |
| `register` | `bool` | `True` | Register on the root dispatcher immediately. Set `False` to defer. |

Raises `ImportError` at instantiation time if `llama-index-core` is not installed.

**Manual mode** — wrap a whole RAG workflow in one run (recommended):

```python
import vap
from llama_index.core import VectorStoreIndex
from vap.integrations.llamaindex import VapLlamaIndex

with vap.trace("RAG query") as run:
    VapLlamaIndex(run)
    index = VectorStoreIndex.from_documents(docs)
    index.as_query_engine().query("…")
```

**Span → VaP node mapping:**

| LlamaIndex | VaP node kind |
|---|---|
| span whose instance class ends with `LLM` (or an LLM method: `chat`/`complete`/`predict`/…) | `llm` |
| span whose instance class ends with `Retriever`, or a `retrieve` call | `tool` |
| span whose instance class contains `Embedding` | `tool` |
| everything else (query engines, synthesizers, splitters, …) | `step` |

The span `id_` (`"<qualname>-<uuid>"`) becomes the node label (`qualname`); `parent_span_id`
becomes the parent node. Node start/end times are captured live, and a dropped span (an error)
marks the node `error`.

**`register()` / `detach()`** add and remove the handler from the dispatcher's `span_handlers`.

> **Scope:** v1 captures the span structure and timings; per-call token/cost enrichment (via the
> event handler) is a planned follow-up.

Requires: `pip install "vap[llamaindex]"`

---

### `VapAutoGen`

AutoGen (AG2) integration. Import from `vap.integrations.autogen`. Wraps `ConversableAgent` so a
multi-agent conversation becomes a VaP graph.

```python
from vap.integrations.autogen import VapAutoGen

VapAutoGen(run: RunContext | None = None, *, patch: bool = True)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `run` | `RunContext \| None` | `None` | Existing run context (manual mode) — conversations attach under it. When `None` (auto mode), each `initiate_chat` starts its own VaP run. |
| `patch` | `bool` | `True` | Patch `ConversableAgent` immediately. |

Raises `ImportError` at instantiation time if `autogen` (ag2) is not installed.

It monkey-patches three `ConversableAgent` methods and keeps a thread-local stack of open nodes so
nesting (tools under the turn that called them, nested chats) is correct:

| Patched method | VaP node kind | Meaning |
|---|---|---|
| `initiate_chat` | `step` `chat/<recipient>` (or `agent` run root in auto mode) | the conversation |
| `generate_reply` | `step` `agent/<name>` | one agent turn |
| `execute_function` | `tool` | a tool/function call |

Agent turns are siblings under the chat node; tool calls nest under the turn that made them. Node
timings are real (captured live). A method that raises marks its node `error`. Patching twice never
stacks wrappers (the pristine original is recovered), and `detach()` restores the originals.

> **Scope:** targets the classic `autogen.ConversableAgent` API (AG2 / `pyautogen`), not the newer
> async `autogen-agentchat` (v0.4+) agents.

Requires: `pip install "vap[autogen]"`

---

### OpenTelemetry export

Mirror VaP runs into OpenTelemetry. Import from `vap.integrations.otel`. One **trace per run**; each
node becomes a span whose parent is the node's parent. Requires `pip install "vap[otel]"`.

#### `enable_otel_export(...)`

```python
enable_otel_export(
    *,
    tracer_provider=None,
    endpoint: str | None = None,
    protocol: str = "grpc",          # "grpc" or "http"
    service_name: str = "vap",
    insecure: bool = True,
    store=None,
) -> OtelExportHandle
```

Wraps a store's `add_event` so that each run is exported when its `agent_end` event is recorded.

| Parameter | Description |
|---|---|
| `tracer_provider` | Use this provider. If `None` and `endpoint` is set, a provider with an OTLP exporter is built; if both are `None`, the **global** `TracerProvider` is used. |
| `endpoint` | OTLP collector, e.g. `"http://localhost:4317"` (gRPC) or `"http://localhost:4318/v1/traces"` (HTTP). |
| `protocol` | `"grpc"` (default) or `"http"` — selects the OTLP exporter (imported lazily). |
| `service_name` | `service.name` resource attribute when a provider is created here. |
| `insecure` | gRPC insecure channel (default `True`). |
| `store` | Store to wrap. Defaults to `vap.store.default_store`. |

Returns an `OtelExportHandle` with `.disable()` (restore the original `add_event`) and `.shutdown()`
(disable + flush the provider). Only runs that complete **after** the call are exported.

```python
import vap
from vap.integrations.otel import enable_otel_export

vap.configure(db="vap.db")
handle = enable_otel_export(endpoint="http://localhost:4317")
# ... run agents ...
handle.shutdown()
```

#### `export_run(graph, *, tracer=None, tracer_provider=None) -> int`

Export a single `RunGraph` on demand; returns the number of spans created (`0` if `graph` is `None`).
Uses the global `TracerProvider` unless a `tracer` or `tracer_provider` is given.

#### `build_spans(graph, tracer) -> int`

Low-level: emit spans for every node in `graph` using an OpenTelemetry `Tracer`, parent-first with
explicit start/end times. Returns the span count.

**Span mapping:**

| VaP | OpenTelemetry |
|---|---|
| run | one trace |
| node (`agent`/`step`/`tool`/`llm`) | span (parent = parent node's span) |
| `started_at` / `ended_at` | span start / end (nanoseconds) |
| `error` status | span `Status(ERROR)` with the error message |
| LLM model / tokens / cost | `gen_ai.request.model`, `gen_ai.usage.{input,output}_tokens`, `vap.cost_usd` |
| kind / status / run id / I-O | `vap.node.kind`, `vap.node.status`, `vap.run_id`, `vap.input`, `vap.output` |

---

## CLI

```
vap serve [OPTIONS]
```

Start the VaP HTTP server.

| Option | Type | Default | Description |
|---|---|---|---|
| `--host` | `str` | `0.0.0.0` | Network interface to bind. Use `127.0.0.1` to restrict to localhost. |
| `--port` | `int` | `8001` | TCP port. |
| `--db` | `PATH` | *(none)* | SQLite database file. If omitted, in-memory store is used. |
| `--static-dir` | `PATH` | *(none)* | Serve the built React UI from this directory. Run `npm run build` inside `ui/` first; the output goes to `ui/dist`. |
| `--reload` | flag | off | Enable Uvicorn auto-reload. Use during development. |
| `--log-level` | `str` | `warning` | Uvicorn log level: `debug`, `info`, `warning`, `error`, `critical`. |

**Examples:**

```bash
# In-memory store (default)
vap serve

# SQLite persistence, custom port, verbose logs
vap serve --db runs.db --port 9000 --log-level info

# Development mode with reload
vap serve --db dev.db --reload --log-level debug
```

When `--db` is supplied the CLI:
1. Creates a `SqliteStore` pointing at the file
2. Sets `vap.store.default_store` to it (so in-process traces land there too)
3. Passes the store to `create_app(store=store)`

---

## REST API

Base URL: `http://localhost:8001` (default)

Interactive docs: `http://localhost:8001/docs`

---

### `GET /runs`

List all runs, newest first.

**Response** `200 OK` — `application/json`

```json
[
  {
    "run_id": "a3f9c2e81b47",
    "label": "Research Agent",
    "status": "success",
    "started_at": 1716720000.123,
    "ended_at": 1716720003.456,
    "node_count": 5,
    "event_count": 10,
    "total_cost_usd": 0.0075,
    "tags": ["prod"]
  }
]
```

---

### `GET /search`

Search runs by free-text query and/or filters. Returns the matching `RunSummary` list (same shape as
`/runs`).

**Query parameters** (all optional; combined with AND):

| Param | Matches |
|---|---|
| `q` | case-insensitive substring across the run label and every node's input / output / error |
| `status` | run status equals this (`success` / `error` / `running` / `pending`) |
| `kind` | at least one node of this kind (`agent` / `step` / `tool` / `llm`) |
| `tool` | at least one `tool` node whose label contains this string |
| `tag` | run is tagged with this exact tag |

```bash
curl "http://localhost:8001/search?q=paris&status=success"
curl "http://localhost:8001/search?tool=search_web"
curl "http://localhost:8001/search?tag=prod"
```

---

### `GET` / `PUT /runs/{run_id}/tags`

Get or replace a run's tags. `PUT` body is `{"tags": ["prod", "v2-prompt"]}`; tags are normalised
(trimmed, de-duplicated, empties dropped) and the normalised list is returned. Tags are persisted in
SQLite when the server runs with `--db`. `404` if the run is unknown.

```bash
curl -X PUT http://localhost:8001/runs/{id}/tags \
  -H "Content-Type: application/json" -d '{"tags": ["prod"]}'
```

---

### `GET /metrics`

Cross-run analytics aggregated over every stored run. Computed by `compute_metrics()` (see the Python API section for the full field reference).

**Response** `200 OK` — `application/json`

```json
{
  "run_count": 7,
  "success_count": 7,
  "error_count": 0,
  "running_count": 0,
  "success_rate": 1.0,
  "total_cost_usd": 0.04526,
  "avg_cost_usd": 0.009052,
  "total_duration_ms": 1113.42,
  "avg_duration_ms": 159.06,
  "total_nodes": 37,
  "total_llm_calls": 5,
  "total_tokens": { "input": 7900, "output": 2590 },
  "by_model": [
    { "model": "claude-3-5-sonnet", "calls": 1, "cost_usd": 0.0231, "input_tokens": 3200, "output_tokens": 900 }
  ],
  "by_kind": { "agent": 7, "step": 11, "tool": 14, "llm": 5 },
  "cost_over_time": [
    { "date": "2026-06-15", "cost_usd": 0.04526, "run_count": 5 }
  ]
}
```

An empty store returns all-zero counts with `success_rate`, `avg_cost_usd`, and `avg_duration_ms` set to `null`, and empty `by_model` / `cost_over_time` arrays.

---

### `GET /runs/{run_id}/budget`

Check a run against a budget supplied as query parameters. All are optional; omitted limits are not enforced.

**Query parameters:** `max_cost_usd`, `max_duration_ms`, `max_total_tokens`.

**Response** `200 OK` — a `BudgetReport`:

```json
{
  "run_id": "a3f9c2e81b47",
  "status": "exceeded",
  "cost_usd": 0.05,
  "duration_ms": 701.2,
  "total_tokens": 1200,
  "violations": [
    { "metric": "cost_usd", "limit": 0.02, "actual": 0.05, "pct_over": 150.0 }
  ]
}
```

**Error** `404 Not Found` — unknown run.

---

### `POST /runs/{run_id}/eval`

Evaluate a run against a list of declarative check specs (see `run_checks`).

**Request body** — a JSON array of check specs:

```json
[
  { "type": "max_cost", "value": 0.02 },
  { "type": "max_latency", "value": 3.0 },
  { "type": "no_errors" },
  { "type": "output_contains", "value": "ticket", "node_label": null, "case_sensitive": false }
]
```

**Response** `200 OK` — an `EvalResult`:

```json
{
  "run_id": "a3f9c2e81b47",
  "passed": false,
  "score": 0.75,
  "checks": [
    { "name": "max_cost<=$0.02", "passed": true, "score": 1.0, "detail": "cost $0.01 (limit $0.02)" },
    { "name": "output_contains('ticket')", "passed": false, "score": 0.0, "detail": "'ticket' not found in any node output" }
  ]
}
```

**Errors** `404` (unknown run), `400` (unknown check `type`).

---

### `GET /runs/{run_id}`

Retrieve a single run summary.

**Path parameter:** `run_id` — the 12-char hex run ID.

**Response** `200 OK` — `RunSummary` JSON

**Error** `404 Not Found` — `{"detail": "Run not found"}`

---

### `GET /runs/compare`

Return the full graphs for two runs in a single request — used by the comparison view.

**Query parameters:**

| Param | Type | Description |
|---|---|---|
| `a` | `str` | Run ID of the first (primary) run. |
| `b` | `str` | Run ID of the second (comparison) run. |

**Response** `200 OK` — `application/json`

```json
{
  "a": { "run_id": "a3f9c2e81b47", "label": "Run A", "nodes": [...], "edges": [...], ... },
  "b": { "run_id": "d7e1b4f02c98", "label": "Run B", "nodes": [...], "edges": [...], ... }
}
```

**Error** `404 Not Found` — `{"detail": "Run not found: {id}"}` (specifies which run was missing)

**Error** `422 Unprocessable Entity` — when `a` or `b` query param is omitted

> **Route ordering note:** `/runs/compare` is registered before `/runs/{run_id}` in FastAPI so the literal path segment `compare` is not treated as a run ID.

---

### `GET /runs/{run_id}/graph`

Retrieve the full graph snapshot for a run (all nodes and edges).

**Path parameter:** `run_id`

**Response** `200 OK` — `RunGraph` JSON

```json
{
  "run_id": "a3f9c2e81b47",
  "label": "Research Agent",
  "status": "success",
  "started_at": 1716720000.123,
  "ended_at": 1716720003.456,
  "nodes": [
    {
      "id": "b5c8d1f2a3e4",
      "kind": "agent",
      "label": "Research Agent",
      "status": "success",
      "parent_id": null,
      "started_at": 1716720000.123,
      "ended_at": 1716720003.456,
      "data": {}
    }
  ],
  "edges": []
}
```

**Error** `404 Not Found`

---

### `GET /runs/{run_id}/export`

Download the full run graph as a JSON file.

**Path parameter:** `run_id`

**Response** `200 OK` — `application/json` with `Content-Disposition: attachment; filename="vap-{run_id}.json"`

The response body is the same schema as `GET /runs/{run_id}/graph` (a `RunGraph` object), pretty-printed with 2-space indentation, suitable for archiving or loading into external tools.

**Error** `404 Not Found` — `{"detail": "Run not found"}`

**Download example (browser):**

```javascript
const resp = await fetch(`/runs/${runId}/export`);
const blob = await resp.blob();
const url  = URL.createObjectURL(blob);
const a    = document.createElement("a");
a.href     = url;
a.download = `vap-${runId}.json`;
a.click();
URL.revokeObjectURL(url);
```

---

### `GET /runs/{run_id}/events`

**SSE stream** — replays all historical events for the run, then streams live events as they arrive.

**Path parameter:** `run_id`

**Response** `200 OK` — `text/event-stream`

See [SSE Stream Protocol](#sse-stream-protocol) for the event format.

---

### `POST /runs/{run_id}/events`

Ingest an event from a remote process or out-of-process tracer.

**Path parameter:** `run_id` — must match `event.run_id` in the request body.

**Request body** — `VapEvent` JSON

```json
{
  "id": "c9e2f4a1b6d7",
  "run_id": "a3f9c2e81b47",
  "timestamp": 1716720001.234,
  "type": "step_start",
  "node_id": "d4f7a2b8c1e5",
  "node_kind": "step",
  "node_label": "fetch_data",
  "parent_id": "b5c8d1f2a3e4",
  "data": {},
  "schema_version": 1
}
```

**Response** `202 Accepted`

```json
{"ok": true}
```

**Error** `400 Bad Request` — `run_id` in path does not match `run_id` in body.

---

### `DELETE /runs/{run_id}`

Delete a single run and all its events.

**Path parameter:** `run_id`

**Response** `204 No Content`

**Error** `404 Not Found`

> For `SqliteStore`, this also deletes the rows from the `events` table permanently.

---

### `DELETE /runs`

Delete all runs from the store.

**Response** `204 No Content`

> Irreversible for `SqliteStore` — all event rows are removed.

---

## SSE Stream Protocol

The `/runs/{run_id}/events` endpoint uses the [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events) protocol.

### Event format

Each SSE message has a named `event:` field matching the `EventType` wire string, and a `data:` field containing the full `VapEvent` JSON:

```
event: step_start
data: {"id":"c9e2f4","run_id":"a3f9c2","timestamp":1716720001.234,"type":"step_start","node_id":"d4f7a2","node_kind":"step","node_label":"fetch_data","parent_id":"b5c8d1","data":{},"schema_version":1}

event: step_end
data: {"id":"e1a8b3","run_id":"a3f9c2","timestamp":1716720002.456,"type":"step_end","node_id":"d4f7a2","node_kind":"step","node_label":"fetch_data","parent_id":"b5c8d1","data":{"input":{"url":"..."},"output":{"rows":42}},"schema_version":1}
```

### Keepalive pings

If no event arrives within 30 seconds, the server sends a ping to keep the connection alive:

```
event: ping
data: {}
```

Clients should ignore `ping` events.

### Consuming the stream

**Browser (JavaScript):**

```javascript
const es = new EventSource(`http://localhost:8001/runs/${runId}/events`);

es.addEventListener("step_start", (e) => {
  const event = JSON.parse(e.data);
  console.log("step started:", event.node_label);
});

es.addEventListener("error", (e) => {
  const event = JSON.parse(e.data);
  console.error("error:", event.data.error);
});

// Clean up
es.close();
```

**Python (httpx):**

```python
import httpx, json

with httpx.stream("GET", f"http://localhost:8001/runs/{run_id}/events") as r:
    for line in r.iter_lines():
        if line.startswith("data:"):
            event = json.loads(line[5:].strip())
            print(event["type"], event["node_label"])
```

**curl:**

```bash
curl -N http://localhost:8001/runs/a3f9c2e81b47/events
```

### Two-phase replay

The stream always begins with a replay of all historical events for the run (in insertion order), then seamlessly continues with live events. This means:

- A client that connects **after** a run completes sees the full history
- A client that connects **during** a run sees history first, then live updates with no gap
- The client code is identical for both cases

---

## Remote Ingest

To trace an agent running in a separate process (or a different language), push `VapEvent` objects to the HTTP endpoint directly.

**Python example:**

```python
import httpx, time, uuid

SERVER = "http://localhost:8001"
run_id = uuid.uuid4().hex[:12]

def uid():
    return uuid.uuid4().hex[:12]

def post(event):
    httpx.post(f"{SERVER}/runs/{run_id}/events", json=event)

# Open the run
root_id = uid()
post({
    "id": uid(), "run_id": run_id,
    "timestamp": time.time(),
    "type": "agent_start",
    "node_id": root_id, "node_kind": "agent",
    "node_label": "Remote Agent", "parent_id": None,
    "data": {"label": "Remote Agent"}, "schema_version": 1,
})

# Open a step
step_id = uid()
post({
    "id": uid(), "run_id": run_id,
    "timestamp": time.time(),
    "type": "step_start",
    "node_id": step_id, "node_kind": "step",
    "node_label": "process", "parent_id": root_id,
    "data": {}, "schema_version": 1,
})

# ... do work ...

# Close the step
post({
    "id": uid(), "run_id": run_id,
    "timestamp": time.time(),
    "type": "step_end",
    "node_id": step_id, "node_kind": "step",
    "node_label": "process", "parent_id": root_id,
    "data": {"input": {"x": 1}, "output": {"y": 2}}, "schema_version": 1,
})

# Close the run
post({
    "id": uid(), "run_id": run_id,
    "timestamp": time.time(),
    "type": "agent_end",
    "node_id": root_id, "node_kind": "agent",
    "node_label": "Remote Agent", "parent_id": None,
    "data": {}, "schema_version": 1,
})
```

The VaP server is language-agnostic — any HTTP client can push events, including agents written in Node.js, Go, or Java.

---

## TypeScript Types

The `ui/src/types/events.ts` module mirrors the Python event models. Import as:

```typescript
import type { VapEvent, RunGraph, RunSummary, GraphNode, GraphEdge, EventType, NodeKind, NodeStatus } from "../types/events";
```

### `EventType`

```typescript
type EventType =
  | "agent_start" | "agent_end"
  | "step_start"  | "step_end"
  | "tool_call"   | "tool_result"
  | "llm_call"    | "llm_response"
  | "state_update"
  | "error";
```

### `NodeKind`

```typescript
type NodeKind = "agent" | "step" | "tool" | "llm";
```

### `NodeStatus`

```typescript
type NodeStatus = "pending" | "running" | "success" | "error";
```

### `VapEvent`

```typescript
interface VapEvent {
  id: string;
  run_id: string;
  timestamp: number;        // Unix epoch seconds
  type: EventType;
  node_id: string;
  node_kind: NodeKind;
  node_label: string;
  parent_id: string | null;
  data: Record<string, unknown>;
}
```

> Note: `schema_version` is not currently included in the TypeScript type since it is not consumed by the UI. Add it if you consume VapEvent in client-side storage.

### `GraphNode`

```typescript
interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  status: NodeStatus;
  parent_id: string | null;
  started_at: number | null;
  ended_at: number | null;
  data: Record<string, unknown>;
}
```

### `GraphEdge`

```typescript
interface GraphEdge {
  id: string;      // "{source}→{target}"
  source: string;
  target: string;
  kind: string;    // "execution"
}
```

### `RunSummary`

```typescript
interface RunSummary {
  run_id: string;
  label: string;
  status: NodeStatus;
  started_at: number;
  ended_at: number | null;
  node_count: number;
  event_count: number;
  total_cost_usd: number | null;  // null when no LLM nodes have a known cost
}
```

### `RunGraph`

```typescript
interface RunGraph {
  run_id: string;
  label: string;
  status: NodeStatus;
  nodes: GraphNode[];
  edges: GraphEdge[];
  started_at: number;
  ended_at: number | null;
}
```

---

## Changelog

### v0.15.0

- **Trace replay / time-travel (UI)** — a scrubber (`ReplayBar.tsx`) replays a run event-by-event with play/pause and step controls; the graph fills in node by node
- **`buildGraphAt(events, n)`** (`ui/src/lib/replay.ts`) — a pure client-side reducer that rebuilds `{nodes, edges}` as of event *n*, mirroring the store's event→graph logic; `App` feeds the partial graph to `AgentGraph` during replay
- **Replay toggle** in the run header; replay state resets when the selected run changes
- UI-only — no Python API changes; **256 Python tests** still passing
- **Package version** bumped to `0.15.0`

### v0.14.0

- **Run search** — `vap/search.py` `run_matches(graph, query=, status=, kind=, tool=)`; `GET /search` composes it with tag filtering and returns matching `RunSummary` list
- **Tags** — persistent per-run tags: `RunStore.get_tags` / `set_tags` (in-memory default; `SqliteStore` persists to a `tags` table), `RunSummary.tags`, and `GET` / `PUT /runs/{id}/tags`
- **UI** — content search box, clickable tag chips on runs (filter by tag), and an inline tag editor (`TagEditor.tsx`) in the run header
- **Test suite** — `tests/test_search.py` with 18 tests (predicate, in-memory + SQLite tag persistence, endpoints); **256 passing** total
- **Package version** bumped to `0.14.0`

### v0.13.0

- **Agent evals & scoring** — `vap/evals.py`: `eval_run(run_or_graph, checks) -> EvalResult` (per-check `passed`/`score`/`detail` + overall `passed`/`score`); built-in `max_cost`, `max_latency`, `max_tokens`, `no_errors`, `output_contains`, plus `custom` and `judge` hooks
- **Declarative checks** — `run_checks(graph, specs)` builds checks from JSON specs; powers `POST /runs/{id}/eval`
- **Workflow** — accepts a `RunContext` or `RunGraph`; `assert eval_run(...).passed` for pytest/CI; a throwing check counts as a failure
- **Exports** — `vap.eval_run`, `vap.run_checks`, `vap.EvalResult`, `vap.Check`, and the check builders; `examples/evals_demo.py`
- **Test suite** — `tests/test_evals.py` with 20 tests; **238 passing** total
- **Package version** bumped to `0.13.0`

### v0.12.0

- **Cost & latency budgets** — `vap/budgets.py`: `Budget` (max cost / duration / tokens), `check_budget(graph, budget) -> BudgetReport` with per-metric `violations`
- **Alerting** — `enable_budget_alerts(budget, on_alert=…)` wraps the store and fires a callback (default: logs a warning) when a completed run exceeds the budget; `BudgetAlertHandle.disable()` restores the store
- **`GET /runs/{id}/budget`** — check any run against a budget via query params
- **Exports** — `vap.Budget`, `vap.BudgetReport`, `vap.check_budget`, `vap.enable_budget_alerts`; `examples/budgets_demo.py` (no API key)
- **Test suite** — `tests/test_budgets.py` with 13 tests; **218 passing** total
- **Package version** bumped to `0.12.0`

### v0.11.0

- **AutoGen integration** — `vap/integrations/autogen.py`: `VapAutoGen` monkey-patches `ConversableAgent.initiate_chat` / `generate_reply` / `execute_function`, reproducing a multi-agent conversation as a chat root, an agent-turn node per reply, and tool nodes per function call
- **Correct nesting** — a thread-local node stack parents tool calls under the turn that made them and supports nested chats; agent turns are siblings under the chat; timings are live
- **Two usage modes** — manual (under a provided run) and auto (each `initiate_chat` = its own run); dropped/raised calls mark nodes `error`; double-patching never stacks wrappers; `detach()` restores originals
- **`pip install "vap[autogen]"`** — new optional extra (`ag2`, classic `ConversableAgent` API) + `examples/autogen_demo.py` (offline `register_reply` agents, no API key)
- **Test suite** — `tests/test_autogen.py` with 8 tests; **191 passing** total
- **Package version** bumped to `0.11.0`

### v0.10.0

- **LlamaIndex integration** — `vap/integrations/llamaindex.py`: `VapLlamaIndex` registers a span handler on LlamaIndex's instrumentation dispatcher and reproduces every span (query engines, retrievers, embeddings, synthesizers, LLM calls) as a VaP node, with `parent_span_id` → node hierarchy and live timings
- **Kind classification** — retrievers/embeddings → `tool`, LLM spans → `llm`, the rest → `step`; dropped spans mark the node `error`
- **Two usage modes** — manual (all spans under a provided run) and auto (each top-level span = its own run); `register()` / `detach()` manage the dispatcher hook
- **`pip install "vap[llamaindex]"`** — new optional extra (`llama-index-core`) + `examples/llamaindex_demo.py` (MockLLM/MockEmbedding, no API key)
- **Test suite** — `tests/test_llamaindex.py` with 8 tests; **183 passing** total
- **Package version** bumped to `0.10.0`

### v0.9.0

- **OpenTelemetry export** — `vap/integrations/otel.py`: `enable_otel_export(...)` wraps a store to emit each completed run as an OTLP trace (one trace per run; node hierarchy → span parent/child) via a BatchSpanProcessor; `export_run()` / `build_spans()` for one-shot export
- **GenAI semantics** — spans carry `gen_ai.request.model`, `gen_ai.usage.{input,output}_tokens`, `vap.cost_usd`, `vap.node.*`, real node start/end times, and ERROR status
- **Flexible wiring** — bring your own `TracerProvider`, pass an OTLP `endpoint` (gRPC/HTTP), or use the global provider; OTLP exporter imported lazily; `OtelExportHandle.disable()` / `.shutdown()`
- **`pip install "vap[otel]"`** — new optional extra (`opentelemetry-sdk`, `opentelemetry-exporter-otlp`) + `examples/otel_demo.py` (ConsoleSpanExporter, no network)
- **Test suite** — `tests/test_otel.py` with 11 tests (in-memory exporter); **175 passing** total
- **Package version** bumped to `0.9.0`

### v0.8.0

- **Pydantic AI integration** — `VapPydanticAI` wraps `Agent.run` / `run_sync` and reconstructs the agent, each model request (tokens + cost), and each tool call as nested VaP nodes from `result.all_messages()`; tool nodes are parented under the model request that called them
- **Two usage modes** — auto mode (new VaP run per `agent.run()`) and manual mode (agent nests inside an existing `RunContext`); `.detach()` restores the original methods
- **`patch_pydantic_ai(run=None)`** convenience wrapper; re-entrancy guard prevents double-counting when `run_sync` delegates to `run`
- **`vap/integrations/pydantic_ai.py`** + `examples/pydantic_ai_demo.py` (runs with no API key via `TestModel`)
- **`pip install "vap[pydantic-ai]"`** — new optional extra (`pydantic-ai-slim>=1.0.0`)
- **Test suite** — `tests/test_pydantic_ai.py` with 13 tests (manual/auto/async modes, tool parenting, cost wiring, error path, detach, double-patch guard); **164 passing** total
- **Package version** bumped to `0.8.0` (was stale at `0.6.0`)

### v0.7.0

- **Analytics dashboard** — cross-run overview in the UI: run/success counts, total & average cost, average duration, LLM-call and token totals, a per-model breakdown table, a cost-over-time bar chart, and a nodes-by-kind breakdown. Toggled from the sidebar header; auto-refreshes every 5 s
- **`GET /metrics`** — aggregates every stored run into one `Metrics` snapshot
- **`vap.compute_metrics(graphs)`** — pure aggregation function over `RunGraph` snapshots; exported as `vap.compute_metrics` / `vap.Metrics`
- **`vap/metrics.py`** — `Metrics`, `ModelStat`, `TokenTotals`, `KindCounts`, `DailyCost` pydantic models + `compute_metrics()`
- **`Dashboard.tsx`** + `view` state in `runStore` (`"runs" | "dashboard"`); selecting a run returns to the graph view
- **Test suite** — `tests/test_metrics.py` with 14 tests (empty input, status/duration/cost aggregation, model breakdown + label fallback, daily bucketing, and the endpoint); **151 passing** total
- **Fix: test isolation** — an `autouse` fixture in `tests/conftest.py` resets the `_current_step` ContextVar between tests, so a `RunContext._start()` without a matching `_end()` (as in the CrewAI listener tests) no longer leaks into later test files

### v0.6.0

- **CrewAI integration** — `VapCrewAIListener` hooks into CrewAI's native `BaseEventListener` event bus; traces Crew runs, Tasks, Agent executions, Tool calls, and LLM round-trips automatically
- **Two usage modes** — auto mode (new VaP run per `kickoff()`) and manual mode (tasks as children of an existing `RunContext`)
- **LLM cost on CrewAI nodes** — `cost_usd` automatically attached to every `llm/` node when the model is in the pricing table (LiteLLM usage dict parsed transparently)
- **`pip install "vap[crewai]"`** — new optional extra; `crewai>=1.0.0` dependency
- **`vap/integrations/crewai_listener.py`** — `VapCrewAIListener`, `detach()` helper for manual cleanup
- **`examples/crewai_demo.py`** — two-demo example (sequential crew + pipeline embedding); no custom tools required
- **Test suite** — `tests/test_crewai_listener.py` with 19 tests across 7 classes; skipped when `crewai` is not installed
- **Fix: deadlock in `_on_agent_exec_start`** — `_get_crew_root()` was called while holding `self._lock`; since `_get_crew_root()` also acquires the same non-reentrant lock, accumulated listener instances from multiple test runs deadlocked the `ThreadPoolExecutor` thread pool. Fixed by calling `_get_crew_root()` outside the lock block.
- **Fix: agent node parent lookup** — `task_name` was read only from `event.task_name` (always `None` when callers pass `task=<Task>`). Added the same name-derivation chain used by `_on_task_start` (`event.task_name` → `task.name` → first-6-words of `task.description`) so agent nodes are correctly parented under the matching task node.

### v0.5.0

- **Run comparison** — `GET /runs/compare?a={id}&b={id}` returns both `RunGraph` objects; `RunComparison` React component shows side-by-side ReactFlow graphs with a stats header (duration Δ, cost Δ, node diff)
- **Export** — `GET /runs/{id}/export` serves the `RunGraph` as a JSON attachment; UI `ExportMenu` adds "Download JSON" and "Download PNG" (via dynamically-imported `html2canvas`)
- **Compare mode in sidebar** — hover any run to reveal `⊕` compare button; active comparison run gets amber highlight; a banner confirms comparison mode is active
- **`runStore`** — new `compareRunId` state + `setCompareRun` action; `selectRun` clears `compareRunId` automatically
- **Test suite** — 8 new server tests (export + compare); **118 passing** total

### v0.4.0

- **Token cost overlay** — per-node `cost_usd` on every `llm_response` event; total run cost in sidebar
- **Pricing table** (`vap/cost.py`) — 20+ OpenAI and Anthropic models with prefix-match fallback for versioned variants
- **`vap.calculate_cost(model, input_tokens, output_tokens)`** — public cost utility, returns `float | None`
- **`vap.format_cost(cost_usd)`** — display helper for USD amounts
- **`RunSummary.total_cost_usd`** — new optional field; `None` when no LLM nodes have a recognised model
- **`patch_openai` + `patch_anthropic`** now attach `cost_usd` to every `llm_response` output when the model is in the pricing table
- **React UI** — `AgentGraph` shows cost on LLM nodes; `RunList` shows per-run total; `NodeDetail` shows cost badge; `runStore` recomputes `total_cost_usd` live on every event

### v0.3.0

- **OpenAI SDK integration** — `patch_openai()` for `openai.OpenAI` and `openai.AsyncOpenAI`
- **LangGraph / LangChain integration** — `VapCallbackHandler(run)` for any LangChain-compatible framework
- **Test suite** — 90 tests covering tracer, stores, server, OpenAI integration, and LangChain handler (14 additional tests run when `langchain-core` is installed)
- **`SqliteStore` deduplication** — `_event_ids` set prevents duplicate in-memory entries alongside `INSERT OR IGNORE`
- `anthropic`, `openai`, `langchain-core` all moved to separate optional extra groups; `all` group installs all three

### v0.2.0

- **Async tracer** — `vap.atrace()` and `run.astep()` with `asynccontextmanager`
- **SQLite persistence** — `SqliteStore` in `vap/backends/sqlite.py`; WAL mode, startup replay
- **`vap.configure(db=...)`** — module-level store configuration
- **CLI** — `vap serve --db <path> --port <n> --reload`
- **Async Anthropic patch** — `patch_anthropic()` auto-detects `AsyncAnthropic`
- **New REST endpoints** — `GET /runs/{id}`, `DELETE /runs/{id}`
- **`schema_version`** field on `VapEvent` (default `1`)
- **`RunStore` refactored to ABC** — `_apply_event_to_graph` extracted as shared pure function
- `anthropic` moved to optional dependency (`pip install "vap[anthropic]"`)

### v0.1.0

- Initial release
- Sync tracer (`trace`, `step`)
- In-memory store with asyncio pub/sub
- FastAPI server with SSE streaming
- ReactFlow + dagre UI
- Anthropic SDK sync integration
