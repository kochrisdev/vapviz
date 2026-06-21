# vapviz Roadmap

Forward-looking plan for what comes after **1.0**. This is a set of *intentions*, not
commitments — priorities may shift with usage and feedback. For shipped changes, see
[CHANGELOG.md](CHANGELOG.md).

Each item is sized roughly (small / medium / large) by effort, and chosen to build on what 1.0
already provides (remote ingest, evals, budgets, OpenTelemetry export, the `RunStore` abstraction)
rather than starting fresh.

---

## 🎯 Near-term — v1.1 ("sharpen what's there")

High value, mostly small, leverages existing features.

- **Budget alert channels** *(small)* — `enable_budget_alerts` currently logs or calls a callback;
  add built-in **webhook / Slack / OpenTelemetry-event** sinks so an overrun actually notifies
  someone.
- **Evals as a CI gate** *(medium, differentiating)* — an `eval-suite` concept (checks + expected
  runs) plus a **`vapviz-eval` GitHub Action** that runs evals and fails the build on regressions —
  turning agent evals into real CI quality-gating.
- **Scale hygiene** *(small–medium)* — `/runs` **pagination + filtering**, and a **retention policy**
  (prune/archive old runs) so the store doesn't grow unbounded.
- **More integrations** *(small each)* — e.g. **Google ADK**, **DSPy**, **Semantic Kernel**,
  following the established `vapviz/integrations/<name>.py` pattern.

## 🔭 Mid-term — v1.2 ("team-ready")

- **Postgres backend** *(medium)* — a `PostgresStore` alongside SQLite for multi-writer / shared-team
  deployments (the `RunStore` ABC already abstracts the storage layer).
- **Auth & multi-tenant** *(medium)* — API keys / basic auth on the server and the ingest endpoint,
  so it's safe to host beyond localhost.
- **Live token streaming + UX polish** *(medium)* — stream LLM tokens into a node as they arrive;
  in-run node search, subtree collapse/expand, and shareable run links.

## 🚀 Bigger bets — v2.0

- **JS/TS SDK** *(large, biggest reach)* — much of the agent ecosystem is TypeScript (Vercel AI SDK,
  LangChain.js, Mastra, LlamaIndex.TS). A TypeScript tracer that posts to the **existing
  remote-ingest endpoint** would expand the addressable users without changing the server.
- **Distributed / cross-service tracing** *(large)* — propagate trace context so runs spawned across
  processes or services link into one graph (ties into the OpenTelemetry export work).

## 🔁 Continuous

- More framework integrations as they emerge.
- A hosted **docs site** (docs are Markdown in-repo today) and a public **demo instance**.
- Performance work for large traces and high run counts.

---

## Where we'd start

**v1.1** is the best impact-per-effort: budget alert channels and the evals CI Action are
differentiators that build directly on 1.0 features, and pagination/retention are cheap insurance.
The **JS/TS SDK** is the highest-*reach* item long-term, but big enough to warrant a deliberate 2.0
push.

Have a request or want to weigh in on priorities? Open an
[issue](https://github.com/kochrisdev/vapviz/issues).
