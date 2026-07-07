# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

vapviz ("Visualization Agentic Process") is a self-hostable tracer/visualizer for AI agent pipelines: a Python library + FastAPI server that records agent activity as a stream of events, and a React UI that draws those events as a live, interactive graph. It is the lightweight, local-first cousin of LangSmith / Langfuse / Arize Phoenix.

> Naming: the distribution, import package, and CLI are all `vapviz` (`pip install vapviz`, `import vapviz`, `vapviz serve`). The PyPI name `vap` was taken, hence the rename — but the public `Vap*` class names (`VapEvent`, `VapCallbackHandler`, `VapPydanticAI`, …) are unchanged.

## Commands

The Python package is developed in a virtualenv at `.venv/`. Prefer absolute or `.venv/bin/`-prefixed commands.

```bash
# Install (Python) — from repo root
.venv/bin/python -m pip install -e ".[dev]"     # core + tests + openai/anthropic/langchain/pydantic-ai/llamaindex/otel
.venv/bin/python -m pip install -e ".[all]"     # also installs crewai + autogen (heavy; un-skips those tests)

# Install (UI)
cd ui && npm install

# Tests / the gate
make check                                                   # THE GATE: fast unit tests + UI typecheck (also blocks commits)
.venv/bin/python -m pytest -m "not integration"              # fast/free Python unit tests (313 pass)
.venv/bin/python -m pytest                                   # everything incl. real-LLM integration (319 collected)
.venv/bin/python -m pytest tests/test_tracer.py::TestNesting::test_auto_parent   # one test
cd ui && npm test                                            # UI unit tests (vitest) — incl. dual-reducer parity
# tests/*_integration.py are auto-marked `integration` (tests/conftest.py): they hit OpenRouter
# (PAID) via scratch/.env and skip when the dep/key is absent. EXCLUDED from the gate; run them
# with `make test-all` / `make check-all`.

# Run the app (development)
.venv/bin/python run_dev.py            # backend on :8001 + a demo run, in-memory store
vapviz serve --db vapviz.db            # CLI server, persistent SQLite (omit --db for in-memory)
cd ui && npm run dev                   # UI on :5173 (Vite proxies /runs -> :8001)

# Build / production
cd ui && npm run build                                  # tsc + vite build -> ui/dist
vapviz serve --db vapviz.db --static-dir ui/dist        # single process serves API + UI on :8001
docker compose up                                       # same, containerized, on :8001
```

There are **no configured linters or formatters** (no ruff/black/eslint/prettier) — don't look for them.

## Working rules (read before creating files or finishing work)

- **The gate = `make check`** (`scripts/check.sh`: fast Python unit tests + UI `tsc --noEmit` + vitest, which includes the dual-reducer parity test). A change is "done" only when it passes. It's wired as a **commit hook** (`scripts/commit-gate.sh`, registered in `.claude/settings.json`) that **blocks `git commit` on failure** — override only with `git commit --no-verify`. When wrapping up, run **`/ship`** (full build + doc-surface check + review for big changes).
- **Real-LLM tests cost money.** `tests/*_integration.py` are auto-marked `integration` and hit OpenRouter via `scratch/.env`; they're excluded from the gate. Run explicitly via `make test-all` / `make check-all`.
- **Where new files go:**

  | Writing… | Goes in… | Tracked? |
  |---|---|---|
  | library/app code | `vapviz/` or `ui/src/` | yes |
  | a real test | `tests/` | yes |
  | public doc | `docs/` or root (`README`/`CHANGELOG`) | yes |
  | private working note | `docs/notes/` | no (gitignored) |
  | throwaway script / db / experiment | `scratch/` | no (gitignored) |

- **Public vs local boundary:** shared ignore rules live in the committed `.gitignore` (`scratch/`, `docs/notes/`, build artifacts, `.claude/settings.local.json`). `.git/info/exclude` is ONLY for this-clone-only paths (`crewai-agent/`). **`CLAUDE.md` and `.claude/settings.json` ARE committed (shared);** `.claude/settings.local.json` and `scratch/.env` (OpenRouter key) are not — never print or commit the key.
- **Done includes docs.** A change isn't done until the doc surface it touches is updated in the same change: README, CHANGELOG, `docs/*`, Dockerfile/compose, `pyproject.toml` version, test-count references, `ASSETS.md`, CLAUDE.md. `/ship` lists this; the `doc-surface-verifier` subagent checks it for big changes.
- **Knowledge ladder:** a rule that bites twice stops being prose and becomes a test/type/lint. Keep CLAUDE.md a lean *map*, not a manual.

## Architecture — the big picture

**Everything is an event; the graph is derived, never stored directly.** Each agent action emits a `VapEvent` (`vapviz/events.py`). Nodes are represented by a *start* event and an *end* event (`agent_start`/`agent_end`, `step_start`/`step_end`, `tool_call`/`tool_result`, `llm_call`/`llm_response`, plus `error`). A run is an ordered list of these; the visual graph is rebuilt by replaying them.

The data pipeline (one direction):

```
agent code → Tracer (vapviz/tracer.py) → RunStore (vapviz/store.py) → FastAPI+SSE (vapviz/server.py) → React UI (ui/src/)
```

- **Tracer (`vapviz/tracer.py`):** `trace`/`step` (sync) and `atrace`/`astep` (async) are context managers. Parent/child nesting is automatic via a single `contextvars.ContextVar` (`_current_step`): on enter a node reads it (→ its parent) then sets itself; on exit it restores the previous value via the saved token. `RunContext` is the root (agent) node; `StepContext` is every other node and owns `_emit()`. Exceptions emit an `error` event then re-raise; `finally` always resets the ContextVar.
- **Store (`vapviz/store.py`):** `RunStore` ABC with `MemoryStore` (default) and `SqliteStore` (`vapviz/backends/sqlite.py`, WAL mode, replays the DB into an in-memory graph cache on startup). Both keep the raw event log **and** a derived `RunGraph`, built by the shared pure function `_apply_event_to_graph`. Cross-thread delivery to SSE: a `threading.Lock` guards state, one `asyncio.Queue` per subscriber, and `loop.call_soon_threadsafe(q.put_nowait, event)` bridges the tracer thread to the asyncio loop (the loop is injected at server startup in the FastAPI `lifespan`).
- **Server (`vapviz/server.py`):** thin façade over the store. The SSE endpoint `GET /runs/{id}/events` is two-phase: replay history, then stream live from the queue (with periodic `ping`). Route-order gotcha: `/runs/compare` is declared before `/runs/{id}` so "compare" isn't parsed as a run id. **Footgun (M3, open):** `create_app()` binds `default_store` at construction, so the prebuilt `vapviz.app` does **not** follow a later `configure(db=...)` — pass the store explicitly (`vapviz.create_app(store=vapviz.store.default_store)`) or configure before building.
- **Integrations (`vapviz/integrations/`):** three patterns. (A) monkey-patch the client method — `patch_openai`, `patch_anthropic` — relying on the `_current_step` ContextVar; no-op when no trace is active. (B) callback/handler — `VapCallbackHandler` (LangChain/LangGraph), `VapLlamaIndex` (instrumentation dispatcher), `VapPydanticAI` / `VapAutoGen` (method wrappers). (C) event-bus listener — `VapCrewAIListener`, which runs on CrewAI's background threads with **no** ContextVar, so it tracks parents via explicit dicts guarded by a `threading.Lock`. All ultimately call `StepContext._emit(...)`. `otel.py` is export-only (runs → OTLP spans).
- **Cost (`vapviz/cost.py`):** pure pricing table with longest-prefix matching (`gpt-4o-2025-xx` → `gpt-4o`; strips provider prefixes like `openai/`). Integrations call `calculate_cost(...)` and attach `cost_usd` to LLM nodes' output; `_total_cost` (store.py) sums it over **LLM-kind nodes only** (PA1 fix — parents that also carry an aggregate cost are excluded) into `total_cost_usd`.

**React UI mirrors the backend.** `ui/src/store/runStore.ts` (Zustand) re-implements the same start/end graph-building as `_apply_event_to_graph`. `ui/src/hooks/useRunStream.ts` opens an `EventSource` per selected run; `RunList` separately polls `GET /runs` every ~3s. `ui/src/components/AgentGraph.tsx` lays the DAG out with dagre and renders it with ReactFlow (`@xyflow/react`); node color = kind, border = status.

## Conventions and traps that span multiple files

- **The "events → graph" reduction is implemented twice and must stay in sync:** Python `_apply_event_to_graph` (`vapviz/store.py`) and TypeScript `applyEventToGraph` (`ui/src/store/runStore.ts`). **A cross-impl parity test guards this** (`tests/test_reducer_parity.py` ↔ `ui/src/store/runStore.parity.test.ts`, shared fixtures in `tests/fixtures/reducer_parity/`): both reducers replay the same events and must produce the same graph, so drift fails the gate. The event schema is also dual: `vapviz/events.py` (Pydantic) and `ui/src/types/events.ts` (TS). The per-run cost reduce is also dual (`_total_cost` ↔ `runStore.ts` — both LLM-kind only). **Adding/changing an event type, node kind, or cost logic means editing all the relevant ones** — plus `KIND_BG` in `AgentGraph.tsx` and the `_start_event`/`_end_event` maps in `tracer.py`. See the Extension Guide in `docs/ARCHITECTURE.md`.
- **`vapviz.configure(db=...)` ordering:** it swaps the module-level `default_store`. The module-level `trace`/`atrace` read `default_store` dynamically (so they pick up the change), but the pre-built `vapviz.app` captured its store at import (see M3 above). For an in-process persistent server, call `vapviz.configure(db=...)` **before** building the app, then build with `vapviz.create_app()`. See `examples/crewai_demo.py`.
- **Live updates require sharing one store in one process.** A separate process that only writes to the same SQLite file is **not** seen live by a running server (the server loads the file once at startup; it sees those runs only after a restart). Live cross-process tracing must use HTTP remote ingest (`POST /runs/{id}/events`); see `examples/remote_ingest_demo.py`.
- **In-memory store loses everything on restart** — use SQLite (`--db` / `configure(db=...)`) to persist.
- **`state_update` event type exists but is currently inert** in both graph builders (it appears in the timeline but doesn't mutate the graph).
- **Ports:** backend `8001`, UI dev server `5173`. CORS is wide-open (`allow_origins=["*"]`) — intended for local use, not hardened for public exposure.

## Session continuity

Personal (gitignored) notes live in `docs/notes/`: dated handoffs in **`docs/notes/handoffs/`** (`HANDOFF-YYYY-MM-DD.md`, one per session — **read the newest first in a new session**), **SESSION-FINDINGS.md** (the bug work order with repro/fix/verify steps + FIXED stamps), **FLAGGED.md** (parked/deferred items — **read in a new session**; some say "remind Nick when X ships"), **UI-ROADMAP.md** (the legible/watchable UI plan — Phase 4a Office Building DONE; 4b art left), REFERENCE.md (plain-English explainer), NEXT-SESSION-STARTER.md. Throwaway test scripts belong in `scratch/` (gitignored; `scratch/.env` holds the OpenRouter key — never print or commit it).

## Where things live

`vapviz/tracer.py` (Note-Taker) · `vapviz/store.py` + `vapviz/backends/sqlite.py` (storage) · `vapviz/server.py` (REST + SSE) · `vapviz/cli.py` · `vapviz/cost.py` · `vapviz/metrics.py` · `vapviz/budgets.py` · `vapviz/evals.py` · `vapviz/search.py` · `vapviz/summary.py` · `vapviz/integrations/` (openai_sdk, anthropic_sdk, langchain, crewai_listener, pydantic_ai, llamaindex, autogen, otel) · `ui/src/` (App, components/, store/runStore.ts, hooks/useRunStream.ts, types/events.ts) · `examples/` (runnable demos, several need no API key) · `docs/ARCHITECTURE.md` (deep internals + Extension Guide), `docs/TUTORIAL.md`, `docs/DEVELOPER_REFERENCE.md`, `docs/DEPLOYMENT.md`, `docs/UI_GUIDE.md`.

**Theater / Office Building (UI Phases 3–4b, shipped):** both views render the **sprite office** — hand-authored 12×16 "art-as-data" sprites (palette + char-grid, rasterized to canvas, recolored per agent — zero AI, zero third-party pack; authoring rules in the **`pixel-art-set`** skill, reference prototype `scratch/sprite-proto/`, **room layout LOCKED 2026-07-01**): `ui/src/lib/sprites.ts` (worker + recolor + rasterizer) · `ui/src/lib/officeArt.ts` (furniture + the locked layout; provenance in `ui/src/lib/ASSETS.md`) · `ui/src/lib/officeScene.ts` (pure tool→station keyword routing + per-agent call attribution + dialogue, unit-tested) · `ui/src/components/OfficeStage.tsx` (canvas renderer, duration-adaptive walk speed; a **`compact` prop** drops station chips + speech bubbles and floors the name-tag size for the Building's small room tiles; **desks assigned by sorted agent name** → seats stable across re-runs). `ui/src/lib/theater.ts` (pure `buildScene` cast/state/desk reduction; owns `AvatarState`) still drives it. The **Office Building** (`BuildingView.tsx`, `view:"floor"`, polls `/runs`+`/graph`) re-keys the monitor from runs to **apps** (grouping key `app_id ?? label`): app = sticky room, 6 rooms/floor, earliest app descends when the top floor fills. **4b — the visual building (2026-07-07):** CSS shell (roof/`VAPVIZ` sign/floor slabs/**lobby directory board**), floors as a **2×3 grid around a Walk Way** + a **Door/Stairs column**; a failed app's room **stays in place (red)** and the app surfaces to the shared **Lounge** (top floor's east side; `ui/src/lib/loungeArt.ts` break-room diorama + `LoungeStage.tsx`, one distinct idle activity per waiting agent; inspect + dismiss on lounge cards; dismissed failed run ids in `localStorage`, pruned on load; solid east wall + windows below). Transitions ride the **walk overlay** (`ui/src/lib/walkOverlay.ts`, a sprite canvas above the rooms): descent = Walk Way → Stairs *vanish* → Door below → room; failure = room → lounge; FLIP glide is the fallback; reduced-motion snaps everything. Placement is the pure unit-tested reducer `ui/src/lib/building.ts` (`buildBuilding`; its `appKey`/`groupApps` are shared with the **app-grouped sidebar** `RunList.tsx` so floor and sidebar never disagree). Retired: the interim SVG stage (`avatar.ts` + `AgentStage.tsx`, 2026-07-03) and the run-keyed `FloorView.tsx` (2026-07-06). **UI-only** — none of these are part of the dual-logic rule (they re-present the already-derived graph). The two backend touches are both **additive metadata**: the `langgraph_node` marker in `vapviz/integrations/langchain.py`, and **`trace(..., app_id=…)`** (rides in `agent_start` data → `RunSummary.app_id` / `RunGraph.app_id`, set at run creation — deliberately NOT in `_apply_event_to_graph`, so the parity fixtures are untouched).
