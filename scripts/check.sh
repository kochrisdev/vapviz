#!/usr/bin/env bash
#
# The fast quality gate for vapviz — what blocks a commit. A change is "done"
# only when this passes. Kept deliberately fast & free:
#   - Python: unit tests only (real-LLM integration tests are excluded — they're paid/slow)
#   - UI: TypeScript typecheck only (full `vite build` runs in /ship / `make build`)
#
# Run from anywhere:  ./scripts/check.sh   (or:  make check)
set -euo pipefail
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo "==> [1/3] Python unit tests (pytest, fast/free — excludes real-LLM integration)"
.venv/bin/python -m pytest -q -m "not integration"

echo
echo "==> [2/3] UI typecheck (tsc --noEmit)"
( cd ui && npx tsc --noEmit )

echo
echo "==> [3/3] UI unit tests (vitest — incl. dual-reducer parity)"
( cd ui && npm test --silent )

echo
echo "==> Gate PASSED."
