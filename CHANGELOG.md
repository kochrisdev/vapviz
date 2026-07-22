# Changelog

All notable changes to vapviz are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For the detailed per-release notes (APIs, fixes, internals), see the
[Developer Reference changelog](docs/DEVELOPER_REFERENCE.md#changelog).

## [Unreleased]

_Nothing yet._

## [1.5.0] - 2026-07-21

### Added
- **Agent control Layer 2b — two-way conversation.** Layer 2 let you send a message *into* a
  running agent; now the agent can talk *back*. Two new calls (sync + async):
  - **`vapviz.ask(prompt, timeout=None)`** / **`aask(...)`** — post a question the user sees and
    block for their reply. The prompt shows in a new docked **chat panel** (Theater tab) and the
    reply box lights up; the reply arrives on the same mailbox `take_input()` uses, so **Stop
    still interrupts** a waiting agent (`VapStopped`). Returns the reply (or `None` on timeout).
  - **`vapviz.say(text)`** / **`asay(...)`** — post a statement the user sees, without blocking
    (e.g. confirm you acted on a steer). Fire-and-forget.

  Together with `take_input()` (receive an unprompted steer) this is a full back-and-forth. Both
  new calls raise `RuntimeError` outside an active trace.
- **Docked conversation panel (Theater tab).** A chat surface beside the office scene renders the
  agent ↔ user turns as bubbles (agent left, you right) and hosts the reply box. It reads the
  run's events, so it works live *and* as a **read-only transcript for a completed run**. The
  message box moved here out of the control bar (one input surface, not two); the bar stays
  lifecycle-only (Pause/Resume/Stop).
- **"💬 needs input" nudge on Building rooms.** A running room whose agent is parked in
  `ask()`/`take_input()` flags a badge in the Office Building overview — click through to Theater
  to answer. (Reuses the per-room control poll; no new request.)
- **`GET /runs/{id}/control`** gains a **`question`** field — the prompt `ask()` is currently
  displaying (echoed as text, unlike the injected message, since it's the agent's own words meant
  to be shown; `null` when the agent isn't asking).

### Internal
- The conversation turns **reuse the inert `control` event** with new `action` values `ask` /
  `say` (like Layer 2's `input`) — **no new event type, no reducer/dual-logic change.** New parity
  fixture `control_conversation_inert.json` pins that a full ask→input→say exchange is ignored
  identically by both reducers.
- The Theater's control bar and conversation panel now share **one** control-latch poll
  (`useControlLatch`) instead of two.
- Tests: **390** fast Python unit tests (was 377), **64** UI (vitest, was 57).

## [1.4.0] - 2026-07-21

### Added
- **Agent control Layer 2 — inject a message into a running agent.** Building on Layer 1's
  Pause/Resume/Stop, a live in-process run can now receive a short text message from the UI.
  The agent picks it up with **`vapviz.take_input(timeout=None)`** (and the async
  **`vapviz.atake_input(...)`**): by default it blocks at that point in the code until the UI
  sends a message and returns the string — the "agent asks, then waits for a human" pattern.
  Pass `timeout=0` for a non-blocking peek at the mailbox, or `timeout=N` to wait up to `N`
  seconds and give up with `None`. While waiting, the UI shows "agent is waiting for your
  input" — and **Stop still interrupts a waiting agent** (raises `vapviz.VapStopped`, same as
  any other checkpoint). Calling either function outside an active trace raises `RuntimeError`.
  Delivery is a new **`POST /runs/{id}/input`** endpoint (body `{"message": "<text>"}`; 404 on
  an unknown run, a no-op `{"ended": true}` on an already-ended one). The mailbox is
  **single-slot / last-write-wins** — sending a second message before the agent consumes the
  first overwrites it — and the UI marks a sent-but-unconsumed message as "queued" so an
  overwrite is never silent.
- **`vapviz.checkpoint()` / `vapviz.acheckpoint()`** — a manual control checkpoint you drop
  inside a long loop that has no natural per-iteration `step`/`astep`, so it stays
  pausable/stoppable exactly like a stepped loop (parks on Pause, raises `VapStopped` on Stop).
  Closes out the escape hatch Layer 1 deferred. Raises `RuntimeError` outside an active trace.
- **`GET /runs/{id}/control`** gains two read-only fields so the UI can render the waiting
  state from its existing ~1s poll, no second endpoint needed: `waiting_for_input` (the agent
  is currently parked in `take_input()`) and `pending_input` (a message is queued but not yet
  consumed). The message **text** itself is never echoed back by this endpoint — only whether
  one is pending.
- **The message shows up in the timeline for free.** Rather than a new event type, an injected
  message reuses the existing inert `control` event (`data.action="input"`, `data.message`),
  the same audit marker Layer 1 uses for pause/resume/stop — so it's ignored by both graph
  reducers with zero reducer changes (a new `control_input_inert.json` parity fixture pins
  this down). Logs renders it as `Message from user: "<text>"`.
- **Two UI ride-alongs.** The Theater office scene now visibly rests — dimmed/desaturated with
  a "⏸ Paused" or "💬 Waiting for your input" badge — while the agent is paused or blocked in
  `take_input()`. The Office Building's room tiles gain hover-revealed Pause/Resume/Stop
  buttons for a running app, so lifecycle control no longer requires opening Theater
  (message-sending stays Theater-only — the room tiles are too small for a text box).
- Try it with no API key: `python examples/input_demo.py`.

## [1.3.0]

### Added
- **Evals as a CI gate.** A declarative **eval suite** (`EvalSuite`, loaded from YAML/JSON) bundles
  the existing checks; `run_suite(suite, graphs)` returns a `SuiteReport`, and the new
  **`vapviz eval`** CLI turns a failing report into a **non-zero exit code** so agent regressions can
  fail a build.
- `vapviz eval --suite S` loads runs from a SQLite store (`--db`, with `--run-id` / `--label` /
  `--tag` / `--latest` filters), a single exported run (`--run`), or a directory (`--runs-dir`);
  `--json` and `--github-summary` (writes a Markdown table to `$GITHUB_STEP_SUMMARY`).
- A composite **`vapviz-eval` GitHub Action** (`action.yml`) that installs vapviz and runs the gate.
- New exports: `vapviz.EvalSuite` / `SuiteReport` / `RunEval` / `load_suite` / `load_runs` /
  `run_suite`; `examples/eval_suite.yaml` and `examples/evals_ci_demo.py`.

## [1.2.0] - 2026-07-20

### Added
- **Live run control — Pause / Resume / Stop (in-process).** vapviz gains its first return
  lane: while a run is live, an **Agent control** bar in the Theater tab (or
  `GET`/`POST /runs/{id}/control`) can pause, resume, or stop the agent. Control is
  **cooperative** — the tracer checks a per-run desired/acked latch at every `step`/`astep`
  entry and obeys there: pause parks the agent *between* steps (sync agents block their own
  thread, async agents yield to the event loop), stop raises the new `vapviz.VapStopped`
  inside the agent so its code genuinely unwinds and halts (catchable for a graceful
  shutdown). The UI shows the honest lag ("pausing…" until the agent actually parks). A
  user-stopped run ends with a **first-class `stopped` status** — neither a success nor a
  failure — rendered as a neutral ⏹ badge everywhere and excluded from the dashboard's
  success/error rates, and every action is recorded as an inert `control` event in the run's
  timeline ("Paused by user" in Logs). In-process agents only for this slice; remote-ingest
  agents can't see the server's latch yet. Try `python examples/control_demo.py` (no API key).

### Changed
- **Clicking a room in the Office Building now lands on the Theater tab** (was: Story), so
  the room you were watching opens straight onto its live office scene — where the new
  control bar also lives. Lounge cards still open the Story view for debugging a failure.
- **Pixel look, end to end — the app now lives in the office's world.** Square corners,
  chunky 2px borders, hard-offset "pixel-step" shadows, a faint checkerboard ground (the
  Building's yard tile), pixel scrollbars, and an all-pixel type system (self-hosted, OFL):
  **Silkscreen** for display chrome (headings, tabs, badges), **Pixelify Sans** for all
  reading text, **VT323** for code-shaped text (JSON, logs, durations). The **color tokens
  are now derived from the sprite office's own palette** so the chrome matches the Theater
  and Building scenes in both themes — dark is the office after hours (deep warm browns,
  cream text, amber accent), light is the office by day (wall-cream surfaces, wood borders,
  deep amber accent). The sidebar is topped by a VAPVIZ plate like the building's rooftop
  sign. Backgrounds stay plain (subtle tile only — no imagery).
- **The Simple/Technical mode toggle is gone — one adaptive UI for everyone.** Every run
  shows the Story, Theater, Graph, and Logs tabs; tags, export, and replay are always
  available. Depth is progressive instead of gated: runs open on the plain-language Story,
  and raw JSON sits behind the detail panel's "Show technical details" expander (for
  everyone now). The stored `vapviz-mode` preference is simply ignored.

### Fixed
- **`configure(db=...)` → `create_app()` no longer serves an empty store (M3).**
  `create_app()` used to freeze an import-time copy of the default store, so building an
  in-process server after `vapviz.configure(db=...)` silently served a blank in-memory
  store while the SQLite file grew — the UI showed zero runs. It now resolves the default
  store when called, matching the tracer's behavior, so configure-then-build just works
  (guarded by a regression test). Note the prebuilt `vapviz.app` is still constructed at
  import and cannot follow a later `configure` — build your own app with `create_app()`.
- **Dashboard's "cost by model" no longer splits one model into two rows.** The by-model
  breakdown grouped raw model strings, so `gpt-4o-mini` (CrewAI listener) and
  `openai/gpt-4o-mini` (patched OpenAI client) appeared as separate models. Model names
  are now normalized with the same provider-prefix stripping the pricing table uses, so
  both count as one model. Costs were always correct; only the grouping was split.
- **Dashboard token totals now understand OpenAI-style usage keys.** `compute_metrics`
  (behind `GET /metrics` and the Dashboard) only counted `usage.input_tokens`/
  `output_tokens`, so runs whose usage arrived as `prompt_tokens`/`completion_tokens`
  (the OpenAI shape, written through the public `set_output()`) showed **0 tokens** —
  even though the node detail panel already understood those aliases. The backend now
  accepts both shapes, and a non-numeric usage value counts as 0 instead of crashing
  the `/metrics` endpoint.
- **A malformed node can no longer blank the whole app.** The node-detail panel assumed
  token usage always arrived as `usage.input_tokens`/`output_tokens`; any other shape
  (e.g. OpenAI-style `prompt_tokens` written through the public `set_output()`) threw while
  rendering and, with no error boundary in the tree, unmounted the entire UI to a black
  screen. The panel now tolerates unknown usage shapes (and understands the
  `prompt_tokens`/`completion_tokens` aliases), and the app gained error boundaries — one
  around the whole app, one around the detail panel — so a bad node shows a friendly
  "couldn't display this" card instead of killing the page.
- **Graph text was unreadable in the dark theme.** ReactFlow v12 adds its own
  `colorMode` class (default `"light"`) to the graph container, which collided with
  vapviz's `.light` theme selector and flipped every design token inside the graph to
  light-theme values on a dark page. The theme selector is now scoped to `html.light` and
  the graph receives the app theme via ReactFlow's `colorMode` prop.
- **Streamed runs showed their raw run id as the title.** The store now takes the run's
  label from the `agent_start` event, so the run header and Story card say
  "Research Agent", not `44bf3d452b05` (previously only the Office Building's polling
  path set a real label). Guarded by a new unit test.

### Added
- **Office Building — the actual floor** — every floor is now drawn as one pixel-art
  environment (a per-floor canvas under the rooms — `ui/src/lib/floorArt.ts` +
  `ui/src/components/FloorEnv.tsx`, hand-authored owned art): stone corridor tiles, shared
  wall runs with a drawn door opening per room, a runner rug and ceiling lights down the
  Walk Way, plants, a water cooler, a notice board, wall art and a clock, the Door/Stairs
  alcove, and east-wall windows. Rooms drop their CSS card chrome; each app's name + status
  moved to a **nameplate** hung on the wall by its door (crisp text + status light). Empty
  rooms read as unlet offices. UI-only; the locked 12×16 room diorama is untouched.
- **Office Building — floor life / room doors** — the walk overlay
  (`ui/src/lib/walkOverlay.ts`) grows a persistent floor-life layer (`reconcileFloorLife`,
  driven each poll from `BuildingView`): a coworker steps out of every **running** room's
  door and mills on that floor's Walk Way, walking back inside when the app finishes — so
  the floor is alive while work is happening, not only during a descent/failure transition.
  Kept honest — exactly one walker per running room, nothing decorative; a quiet floor is an
  empty corridor. No floor life under `prefers-reduced-motion`. UI-only (re-presents the
  derived graph).
- **`app_id` — stable app identity for runs** — `vapviz.trace()` and `atrace()` accept an
  optional `app_id`: a stable identifier for the pipeline ("app") a run belongs to, so every
  invocation of the same app can be grouped. It rides in the run's `agent_start` data
  (additive — the `langgraph_node` pattern, no event→graph change) and is surfaced as
  `RunSummary.app_id` (+ the TS mirror). The UI groups runs by `app_id ?? label`, so
  existing instrumentation groups sensibly with zero changes.

### Changed
- **Sidebar grouped by app** — the run list becomes an **app list** (current-run status dot,
  ×N run count, plain-language subtitle); expanding an app shows its run history (status,
  start time, duration, cost) where each row selects that run for inspection and replay.
  Search, tags, compare and per-run delete are unchanged.
- **Theater: the cozy sprite office** — the Theater tab's stage is rebuilt on hand-authored
  12×16 "art-as-data" pixel sprites (palette + char-grid data rasterized to canvas and
  recolored per agent — owned art, zero AI, zero third-party packs). One shared office with
  five stations — the LLM desk plus SEARCH shelves, FETCH server racks, DATA cabinet and a
  PRINT table — where tool calls are routed to a station by keyword-matching the tool's
  name (unknown tools spread deterministically). Agents walk between their own home desk
  and stations (walk speed adapts so they arrive before the call finishes), the active
  station glows, and a playful speech bubble says what each agent is doing ("phoning the
  API", "querying the DB", …). New: `ui/src/lib/{sprites,officeArt,officeScene}.ts` and
  `ui/src/components/OfficeStage.tsx`. The Office building's rooms tile the **same engine in
  a `compact` mode** (station chips + speech bubbles dropped at room scale, name tags keep a
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
  its name overhead; a tab on every run, driven by the existing replay/live pipeline.
  New: `ui/src/lib/theater.ts`, `ui/src/components/TheaterView.tsx`.
- **Office building** — a centralized monitor (`ui/src/components/BuildingView.tsx`, sidebar 🎭
  icon) keyed to **apps**, not runs: each app owns one room shown as a live compact sprite
  office (a re-run lights the same room back up, with an ×N run count) and each agent keeps a
  stable desk within its room. Floors hold **6 rooms**; when the top floor fills, the earliest
  app descends a floor (oldest finished preferred; an all-running floor sends its
  earliest-started app down still live; floors grow downward, never sideways). Placement lives
  in the pure, unit-tested reducer `ui/src/lib/building.ts` (`buildBuilding`); polls existing
  endpoints — the only backend touch is the additive `app_id`. *(Supersedes the interim
  run-keyed `FloorView.tsx`, added and retired within this unreleased window.)*
- **The visual Office Building** — the monitor renders as an actual pixel-and-CSS building:
  a roof with the `VAPVIZ` sign, floors as **two rows of three rooms around a central Walk
  Way**, a **Door/Stairs** column, and a **lobby directory board** with the live tally (apps
  working · in the lounge · spend today). When an app moves down a floor, a coworker **walks
  the move** — across the Walk Way, into the Stairs (vanishing), out of the Door one floor
  below (a new sprite-overlay engine, `ui/src/lib/walkOverlay.ts`). An app whose current run
  **failed keeps its room** — the room turns red — while its agents head up to the shared
  **Lounge**, a hand-authored break-room diorama on the top floor's east side
  (`ui/src/lib/loungeArt.ts`, `ui/src/components/LoungeStage.tsx`; owned art, zero AI): each
  waiting agent does something different (coffee, vending machine, water cooler, lunch,
  watering the plants, pacing). Click a lounge card to inspect the failed run or **Dismiss**
  it until the app's next run (dismissals key on the failed run id, persist in
  `localStorage`, and are pruned against the live run roster). All motion respects
  `prefers-reduced-motion` (walkers and glides are skipped; the building snaps).
- LangChain integration now carries the `langgraph_node` name through to node data (additive
  metadata), so multi-agent LangGraph runs show their real cast (supervisor / workers) in Theater.

## [1.2.0]

### Added
- **Evals as a CI gate.** A declarative **eval suite** (`EvalSuite`, loaded from YAML/JSON) bundles
  the existing checks; `run_suite(suite, graphs)` returns a `SuiteReport`, and the new
  **`vapviz eval`** CLI turns a failing report into a **non-zero exit code** so agent regressions can
  fail a build.
- `vapviz eval --suite S` loads runs from a SQLite store (`--db`, with `--run-id` / `--label` /
  `--tag` / `--latest` filters), a single exported run (`--run`), or a directory (`--runs-dir`);
  `--json` and `--github-summary` (writes a Markdown table to `$GITHUB_STEP_SUMMARY`).
- A composite **`vapviz-eval` GitHub Action** (`action.yml`) that installs vapviz and runs the gate.
- New exports: `vapviz.EvalSuite` / `SuiteReport` / `RunEval` / `load_suite` / `load_runs` /
  `run_suite`; `examples/eval_suite.yaml` and `examples/evals_ci_demo.py`.

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

[Unreleased]: https://github.com/kochrisdev/vapviz/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/kochrisdev/vapviz/releases/tag/v1.4.0
[1.3.0]: https://github.com/kochrisdev/vapviz/releases/tag/v1.3.0
[1.2.0]: https://github.com/kochrisdev/vapviz/releases/tag/v1.2.0
[1.1.0]: https://github.com/kochrisdev/vapviz/releases/tag/v1.1.0
[1.0.1]: https://github.com/kochrisdev/vapviz/releases/tag/v1.0.1
[1.0.0]: https://github.com/kochrisdev/vapviz/releases/tag/v1.0.0
[0.15.0]: https://github.com/kochrisdev/vapviz/releases/tag/v0.15.0
