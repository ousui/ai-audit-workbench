#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "conf/README.md",
    "docs/README.md",
    "benchmarks/README.md",
    "scripts/README.md",
    "templates/README.md",
    "local/README.md",
    "var/README.md",
    "spec/README.md",
    "spec/env/README.md",
    "spec/env/TOOL_MATRIX.yaml",
    "spec/env/TOOL_MATRIX_EXTENSIONS.yaml",
    "spec/rules/README.md",
    "spec/rules/candidate-recipes.yaml",
    "spec/rules/risk-taxonomy.yaml",
    "spec/rules/project-doc-fields.yaml",
    "spec/prompts/README.md",
    "spec/prompts/triage/FAST_STATIC.md",
    "spec/schemas/README.md",
    "spec/schemas/AI_TRIAGE_RESULT.schema.json",
    "spec/workflows/README.md",
    "spec/debug/README.md",
]

COMPILE_SCRIPTS = [
    "scripts/00_env_check.py",
    "scripts/05_check_deps.py",
    "scripts/10_run_init.py",
    "scripts/20_build_audit_map.py",
    "scripts/25_run_preflight.py",
    "scripts/26_run_assisted_change.py",
    "scripts/27_reset_assisted_change.py",
    "scripts/30_build_tool_plan.py",
    "scripts/31_stack_env_check.py",
    "scripts/32_build_tool_execution_plan.py",
    "scripts/33_run_tool_execution_plan.py",
    "scripts/34_import_tool_candidates.py",
    "scripts/35_merge_external_candidates.py",
    "scripts/36_check_tool_adapters.py",
    "scripts/37_check_tool_cache.py",
    "scripts/38_update_tool_cache.py",
    "scripts/40_build_evidence_pack.py",
    "scripts/50_run_static_tools.py",
    "scripts/60_build_candidates.py",
    "scripts/70_prepare_ai_triage.py",
    "scripts/72_build_context_pack.py",
    "scripts/74_prepare_deep_explore.py",
    "scripts/80_merge_results.py",
    "scripts/90_render_delivery.py",
    "scripts/95_validate_run.py",
    "scripts/100_fast_static.py",
    "scripts/110_collect_debug.py",
    "scripts/120_run_benchmark.py",
    "scripts/130_audit_static.py",
    "scripts/190_verify_layout.py",
    "scripts/99_smoke_check.py",
]


def run_cmd(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(args, cwd=str(ROOT), text=True, capture_output=True)
    return proc.returncode, proc.stdout, proc.stderr


def check_files() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            errors.append(f"missing required file: {rel}")
    legacy_dirs = ["env", "rules", "prompts", "schemas", "config", "dicts"]
    for rel in legacy_dirs:
        if (ROOT / rel).exists():
            warnings.append(f"legacy directory still exists for compatibility: {rel}")
    return errors, warnings


def check_compile() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    args = [sys.executable, "-m", "py_compile", *COMPILE_SCRIPTS]
    code, stdout, stderr = run_cmd(args)
    if code != 0:
        errors.append("python compile failed")
        if stdout.strip():
            warnings.append("compile stdout: " + stdout.strip()[-1000:])
        if stderr.strip():
            warnings.append("compile stderr: " + stderr.strip()[-1000:])
    return errors, warnings


def check_smoke() -> tuple[list[str], list[str]]:
    code, stdout, stderr = run_cmd([sys.executable, "scripts/99_smoke_check.py"])
    errors: list[str] = []
    warnings: list[str] = []
    if code != 0:
        errors.append(f"smoke check failed with exit code {code}")
        if stderr.strip():
            warnings.append("smoke stderr: " + stderr.strip()[-1000:])
    if stdout.strip():
        warnings.append("smoke stdout tail: " + "\n".join(stdout.splitlines()[-12:]))
    return errors, warnings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify layout migration integrity.")
    parser.add_argument("--with-smoke", action="store_true", help="Also run smoke check.")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    errors: list[str] = []
    warnings: list[str] = []
    file_errors, file_warnings = check_files()
    errors.extend(file_errors)
    warnings.extend(file_warnings)
    compile_errors, compile_warnings = check_compile()
    errors.extend(compile_errors)
    warnings.extend(compile_warnings)
    if args.with_smoke:
        smoke_errors, smoke_warnings = check_smoke()
        errors.extend(smoke_errors)
        warnings.extend(smoke_warnings)

    result: dict[str, Any] = {
        "schema_version": "layout-verify-result-0.4.0",
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
    out = ROOT / "var" / "tmp" / "layout-verify"
    out.mkdir(parents=True, exist_ok=True)
    (out / "LAYOUT_VERIFY_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.print_summary:
        print("layout-verify summary")
        print(f"  status: {result['status']}")
        print(f"  errors: {len(errors)}")
        print(f"  warnings: {len(warnings)}")
        for error in errors:
            print(f"  error: {error}")
        for warning in warnings[:8]:
            print(f"  warning: {warning.splitlines()[0]}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
