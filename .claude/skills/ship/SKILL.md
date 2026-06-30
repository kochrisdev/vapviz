---
name: ship
description: Wrap up a vapviz change — run the full gate, verify the documentation surface was updated, and (for big changes) get a dual-lens review before committing. Invoke when a change is ready to be considered done.
---

# /ship — vapviz definition of done

Run these in order. Do not call a change "done" until all pass.

## 1. The gate (always)
```
make check        # fast: unit tests + UI typecheck (what the commit hook enforces)
make build        # full UI production build (tsc && vite build)
```
If the change touched anything LLM / cost / integration-related, also:
```
make check-all    # includes real-LLM integration tests (paid; needs OPENROUTER_API_KEY)
```

## 2. Documentation surface (always)
Confirm every doc this change affects was updated **in this same change**:
- `README.md`, `CHANGELOG.md` — user-facing behavior, install, feature list
- `docs/*.md` — ARCHITECTURE / TUTORIAL / DEVELOPER_REFERENCE / DEPLOYMENT / UI_GUIDE
- `Dockerfile`, `docker-compose.yml` — if deps, ports, build steps, or run command changed
- `pyproject.toml` version — if releasing
- test-count references in `CLAUDE.md` / `README.md` — if tests were added/removed
- `ui/src/assets/**/ASSETS.md` — if art assets changed (provenance)
- `CLAUDE.md` (root + nested) — if a convention or sharp edge changed

If a rule bit you twice this session, **push it down the durability ladder**: make it a test/type/lint, don't just add a sentence.

## 3. Review — only for a BIG change
First classify the change. It is **BIG** if ANY of these hold (otherwise it's small — skip this step):
- touches **≥ 8 files** or **≥ ~200 changed lines**, OR
- adds/removes/renames a **public surface**: a `Vap*` symbol, a CLI flag, an event type/node kind, or a server route, OR
- changes **event/graph/cost logic** (the dual-logic surface: `store.py` ↔ `runStore.ts`), OR
- changes **install/deps/build/run**: `pyproject.toml` deps, `Dockerfile`, `docker-compose.yml`, ports, OR
- **adds/removes tests**, changes **art assets**, or is a **release** (version bump).

If BIG, run both lenses before committing:
- correctness/grounding → `/code-review`
- doc-surface + blast-radius → spawn the **`doc-surface-verifier`** subagent (its full ruleset lives in `.claude/agents/doc-surface-verifier.md` and loads only when spawned — it is not in the main context until then).

If small, the gate + your own glance at the doc surface (step 2) is enough.

## 4. Commit
Only after the above. The commit hook re-runs `make check` and blocks if anything regressed (`--no-verify` to override, rarely).
