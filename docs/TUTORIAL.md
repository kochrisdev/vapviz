# VaP Tutorial — Step-by-Step Guide

This tutorial walks you from zero to a fully instrumented AI agent pipeline. Each step builds on
the last, so work through them in order. No prior VaP knowledge required.

---

## Contents

1. [What is VaP?](#1-what-is-vap)
2. [Installation](#2-installation)
3. [Your First Trace](#3-your-first-trace)
4. [Adding Steps and Tools](#4-adding-steps-and-tools)
5. [Capturing Inputs and Outputs](#5-capturing-inputs-and-outputs)
6. [Automatic Nesting](#6-automatic-nesting)
7. [Async Tracing](#7-async-tracing)
8. [Error Handling](#8-error-handling)
9. [LLM Cost Tracking](#9-llm-cost-tracking)
10. [OpenAI Auto-Instrumentation](#10-openai-auto-instrumentation)
11. [Anthropic Auto-Instrumentation](#11-anthropic-auto-instrumentation)
12. [LangGraph / LangChain Integration](#12-langgraph--langchain-integration)
13. [CrewAI Integration](#13-crewai-integration)
14. [Remote Ingest (any language)](#14-remote-ingest-any-language)
15. [Comparing Runs](#15-comparing-runs)
16. [Exporting Runs](#16-exporting-runs)
17. [Persistence with SQLite](#17-persistence-with-sqlite)
18. [What's Next?](#18-whats-next)

---

## 1. What is VaP?

VaP (**Visualization Agentic Process**) is a lightweight Python + React framework that lets you
**trace and visualize AI agent pipelines in real time**. You instrument your Python code with a
single context manager; every step, tool call, and LLM invocation appears instantly as a
live interactive graph in the browser.

```
Your agent code
     │  VapEvents (in-process)
     ▼
Python VaP store
     │  asyncio.Queue
     ▼
FastAPI server (REST + SSE)
     │  Server-Sent Events
     ▼
React UI  →  you see a live graph in the browser
```

**Key concepts:**

| Term | Meaning |
|---|---|
| **Run** | One execution of your agent (one call to `vap.trace()`). Each run gets an entry in the sidebar. |
| **Node** | A single traced unit of work (a step, tool call, or LLM call). Nodes appear as boxes in the graph. |
| **Event** | A lightweight JSON message emitted when a node starts or ends. The graph is built from events. |
| **Store** | The backend that accumulates events. In-memory by default; SQLite for persistence. |

---

## 2. Installation

### Clone and install the Python package

```bash
git clone https://github.com/kochrisdev/vap.git
cd vap

# Core package (no LLM integrations)
pip install -e .

# Or install everything at once (Anthropic, OpenAI, LangChain support)
pip install -e ".[all]"
```

### Build and start the React UI

```bash
cd ui
npm install
npm run dev      # starts on http://localhost:5173
```

### Start the VaP server

Open a second terminal in the repo root:

```bash
vap serve        # in-memory store, resets on restart
# or
vap serve --db vap.db   # SQLite store, survives restarts
```

Open **http://localhost:5173** — you should see an empty sidebar that says "No runs yet".

> **Tip:** For quick experiments you can also start the server inside your script and skip the
> separate terminal — see the `main_with_server()` pattern used in all the examples.

---

## 3. Your First Trace

Create a file `my_agent.py`:

```python
import time
import vap

# Tell VaP to store runs in SQLite so they survive restarts
vap.configure(db="vap.db")

with vap.trace("Hello VaP") as run:
    print(f"Run started: {run.run_id}")
    time.sleep(0.5)   # simulate work

print("Done!")
```

Run it:

```bash
python my_agent.py
```

**What you'll see in the browser:**

- A new entry "Hello VaP" appears in the sidebar with a green ✓ badge.
- Click it — the graph shows a single indigo node labelled "Hello VaP".
- The right panel shows the run ID, start time, duration, and status.

That single indigo node is the **agent root node**, created automatically by `vap.trace()`.

---

## 4. Adding Steps and Tools

A flat agent with just a root node isn't very useful. Add child nodes with `run.step()`:

```python
import time
import vap

vap.configure(db="vap.db")

with vap.trace("Research Agent") as run:

    # A planning step
    with run.step("plan", kind="step") as step:
        time.sleep(0.1)

    # Two tool calls
    with run.step("search_web", kind="tool") as step:
        time.sleep(0.2)

    with run.step("fetch_page", kind="tool") as step:
        time.sleep(0.15)

    # A final step to write the result
    with run.step("write_report", kind="step") as step:
        time.sleep(0.1)
```

**What you'll see:**

The graph now has five nodes — the root agent node (indigo) plus four children connected by edges:

| `kind=` | Colour | Semantic meaning |
|---|---|---|
| `"agent"` | Indigo | The root of the whole run (created by `trace()`) |
| `"step"` | Sky blue | A logical phase or stage of the pipeline |
| `"tool"` | Emerald | A discrete tool invocation (search, DB query, API call, …) |
| `"llm"` | Purple | An LLM API call (see [Step 9](#9-llm-cost-tracking)) |

> **Tip:** The colour you see in the graph is purely determined by `kind=`. It has no effect on
> how the event is recorded — it only changes the visual.

---

## 5. Capturing Inputs and Outputs

Nodes become much more useful once they carry data. Use `step.set_input()` and `step.set_output()`
to attach any JSON-serialisable dict:

```python
import time
import vap

vap.configure(db="vap.db")

with vap.trace("Data Pipeline") as run:

    with run.step("ingest", kind="step") as step:
        step.set_input({"source": "s3://bucket/data.parquet", "format": "parquet"})
        time.sleep(0.2)
        step.set_output({"rows": 50_000, "bytes": 4_200_000})

    with run.step("validate", kind="tool") as step:
        step.set_input({"rows": 50_000, "schema_version": 2})
        time.sleep(0.1)
        step.set_output({"passed": True, "errors": 0})

    with run.step("transform", kind="step") as step:
        step.set_input({"format": "parquet → csv"})
        time.sleep(0.3)
        step.set_output({"rows": 50_000, "output_path": "s3://bucket/out.csv"})
```

**What you'll see:**

Click any node in the graph — the right panel shows an **"Input"** and **"Output"** section with
the data you attached, rendered as formatted JSON. You'll also see the node's duration and status.

> **Tip:** Call `set_input()` right at the top of the `with` block (before the work starts) and
> `set_output()` right before the block ends. This way partial data is visible even if the step
> crashes.

---

## 6. Automatic Nesting

VaP uses Python's `contextvars.ContextVar` to track the current node automatically. You never
pass parent IDs — just nest your `with run.step(...)` blocks and the graph wires itself up:

```python
import time
import vap

vap.configure(db="vap.db")

with vap.trace("Nested Pipeline") as run:

    with run.step("phase_1", kind="step") as step:
        step.set_input({"items": 3})

        # These two tool calls are automatically children of phase_1
        with run.step("fetch_a", kind="tool") as step:
            time.sleep(0.1)
            step.set_output({"data": "result_a"})

        with run.step("fetch_b", kind="tool") as step:
            time.sleep(0.1)
            step.set_output({"data": "result_b"})

        step.set_output({"merged": 2})

    with run.step("phase_2", kind="step") as step:
        step.set_input({"source": "phase_1 output"})

        with run.step("write", kind="tool") as step:
            time.sleep(0.15)
            step.set_output({"written": True})

        step.set_output({"status": "done"})
```

**What you'll see:**

`fetch_a` and `fetch_b` are drawn as children of `phase_1`. `write` is a child of `phase_2`. The
edges reflect the actual code structure without any manual wiring.

> **How it works:** When `run.step("phase_1")` is entered it pushes its node ID to a
> `ContextVar`. Any nested `run.step()` call reads that variable to get its parent ID. When
> `phase_1` exits it pops back to the previous value (the root agent node).

---

## 7. Async Tracing

For async agents use `atrace` and `astep`. The API is identical — just add `async with` and
`await`:

```python
import asyncio
import vap

vap.configure(db="vap.db")


async def fetch(run: vap.RunContext, url: str) -> dict:
    async with run.astep(f"fetch/{url.split('/')[-1]}", kind="tool") as step:
        step.set_input({"url": url})
        await asyncio.sleep(0.15)   # simulate HTTP call
        step.set_output({"status": 200, "bytes": 1024})
        return {"url": url, "ok": True}


async def main():
    async with vap.atrace("Async Research Agent") as run:

        async with run.astep("plan", kind="step") as step:
            step.set_input({"goal": "fetch three pages"})
            await asyncio.sleep(0.05)
            urls = ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
            step.set_output({"urls": urls})

        # All three fetches run concurrently — they appear as sibling nodes
        results = await asyncio.gather(*[fetch(run, url) for url in urls])

        async with run.astep("summarise", kind="step") as step:
            step.set_input({"results": len(results)})
            await asyncio.sleep(0.1)
            step.set_output({"summary": "All pages fetched successfully"})


asyncio.run(main())
```

**What you'll see:**

The three `fetch/*` nodes appear as siblings. Because they overlap in real time their start times
are very close — you can confirm this in the **Event Timeline** tab (the chronological log at the
bottom of the detail panel).

> **Tip:** `ContextVar` is coroutine-local, so concurrent `asyncio.gather` tasks each get their
> own parent-tracking context. The nesting is correct even when tasks are truly concurrent.

---

## 8. Error Handling

Exceptions inside a `with run.step(...)` block are automatically caught, recorded on the node as
`status: error`, and then **re-raised** — your normal Python exception handling still works:

```python
import time
import vap

vap.configure(db="vap.db")

with vap.trace("Error Demo") as run:

    with run.step("setup", kind="step") as step:
        step.set_input({"config": "prod"})
        time.sleep(0.05)
        step.set_output({"ready": True})

    # Leaf error — caller catches it
    try:
        with run.step("risky_fetch", kind="tool") as step:
            step.set_input({"url": "https://api.example.com"})
            time.sleep(0.1)
            raise ConnectionError("API timeout after 10 s")
            # VaP catches this, marks node red, then re-raises
    except ConnectionError as exc:
        print(f"[handled] {exc}")

    # The run continues normally after a caught error
    with run.step("fallback", kind="step") as step:
        step.set_input({"strategy": "use_cache"})
        time.sleep(0.08)
        step.set_output({"data": "cached_result", "fresh": False})
```

**What you'll see:**

- `setup` → green ✓
- `risky_fetch` → **red ✗** — the node detail panel shows the exception type and message
- `fallback` → green ✓
- The run itself ends green because the error was caught

**Nested errors:** If an inner step raises and the exception propagates through an outer step, both
nodes turn red. See `examples/error_handling_demo.py` for all three scenarios.

> **Rule of thumb:** Catch exceptions outside the `with run.step(...)` block (not inside), so VaP
> always gets to record the error before you handle it.

---

## 9. LLM Cost Tracking

VaP ships a pricing table covering 20+ OpenAI and Anthropic models. You can attach cost to any
node manually — no API key needed to explore this feature:

```python
import time
import vap

vap.configure(db="vap.db")


def simulate_llm(run: vap.RunContext, label: str, model: str,
                 input_tokens: int, output_tokens: int, text: str) -> str:
    """Create a traced LLM node with cost attached."""
    with run.step(label, kind="llm") as step:
        step.set_input({"model": model, "input_tokens": input_tokens})
        time.sleep(0.05)

        cost = vap.calculate_cost(model, input_tokens, output_tokens)
        output = {
            "text": text,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
        if cost is not None:
            output["cost_usd"] = round(cost, 8)

        step.set_output(output)
        return text


with vap.trace("Cost Demo") as run:

    simulate_llm(run, "llm/plan",      "gpt-4o-mini", 500,  150, "Plan: search → analyse → summarise")
    simulate_llm(run, "llm/analyse",   "gpt-4o-mini", 800,  300, "Analysis: three key themes found.")
    simulate_llm(run, "llm/summarise", "gpt-4o-mini", 600,  120, "Summary: themes are X, Y, Z.")
```

**What you'll see:**

- Each purple LLM node shows a small **"$0.000…"** label on the graph.
- The sidebar entry shows the **total run cost**.
- The node detail panel shows the full `usage` dict and `cost_usd`.

**Check which models are supported and what they cost:**

```python
import vap

models = [
    ("gpt-4o-mini",               1_000, 500),
    ("gpt-4o",                    1_000, 500),
    ("claude-3-5-haiku-20241022", 1_000, 500),
    ("claude-3-5-sonnet-20241022",1_000, 500),
    ("o1",                        1_000, 500),
    ("my-custom-model",           1_000, 500),   # unknown → None
]

for model, inp, out in models:
    cost = vap.calculate_cost(model, inp, out)
    label = vap.format_cost(cost) if cost is not None else "unknown model"
    print(f"  {model:<38}  {label}")
```

> **Tip:** If you use a model that isn't in the pricing table, `calculate_cost()` returns `None`
> and no cost label is shown. You can still attach a cost manually by computing it yourself and
> putting it in `output["cost_usd"]`.

---

## 10. OpenAI Auto-Instrumentation

When you call `vap.patch_openai(client)`, every subsequent `client.chat.completions.create()` call
is automatically wrapped in a `kind="llm"` step — model name, token counts, cost, and response
text are all captured without any manual code:

```python
import os
import time
import vap
import openai

vap.configure(db="vap.db")

# Requires: pip install "vap[openai]"  and  export OPENAI_API_KEY=sk-...
client = openai.OpenAI()
vap.patch_openai(client)    # one line — that's all the instrumentation needed

with vap.trace("OpenAI Agent") as run:

    with run.step("research", kind="step") as step:
        step.set_input({"topic": "agent architectures"})

        # This call is automatically traced as a child 'llm' node
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=120,
            messages=[
                {"role": "system", "content": "You are a concise technical writer."},
                {"role": "user",   "content": "Write 2 sentences about agent architectures."},
            ],
        )
        text = response.choices[0].message.content or ""
        step.set_output({"text": text[:120]})
```

**What you'll see:**

The graph has a `research` (sky blue) step with a nested `gpt-4o-mini` (purple) LLM node inside
it. The LLM node automatically shows the model, prompt messages, response, token usage, and USD
cost — zero manual `set_input` / `set_output` calls needed.

**Async OpenAI** is also supported:

```python
import asyncio, openai, vap

vap.configure(db="vap.db")
client = openai.AsyncOpenAI()
vap.patch_openai(client)

async def main():
    async with vap.atrace("Async OpenAI Agent") as run:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=50,
            messages=[{"role": "user", "content": "Hello!"}],
        )
        print(response.choices[0].message.content)

asyncio.run(main())
```

---

## 11. Anthropic Auto-Instrumentation

Same pattern as OpenAI — `vap.patch_anthropic(client)` does the work:

```python
import os
import time
import vap
import anthropic

vap.configure(db="vap.db")

# Requires: pip install "vap[anthropic]"  and  export ANTHROPIC_API_KEY=sk-ant-...
client = anthropic.Anthropic()
vap.patch_anthropic(client)

with vap.trace("Anthropic Agent") as run:

    with run.step("plan", kind="step") as step:
        step.set_input({"goal": "Summarise AI news"})
        time.sleep(0.05)
        topics = ["tool use", "multi-agent", "reasoning"]
        step.set_output({"topics": topics})

    for topic in topics:
        with run.step(f"expand/{topic.replace(' ', '_')}", kind="step") as step:
            step.set_input({"topic": topic})

            # Automatically traced as a child 'llm' node with cost attached
            message = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=80,
                messages=[{"role": "user", "content": f"One sentence on: {topic}"}],
            )
            text = message.content[0].text
            step.set_output({"text": text[:100]})
```

**Async Anthropic** works the same way — create an `anthropic.AsyncAnthropic()` client, patch it,
and use `async with vap.atrace(...)`.

---

## 12. LangGraph / LangChain Integration

`VapCallbackHandler` wires into LangChain's callback system. Pass it in the `config` dict and
every chain, tool call, and LLM round-trip is traced automatically:

```python
import os
import vap
from vap.integrations.langchain import VapCallbackHandler

# Requires: pip install "vap[langchain]" langgraph langchain-openai
# and: export OPENAI_API_KEY=sk-...

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

vap.configure(db="vap.db")


@tool
def search_web(query: str) -> str:
    """Search the web for a topic."""
    return f"Results for '{query}': significant progress found in 2024."


@tool
def calculate(expression: str) -> str:
    """Evaluate an arithmetic expression."""
    return str(eval(expression, {"__builtins__": {}}))


llm   = ChatOpenAI(model="gpt-4o-mini", temperature=0)
agent = create_react_agent(llm, [search_web, calculate])

with vap.trace("LangGraph ReAct Agent") as run:
    handler = VapCallbackHandler(run)   # attach VaP to this run

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Search for AI trends and calculate 128 * 37."}]},
        config={"callbacks": [handler]},
    )
    print(result["messages"][-1].content)
```

**What you'll see:**

The graph shows the full ReAct loop — each LLM thought, each tool call, and each LLM response
appear as separate nodes. You can see exactly how many tool-call rounds the agent took before
arriving at its final answer.

---

## 13. CrewAI Integration

`VapCrewAIListener` hooks into CrewAI's native event bus. Instantiate it once before calling
`crew.kickoff()` — no other changes to your crew code are needed.

**Requires:** `pip install "vap[crewai]"` and an LLM API key.

### Auto mode — one trace per kickoff

```python
import vap
from vap.integrations.crewai_listener import VapCrewAIListener
from crewai import Agent, Crew, Process, Task

vap.configure(db="vap.db")

# Register listener once — auto-creates a VaP run for every kickoff()
VapCrewAIListener()

researcher = Agent(
    role="Senior Researcher",
    goal="Summarise '{topic}' in three bullet points.",
    backstory="You are a meticulous researcher.",
    verbose=False,
)
writer = Agent(
    role="Content Writer",
    goal="Write a paragraph from the research findings.",
    backstory="You craft clear technical summaries.",
    verbose=False,
)
research_task = Task(
    description="Research '{topic}' and list three key developments.",
    expected_output="Three bullet points.",
    agent=researcher,
)
write_task = Task(
    description="Summarise '{topic}' in one paragraph (max 80 words).",
    expected_output="One paragraph.",
    agent=writer,
    context=[research_task],
)

crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task],
            process=Process.sequential, verbose=False)

result = crew.kickoff(inputs={"topic": "AI agent frameworks"})
print(result.raw)
```

**What you'll see:**

The VaP graph has this structure:

```
Research Crew (agent root)
├── task/research
│   └── agent/Senior Researcher
│       ├── llm/gpt-4o-mini   (thinking call)
│       └── llm/gpt-4o-mini   (response)
└── task/write
    └── agent/Content Writer
        └── llm/gpt-4o-mini
```

Each `llm/` node shows the model, messages, token usage, and USD cost. Tool calls would also appear
here as `tool/` nodes if the agents have tools attached.

### Manual mode — crew inside a larger pipeline

```python
import time
import vap
from vap.integrations.crewai_listener import VapCrewAIListener

with vap.trace("Full Pipeline") as run:

    # Step 1 — plain VaP, no CrewAI
    with run.step("load_data", kind="step") as step:
        step.set_input({"source": "s3://bucket/data.csv"})
        time.sleep(0.05)
        step.set_output({"rows": 10_000})

    # Step 2 — CrewAI crew attached to this run
    VapCrewAIListener(run=run)
    result = crew.kickoff(inputs={"topic": "quarterly trends"})

    # Step 3 — plain VaP again
    with run.step("store_report", kind="step") as step:
        step.set_input({"destination": "reports/q4.json"})
        time.sleep(0.03)
        step.set_output({"written": True})
```

**What you'll see:**

One run in the sidebar called "Full Pipeline". `load_data`, the `crew/` step containing all tasks,
and `store_report` all sit side by side as siblings.

> **Note:** In manual mode the listener does NOT close the provided `RunContext` — your
> `with vap.trace(...)` block controls the run lifecycle.

---

## 14. Remote Ingest (any language)

You don't need to import `vap` in the process that runs your agent. Any process — including
non-Python code — can push events by POSTing JSON to `POST /runs/{run_id}/events`.

Here is a minimal Python example using only the standard library:

```python
import json
import time
import uuid
import urllib.request

SERVER = "http://localhost:8001"


def post_event(run_id: str, event: dict) -> None:
    body = json.dumps(event).encode()
    req  = urllib.request.Request(
        f"{SERVER}/runs/{run_id}/events",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=5)


def uid() -> str:
    return uuid.uuid4().hex[:12]


run_id  = uid()
root_id = uid()
ts      = time.time

# 1. Open the run
post_event(run_id, {
    "id": uid(), "run_id": run_id, "timestamp": ts(),
    "type": "agent_start", "node_id": root_id,
    "node_kind": "agent", "node_label": "Remote Agent",
    "parent_id": None, "data": {}, "schema_version": 1,
})

# 2. A step
step_id = uid()
post_event(run_id, {
    "id": uid(), "run_id": run_id, "timestamp": ts(),
    "type": "step_start", "node_id": step_id,
    "node_kind": "step", "node_label": "process",
    "parent_id": root_id, "data": {"input": {"items": 10}}, "schema_version": 1,
})
time.sleep(0.2)
post_event(run_id, {
    "id": uid(), "run_id": run_id, "timestamp": ts(),
    "type": "step_end", "node_id": step_id,
    "node_kind": "step", "node_label": "process",
    "parent_id": root_id, "data": {"output": {"processed": 10}}, "schema_version": 1,
})

# 3. Close the run
post_event(run_id, {
    "id": uid(), "run_id": run_id, "timestamp": ts(),
    "type": "agent_end", "node_id": root_id,
    "node_kind": "agent", "node_label": "Remote Agent",
    "parent_id": None, "data": {"output": {"status": "ok"}}, "schema_version": 1,
})

print(f"View at {SERVER}  run_id={run_id}")
```

**Make sure the server is running first:**

```bash
vap serve --db vap.db
python my_remote_agent.py
```

**What you'll see:** The run appears in the browser in real time as each event is posted — even
though the agent process has no knowledge of VaP internals.

> **Full event reference:** see `POST /runs/{id}/events` in
> [DEVELOPER_REFERENCE.md](DEVELOPER_REFERENCE.md#post-runsrunid-events--remote-event-ingest) for
> the complete list of event types and their required fields.

---

## 15. Comparing Runs

Once you have two or more runs you can diff them side by side to understand what changed — useful
for comparing model variants, prompt changes, or pipeline refactors.

**How to compare:**

1. In the sidebar, select the first run (single click — it turns blue).
2. Hover over a second run — a **⇄** icon appears on the right.
3. Click ⇄ to enter comparison mode.
4. The centre panel splits: Run A on the left, Run B on the right.

**What the comparison shows:**

| Section | Description |
|---|---|
| **Stats header** | Label, status, duration, and total cost for each run |
| **Diff pill** | Counts of nodes only in A / only in B / common to both |
| **Duration Δ** | How much faster or slower Run B was vs Run A |
| **Cost Δ** | Total cost difference between the two runs |
| **Graph (left)** | Run A graph — nodes that don't exist in B have a yellow strip |
| **Graph (right)** | Run B graph — nodes that don't exist in A have a yellow strip |

To leave comparison mode click the **×** that appears on the active comparison run, or click any
run in the sidebar normally.

> **Tip:** The `cost_tracking_demo.py` example creates three runs with different model choices —
> run it and compare `gpt-4o-mini` vs `gpt-4o` to see the cost Δ immediately.

---

## 16. Exporting Runs

Every run can be exported in two formats from the **Export ▾** button in the top-right toolbar
(only visible when a run is selected).

### JSON export

Downloads the complete `RunGraph` as a JSON file (`vap-{run_id}.json`). The JSON contains every
node, every edge, all input/output data, durations, and status. Useful for:

- Archiving important runs
- Feeding run data into offline analysis scripts
- Sharing a specific run with a colleague who doesn't have server access

```bash
# You can also download it with curl:
curl http://localhost:8001/runs/{run_id}/export -o run.json
```

### PNG export

Captures the current ReactFlow graph as a PNG image. Uses `html2canvas` under the hood so the
screenshot includes the layout exactly as you see it — useful for reports or documentation.

> **Tip:** Before taking a PNG screenshot, use the zoom/pan controls to frame the graph the way
> you want it. The PNG captures only what's visible in the canvas.

---

## 17. Persistence with SQLite

By default VaP uses an in-memory store — fast, zero setup, but all runs are lost when the
process exits. Switch to SQLite with one line:

```python
import vap
vap.configure(db="vap.db")
```

Or via the CLI:

```bash
vap serve --db vap.db
```

**What this gives you:**

- Runs survive server restarts
- The full event history is replayed when the browser connects
- Multiple scripts can write to the same database file concurrently (WAL mode is enabled
  automatically)

**Viewing historical runs:**

Start the server against an existing database and all previous runs appear immediately in the
sidebar:

```bash
vap serve --db vap.db        # loads all past runs on startup
```

**Backup:**

```bash
sqlite3 vap.db ".backup vap_backup_$(date +%Y%m%d).db"
```

> **Note:** SQLite is well-suited for single-machine deployments. If you need multiple server
> replicas sharing state, see the
> [Deployment Guide](DEPLOYMENT.md) for production options.

---

## 18. What's Next?

You now know everything you need to instrument real agents. Here are pointers for going deeper:

### Run the bundled examples

```bash
# No API key needed:
python examples/simple_demo.py
python examples/error_handling_demo.py
python examples/cost_tracking_demo.py
python examples/remote_ingest_demo.py

# Requires an API key:
python examples/openai_demo.py
python examples/anthropic_demo.py
python examples/langgraph_demo.py
```

### Read the reference docs

| Document | Contents |
|---|---|
| [DEVELOPER_REFERENCE.md](DEVELOPER_REFERENCE.md) | Complete Python API, CLI flags, every REST endpoint, SSE protocol, TypeScript types |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Internal design — event flow, store internals, React state machine, component tree |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Docker, Nginx, Railway/Render/Fly.io, security, health checks |

### Common patterns

**Pattern 1 — wrap an existing function without modifying it:**

```python
import vap

def my_function(data: dict) -> dict:
    # existing code, untouched
    return {"result": data}

with vap.trace("Wrapped Agent") as run:
    with run.step("my_function", kind="tool") as step:
        step.set_input(data)
        result = my_function(data)
        step.set_output(result)
```

**Pattern 2 — trace a long-running background job:**

```python
import threading
import vap

vap.configure(db="vap.db")

def background_job():
    with vap.trace("Background Job") as run:
        with run.step("batch_process", kind="step") as step:
            step.set_input({"items": 10_000})
            # ... long work ...
            step.set_output({"processed": 10_000})

t = threading.Thread(target=background_job, daemon=True)
t.start()
# The graph updates live in the browser while the thread runs
```

**Pattern 3 — multiple concurrent agents in the same process:**

```python
import asyncio, vap

vap.configure(db="vap.db")

async def agent(name: str, delay: float):
    async with vap.atrace(name) as run:
        async with run.astep("work", kind="step") as step:
            step.set_input({"agent": name})
            await asyncio.sleep(delay)
            step.set_output({"done": True})

async def main():
    await asyncio.gather(
        agent("Agent A", 0.3),
        agent("Agent B", 0.5),
        agent("Agent C", 0.2),
    )

asyncio.run(main())
# Three independent runs appear in the sidebar simultaneously
```

---

*Happy tracing! If you run into a problem or want to contribute, open an issue on
[GitHub](https://github.com/kochrisdev/vap).*
