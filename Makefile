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
BENCHMARK_ID ?= all
WORKSPACE_MODE ?= workbench
OUTPUT_ROOT ?= runs
NETWORK_AUTHORIZATION ?= deny
STACK_ENV_RESULT ?=

.PHONY: help
help:
	@echo "AI Audit Workbench commands"
	@echo ""
	@echo "Dependencies:"
	@echo "  make install-deps    Install Python dependencies from requirements.txt"
	@echo "  make check-deps      Check required Python dependencies"
	@echo ""
	@echo "M0 env-check / smoke:"
	@echo "  make env-check       Run core env-check and write env/ENV_CHECK_RESULT.local.json"
	@echo "  make env-summary     Run core env-check and print summary"
	@echo "  make smoke           Run workbench smoke check"
	@echo "  make m0              Run env-summary and smoke"
	@echo ""
	@echo "M1-M14 pipeline:"
	@echo "  make m1 PROJECT_PATH=projects/demo PROJECT_CODE=DEMO PROJECT_NAME='Demo Project' NETWORK_AUTHORIZATION=once"
	@echo "  make m2 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m3 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m4 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m5 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m6 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m7 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m8 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m9 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m10 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m11 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS DEBUG_LEVEL=basic"
	@echo "  make m12"
	@echo "  make m13 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo "  make m14 RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"
	@echo ""
	@echo "One-shot:"
	@echo "  make fast-static PROJECT_PATH=projects/demo PROJECT_CODE=DEMO PROJECT_NAME='Demo Project' NETWORK_AUTHORIZATION=once"
	@echo ""
	@echo "Direct targets: run-init, audit-map, stack-env-check, tool-plan, tool-plan-stack, tool-execution-plan, evidence-pack, tool-run, candidates, ai-triage, merge, delivery, validate-run, debug-trace, benchmark, context-pack, deep-explore-input"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean-smoke     Remove tmp/smoke"
	@echo "  make clean-env       Remove local env-check result"
	@echo ""
	@echo "Developer checks:"
	@echo "  make py-compile      Compile current Python scripts"
	@echo "  make status          Show git status"

.PHONY: install-deps
install-deps:
	$(PYTHON) -m pip install -r requirements.txt

.PHONY: check-deps
check-deps:
	$(PYTHON) scripts/05_check_deps.py --strict --print-summary

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
		--workspace-mode "$(WORKSPACE_MODE)" \
		--output-root "$(OUTPUT_ROOT)" \
		--network-authorization "$(NETWORK_AUTHORIZATION)" \
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

.PHONY: stack-env-check
stack-env-check: check-deps
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make stack-env-check RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/31_stack_env_check.py --run-root "$(RUN_ROOT)" --include-all-tools --print-summary

.PHONY: tool-plan
tool-plan: check-deps
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make tool-plan RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/30_build_tool_plan.py --run-root "$(RUN_ROOT)" --env-result "$(ENV_CHECK_RESULT)" --print-summary

.PHONY: tool-plan-stack
tool-plan-stack: check-deps
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make tool-plan-stack RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/30_build_tool_plan.py --run-root "$(RUN_ROOT)" --env-result "$${STACK_ENV_RESULT:-$(RUN_ROOT)/evidence/STACK_ENV_CHECK_RESULT.json}" --print-summary

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
tool-run: check-deps
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

.PHONY: ai-triage
ai-triage:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make ai-triage RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/70_prepare_ai_triage.py --run-root "$(RUN_ROOT)" --write-stub --print-summary

.PHONY: m7
m7: py-compile ai-triage
	@echo ""
	@echo "M7 AI triage input validation completed."

.PHONY: merge
merge:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make merge RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/80_merge_results.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m8
m8: py-compile merge
	@echo ""
	@echo "M8 merge validation completed."

.PHONY: delivery
delivery:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make delivery RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/90_render_delivery.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m9
m9: py-compile delivery
	@echo ""
	@echo "M9 delivery validation completed."

.PHONY: validate-run
validate-run:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make validate-run RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/95_validate_run.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m10
m10: py-compile validate-run
	@echo ""
	@echo "M10 validation completed."

.PHONY: debug-trace
debug-trace:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make debug-trace RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/110_collect_debug.py --run-root "$(RUN_ROOT)" --debug-level "$(DEBUG_LEVEL)" --print-summary

.PHONY: m11
m11: py-compile debug-trace
	@echo ""
	@echo "M11 debug trace validation completed."

.PHONY: benchmark
benchmark: check-deps
	$(PYTHON) scripts/120_run_benchmark.py --benchmark-id "$(BENCHMARK_ID)" --print-summary

.PHONY: m12
m12: py-compile benchmark
	@echo ""
	@echo "M12 benchmark validation completed."

.PHONY: context-pack
context-pack:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make context-pack RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/72_build_context_pack.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: deep-explore-input
deep-explore-input:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make deep-explore-input RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/74_prepare_deep_explore.py --run-root "$(RUN_ROOT)" --write-empty-discovered --print-summary

.PHONY: m13
m13: py-compile context-pack deep-explore-input
	@echo ""
	@echo "M13 STANDARD / DEEP scaffold validation completed."

.PHONY: tool-execution-plan
tool-execution-plan:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required. Example: make tool-execution-plan RUN_ROOT=runs/DEMO/FAST_STATIC_R1_YYYYMMDD_HHMMSS"; exit 2)
	$(PYTHON) scripts/32_build_tool_execution_plan.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m14
m14: py-compile stack-env-check tool-plan-stack tool-execution-plan
	@echo ""
	@echo "M14 stack env-check and tool execution plan validation completed."

.PHONY: fast-static
fast-static: check-deps
	@test -n "$(PROJECT_PATH)" || (echo "PROJECT_PATH is required. Example: make fast-static PROJECT_PATH=projects/demo PROJECT_CODE=DEMO PROJECT_NAME='Demo Project'"; exit 2)
	$(PYTHON) scripts/100_fast_static.py \
		--project-path "$(PROJECT_PATH)" \
		--project-code "$(PROJECT_CODE)" \
		--project-name "$(PROJECT_NAME)" \
		--round "$(ROUND)" \
		--debug-level "$(DEBUG_LEVEL)" \
		--workspace-mode "$(WORKSPACE_MODE)" \
		--output-root "$(OUTPUT_ROOT)" \
		--network-authorization "$(NETWORK_AUTHORIZATION)"

.PHONY: clean-smoke
clean-smoke:
	rm -rf $(SMOKE_RESULT_DIR)

.PHONY: clean-env
clean-env:
	rm -f $(ENV_CHECK_RESULT)

.PHONY: py-compile
py-compile:
	$(PYTHON) -m py_compile scripts/00_env_check.py scripts/05_check_deps.py scripts/10_run_init.py scripts/20_build_audit_map.py scripts/30_build_tool_plan.py scripts/31_stack_env_check.py scripts/32_build_tool_execution_plan.py scripts/40_build_evidence_pack.py scripts/50_run_static_tools.py scripts/60_build_candidates.py scripts/70_prepare_ai_triage.py scripts/72_build_context_pack.py scripts/74_prepare_deep_explore.py scripts/80_merge_results.py scripts/90_render_delivery.py scripts/95_validate_run.py scripts/100_fast_static.py scripts/110_collect_debug.py scripts/120_run_benchmark.py scripts/99_smoke_check.py

.PHONY: status
status:
	git status --short
