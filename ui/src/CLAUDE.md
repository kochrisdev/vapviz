# ui/src/ — React UI (map, not a manual)

Mirrors the backend. Vite + React + Zustand + ReactFlow (`@xyflow/react`).

- `store/runStore.ts` — Zustand store; the pure `applyEventToGraph` + `totalLlmCost` re-implement the backend's reduction (the store's `applyEvent` just calls them).
- `hooks/useRunStream.ts` — one `EventSource` per selected run; `RunList` polls `/runs` ~3s.
- `components/AgentGraph.tsx` — dagre layout + ReactFlow; node color = kind (`KIND_BG`), border = status.
- `types/events.ts` — TS mirror of `vapviz/events.py`.
- `lib/theater.ts`, `lib/avatar.ts`, Theater/Floor components — **UI-only presentation** of the already-derived graph.

## Sharp edge — DUAL LOGIC (must stay in sync)
`applyEventToGraph` / `totalLlmCost` (runStore.ts), `types/events.ts`, and the cost reduce here MUST track their Python counterparts in `vapviz/` (`_apply_event_to_graph`, `events.py`, `_total_cost`) — guarded by the cross-impl parity test (`runStore.parity.test.ts` ↔ `tests/test_reducer_parity.py`, shared fixtures in `tests/fixtures/reducer_parity/`). See `vapviz/CLAUDE.md`. **Exempt:** `lib/theater.ts` / `lib/avatar.ts` / `AgentStage` / Theater views only re-present derived data, so they are *not* part of the dual-logic rule.
