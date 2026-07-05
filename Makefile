SHELL := /usr/bin/env bash

PYTHON ?= python3
ENV_CHECK_RESULT ?= local/registry/hosts/current/ENV_CHECK_RESULT.local.json
SMOKE_RESULT_DIR ?= var/tmp/smoke
TOOL_MATRIX ?= spec/env/TOOL_MATRIX.yaml
TOOL_MATRIX_EXTENSIONS ?= spec/env/TOOL_MATRIX_EXTENSIONS.yaml
RECIPES ?= spec/rules/candidate-recipes.yaml

PROJECT_PATH ?=
PROJECT_CODE ?=
PROJECT_NAME ?=
AUDIT_MODE ?= FAST_STATIC
ROUND ?= R1
DEBUG_LEVEL ?= off
RUN_ROOT ?=
BENCHMARK_ID ?= all
WORKSPACE_MODE ?= workbench
OUTPUT_ROOT ?= var/runs
NETWORK_AUTHORIZATION ?= deny
STACK_ENV_RESULT ?=
TOOL_TIMEOUT ?= 900
DRY_RUN ?= false

.PHONY: help
help:
	@echo "AI Audit Workbench"
	@echo ""
	@echo "Common:"
	@echo "  make install-deps"
	@echo "  make check-deps"
	@echo "  make env-summary"
	@echo "  make audit-static PROJECT_PATH=benchmarks/fixtures/static-demo PROJECT_CODE=DEMO DRY_RUN=true"
	@echo "  make benchmark"
	@echo ""
	@echo "Verify:"
	@echo "  make py-compile"
	@echo "  make smoke"
	@echo "  make layout-verify"
	@echo "  make verify"
	@echo "  make verify-full"
	@echo ""
	@echo "Debug steps:"
	@echo "  make run-init PROJECT_PATH=... PROJECT_CODE=..."
	@echo "  make audit-map RUN_ROOT=..."
	@echo "  make stack-env-check RUN_ROOT=..."
	@echo "  make tool-plan-stack RUN_ROOT=..."
	@echo "  make tool-execution-plan RUN_ROOT=..."
	@echo "  make ext-tool-run RUN_ROOT=... DRY_RUN=true"
	@echo "  make ext-tool-candidates RUN_ROOT=..."
	@echo "  make evidence-pack RUN_ROOT=..."
	@echo "  make tool-run RUN_ROOT=..."
	@echo "  make candidates RUN_ROOT=..."
	@echo "  make merge-external-candidates RUN_ROOT=..."
	@echo "  make ai-triage RUN_ROOT=..."
	@echo "  make merge RUN_ROOT=..."
	@echo "  make delivery RUN_ROOT=..."
	@echo "  make validate-run RUN_ROOT=..."
	@echo "  make debug-trace RUN_ROOT=... DEBUG_LEVEL=basic"
	@echo ""
	@echo "Legacy milestones:"
	@echo "  make fast-static PROJECT_PATH=... PROJECT_CODE=..."
	@echo "  make m0 ... m15"

.PHONY: install-deps
install-deps:
	$(PYTHON) -m pip install -r requirements.txt

.PHONY: check-deps
check-deps:
	$(PYTHON) scripts/05_check_deps.py --strict --print-summary

.PHONY: env-check
env-check:
	$(PYTHON) scripts/00_env_check.py --matrix $(TOOL_MATRIX) --output $(ENV_CHECK_RESULT)

.PHONY: env-summary
env-summary:
	$(PYTHON) scripts/00_env_check.py --matrix $(TOOL_MATRIX) --output $(ENV_CHECK_RESULT) --print-summary

.PHONY: smoke
smoke:
	$(PYTHON) scripts/99_smoke_check.py

.PHONY: layout-verify
layout-verify:
	$(PYTHON) scripts/190_verify_layout.py --print-summary

.PHONY: verify
verify: py-compile layout-verify smoke benchmark
	@echo ""
	@echo "Workbench verification completed."

.PHONY: verify-full
verify-full: verify
	$(MAKE) audit-static PROJECT_PATH=benchmarks/fixtures/static-demo PROJECT_CODE=VERIFY_STATIC_DEMO PROJECT_NAME="Verify Static Demo" NETWORK_AUTHORIZATION=once DRY_RUN=true TOOL_TIMEOUT=30
	@echo ""
	@echo "Full workbench verification completed."

.PHONY: m0
m0: env-summary smoke
	@echo "M0 validation completed."

.PHONY: run-init
run-init:
	@test -n "$(PROJECT_PATH)" || (echo "PROJECT_PATH is required"; exit 2)
	$(PYTHON) scripts/10_run_init.py --project-path "$(PROJECT_PATH)" --project-code "$(PROJECT_CODE)" --project-name "$(PROJECT_NAME)" --audit-mode "$(AUDIT_MODE)" --round "$(ROUND)" --debug-level "$(DEBUG_LEVEL)" --workspace-mode "$(WORKSPACE_MODE)" --output-root "$(OUTPUT_ROOT)" --network-authorization "$(NETWORK_AUTHORIZATION)" --print-summary

.PHONY: m1
m1: py-compile run-init
	@echo "M1 run-init validation completed."

.PHONY: audit-map
audit-map:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/20_build_audit_map.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m2
m2: py-compile audit-map
	@echo "M2 audit-map validation completed."

.PHONY: stack-env-check
stack-env-check: check-deps
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/31_stack_env_check.py --run-root "$(RUN_ROOT)" --include-all-tools --tool-matrix "$(TOOL_MATRIX)" --tool-matrix-extensions "$(TOOL_MATRIX_EXTENSIONS)" --print-summary

.PHONY: tool-plan
tool-plan: check-deps
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/30_build_tool_plan.py --run-root "$(RUN_ROOT)" --env-result "$(ENV_CHECK_RESULT)" --tool-matrix "$(TOOL_MATRIX)" --tool-matrix-extensions "$(TOOL_MATRIX_EXTENSIONS)" --print-summary

.PHONY: tool-plan-stack
tool-plan-stack: check-deps
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/30_build_tool_plan.py --run-root "$(RUN_ROOT)" --env-result "$${STACK_ENV_RESULT:-$(RUN_ROOT)/evidence/STACK_ENV_CHECK_RESULT.json}" --tool-matrix "$(TOOL_MATRIX)" --tool-matrix-extensions "$(TOOL_MATRIX_EXTENSIONS)" --print-summary

.PHONY: m3
m3: py-compile tool-plan
	@echo "M3 tool-plan validation completed."

.PHONY: evidence-pack
evidence-pack:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/40_build_evidence_pack.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m4
m4: py-compile evidence-pack
	@echo "M4 evidence-pack validation completed."

.PHONY: tool-run
tool-run: check-deps
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/50_run_static_tools.py --run-root "$(RUN_ROOT)" --recipes "$(RECIPES)" --print-summary

.PHONY: m5
m5: py-compile tool-run
	@echo "M5 static tool-run validation completed."

.PHONY: candidates
candidates:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/60_build_candidates.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m6
m6: py-compile candidates
	@echo "M6 candidate-pool validation completed."

.PHONY: ai-triage
ai-triage:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/70_prepare_ai_triage.py --run-root "$(RUN_ROOT)" --write-stub --print-summary

.PHONY: m7
m7: py-compile ai-triage
	@echo "M7 AI triage input validation completed."

.PHONY: merge
merge:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/80_merge_results.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m8
m8: py-compile merge
	@echo "M8 merge validation completed."

.PHONY: delivery
delivery:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/90_render_delivery.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m9
m9: py-compile delivery
	@echo "M9 delivery validation completed."

.PHONY: validate-run
validate-run:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/95_validate_run.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m10
m10: py-compile validate-run
	@echo "M10 validation completed."

.PHONY: debug-trace
debug-trace:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/110_collect_debug.py --run-root "$(RUN_ROOT)" --debug-level "$(DEBUG_LEVEL)" --print-summary

.PHONY: m11
m11: py-compile debug-trace
	@echo "M11 debug trace validation completed."

.PHONY: benchmark
benchmark: check-deps
	$(PYTHON) scripts/120_run_benchmark.py --benchmark-id "$(BENCHMARK_ID)" --print-summary

.PHONY: m12
m12: py-compile benchmark
	@echo "M12 benchmark validation completed."

.PHONY: context-pack
context-pack:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/72_build_context_pack.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: deep-explore-input
deep-explore-input:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/74_prepare_deep_explore.py --run-root "$(RUN_ROOT)" --write-empty-discovered --print-summary

.PHONY: m13
m13: py-compile context-pack deep-explore-input
	@echo "M13 STANDARD / DEEP scaffold validation completed."

.PHONY: tool-execution-plan
tool-execution-plan:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/32_build_tool_execution_plan.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: ext-tool-run
ext-tool-run:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	@if [ "$(DRY_RUN)" = "true" ]; then \
		$(PYTHON) scripts/33_run_tool_execution_plan.py --run-root "$(RUN_ROOT)" --timeout "$(TOOL_TIMEOUT)" --dry-run --print-summary; \
	else \
		$(PYTHON) scripts/33_run_tool_execution_plan.py --run-root "$(RUN_ROOT)" --timeout "$(TOOL_TIMEOUT)" --print-summary; \
	fi

.PHONY: ext-tool-candidates
ext-tool-candidates:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/34_import_tool_candidates.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: merge-external-candidates
merge-external-candidates:
	@test -n "$(RUN_ROOT)" || (echo "RUN_ROOT is required"; exit 2)
	$(PYTHON) scripts/35_merge_external_candidates.py --run-root "$(RUN_ROOT)" --print-summary

.PHONY: m14
m14: py-compile stack-env-check tool-plan-stack tool-execution-plan ext-tool-run ext-tool-candidates merge-external-candidates
	@echo "M14 validation completed."

.PHONY: audit-static
audit-static: check-deps
	@test -n "$(PROJECT_PATH)" || (echo "PROJECT_PATH is required"; exit 2)
	@if [ "$(DRY_RUN)" = "true" ]; then \
		$(PYTHON) scripts/130_audit_static.py --project-path "$(PROJECT_PATH)" --project-code "$(PROJECT_CODE)" --project-name "$(PROJECT_NAME)" --round "$(ROUND)" --debug-level "$(DEBUG_LEVEL)" --workspace-mode "$(WORKSPACE_MODE)" --output-root "$(OUTPUT_ROOT)" --network-authorization "$(NETWORK_AUTHORIZATION)" --tool-timeout "$(TOOL_TIMEOUT)" --dry-run-external-tools; \
	else \
		$(PYTHON) scripts/130_audit_static.py --project-path "$(PROJECT_PATH)" --project-code "$(PROJECT_CODE)" --project-name "$(PROJECT_NAME)" --round "$(ROUND)" --debug-level "$(DEBUG_LEVEL)" --workspace-mode "$(WORKSPACE_MODE)" --output-root "$(OUTPUT_ROOT)" --network-authorization "$(NETWORK_AUTHORIZATION)" --tool-timeout "$(TOOL_TIMEOUT)"; \
	fi

.PHONY: m15
m15: py-compile audit-static
	@echo "M15 audit-static validation completed."

.PHONY: fast-static
fast-static: check-deps
	@echo "[DEPRECATED] fast-static is a legacy MVP flow. Prefer: make audit-static ..."
	@test -n "$(PROJECT_PATH)" || (echo "PROJECT_PATH is required"; exit 2)
	$(PYTHON) scripts/100_fast_static.py --project-path "$(PROJECT_PATH)" --project-code "$(PROJECT_CODE)" --project-name "$(PROJECT_NAME)" --round "$(ROUND)" --debug-level "$(DEBUG_LEVEL)" --workspace-mode "$(WORKSPACE_MODE)" --output-root "$(OUTPUT_ROOT)" --network-authorization "$(NETWORK_AUTHORIZATION)"

.PHONY: clean-smoke
clean-smoke:
	rm -rf $(SMOKE_RESULT_DIR)

.PHONY: clean-env
clean-env:
	rm -f $(ENV_CHECK_RESULT)

.PHONY: py-compile
py-compile:
	$(PYTHON) -m py_compile scripts/00_env_check.py scripts/05_check_deps.py scripts/10_run_init.py scripts/20_build_audit_map.py scripts/30_build_tool_plan.py scripts/31_stack_env_check.py scripts/32_build_tool_execution_plan.py scripts/33_run_tool_execution_plan.py scripts/34_import_tool_candidates.py scripts/35_merge_external_candidates.py scripts/40_build_evidence_pack.py scripts/50_run_static_tools.py scripts/60_build_candidates.py scripts/70_prepare_ai_triage.py scripts/72_build_context_pack.py scripts/74_prepare_deep_explore.py scripts/80_merge_results.py scripts/90_render_delivery.py scripts/95_validate_run.py scripts/100_fast_static.py scripts/110_collect_debug.py scripts/120_run_benchmark.py scripts/130_audit_static.py scripts/190_verify_layout.py scripts/99_smoke_check.py

.PHONY: status
status:
	git status --short
