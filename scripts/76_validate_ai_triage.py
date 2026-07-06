#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SCHEMA = "ai-triage-result-0.2.0"
ALLOWED_TRIAGE_MODES = {"FAST_STATIC", "STANDARD_STATIC", "DEEP_STATIC_EXPLORE", "STUB"}
ALLOWED_DECISIONS = {"FIND", "REVIEW", "RUNTIME", "CAND", "FP", "BLOCKED"}
ALLOWED_SEVERITY = {"P0", "P1", "P2", "P3", "P4"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
FORBIDDEN_AI_FIELDS = {"business_status", "verification_status", "resolution_reason", "accepted_risk", "ACCEPTED_RISK"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def candidate_ids(pool: dict[str, Any]) -> set[str]:
    return {str(item.get("candidate_id")) for item in pool.get("candidates", []) if item.get("candidate_id")}


def non_empty(item: dict[str, Any], key: str) -> bool:
    value = item.get(key)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return value is not None


def find_forbidden_fields(obj: dict[str, Any], prefix: str) -> list[str]:
    found = []
    for key, value in obj.items():
        if key in FORBIDDEN_AI_FIELDS:
            found.append(f"{prefix}.{key}")
        if isinstance(value, dict):
            found.extend(find_forbidden_fields(value, f"{prefix}.{key}"))
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                if isinstance(child, dict):
                    found.extend(find_forbidden_fields(child, f"{prefix}.{key}[{idx}]"))
    return found


def validate_suggestion(raw: dict[str, Any], path: str, errors: list[str]) -> None:
    if raw.get("requires_human_approval") is not True:
        errors.append(f"{path}: knowledge suggestion must set requires_human_approval=true")
    if not non_empty(raw, "type"):
        errors.append(f"{path}: knowledge suggestion missing type")
    if not non_empty(raw, "summary"):
        errors.append(f"{path}: knowledge suggestion missing summary")


def validate_item(item: dict[str, Any], idx: int, known_candidates: set[str], seen_candidates: set[str], errors: list[str], warnings: list[str]) -> None:
    cid = str(item.get("candidate_id") or "")
    path = f"items[{idx}]"
    if not cid:
        errors.append(f"{path}: candidate_id is required")
    elif cid not in known_candidates:
        errors.append(f"{path}: unknown candidate_id: {cid}")
    elif cid in seen_candidates:
        errors.append(f"{path}: duplicate candidate_id: {cid}")
    else:
        seen_candidates.add(cid)

    decision = item.get("decision")
    if decision not in ALLOWED_DECISIONS:
        errors.append(f"{path}: invalid decision: {decision}")
    if decision == "ACCEPTED_RISK":
        errors.append(f"{path}: ACCEPTED_RISK is not an audit_status")

    severity = item.get("severity")
    if severity not in ALLOWED_SEVERITY:
        errors.append(f"{path}: invalid severity: {severity}")
    confidence = item.get("confidence")
    if confidence not in ALLOWED_CONFIDENCE:
        errors.append(f"{path}: invalid confidence: {confidence}")

    for field in ["title", "risk_type", "evidence", "reason"]:
        if not non_empty(item, field):
            errors.append(f"{path}: {field} is required")

    if decision == "FIND":
        for field in ["evidence", "risk_chain", "impact", "recommendation", "reason"]:
            if not non_empty(item, field):
                errors.append(f"{path}: FIND requires non-empty {field}")
        if not item.get("negative_evidence_checked"):
            errors.append(f"{path}: FIND requires negative_evidence_checked")
    if decision == "FP" and not non_empty(item, "reason"):
        errors.append(f"{path}: FP requires false-positive reason")
    if decision == "RUNTIME" and not (item.get("questions_for_human") or item.get("missing_evidence") or item.get("reason")):
        warnings.append(f"{path}: RUNTIME should explain required runtime evidence")

    event = item.get("lifecycle_event")
    if event is not None:
        if not isinstance(event, dict):
            errors.append(f"{path}: lifecycle_event must be an object")
        elif event.get("event_type") != "audit_decision":
            errors.append(f"{path}: lifecycle_event.event_type must be audit_decision")

    for sug_idx, raw in enumerate(item.get("knowledge_update_suggestions") or []):
        if isinstance(raw, dict):
            validate_suggestion(raw, f"{path}.knowledge_update_suggestions[{sug_idx}]", errors)
        else:
            errors.append(f"{path}.knowledge_update_suggestions[{sug_idx}]: suggestion must be object")


def validate(run_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    pool_path = run_root / "candidates" / "CANDIDATE_POOL.json"
    result_path = run_root / "ai" / "AI_TRIAGE_RESULT.json"
    if not pool_path.is_file():
        errors.append("CANDIDATE_POOL.json not found")
        return build_result(errors, warnings, checks)
    if not result_path.is_file():
        errors.append("AI_TRIAGE_RESULT.json not found")
        return build_result(errors, warnings, checks)

    pool = load_json(pool_path)
    result = load_json(result_path)
    known_candidates = candidate_ids(pool)
    checks.append({"check": "known_candidates", "status": "ok", "count": len(known_candidates)})

    if result.get("schema_version") != EXPECTED_SCHEMA:
        errors.append(f"schema_version must be {EXPECTED_SCHEMA}, got {result.get('schema_version')}")
    if result.get("triage_mode") not in ALLOWED_TRIAGE_MODES:
        errors.append(f"invalid triage_mode: {result.get('triage_mode')}")

    forbidden = find_forbidden_fields(result, "result")
    if forbidden:
        errors.append("AI triage result contains forbidden lifecycle/business fields: " + ", ".join(forbidden[:20]))

    items = result.get("items")
    if not isinstance(items, list):
        errors.append("items must be an array")
        items = []
    seen_candidates: set[str] = set()
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{idx}] must be object")
            continue
        validate_item(item, idx, known_candidates, seen_candidates, errors, warnings)

    for idx, raw in enumerate(result.get("knowledge_update_suggestions") or []):
        if isinstance(raw, dict):
            validate_suggestion(raw, f"knowledge_update_suggestions[{idx}]", errors)
        else:
            errors.append(f"knowledge_update_suggestions[{idx}]: suggestion must be object")

    if result.get("triage_mode") != "STUB" and not items:
        warnings.append("AI_TRIAGE_RESULT contains no items; merge will keep candidates as CAND")

    checks.append({"check": "ai_triage_items", "status": "ok" if not errors else "failed", "items": len(items), "referenced_candidates": len(seen_candidates)})
    return build_result(errors, warnings, checks)


def build_result(errors: list[str], warnings: list[str], checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "ai-triage-validation-result-0.1.0",
        "generated_at": now(),
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def render_md(result: dict[str, Any]) -> str:
    lines = [
        "# AI_TRIAGE_VALIDATION_RESULT", "",
        f"- Status: `{result['status']}`",
        f"- Errors: {result['error_count']}",
        f"- Warnings: {result['warning_count']}", "",
    ]
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


def print_summary(result: dict[str, Any]) -> None:
    print("ai-triage-validation summary")
    print(f"  status: {result['status']}")
    print(f"  errors: {result['error_count']}")
    print(f"  warnings: {result['warning_count']}")
    for error in result.get("errors") or []:
        print(f"  error: {error}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate AI_TRIAGE_RESULT.json against candidate pool and lifecycle rules.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    result = validate(run_root)
    out = run_root / "ai"
    write_json(out / "AI_TRIAGE_VALIDATION_RESULT.json", result)
    (out / "AI_TRIAGE_VALIDATION_RESULT.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
