# REPRO-01 / NFR-4: clean clone -> full run with one command.
# Needs a filled-in .env (copy env.example): TigerGraph workspace + LLM endpoint.
#   make reproduce   install, check, verify endpoints, build graph, run all benchmarks
# Outputs: out/$(RUN_ID)-public.jsonl (throughput), out/$(RUN_ID)-public-timing.jsonl
# (latency figures), out/$(RUN_ID)-holdout.jsonl (one-time hidden-set run),
# out/$(RUN_ID)-public-report.md and out/$(RUN_ID)-holdout-export.json (submission).

PYTHON ?= python3
# Expanded once, so every target in one `make` invocation shares the id.
ifndef RUN_ID
RUN_ID := $(shell date -u +%Y%m%dT%H%M%SZ)
endif
OGR := $(PYTHON) -m ogr.cli

.PHONY: reproduce install check verify build benchmark timing holdout results smoke

reproduce: install check verify build benchmark timing holdout results

install:
	$(PYTHON) -m pip install -e "backend[dev]"
	cd frontend && npm ci

check:
	cd backend && ruff check src tests && $(PYTHON) -m pytest -q
	cd frontend && npm run lint && npm run build && npm test

# Before the first build the GSQL queries do not exist yet: reported, not fatal.
verify:
	$(OGR) verify --pre-build

build:
	$(OGR) build

benchmark:
	$(OGR) batch data/questions/eval_public.jsonl --mode throughput --run-id $(RUN_ID)-public --out out/$(RUN_ID)-public.jsonl

timing:
	$(OGR) batch data/questions/eval_public.jsonl --mode timing --run-id $(RUN_ID)-public-timing --out out/$(RUN_ID)-public-timing.jsonl

holdout:
	$(OGR) batch acceptance/holdout/eval_hidden.jsonl --mode throughput --run-id $(RUN_ID)-holdout --out out/$(RUN_ID)-holdout.jsonl

results:
	$(OGR) report out/$(RUN_ID)-public.jsonl --out out/$(RUN_ID)-public-report.md
	$(OGR) export out/$(RUN_ID)-holdout.jsonl --out out/$(RUN_ID)-holdout-export.json

# One question through all three pipelines on the live graph: GSQL + LLM end to end.
smoke:
	$(OGR) ask "How many nations competed in sailing at the 2016 Summer Olympics?" --pipelines rag,graphrag,agentic_graphrag --show-trace
