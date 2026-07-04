SHELL := /usr/bin/env bash

PYTHON ?= python3
ENV_CHECK_RESULT ?= env/ENV_CHECK_RESULT.local.json
SMOKE_RESULT_DIR ?= tmp/smoke

PROJECT_PATH ?=
PROJECT_CODE ?=
PROJECT_NAME ?=
AUDIT_MODE ?= FAST_STATIC
ROUND ?= R1
DEBUG_LEVEL ?= off
RUN_ROOT ?=

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
	@echo "M1-M6 static pipeline:"
	@echo "  make m1 PROJECT_PATH=projects/demo PROJECT_CODE=DEMO PROJECT_NAME='Demo Project'"
	@echo "  make m2 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m3 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m4 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m5 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m6 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo ""
	@echo "Direct targets: run-init, audit-map, tool-plan, evidence-pack, tool-run, candidates"
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

.PHONY: run-init
run-init:
	@test -n "$(PROJECT_PATH)" || (echo "PROJECT_PATH is required. Example: make run-init PROJECT_PATH=projects/demo"; exit 2)
	$(PYTHON) scripts/10_run_init.py \
		--project-path "$(PROJECT_PATH)" \
		--project-code "$(PROJECT_CODE)" \
		--project-name "$(PROJECT_NAME)" \
		--audit-mode "$(AUDIT_MODE)" \
		--round "$(ROUND)" \
		--debug-level "$(DEBUG_LEVEL)" \
		--print-summary

.PHONY: m1
m1: py-compile run-init
	@echo ""
	@echo "M1 run-init validation completed."

.PHONY: audit-map
audit-map:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make audit-map RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/20_build_audit_map.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m2
m2: py-compile audit-map
	@echo ""
	@echo "M2 audit-map validation completed."

.PHONY: tool-plan
tool-plan:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make tool-plan RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/30_build_tool_plan.py --run-root "$(RUN_ROOT)" --env-result "$(ENV_CHECK_RESULT)" --print-summary

.PHONY: m3
m3: py-compile tool-plan
	@echo ""
	@echo "M3 tool-plan validation completed."

.PHONY: evidence-pack
evidence-pack:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make evidence-pack RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/40_build_evidence_pack.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m4
m4: py-compile evidence-pack
	@echo ""
	@echo "M4 evidence-pack validation completed."

.PHONY: tool-run
tool-run:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make tool-run RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/50_run_static_tools.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m5
m5: py-compile tool-run
	@echo ""
	@echo "M5 static tool-run validation completed."

.PHONY: candidates
candidates:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make candidates RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/60_build_candidates.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m6
m6: py-compile candidates
	@echo ""
	@echo "M6 candidate-pool validation completed."

.PHONY: clean-smoke
clean-smoke:
	rm -rf $(SMOKE_RESULT_DIR)

.PHONY: clean-env
clean-env:
	rm -f $(ENV_CHECK_RESULT)

.PHONY: py-compile
py-compile:
	$(PYTHON) -m py_compile scripts/00_env_check.py scripts/10_run_init.py scripts/20_build_audit_map.py scripts/30_build_tool_plan.py scripts/40_build_evidence_pack.py scripts/50_run_static_tools.py scripts/60_build_candidates.py scripts/99_smoke_check.py

.PHONY: status
status:
	git status --short
