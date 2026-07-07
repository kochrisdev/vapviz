# vapviz Tutorial — Step-by-Step Guide

This tutorial walks you from zero to a fully instrumented AI agent pipeline. Each step builds on
the last, so work through them in order. No prior vapviz knowledge required.

---

## Contents

1. [What is vapviz?](#1-what-is-vapviz)
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
14. [Pydantic AI Integration](#14-pydantic-ai-integration)
15. [LlamaIndex Integration](#15-llamaindex-integration)
16. [AutoGen Integration](#16-autogen-integration)
17. [Remote Ingest (any language)](#17-remote-ingest-any-language)
18. [Comparing Runs](#18-comparing-runs)
19. [Exporting Runs](#19-exporting-runs)
20. [Persistence with SQLite](#20-persistence-with-sqlite)
21. [Analytics Dashboard](#21-analytics-dashboard)
22. [OpenTelemetry Export](#22-opentelemetry-export)
23. [Cost & Latency Budgets](#23-cost--latency-budgets)
24. [Agent Evals & Scoring](#24-agent-evals--scoring)
25. [Search & Tagging](#25-search--tagging)
26. [Trace Replay](#26-trace-replay)
27. [Theater & the Office Building](#27-theater--the-office-building)
28. [What's Next?](#28-whats-next)

---

## 1. What is vapviz?

vapviz (**Visualization Agentic Process**) is a lightweight Python + React framework that lets you
**trace and visualize AI agent pipelines in real time**. You instrument your Python code with a
single context manager; every step, tool call, and LLM invocation appears instantly as a
live interactive graph in the browser.

```
Your agent code
     │  VapEvents (in-process)
     ▼
Python vapviz store
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
| **Run** | One execution of your agent (one call to `vapviz.trace()`). Each run gets an entry in the sidebar. |
| **Node** | A single traced unit of work (a step, tool call, or LLM call). Nodes appear as boxes in the graph. |
| **Event** | A lightweight JSON message emitted when a node starts or ends. The graph is built from events. |
| **Store** | The backend that accumulates events. In-memory by default; SQLite for persistence. |

---

## 2. Installation

### Clone and install the Python package

```bash
git clone https://github.com/kochrisdev/vapviz.git
cd vapviz

# Core package (no LLM integrations)
pip install -e .

# Or install everything at once (all integrations + OpenTelemetry export)
pip install -e ".[all]"
```

### Build and start the React UI

```bash
cd ui
npm install
npm run dev      # starts on http://localhost:5173
```

### Start the vapviz server

Open a second terminal in the repo root:

```bash
vapviz serve        # in-memory store, resets on restart
# or
vapviz serve --db vapviz.db   # SQLite store, survives restarts
```

Open **http://localhost:5173** — you should see an empty sidebar that says "No runs yet".

> **Tip:** For quick experiments you can also start the server inside your script and skip the
> separate terminal — see the `main_with_server()` pattern used in all the examples.

---

## 3. Your First Trace

Create a file `my_agent.py`:

```python
import time
import vapviz

# Tell vapviz to store runs in SQLite so they survive restarts
vapviz.configure(db="vapviz.db")

with vapviz.trace("Hello vapviz") as run:
    print(f"Run started: {run.run_id}")
    time.sleep(0.5)   # simulate work

print("Done!")
```

Run it:

```bash
python my_agent.py
```

**What you'll see in the browser:**

- A new entry "Hello vapviz" appears in the sidebar with a green ✓ badge.
- Click it — the graph shows a single indigo node labelled "Hello vapviz".
- The right panel shows the run ID, start time, duration, and status.

That single indigo node is the **agent root node**, created automatically by `vapviz.trace()`.

> **Tip — give your app one home.** If you'll run this script many times, pass a stable
> `app_id`: `vapviz.trace("Hello vapviz", app_id="hello-vapviz")`. Every run of the same
> `app_id` groups into **one sidebar entry** (expand it for the run history) and **one room**
> in the Office building view, instead of piling up as separate entries. Without an
> `app_id`, runs group by their exact label.

---

## 4. Adding Steps and Tools

A flat agent with just a root node isn't very useful. Add child nodes with `run.step()`:

```python
import time
import vapviz

vapviz.configure(db="vapviz.db")

with vapviz.trace("Research Agent") as run:

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
import vapviz

vapviz.configure(db="vapviz.db")

with vapviz.trace("Data Pipeline") as run:

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

vapviz uses Python's `contextvars.ContextVar` to track the current node automatically. You never
pass parent IDs — just nest your `with run.step(...)` blocks and the graph wires itself up:

```python
import time
import vapviz

vapviz.configure(db="vapviz.db")

with vapviz.trace("Nested Pipeline") as run:

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
import vapviz

vapviz.configure(db="vapviz.db")


async def fetch(run: vapviz.RunContext, url: str) -> dict:
    async with run.astep(f"fetch/{url.split('/')[-1]}", kind="tool") as step:
        step.set_input({"url": url})
        await asyncio.sleep(0.15)   # simulate HTTP call
        step.set_output({"status": 200, "bytes": 1024})
        return {"url": url, "ok": True}


async def main():
    async with vapviz.atrace("Async Research Agent") as run:

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
are very close — you can confirm this in the **Logs** tab (the full-width chronological event log,
Technical mode).

> **Tip:** `ContextVar` is coroutine-local, so concurrent `asyncio.gather` tasks each get their
> own parent-tracking context. The nesting is correct even when tasks are truly concurrent.

---

## 8. Error Handling

Exceptions inside a `with run.step(...)` block are automatically caught, recorded on the node as
`status: error`, and then **re-raised** — your normal Python exception handling still works:

```python
import time
import vapviz

vapviz.configure(db="vapviz.db")

with vapviz.trace("Error Demo") as run:

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
            # vapviz catches this, marks node red, then re-raises
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

> **Rule of thumb:** Catch exceptions outside the `with run.step(...)` block (not inside), so vapviz
> always gets to record the error before you handle it.

---

## 9. LLM Cost Tracking

vapviz ships a pricing table covering 20+ OpenAI and Anthropic models. You can attach cost to any
node manually — no API key needed to explore this feature:

```python
import time
import vapviz

vapviz.configure(db="vapviz.db")


def simulate_llm(run: vapviz.RunContext, label: str, model: str,
                 input_tokens: int, output_tokens: int, text: str) -> str:
    """Create a traced LLM node with cost attached."""
    with run.step(label, kind="llm") as step:
        step.set_input({"model": model, "input_tokens": input_tokens})
        time.sleep(0.05)

        cost = vapviz.calculate_cost(model, input_tokens, output_tokens)
        output = {
            "text": text,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
        if cost is not None:
            output["cost_usd"] = round(cost, 8)

        step.set_output(output)
        return text


with vapviz.trace("Cost Demo") as run:

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
import vapviz

models = [
    ("gpt-4o-mini",               1_000, 500),
    ("gpt-4o",                    1_000, 500),
    ("claude-3-5-haiku-20241022", 1_000, 500),
    ("claude-3-5-sonnet-20241022",1_000, 500),
    ("o1",                        1_000, 500),
    ("my-custom-model",           1_000, 500),   # unknown → None
]

for model, inp, out in models:
    cost = vapviz.calculate_cost(model, inp, out)
    label = vapviz.format_cost(cost) if cost is not None else "unknown model"
    print(f"  {model:<38}  {label}")
```

> **Tip:** If you use a model that isn't in the pricing table, `calculate_cost()` returns `None`
> and no cost label is shown. You can still attach a cost manually by computing it yourself and
> putting it in `output["cost_usd"]`.

---

## 10. OpenAI Auto-Instrumentation

When you call `vapviz.patch_openai(client)`, every subsequent `client.chat.completions.create()` call
is automatically wrapped in a `kind="llm"` step — model name, token counts, cost, and response
text are all captured without any manual code:

```python
import os
import time
import vapviz
import openai

vapviz.configure(db="vapviz.db")

# Requires: pip install "vapviz[openai]"  and  export OPENAI_API_KEY=sk-...
client = openai.OpenAI()
vapviz.patch_openai(client)    # one line — that's all the instrumentation needed

with vapviz.trace("OpenAI Agent") as run:

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
import asyncio, openai, vapviz

vapviz.configure(db="vapviz.db")
client = openai.AsyncOpenAI()
vapviz.patch_openai(client)

async def main():
    async with vapviz.atrace("Async OpenAI Agent") as run:
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

Same pattern as OpenAI — `vapviz.patch_anthropic(client)` does the work:

```python
import os
import time
import vapviz
import anthropic

vapviz.configure(db="vapviz.db")

# Requires: pip install "vapviz[anthropic]"  and  export ANTHROPIC_API_KEY=sk-ant-...
client = anthropic.Anthropic()
vapviz.patch_anthropic(client)

with vapviz.trace("Anthropic Agent") as run:

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
and use `async with vapviz.atrace(...)`.

---

## 12. LangGraph / LangChain Integration

`VapCallbackHandler` wires into LangChain's callback system. Pass it in the `config` dict and
every chain, tool call, and LLM round-trip is traced automatically:

```python
import os
import vapviz
from vapviz.integrations.langchain import VapCallbackHandler

# Requires: pip install "vapviz[langchain]" langgraph langchain-openai
# and: export OPENAI_API_KEY=sk-...

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

vapviz.configure(db="vapviz.db")


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

with vapviz.trace("LangGraph ReAct Agent") as run:
    handler = VapCallbackHandler(run)   # attach vapviz to this run

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

**Requires:** `pip install "vapviz[crewai]"` and an LLM API key.

### Auto mode — one trace per kickoff

```python
import vapviz
from vapviz.integrations.crewai_listener import VapCrewAIListener
from crewai import Agent, Crew, Process, Task

vapviz.configure(db="vapviz.db")

# Register listener once — auto-creates a vapviz run for every kickoff()
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

The vapviz graph has this structure:

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
import vapviz
from vapviz.integrations.crewai_listener import VapCrewAIListener

with vapviz.trace("Full Pipeline") as run:

    # Step 1 — plain vapviz, no CrewAI
    with run.step("load_data", kind="step") as step:
        step.set_input({"source": "s3://bucket/data.csv"})
        time.sleep(0.05)
        step.set_output({"rows": 10_000})

    # Step 2 — CrewAI crew attached to this run
    VapCrewAIListener(run=run)
    result = crew.kickoff(inputs={"topic": "quarterly trends"})

    # Step 3 — plain vapviz again
    with run.step("store_report", kind="step") as step:
        step.set_input({"destination": "reports/q4.json"})
        time.sleep(0.03)
        step.set_output({"written": True})
```

**What you'll see:**

One run in the sidebar called "Full Pipeline". `load_data`, the `crew/` step containing all tasks,
and `store_report` all sit side by side as siblings.

> **Note:** In manual mode the listener does NOT close the provided `RunContext` — your
> `with vapviz.trace(...)` block controls the run lifecycle.

---

## 14. Pydantic AI Integration

`VapPydanticAI` traces [Pydantic AI](https://ai.pydantic.dev/) agents. Instantiate it once and
every `agent.run()` / `run_sync()` is captured — the agent, each model request (with tokens and
cost), and each tool call (with its arguments and result) — with no changes to your agent code.

```bash
pip install "vapviz[pydantic-ai]"
```

**Auto mode** — one fresh vapviz run per `agent.run()`:

```python
import vapviz
from pydantic_ai import Agent
from vapviz.integrations.pydantic_ai import VapPydanticAI

vapviz.configure(db="vapviz.db")

agent = Agent("openai:gpt-4o-mini", name="weather-agent")

@agent.tool_plain
def get_weather(city: str) -> str:
    return f"{city}: 21°C, partly cloudy"

VapPydanticAI()                       # patch once, before any run
result = agent.run_sync("What's the weather in Paris?")
```

The graph for that run looks like:

```
weather-agent                 (agent — the run root)
├── llm/gpt-4o-mini           (first model request — decides to call the tool)
│   └── get_weather           (tool — parented under the request that called it)
└── llm/gpt-4o-mini           (final model response)
```

**Manual mode** — nest the agent inside a larger pipeline by passing a `RunContext`:

```python
with vapviz.trace("Trip planner") as run:
    with run.step("load_preferences", kind="step") as step:
        step.set_output({"prefers": "warm cities"})

    listener = VapPydanticAI(run)     # agent runs become children of this run
    result = agent.run_sync("Is Lisbon warm enough for a beach trip?")
    listener.detach()                 # optional — restore Agent.run/run_sync

    with run.step("format_itinerary", kind="step") as step:
        step.set_output({"itinerary": "Day 1: beach, Day 2: old town"})
```

Each model request becomes an `llm` node with token usage and (for priced models) `cost_usd`;
the totals are aggregated onto the agent node. Tool calls are matched to their results by
`tool_call_id` and parented under the model request that issued them.

> **Try it with no API key:** `python examples/pydantic_ai_demo.py` uses Pydantic AI's built-in
> `TestModel`, so it runs fully offline.

> **Note:** the graph is reconstructed from the run's message history after it completes, so node
> timings come from the message timestamps. Streaming methods (`run_stream`) aren't traced yet.

---

## 15. LlamaIndex Integration

`VapLlamaIndex` traces [LlamaIndex](https://docs.llamaindex.ai/) by registering a span handler on
its instrumentation dispatcher. A whole RAG query — query engine, retriever, embeddings, response
synthesizer, and LLM calls — shows up as a nested vapviz graph with real timings, no changes to your
LlamaIndex code.

```bash
pip install "vapviz[llamaindex]"
```

The recommended pattern is **manual mode**: wrap your indexing/query work in a `vapviz.trace()` so the
whole workflow is one run.

```python
import vapviz
from llama_index.core import VectorStoreIndex, Document
from vapviz.integrations.llamaindex import VapLlamaIndex

with vapviz.trace("RAG query") as run:
    VapLlamaIndex(run)
    index = VectorStoreIndex.from_documents([Document(text="vapviz traces AI agents.")])
    response = index.as_query_engine().query("What does vapviz do?")
```

The resulting graph reflects LlamaIndex's real call tree, for example:

```
RAG query                          (the trace's run root)
└── RetrieverQueryEngine.query     (step)
    ├── VectorIndexRetriever.retrieve         (tool)
    │   └── MockEmbedding.get_query_embedding (tool)
    └── CompactAndRefine.synthesize           (step)
        └── …                                 (step)
            └── MockLLM.predict               (llm)
```

Spans are classified by kind — **retrievers and embeddings** become `tool` nodes, **LLM calls**
become `llm` nodes, and orchestration (query engines, synthesizers, splitters) stays `step`. Node
timings are captured live, so durations are real.

Prefer one run per top-level call instead? Use **auto mode** — `VapLlamaIndex()` with no run — and
each top-level instrumented call (e.g. each `.query(...)`) becomes its own vapviz run. Call `.detach()`
to remove the handler when you're done.

> **Try it with no API key:** `python examples/llamaindex_demo.py` uses LlamaIndex's `MockLLM` and
> `MockEmbedding`, so it runs fully offline.

---

## 16. AutoGen Integration

`VapAutoGen` traces [AutoGen](https://microsoft.github.io/autogen/) (AG2) multi-agent conversations
by wrapping `ConversableAgent`. The chat becomes a root, each agent turn becomes a child node, and
any tool/function call nests under the turn that made it — with real timings and no changes to your
agent code.

```bash
pip install "vapviz[autogen]"
```

Wrap your conversation in a `vapviz.trace()` (manual mode):

```python
import vapviz
from autogen import ConversableAgent
from vapviz.integrations.autogen import VapAutoGen

assistant = ConversableAgent("assistant", llm_config={"model": "gpt-4o-mini"})
user = ConversableAgent("user", human_input_mode="NEVER", max_consecutive_auto_reply=2)

with vapviz.trace("Support chat") as run:
    VapAutoGen(run)
    user.initiate_chat(assistant, message="How do I reset my password?")
```

The resulting graph mirrors the conversation:

```
Support chat                 (the trace's run root)
└── chat/assistant           (step — the initiate_chat)
    ├── agent/assistant       (turn)
    ├── agent/user            (turn)
    └── agent/assistant       (turn)
```

Each `generate_reply` becomes an `agent/<name>` turn node; `execute_function` tool calls appear as
`tool` nodes nested under the turn that called them. Turns are siblings under the chat in
conversation order.

Prefer one run per conversation instead? Use **auto mode** — `VapAutoGen()` with no run — and each
`initiate_chat` becomes its own vapviz run. Call `.detach()` to restore the original methods.

> **Try it with no API key:** `python examples/autogen_demo.py` uses offline agents (registered reply
> functions), so it runs fully offline.

> **Note:** this targets the classic `autogen.ConversableAgent` API (AG2 / `pyautogen`), not the
> newer async `autogen-agentchat` (v0.4+) agents.

---

## 17. Remote Ingest (any language)

You don't need to import `vapviz` in the process that runs your agent. Any process — including
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
vapviz serve --db vapviz.db
python my_remote_agent.py
```

**What you'll see:** The run appears in the browser in real time as each event is posted — even
though the agent process has no knowledge of vapviz internals.

> **Full event reference:** see `POST /runs/{id}/events` in
> [DEVELOPER_REFERENCE.md](DEVELOPER_REFERENCE.md#post-runsrunid-events--remote-event-ingest) for
> the complete list of event types and their required fields.

---

## 18. Comparing Runs

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

## 19. Exporting Runs

Every run can be exported in two formats from the **Export ▾** button in the top-right toolbar
(only visible when a run is selected).

### JSON export

Downloads the complete `RunGraph` as a JSON file (`vapviz-{run_id}.json`). The JSON contains every
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

## 20. Persistence with SQLite

By default vapviz uses an in-memory store — fast, zero setup, but all runs are lost when the
process exits. Switch to SQLite with one line:

```python
import vapviz
vapviz.configure(db="vapviz.db")
```

Or via the CLI:

```bash
vapviz serve --db vapviz.db
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
vapviz serve --db vapviz.db        # loads all past runs on startup
```

**Backup:**

```bash
sqlite3 vapviz.db ".backup vap_backup_$(date +%Y%m%d).db"
```

> **Note:** SQLite is well-suited for single-machine deployments. If you need multiple server
> replicas sharing state, see the
> [Deployment Guide](DEPLOYMENT.md) for production options.

---

## 21. Analytics Dashboard

Once you have several runs stored, the **Analytics** dashboard gives you a bird's-eye view across
all of them — no extra instrumentation required, it reads the same data your traces already
capture. Click the bar-chart icon in the sidebar header to toggle it (click any run to return to
the graph view).

It shows:

- **Overview cards** — run count, success rate, total & average cost, average duration, LLM-call
  count, and total tokens
- **Cost over time** — total LLM spend bucketed per day
- **By model** — calls, tokens, and USD cost for each model, sorted by spend
- **Nodes by kind** — how your runs break down across agent / step / tool / LLM nodes

The dashboard auto-refreshes every few seconds, so it stays current while live runs complete.

**Programmatic access:** the same numbers are available without the UI.

```bash
curl http://localhost:8001/metrics
```

```python
import vapviz
from vapviz.backends.sqlite import SqliteStore

store = SqliteStore("vapviz.db")
graphs = [g for g in (store.get_graph(s.run_id) for s in store.list_runs()) if g]
metrics = vapviz.compute_metrics(graphs)

print(f"{metrics.run_count} runs · {vapviz.format_cost(metrics.total_cost_usd)} total")
for m in metrics.by_model:
    print(f"  {m.model}: {m.calls} calls, {vapviz.format_cost(m.cost_usd)}")
```

See the [`GET /metrics`](DEVELOPER_REFERENCE.md#get-metrics) reference for the full field list.

---

## 22. OpenTelemetry Export

vapviz can mirror every run into [OpenTelemetry](https://opentelemetry.io/) — useful when you already
run Jaeger, Grafana Tempo, or Datadog and want your agent traces alongside the rest of your service
telemetry. Each run becomes **one OTel trace**; each node (agent / step / tool / LLM) becomes a span
nested exactly like the vapviz graph.

```bash
pip install "vapviz[otel]"
```

Point it at an OTLP collector and every completed run is exported automatically:

```python
import vapviz
from vapviz.integrations.otel import enable_otel_export

vapviz.configure(db="vapviz.db")
enable_otel_export(endpoint="http://localhost:4317")   # OTLP/gRPC (use protocol="http" for 4318)

with vapviz.trace("My agent") as run:
    with run.step("ask", kind="llm") as s:
        s.set_input({"model": "gpt-4o"})
        s.set_output({"usage": {"input_tokens": 1200, "output_tokens": 180}, "cost_usd": 0.0048})
# → exported to OpenTelemetry when the run completes
```

LLM spans use the OTel **GenAI semantic conventions** (`gen_ai.request.model`,
`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`), cost rides along as `vapviz.cost_usd`, and a
failed node sets the span's status to `ERROR`.

**Already have OpenTelemetry configured?** Call `enable_otel_export()` with no arguments to use your
existing global `TracerProvider`, or pass your own with `enable_otel_export(tracer_provider=...)`.

**Export on demand** (instead of auto-export) — convert any stored run to spans yourself:

```python
from vapviz.integrations.otel import export_run
export_run(store.get_graph(run_id), tracer_provider=my_provider)
```

> **Try it with no collector:** `python examples/otel_demo.py` exports a run to the console via
> OpenTelemetry's `ConsoleSpanExporter`, so you can see the spans without any backend.

This is **export**, not replacement — runs still stream into the vapviz UI as usual.

---

## 23. Cost & Latency Budgets

Once you're tracking cost and duration, you can set **budgets** — limits that vapviz checks on every
completed run, alerting you when one is exceeded. This turns passive metrics into active guardrails
(catch a runaway agent, a prompt that 10×'d your token use, or a slow regression).

Define a `Budget` and enable alerts:

```python
import vapviz
from vapviz.budgets import Budget, enable_budget_alerts

vapviz.configure(db="vapviz.db")

# Any limit left unset is not enforced.
enable_budget_alerts(Budget(max_cost_usd=0.05, max_duration_ms=5000, max_total_tokens=20_000))

# From here on, any run that finishes over budget logs a warning:
#   WARNING vapviz.budgets: vapviz budget exceeded for run <id>: cost_usd 0.08 > 0.05 (+60%)
```

Do something custom on a violation by passing `on_alert` — page someone, post to Slack, raise, etc.:

```python
def on_over_budget(report):
    print(f"OVER BUDGET: {report.run_id}")
    for v in report.violations:
        print(f"  {v.metric}: {v.actual} > {v.limit}  (+{v.pct_over:.0f}%)")

enable_budget_alerts(Budget(max_cost_usd=0.05), on_alert=on_over_budget)
```

Or use a **built-in channel** — a webhook, a Slack incoming webhook, or an OpenTelemetry span — and
fan out to several at once by passing a list. HTTP delivery runs on a background thread and is
best-effort, so a flaky endpoint never slows or breaks the traced run:

```python
from vapviz.budgets import enable_budget_alerts, webhook_alert, slack_alert, otel_alert

enable_budget_alerts(
    Budget(max_cost_usd=0.05, max_duration_ms=5000),
    on_alert=[
        slack_alert("https://hooks.slack.com/services/…"),  # formatted Slack message
        webhook_alert("https://my-svc/alerts"),             # POSTs the BudgetReport as JSON
        otel_alert(),                                       # emits a vapviz.budget_exceeded span
    ],
)
```

Check a single run on demand (no alerting), or from any language via the REST API:

```python
from vapviz.budgets import Budget, check_budget

report = check_budget(store.get_graph(run_id), Budget(max_cost_usd=0.02, max_duration_ms=3000))
print(report.status)        # "ok" or "exceeded"
```

```bash
curl "http://localhost:8001/runs/{run_id}/budget?max_cost_usd=0.02&max_duration_ms=3000"
```

> **Try it with no API key:** `python examples/budgets_demo.py` runs one agent within budget and one
> over it, so you can watch the alert fire.

---

## 24. Agent Evals & Scoring

Budgets catch runs that are *too expensive or slow*. **Evals** go further: they assert a run did the
*right thing* — turning vapviz into a regression-testing tool for your agents. Trace a run, then check it
against a list of assertions and get a pass/fail with a score.

```python
import vapviz
from vapviz.evals import eval_run, max_cost, max_latency, no_errors, output_contains

with vapviz.trace("support agent") as run:
    answer_support_ticket("How do I reset my password?")    # your agent

result = eval_run(run, [
    max_cost(0.02),
    max_latency(3.0),
    no_errors(),
    output_contains("reset password"),
])

print(result.summary())
assert result.passed          # <- drop this straight into pytest / CI
```

`result.summary()` prints a per-check report:

```
PASSED (100%)
  PASS  max_cost<=$0.02 — cost $0.0013 (limit $0.02)
  PASS  max_latency<=3.0s — 51 ms (limit 3000 ms)
  PASS  no_errors — no error nodes
  PASS  output_contains('reset password') — found in node 'answer'
```

**Built-in checks:** `max_cost`, `max_latency`, `max_tokens`, `no_errors`, `output_contains`. Each
check produces a 0–1 score; `result.score` is their mean and `result.passed` is true only if every
check passed.

**Your own checks** — `custom` for a quick predicate, `judge` for an LLM-as-judge (you supply the
scoring function, so vapviz stays provider-agnostic):

```python
from vapviz.evals import custom, judge

eval_run(run, [
    custom("two_tool_calls", lambda g: sum(n.kind.value == "tool" for n in g.nodes) == 2),
    judge("helpfulness", my_llm_scorer),   # returns (passed, detail, score)
])
```

**Over HTTP / from another language** — declarative check specs via `POST /runs/{id}/eval`:

```bash
curl -X POST http://localhost:8001/runs/{run_id}/eval \
  -H "Content-Type: application/json" \
  -d '[{"type":"max_cost","value":0.02},{"type":"output_contains","value":"reset"}]'
```

> **Try it with no API key:** `python examples/evals_demo.py` traces a fake support agent and asserts
> five checks against it — the exact shape you'd use in a test.

---

## 25. Search & Tagging

Once you've accumulated a lot of runs, two features make them navigable: **search** (find runs by
their contents) and **tags** (organise runs with labels).

**Search** in the sidebar box matches your query against run labels *and* every node's input/output —
so searching `paris` finds runs whose tools or LLM calls mention Paris, not just runs named "Paris".
Over the API you can also filter structurally:

```bash
curl "http://localhost:8001/search?q=paris"                       # content search
curl "http://localhost:8001/search?tool=search_web&status=error"  # failed runs that used a tool
curl "http://localhost:8001/search?tag=prod"                      # runs tagged prod
```

**Tags** are persistent per-run labels. In the UI, select a run and use the **+ tag** editor in the
header (remove a tag with its **×**); each run shows its tags as chips in the sidebar — click a chip
to filter the list to that tag. From code or another language:

```bash
curl -X PUT http://localhost:8001/runs/{run_id}/tags \
  -H "Content-Type: application/json" -d '{"tags": ["prod", "v2-prompt"]}'
```

When the server runs with `--db vapviz.db`, tags persist across restarts.

> **Tip:** tag your baseline runs (e.g. `baseline`) and your experiments (`v2-prompt`), then use the
> [comparison view](#18-comparing-runs) to diff one against the other.

---

## 26. Trace Replay

A finished graph shows you *what* happened; **replay** shows you the *order* it happened in. Select a
run and click **Replay** in the run header — a scrubber appears beneath the graph.

- **Play / pause** steps through the run's events on a timer; the graph fills in node by node, exactly
  as the agent executed.
- **Step** (‹ ›) moves one event at a time — handy for understanding a specific branch or a retry.
- **Drag the slider** to jump to any point; the graph shows the run "as of" that event.
- **×** exits replay and returns to the full graph.

This is especially useful for deep agent runs (a long ReAct loop, a multi-agent conversation, a RAG
pipeline) where the final graph is dense — replay untangles the sequence. It's entirely client-side
and reads the events already streamed for the run, so it works on live and historical runs alike.

---

## 27. Theater & the Office Building

Where the graph is the analytical view, the **Theater** is the *watchable* one — it turns a run into a
little pixel "office". Select a run and open the **Theater** tab (it's available in both Simple and
Technical modes).

- Each agent is a **hand-drawn pixel worker**, recolored deterministically from its name (same
  name → same hair/shirt/skin, every run), with its **name floating overhead** — that's what
  identifies who's who. Every agent has its own **home desk**.
- A character **walks to the LLM desk** when one of its model calls is running, and to the tool
  station that matches the tool's name — **SEARCH** shelves, **FETCH** racks, **DATA** cabinet or
  **PRINT** table. The active station glows and a speech bubble says what the agent is doing
  ("phoning the API", "querying the DB"). Idle or finished agents sit at their desk; an errored
  agent says it **hit a snag**.
- It's driven by the same events as everything else, so it animates **live** as a run executes, and a
  finished run can be **replayed** with the bar at the bottom (open static, press play, or scrub).

Multi-agent runs are where it shines — a CrewAI crew shows `Researcher` and `Writer`; a LangGraph
supervisor shows `supervisor` + its workers — so you can see which agent is doing what.

### The Office Building

Click the **🎭 masks icon** at the top of the sidebar for the **Office building**: the control-room
view where every **app** (grouping key: `app_id ?? label` — see the `app_id` tip in §3) owns a
miniature office room. Re-running an app lights **the same room** back up (the ×N badge counts its
runs) and each agent keeps its desk. Floors hold **six rooms** (two rows of three around a Walk
Way); when the top floor fills, the app that's been there longest moves down a floor — still
live — and a coworker walks the move: across the Walk Way, into the Stairs, out of the Door one
floor below. An app whose latest run **failed** keeps its room — it just **turns red** — while
its agents head up to the shared **Lounge** (the break room at the top-right) to wait: click the
app's lounge card to inspect the failed run, or **Dismiss** it until that app runs again. The
lobby board at the base tallies apps working, agents in the lounge, and spend today. Click any
room to drop into that app's current run; the sidebar lists the same apps, and expanding one
shows its full run history for inspection and replay.

Both views are pure UI over the event stream — the only instrumentation that helps is passing a
stable `app_id` to `trace()`. See the [UI Guide](UI_GUIDE.md) for the non-technical walkthrough.

---

## 28. What's Next?

You now know everything you need to instrument real agents. Here are pointers for going deeper:

### Run the bundled examples

```bash
# No API key needed:
python examples/simple_demo.py
python examples/error_handling_demo.py
python examples/cost_tracking_demo.py
python examples/remote_ingest_demo.py
python examples/pydantic_ai_demo.py   # uses TestModel — requires pip install "vapviz[pydantic-ai]"
python examples/llamaindex_demo.py    # uses MockLLM — requires pip install "vapviz[llamaindex]"
python examples/autogen_demo.py       # offline agents — requires pip install "vapviz[autogen]"
python examples/otel_demo.py          # console OTel export — requires pip install "vapviz[otel]"
python examples/budgets_demo.py       # cost/latency budget alerting
python examples/evals_demo.py         # agent evals / assertions

# Requires an API key:
python examples/openai_demo.py
python examples/anthropic_demo.py
python examples/langgraph_demo.py
python examples/crewai_demo.py      # requires pip install "vapviz[crewai]"
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
import vapviz

def my_function(data: dict) -> dict:
    # existing code, untouched
    return {"result": data}

with vapviz.trace("Wrapped Agent") as run:
    with run.step("my_function", kind="tool") as step:
        step.set_input(data)
        result = my_function(data)
        step.set_output(result)
```

**Pattern 2 — trace a long-running background job:**

```python
import threading
import vapviz

vapviz.configure(db="vapviz.db")

def background_job():
    with vapviz.trace("Background Job") as run:
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
import asyncio, vapviz

vapviz.configure(db="vapviz.db")

async def agent(name: str, delay: float):
    async with vapviz.atrace(name) as run:
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
[GitHub](https://github.com/kochrisdev/vapviz).*
