# Changelog

All notable changes to vapviz are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For the detailed per-release notes (APIs, fixes, internals), see the
[Developer Reference changelog](docs/DEVELOPER_REFERENCE.md#changelog).

## [Unreleased]

### Changed
- **Theater: the cozy sprite office** — the Theater tab's stage is rebuilt on hand-authored
  12×16 "art-as-data" pixel sprites (palette + char-grid data rasterized to canvas and
  recolored per agent — owned art, zero AI, zero third-party packs). One shared office with
  five stations — the LLM desk plus SEARCH shelves, FETCH server racks, DATA cabinet and a
  PRINT table — where tool calls are routed to a station by keyword-matching the tool's
  name (unknown tools spread deterministically). Agents walk between their own home desk
  and stations (walk speed adapts so they arrive before the call finishes), the active
  station glows, and a playful speech bubble says what each agent is doing ("phoning the
  API", "querying the DB", …). New: `ui/src/lib/{sprites,officeArt,officeScene}.ts` and
  `ui/src/components/OfficeStage.tsx`. The Live Floor's run-zones tile the **same engine in
  a `compact` mode** (station chips + speech bubbles dropped at zone scale, name tags keep a
  legible minimum size; glow / walk / ✓ ! cues carry the signal), so both views share one
  renderer, one art set, and one per-agent colorway — the interim SVG stage
  (`AgentStage.tsx`, `lib/avatar.ts`) is retired. Stage polish for the tiled Floor: canvas
  text widths are cached, a stage scrolled out of view pauses its animation loop entirely
  (browsers only pause hidden *tabs*), and casts larger than 6 wrap their home desks into
  an overflow back row instead of overlapping (additive — the locked furniture layout is
  untouched).

### Added
- **Theater view** — a watchable, game-like per-run view (UI). Each agent is a deterministic
  pixel character (built from its name) that walks to an LLM/tool desk while it's working, with
  its name overhead; available in both Simple and Technical modes and driven by the existing
  replay/live pipeline. New: `ui/src/lib/theater.ts`, `ui/src/components/TheaterView.tsx`.
- **Live floor** — a centralized monitor (`ui/src/components/FloorView.tsx`, sidebar 🎭 icon)
  showing every active/recent run as a soft labeled zone on one office floor, each a live
  compact sprite office, so you can watch many runs' agents work at once. Polls existing
  endpoints; no backend change.
- LangChain integration now carries the `langgraph_node` name through to node data (additive
  metadata), so multi-agent LangGraph runs show their real cast (supervisor / workers) in Theater.

## [1.1.0]

### Added
- **Budget alert channels** — built-in sinks for `enable_budget_alerts`: `webhook_alert(url)`,
  `slack_alert(webhook_url)`, and `otel_alert()` (emits a `vapviz.budget_exceeded` span).
- `on_alert` now accepts a **list** of channels (fan-out), not just one callback. HTTP delivery is
  non-blocking (background thread) and best-effort — one failing channel never breaks the run or the
  others. Exported as `vapviz.webhook_alert` / `slack_alert` / `otel_alert`.

## [1.0.1]

### Changed
- **Renamed the project to `vapviz`.** The PyPI name `vap` was already taken by an unrelated
  project, so the distribution, the import package, and the CLI are all `vapviz` now:
  `pip install vapviz`, `import vapviz`, `vapviz serve`. (The `Vap*` public class names — `VapEvent`,
  `VapPydanticAI`, etc. — are unchanged.)

## [1.0.0]

First stable release. The public API now follows [Semantic Versioning](https://semver.org/) — see
the [Versioning & Stability](README.md#versioning--stability) section for the tracked surface.

### Added
- The published wheel bundles the built React UI, so `pip install vapviz && vapviz serve` serves the full UI with no Node build (`vapviz serve` auto-detects the bundled UI; `--static-dir` still overrides).
- Root `CHANGELOG.md` and a documented public-API stability policy.
- Anthropic integration tests (`tests/test_anthropic_patch.py`), closing the last integration coverage gap (269 tests).

### Changed
- Promoted to `Development Status :: 5 - Production/Stable`.

This release adds no new tracing/integration features beyond 0.15.0 — it marks the project as stable. The capability set: 7 framework integrations (Anthropic, OpenAI, LangChain, CrewAI, Pydantic AI, LlamaIndex, AutoGen), OpenTelemetry export, an analytics dashboard, cost/latency budgets with alerting, agent evals & scoring, run search & tagging, and trace replay.

## [0.15.0]
### Added
- Trace replay / time-travel: a UI scrubber (`ReplayBar`) that replays a run event-by-event; the graph fills in node by node.

## [0.14.0]
### Added
- Run search (`GET /search`) across run labels and node inputs/outputs, with `status` / `kind` / `tool` / `tag` filters.
- Persistent per-run tags (`GET`/`PUT /runs/{id}/tags`, stored in SQLite); UI search box, tag chips, and inline tag editor.

## [0.13.0]
### Added
- Agent evals & scoring: `eval_run(run, [checks…])` → `EvalResult` with built-in `max_cost` / `max_latency` / `max_tokens` / `no_errors` / `output_contains` plus `custom` and `judge` hooks; declarative `POST /runs/{id}/eval`.

## [0.12.0]
### Added
- Cost & latency budgets: `Budget`, `check_budget()`, `enable_budget_alerts(budget, on_alert=…)`, and `GET /runs/{id}/budget`.

## [0.11.0]
### Added
- AutoGen (AG2) integration: `VapAutoGen` traces `ConversableAgent` conversations (chat, agent turns, tool calls).

## [0.10.0]
### Added
- LlamaIndex integration: `VapLlamaIndex` span handler traces query engines, retrievers, embeddings, and LLM calls.

## [0.9.0]
### Added
- OpenTelemetry export: `enable_otel_export(...)` mirrors each run into OTLP spans (Jaeger / Grafana Tempo / Datadog).

## [0.8.0]
### Added
- Pydantic AI integration: `VapPydanticAI` traces `Agent.run` / `run_sync` (model requests + tool calls).
- PyPI-ready packaging (license, classifiers, URLs), MIT `LICENSE`, GitHub Actions CI + release workflows, and `CONTRIBUTING.md`.

## [0.7.0]
### Added
- Analytics dashboard + `GET /metrics`: cross-run cost, tokens, success rate, per-model breakdown, and cost-over-time.

## [0.6.0]
### Added
- CrewAI integration: `VapCrewAIListener` traces Crews, Tasks, Agent executions, Tool calls, and LLM round-trips.

## [0.5.0]
### Added
- Run comparison (side-by-side diff) and export (JSON download + PNG capture).

## [0.4.0]
### Added
- Token cost tracking: pricing table, `calculate_cost()`, per-node cost overlay, per-run totals.

## [0.3.0]
### Added
- OpenAI SDK and LangChain / LangGraph integrations.

## [0.2.0]
### Added
- Async tracer (`atrace` / `astep`), SQLite persistence, the `vapviz serve` CLI.

## [0.1.0]
### Added
- Initial release: sync tracer, in-memory store, FastAPI + SSE server, ReactFlow UI, Anthropic SDK integration.

[Unreleased]: https://github.com/kochrisdev/vapviz/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/kochrisdev/vapviz/releases/tag/v1.1.0
[1.0.1]: https://github.com/kochrisdev/vapviz/releases/tag/v1.0.1
[1.0.0]: https://github.com/kochrisdev/vapviz/releases/tag/v1.0.0
[0.15.0]: https://github.com/kochrisdev/vapviz/releases/tag/v0.15.0
