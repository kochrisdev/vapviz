# vapviz/ — Python package (map, not a manual)

The tracer → store → server pipeline. **Everything is an event; the graph is derived, never stored directly.**

- `tracer.py` — `trace`/`step` (sync) + `atrace`/`astep` (async) context managers; automatic parent/child nesting via the `_current_step` ContextVar. `_start_event`/`_end_event` maps live here. `trace(label, run_id=None, app_id=None)` — `app_id` is a stable pipeline identity riding in `agent_start` data (additive; surfaces as `RunSummary.app_id`, set at run creation — NOT part of the dual reducers).
- `store.py` — `RunStore` ABC + `MemoryStore` (default); the pure `_apply_event_to_graph` builds the derived graph; `_total_cost` sums **LLM-kind nodes only**.
- `backends/sqlite.py` — `SqliteStore` (WAL; replays the DB into an in-memory graph cache on startup).
- `server.py` — FastAPI REST + SSE façade. Route order: `/runs/compare` before `/runs/{id}`.
- `cost.py` — pricing table, longest-prefix match (strips `openai/` etc.).
- `integrations/` — three patterns (monkey-patch / callback-handler / event-bus listener); all funnel into `StepContext._emit`.

## Sharp edge — DUAL LOGIC (must stay in sync)
The events→graph reduction exists **twice**: Python `_apply_event_to_graph` (here) ↔ TypeScript `applyEvent` in `ui/src/store/runStore.ts`. The event schema is dual (`events.py` ↔ `ui/src/types/events.ts`) and so is the cost reduce (`_total_cost` ↔ `runStore.ts`, both LLM-kind only). Changing an event type, node kind, or cost rule means editing **all** of them — plus `KIND_BG` in `ui/src/components/AgentGraph.tsx` and the `_start_event`/`_end_event` maps in `tracer.py`.

> Guarded by the **cross-impl parity test**: shared fixtures in `tests/fixtures/reducer_parity/*.json` are replayed through BOTH reducers — Python `tests/test_reducer_parity.py` and TS `ui/src/store/runStore.parity.test.ts` — and the normalized graphs must match. Drift fails the gate. Add a case = drop another JSON in that dir (both halves auto-pick it up); change behaviour = update the fixture's `expected` AND both reducers.
