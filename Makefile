# Patch-Guard
#
# Everything except the *-record targets runs offline against committed
# cassettes and needs no API key.

PY ?= .venv/Scripts/python.exe
ifeq ($(OS),)
  PY = .venv/bin/python
endif

.PHONY: help setup sanity test baseline agent eval report mcp clean record-baseline record-agent

help:
	@echo "make setup     - create venv, install pinned deps, build cases"
	@echo "make sanity    - gold patch must score 100%, no-op must score 0%"
	@echo "make test      - adversarial tests for the three gates"
	@echo "make baseline  - mini-swe-agent, cassette replay -> results/baseline.jsonl"
	@echo "make agent     - Patch-Guard supervisor, cassette replay -> results/agent.jsonl"
	@echo "make eval      - score both runners -> results/report.md"
	@echo "make mcp       - start the patch-guard MCP server on stdio"

setup:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	$(PY) eval/build_cases.py --rebuild

# The load-bearing self-test. A known-correct patch must score a perfect run
# and a do-nothing agent must score zero. If either fails, the metric is wrong
# and no agent number downstream means anything.
sanity:
	$(PY) eval/harness.py --runner gold --kind standard
	$(PY) eval/harness.py --runner noop --kind standard

test:
	$(PY) -m pytest eval/tests -q

baseline:
	$(PY) baseline/run_baseline.py

agent:
	$(PY) patch_guard/run_agent.py --yes

eval:
	$(PY) eval/report.py

report: eval

mcp:
	$(PY) patch_guard/mcp_server.py

# Re-record cassettes against the live provider. Needs GROQ_API_KEY in .env.
# Judges never need these; `make baseline` / `make agent` replay what is
# committed.
record-baseline:
	PATCHGUARD_CASSETTE=record $(PY) baseline/run_baseline.py

record-agent:
	PATCHGUARD_CASSETTE=record $(PY) patch_guard/run_agent.py --yes

clean:
	rm -rf .scratch
