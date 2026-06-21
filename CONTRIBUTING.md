# Contributing to vapviz

Thanks for your interest in improving vapviz! This guide covers how to set up a
development environment, the checks your change needs to pass, and how to get a
pull request merged.

By participating, you agree that your contributions will be licensed under the
project's [MIT License](LICENSE).

---

## Ways to contribute

- **Report a bug** or **request a feature** — open an
  [issue](https://github.com/kochrisdev/vap/issues). For bugs, include the vapviz
  version, Python version, a minimal repro, and the expected vs. actual behaviour.
- **Improve the docs** — fixes to `README.md` or anything under `docs/` are very
  welcome and make great first contributions.
- **Send a pull request** — see the workflow below. For anything non-trivial,
  please open an issue first so we can agree on the approach before you build it.

---

## Development setup

vapviz is a Python package (`vapviz/`) plus a Vite + React UI (`ui/`). You need
**Python 3.11+** and **Node 20+**.

```bash
git clone https://github.com/kochrisdev/vap.git
cd vapviz

# Python — editable install with all integrations + test/dev tooling
pip install -e ".[dev]"

# UI
cd ui && npm ci && cd ..
```

Run the whole thing locally (server + a demo agent, hot-reloading UI):

```bash
python run_dev.py            # server + demo on http://localhost:8001
# in another terminal:
cd ui && npm run dev         # UI dev server on http://localhost:5173
```

---

## Checks your change must pass

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs these on every
push and pull request to `main`. Run them locally before pushing:

```bash
# Python test suite — 269 tests; integration tests skip automatically
# when their framework (crewai, pydantic-ai, langchain, …) isn't installed
pytest -q

# UI type-check + production build
cd ui && npm run build && cd ..

# Package builds cleanly and its metadata is valid
python -m build
python -m twine check dist/*
```

CI runs the test suite against Python 3.11, 3.12, and 3.13, so avoid
version-specific APIs.

---

## Coding guidelines

- **Match the surrounding code.** Mirror the existing naming, comment density,
  and idioms in the file you're editing rather than introducing a new style.
- **Type everything.** The package ships type hints (`Typing :: Typed`); keep new
  Python code annotated and new TypeScript code free of `any` where practical.
- **Tests are required for behaviour changes.** Add or update tests under
  `tests/`. Keep them hermetic — no network calls or API keys. The integration
  tests use each framework's built-in fakes (e.g. Pydantic AI's `TestModel`,
  mocked SDK clients) and `pytest.importorskip` so the suite stays green even
  when the optional dependency is absent.
- **Keep tracing best-effort.** Instrumentation must never break the user's
  agent — failures in a listener/patch should be swallowed, not raised.
- **Update the docs.** If you change public behaviour, update the relevant file
  in `docs/` (and `README.md` where it overlaps) in the same PR.

Get oriented with the
[Project Structure](README.md#project-structure) section and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Adding a new framework integration

Integrations live in `vapviz/integrations/` and follow one of two patterns
(SDK monkey-patch, or event-bus/listener) described in the
[Extension Guide](docs/ARCHITECTURE.md#extension-guide). When you add one:

1. Implement it in `vapviz/integrations/<name>.py`, reusing `vapviz.calculate_cost`
   for LLM cost and emitting standard `VapEvent`s so it works with the existing
   store, server, and UI unchanged.
2. Add an optional extra in `pyproject.toml` (and to the `all` / `dev` groups).
3. Add `tests/test_<name>.py`, guarded with
   `pytest.importorskip("<package>")` and using the framework's test doubles.
4. Add an `examples/<name>_demo.py` and document it in `README.md`,
   `docs/TUTORIAL.md`, `docs/ARCHITECTURE.md`, and `docs/DEVELOPER_REFERENCE.md`.

---

## Commit messages

This repo uses [Conventional Commits](https://www.conventionalcommits.org/).
Prefix the subject with the change type, e.g.:

```
feat(pydantic-ai): trace Pydantic AI agents
fix(tests): reset _current_step ContextVar between tests
docs: document the analytics dashboard
ci: add GitHub Actions CI/release + PyPI release metadata
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `ci`, `chore`.
Keep the subject in the imperative mood and under ~72 characters; put detail and
rationale in the body.

---

## Pull request workflow

1. Fork the repo (or create a branch if you have write access) — don't commit
   directly to `main`.
2. Make your change with tests and docs updated.
3. Run the [checks above](#checks-your-change-must-pass) locally.
4. Open a PR against `main` with a clear description of **what** changed and
   **why**. Link any related issue.
5. Make sure CI is green — PRs are merged only when all jobs pass.

Small, focused PRs are reviewed fastest. If a change is large, consider splitting
it (e.g. one PR for the feature, one for docs).

---

## Releasing (maintainers)

Releases are tag-driven and publish to PyPI via
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — no API tokens.

1. Bump `version` in [`pyproject.toml`](pyproject.toml) and add a changelog entry
   in [`docs/DEVELOPER_REFERENCE.md`](docs/DEVELOPER_REFERENCE.md#changelog).
2. Commit, then tag and push:
   ```bash
   git tag v0.8.0 && git push origin v0.8.0
   ```
3. [`.github/workflows/release.yml`](.github/workflows/release.yml) builds the
   distribution, verifies the tag matches the package version, and publishes to
   PyPI. (Requires the one-time PyPI publisher configuration noted in that
   workflow's header.)

---

Questions? Open an [issue](https://github.com/kochrisdev/vap/issues) — happy to help.
