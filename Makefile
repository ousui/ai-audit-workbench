SHELL := /usr/bin/env bash

PYTHON ?= python3
ENV_CHECK_RESULT ?= env/ENV_CHECK_RESULT.local.json
SMOKE_RESULT_DIR ?= tmp/smoke

.PHONY: help
help:
	@echo "AI Audit Workbench commands"
	@echo ""
	@echo "M0 env-check / smoke:"
	@echo "  make env-check       Run core env-check and write env/ENV_CHECK_RESULT.local.json"
	@echo "  make env-summary     Run core env-check and print summary"
	@echo "  make smoke           Run workbench smoke check"
	@echo "  make m0              Run env-summary and smoke"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean-smoke     Remove tmp/smoke"
	@echo "  make clean-env       Remove local env-check result"
	@echo ""
	@echo "Developer checks:"
	@echo "  make py-compile      Compile current Python scripts"
	@echo "  make status          Show git status"

.PHONY: env-check
env-check:
	$(PYTHON) scripts/00_env_check.py --output $(ENV_CHECK_RESULT)

.PHONY: env-summary
env-summary:
	$(PYTHON) scripts/00_env_check.py --output $(ENV_CHECK_RESULT) --print-summary

.PHONY: smoke
smoke:
	$(PYTHON) scripts/99_smoke_check.py

.PHONY: m0
m0: env-summary smoke
	@echo ""
	@echo "M0 validation completed."

.PHONY: clean-smoke
clean-smoke:
	rm -rf $(SMOKE_RESULT_DIR)

.PHONY: clean-env
clean-env:
	rm -f $(ENV_CHECK_RESULT)

.PHONY: py-compile
py-compile:
	$(PYTHON) -m py_compile scripts/00_env_check.py scripts/99_smoke_check.py

.PHONY: status
status:
	git status --short