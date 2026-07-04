#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "meta/RUN_METADATA.json",
    "meta/PROJECT_PROFILE.json",
    "audit-map/AUDIT_MAP.json",
    "audit-map/AUDIT_MAP.md",
    "evidence/TOOL_PLAN.json",
    "evidence/EVIDENCE_PACK.json",
    "evidence/TOOL_RUN_RESULT.json",
    "candidates/CANDIDATE_POOL.json",
    "ai/AI_TRIAGE_INPUT.json",
    "ai/AI_TRIAGE_RESULT.json",
    "merge/MERGE_RESULT.json",
    "delivery/AUDIT_REPORT.md",
    "delivery/AUDIT_REPORT.html",
    "delivery/AUDIT_TRACKING.csv",
    "delivery/DELIVERY_RECORD.json",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate(run_root: Path) -> dict[str, Any]:
    checks = []
    errors = []
    warnings = []
    for rel in REQUIRED_FILES:
        path = run_root / rel
        ok = path.is_file()
        checks.append({"check": "file_exists", "path": rel, "status": "ok" if ok else "failed"})
        if not ok:
            errors.append(f"missing file: {rel}")

    merge_path = run_root / "merge" / "MERGE_RESULT.json"
    delivery_record_path = run_root / "delivery" / "DELIVERY_RECORD.json"
    candidate_path = run_root / "candidates" / "CANDIDATE_POOL.json"

    if merge_path.is_file():
        merge = load_json(merge_path)
        summary = merge.get("summary", {})
        report_count = summary.get("report_include_count", 0)
        checks.append({"check": "merge_report_count", "status": "ok", "value": report_count})
        if merge.get("triage_mode") == "STUB":
            warnings.append("AI triage mode is STUB. Delivery is for pipeline validation only.")
    if delivery_record_path.is_file():
        record = load_json(delivery_record_path)
        checks.append({"check": "delivery_record", "status": "ok", "tracking_rows": record.get("tracking_rows")})
    if candidate_path.is_file():
        pool = load_json(candidate_path)
        if pool.get("summary", {}).get("find_count", 0) != 0:
            errors.append("candidate pool must not create FIND directly")

    status = "passed" if not errors else "failed"
    return {"schema_version": "validation-result-0.1.0", "status": status, "error_count": len(errors), "warning_count": len(warnings), "errors": errors, "warnings": warnings, "checks": checks}


def render_md(result: dict[str, Any]) -> str:
    lines = ["# VALIDATION_RESULT", "", f"- Status: `{result['status']}`", f"- Errors: {result['error_count']}", f"- Warnings: {result['warning_count']}", ""]
    if result.get("errors"):
        lines.extend(["## Errors", ""])
        for item in result["errors"]:
            lines.append(f"- {item}")
        lines.append("")
    if result.get("warnings"):
        lines.extend(["## Warnings", ""])
        for item in result["warnings"]:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate one run output.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    result = validate(run_root)
    out = run_root / "validate"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "VALIDATION_RESULT.json", result)
    (out / "VALIDATION_RESULT.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print("validation summary")
        print(f"  status: {result['status']}")
        print(f"  errors: {result['error_count']}")
        print(f"  warnings: {result['warning_count']}")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
