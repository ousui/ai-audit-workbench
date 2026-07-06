#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
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
    "knowledge/KB_HITS.json",
    "ai/AI_TRIAGE_INPUT.json",
    "ai/AI_TRIAGE_HANDOFF.md",
    "ai/AI_TRIAGE_RESULT.json",
    "ai/AI_TRIAGE_VALIDATION_RESULT.json",
    "merge/MERGE_RESULT.json",
    "knowledge/KB_UPDATE_SUGGESTIONS.json",
    "delivery/AUDIT_REPORT.md",
    "delivery/AUDIT_REPORT.html",
    "delivery/AUDIT_TRACKING.csv",
    "delivery/DELIVERY_RECORD.json",
]
CANDIDATE_INITIAL_STATUSES = {"CAND", "REVIEW", "RUNTIME", "BLOCKED"}
MERGE_STATUSES = {"CAND", "REVIEW", "FIND", "FP", "RUNTIME", "BLOCKED"}
REQUIRED_TRACKING_HEADERS = {"finding_id", "candidate_id", "audit_status", "business_status", "verification_status", "risk_parent", "risk_subtype", "tags"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_candidate_pool(path: Path, errors: list[str], warnings: list[str], checks: list[dict[str, Any]]) -> None:
    pool = load_json(path)
    if pool.get("summary", {}).get("find_count", 0) != 0:
        errors.append("candidate pool must not create FIND directly")
    if pool.get("summary", {}).get("fp_count", 0) != 0:
        errors.append("candidate pool must not create FP directly")
    bad_status = []
    missing_events = []
    missing_taxonomy = []
    for item in pool.get("candidates", []):
        cid = item.get("candidate_id")
        if item.get("status") not in CANDIDATE_INITIAL_STATUSES:
            bad_status.append(f"{cid}:{item.get('status')}")
        if not item.get("lifecycle_events"):
            missing_events.append(cid)
        if not item.get("risk_parent") or not item.get("risk_subtype"):
            missing_taxonomy.append(cid)
    if bad_status:
        errors.append("candidate pool has invalid initial audit_status: " + ", ".join(bad_status[:20]))
    if missing_events:
        errors.append("candidate pool missing lifecycle_events: " + ", ".join([str(x) for x in missing_events[:20]]))
    if missing_taxonomy:
        warnings.append("candidate pool has candidates missing taxonomy: " + ", ".join([str(x) for x in missing_taxonomy[:20]]))
    checks.append({"check": "candidate_lifecycle_fields", "status": "ok" if not bad_status and not missing_events else "failed", "candidates": len(pool.get("candidates", []))})


def validate_ai_triage_validation(path: Path, errors: list[str], checks: list[dict[str, Any]]) -> None:
    result = load_json(path)
    status = result.get("status")
    checks.append({"check": "ai_triage_validation", "status": status, "errors": result.get("error_count"), "warnings": result.get("warning_count")})
    if status != "passed":
        errors.append(f"AI triage validation failed: {result.get('errors')}")


def validate_knowledge(run_root: Path, errors: list[str], warnings: list[str], checks: list[dict[str, Any]]) -> None:
    hits_path = run_root / "knowledge" / "KB_HITS.json"
    suggestions_path = run_root / "knowledge" / "KB_UPDATE_SUGGESTIONS.json"
    ai_input_path = run_root / "ai" / "AI_TRIAGE_INPUT.json"
    if hits_path.is_file():
        hits = load_json(hits_path)
        if hits.get("schema_version") != "kb-hits-0.1.0":
            errors.append("KB_HITS schema_version mismatch")
        checks.append({"check": "kb_hits", "status": "ok", "total_hits": hits.get("summary", {}).get("total_hits", 0)})
    if suggestions_path.is_file():
        suggestions = load_json(suggestions_path)
        if suggestions.get("schema_version") != "kb-update-suggestions-0.1.0":
            errors.append("KB_UPDATE_SUGGESTIONS schema_version mismatch")
        for item in suggestions.get("suggestions") or []:
            if item.get("requires_human_approval") is not True:
                errors.append(f"knowledge suggestion must require human approval: {item.get('suggestion_id')}")
        checks.append({"check": "kb_update_suggestions", "status": "ok", "total_suggestions": suggestions.get("summary", {}).get("total_suggestions", 0)})
    if ai_input_path.is_file():
        ai_input = load_json(ai_input_path)
        if "knowledge_policy" not in ai_input:
            errors.append("AI_TRIAGE_INPUT missing knowledge_policy")
        checks.append({"check": "ai_knowledge_policy", "status": "ok" if "knowledge_policy" in ai_input else "failed"})


def validate_merge(path: Path, errors: list[str], warnings: list[str], checks: list[dict[str, Any]]) -> None:
    merge = load_json(path)
    summary = merge.get("summary", {})
    checks.append({"check": "merge_report_count", "status": "ok", "value": summary.get("report_include_count", 0)})
    checks.append({"check": "merge_knowledge_hits", "status": "ok", "value": summary.get("knowledge_hit_count", 0)})
    if merge.get("triage_mode") == "STUB":
        warnings.append("AI triage mode is STUB. Delivery is for pipeline validation only.")
    for bucket in ["findings", "review_items", "runtime_items", "candidate_items", "fp_items", "blocked_items"]:
        for item in merge.get(bucket, []):
            status = item.get("status") or item.get("decision")
            if status not in MERGE_STATUSES:
                errors.append(f"merge item has invalid audit_status: {item.get('risk_id')}={status}")
            if not item.get("lifecycle_events"):
                errors.append(f"merge item missing lifecycle_events: {item.get('risk_id')}")
            if status == "FIND" and (item.get("business_status") != "PENDING" or item.get("verification_status") != "PENDING"):
                errors.append(f"FIND must default business_status/verification_status to PENDING: {item.get('risk_id')}")


def validate_tracking(path: Path, errors: list[str], checks: list[dict[str, Any]]) -> None:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            headers = set(next(reader, []))
    except Exception as exc:
        errors.append(f"failed to read tracking csv: {exc}")
        return
    missing = REQUIRED_TRACKING_HEADERS - headers
    if missing:
        errors.append("tracking csv missing lifecycle headers: " + ", ".join(sorted(missing)))
    checks.append({"check": "tracking_lifecycle_headers", "status": "ok" if not missing else "failed", "missing": sorted(missing)})


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
    tracking_path = run_root / "delivery" / "AUDIT_TRACKING.csv"
    ai_validation_path = run_root / "ai" / "AI_TRIAGE_VALIDATION_RESULT.json"
    if candidate_path.is_file():
        validate_candidate_pool(candidate_path, errors, warnings, checks)
    if ai_validation_path.is_file():
        validate_ai_triage_validation(ai_validation_path, errors, checks)
    validate_knowledge(run_root, errors, warnings, checks)
    if merge_path.is_file():
        validate_merge(merge_path, errors, warnings, checks)
    if delivery_record_path.is_file():
        record = load_json(delivery_record_path)
        checks.append({"check": "delivery_record", "status": "ok", "tracking_rows": record.get("tracking_rows")})
    if tracking_path.is_file():
        validate_tracking(tracking_path, errors, checks)
    status = "passed" if not errors else "failed"
    return {"schema_version": "validation-result-0.4.0", "status": status, "error_count": len(errors), "warning_count": len(warnings), "errors": errors, "warnings": warnings, "checks": checks}


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
