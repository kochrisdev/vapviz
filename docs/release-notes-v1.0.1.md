# vapviz 1.0.1 🎉

**Visualization Agentic Process** — trace and visualize AI agent pipelines in real time.

This is the **first stable release**. Instrument your agent with a single context manager and watch
every step, tool call, and LLM invocation appear instantly as a live, interactive graph in the
browser — with inputs, outputs, durations, token usage, cost, and errors.

```bash
pip install vapviz
vapviz serve --db vapviz.db        # UI + API at http://localhost:8001  (UI is bundled — no Node build)
```

```python
import vapviz

with vapviz.trace("My agent") as run:
    with run.step("search", kind="tool") as step:
        step.set_input({"query": "..."})
        step.set_output({"results": 3})
```

## Highlights

- **Zero-boilerplate tracing** — sync & async (`trace` / `atrace`), automatic parent nesting via `ContextVar`, live SSE streaming to a ReactFlow graph.
- **7 framework integrations** — Anthropic, OpenAI, LangChain/LangGraph, CrewAI, Pydantic AI, LlamaIndex, and AutoGen (AG2). Each auto-captures agents, tools, and LLM calls with token usage and USD cost.
- **OpenTelemetry export** — mirror every run into OTLP spans for Jaeger / Grafana Tempo / Datadog (`enable_otel_export(...)`).
- **Analytics dashboard** — cross-run cost, tokens, success rate, per-model breakdown, and cost-over-time (`GET /metrics`).
- **Cost & latency budgets** — flag and alert on runs that exceed cost / duration / token limits (`enable_budget_alerts(...)`).
- **Agent evals & scoring** — assert cost / latency / output / custom / LLM-judge checks; regression-test agents in pytest or CI (`eval_run(run, [checks…])`).
- **Search & tagging** — full-text search across run contents plus persistent per-run tags.
- **Trace replay / time-travel** — scrub a run event-by-event and watch the graph build up as it happened.
- **Persistence & export** — SQLite store (WAL), run comparison, JSON/PNG export, and HTTP remote ingest from any language.

## Stability

vapviz now follows [Semantic Versioning](https://semver.org/). The public, stability-tracked surface
(top-level `vapviz` exports, the `vapviz.integrations.*` listeners, the `vapviz serve` CLI, and the REST + SSE
schema) is documented in the [Versioning & Stability](https://github.com/kochrisdev/vapviz#versioning--stability)
section of the README.

## Quality

- **269 tests** covering the tracer, stores, server, metrics, budgets, evals, search, and every integration.
- **CI** on Python 3.11 / 3.12 / 3.13, plus UI type-check + build and a packaging check.
- MIT licensed. Every demo under `examples/` runs **without an API key**.

## Install options

```bash
pip install vapviz                 # core + bundled UI
pip install "vapviz[all]"          # + all integrations and OpenTelemetry export
pip install "vapviz[crewai]"       # or pick one: anthropic / openai / langchain / crewai /
                                #              pydantic-ai / llamaindex / autogen / otel
```

## Getting started

- 📖 [Tutorial](https://github.com/kochrisdev/vapviz/blob/main/docs/TUTORIAL.md) — step-by-step from install to a fully instrumented agent
- 📚 [Developer Reference](https://github.com/kochrisdev/vapviz/blob/main/docs/DEVELOPER_REFERENCE.md) — full Python API, CLI, REST, SSE, TypeScript types
- 🏗️ [Architecture](https://github.com/kochrisdev/vapviz/blob/main/docs/ARCHITECTURE.md) · 🚀 [Deployment](https://github.com/kochrisdev/vapviz/blob/main/docs/DEPLOYMENT.md)

**Full changelog:** https://github.com/kochrisdev/vapviz/blob/main/CHANGELOG.md
