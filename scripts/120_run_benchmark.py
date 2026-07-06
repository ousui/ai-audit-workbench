#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = ROOT / "var" / "tmp" / "benchmarks"
RUNS_ROOT = ROOT / "var" / "runs"

BENCHMARKS = [
    {
        "benchmark_id": "STATIC_DEMO",
        "project_path": "benchmarks/fixtures/static-demo",
        "project_code": "BENCH_STATIC_DEMO",
        "project_name": "Benchmark Static Demo",
        "run_id": "FAST_STATIC_BENCHMARK_STATIC_DEMO",
        "expected_path": "benchmarks/expected/STATIC_DEMO.expected.json",
    }
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_cmd(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(args, cwd=str(ROOT), text=True, capture_output=True)
    return proc.returncode, proc.stdout, proc.stderr


def validate_outputs(run_root: Path, expected: dict[str, Any]) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    for rel in expected["expected"].get("required_output_files", []):
        if not (run_root / rel).is_file():
            errors.append(f"missing output file: {rel}")
    pool_path = run_root / "candidates" / "CANDIDATE_POOL.json"
    if pool_path.is_file():
        pool = load_json(pool_path)
        candidates = pool.get("candidates", [])
        risk_types = sorted({item.get("risk_type") for item in candidates if item.get("risk_type")})
        metrics["total_candidates"] = len(candidates)
        metrics["risk_types"] = risk_types
        metrics["candidate_schema_version"] = pool.get("schema_version")
        min_total = expected["expected"].get("min_total_candidates", 0)
        if len(candidates) < min_total:
            errors.append(f"candidate count too low: {len(candidates)} < {min_total}")
        for risk_type in expected["expected"].get("required_risk_types", []):
            if risk_type not in risk_types:
                errors.append(f"required risk_type not found: {risk_type}")
    else:
        errors.append("CANDIDATE_POOL.json missing; cannot validate candidates")
    validation_path = run_root / "validate" / "VALIDATION_RESULT.json"
    if validation_path.is_file():
        validation = load_json(validation_path)
        metrics["validation_status"] = validation.get("status")
        metrics["validation_error_count"] = validation.get("error_count")
        metrics["validation_warning_count"] = validation.get("warning_count")
        if validation.get("status") != "passed":
            errors.append(f"validation failed: {validation.get('errors')}")
        for warning in validation.get("warnings", []):
            warnings.append(str(warning))
    return errors, warnings, metrics


def run_benchmark(item: dict[str, Any]) -> dict[str, Any]:
    benchmark_id = item["benchmark_id"]
    expected = load_json(ROOT / item["expected_path"])
    run_root = RUNS_ROOT / item["project_code"] / item["run_id"]
    if run_root.exists():
        shutil.rmtree(run_root)
    cmd = [
        sys.executable,
        "scripts/130_audit_static.py",
        "--project-path",
        item["project_path"],
        "--project-code",
        item["project_code"],
        "--project-name",
        item["project_name"],
        "--run-id",
        item["run_id"],
        "--output-root",
        "var/runs",
        "--network-authorization",
        "once",
        "--tool-timeout",
        "30",
        "--dry-run-external-tools",
    ]
    code, stdout, stderr = run_cmd(cmd)
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    if code != 0:
        errors.append(f"audit-static exited with code {code}")
    if run_root.is_dir():
        output_errors, output_warnings, metrics = validate_outputs(run_root, expected)
        errors.extend(output_errors)
        warnings.extend(output_warnings)
    else:
        errors.append(f"run root not created: {run_root}")
    return {
        "benchmark_id": benchmark_id,
        "status": "passed" if not errors else "failed",
        "run_root": str(run_root.relative_to(ROOT)) if run_root.exists() else str(run_root),
        "command": cmd,
        "exit_code": code,
        "metrics": metrics,
        "errors": errors,
        "warnings": warnings,
        "stdout_tail": stdout.splitlines()[-30:],
        "stderr_tail": stderr.splitlines()[-30:],
    }


def render_md(result: dict[str, Any]) -> str:
    lines = ["# BENCHMARK_RESULT", "", f"- Status: `{result['status']}`", f"- Total: {result['summary']['total']}", f"- Passed: {result['summary']['passed']}", f"- Failed: {result['summary']['failed']}", ""]
    for item in result.get("items", []):
        lines.extend([f"## {item['benchmark_id']}", "", f"- Status: `{item['status']}`", f"- Run root: `{item['run_root']}`", f"- Candidate count: {item.get('metrics', {}).get('total_candidates', '-')}", f"- Candidate schema: {item.get('metrics', {}).get('candidate_schema_version', '-')}", f"- Risk types: {', '.join(item.get('metrics', {}).get('risk_types', [])) or '-'}", ""])
        if item.get("errors"):
            lines.append("### Errors")
            for error in item["errors"]:
                lines.append(f"- {error}")
            lines.append("")
        if item.get("warnings"):
            lines.append("### Warnings")
            for warning in item["warnings"]:
                lines.append(f"- {warning}")
            lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run workbench benchmark suite.")
    parser.add_argument("--benchmark-id", default="all")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    selected = BENCHMARKS if args.benchmark_id == "all" else [b for b in BENCHMARKS if b["benchmark_id"] == args.benchmark_id]
    if not selected:
        print(f"[FAIL] benchmark not found: {args.benchmark_id}", file=sys.stderr)
        return 2
    items = [run_benchmark(item) for item in selected]
    result = {"schema_version": "benchmark-result-0.3.0", "summary": {"total": len(items), "passed": sum(1 for item in items if item["status"] == "passed"), "failed": sum(1 for item in items if item["status"] == "failed")}, "status": "passed" if all(item["status"] == "passed" for item in items) else "failed", "items": items}
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(RESULT_DIR / "BENCHMARK_RESULT.json", result)
    (RESULT_DIR / "BENCHMARK_RESULT.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print("benchmark summary")
        print(f"  status: {result['status']}")
        print(f"  total: {result['summary']['total']}")
        print(f"  passed: {result['summary']['passed']}")
        print(f"  failed: {result['summary']['failed']}")
        for item in items:
            print(f"  {item['benchmark_id']}: {item['status']} candidates={item.get('metrics', {}).get('total_candidates', '-')}")
            if item.get("errors"):
                print("    errors:")
                for error in item["errors"]:
                    print(f"      - {error}")
            if item.get("warnings"):
                print("    warnings:")
                for warning in item["warnings"]:
                    print(f"      - {warning}")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
