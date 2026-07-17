# vapviz developer shortcuts. The gate is `make check` (see scripts/check.sh).
.PHONY: check check-all test test-all build dev

check:        ## The gate: fast/free pytest (no paid LLM) + UI typecheck/build
	./scripts/check.sh

check-all:    ## Full gate INCLUDING real-LLM integration tests (paid; needs OPENROUTER_API_KEY)
	.venv/bin/python -m pytest -q && cd ui && npm run build

test:         ## Python tests only — fast/free (excludes real-LLM integration)
	.venv/bin/python -m pytest -q -m "not integration"

test-all:     ## Python tests INCLUDING real-LLM integration (paid)
	.venv/bin/python -m pytest -q

build:        ## UI typecheck + production build
	cd ui && npm run build

dev:          ## Backend on :8001 + a demo run (in-memory)
	.venv/bin/python run_dev.py
