#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SEVERITY = {"P0", "P1", "P2", "P3", "P4"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
FORBIDDEN_DECISION_FIELDS = {"decision", "audit_status", "business_status", "verification_status", "resolution_reason", "candidate_id"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return True


def validate_item(item: dict[str, Any], idx: int, seen: set[str], errors: list[str], warnings: list[str]) -> None:
    prefix = f"items[{idx}]"
    item_id = str(item.get("deep_review_id") or "")
    if not item_id:
        errors.append(f"{prefix} missing deep_review_id")
    elif item_id in seen:
        errors.append(f"duplicate deep_review_id: {item_id}")
    else:
        seen.add(item_id)
    for field in ["title", "risk_parent", "risk_subtype", "claim", "evidence", "proof_gaps"]:
        if not non_empty(item.get(field)):
            errors.append(f"{prefix} missing required field: {field}")
    severity = item.get("severity_hint") or "P2"
    if severity not in ALLOWED_SEVERITY:
        errors.append(f"{prefix} invalid severity_hint: {severity}")
    confidence = item.get("confidence_hint") or "medium"
    if confidence not in ALLOWED_CONFIDENCE:
        errors.append(f"{prefix} invalid confidence_hint: {confidence}")
    for field in ["evidence_for", "evidence_against", "proof_gaps", "tags", "notes"]:
        if field in item and not isinstance(item.get(field), list):
            errors.append(f"{prefix}.{field} must be an array")
    forbidden = sorted(field for field in FORBIDDEN_DECISION_FIELDS if field in item)
    if forbidden:
        errors.append(f"{prefix} contains forbidden decision/status fields: {', '.join(forbidden)}")
    if not item.get("file_path"):
        warnings.append(f"{prefix} has no file_path; candidate import may require manual mapping")
    if not item.get("evidence_for"):
        warnings.append(f"{prefix} has no evidence_for; triage confidence may be low")
    if not item.get("tags"):
        warnings.append(f"{prefix} has no tags")


def validate_result(run_root: Path) -> dict[str, Any]:
    result_path = run_root / "ai" / "deep-review" / "AI_DEEP_REVIEW_RESULT.json"
    errors: list[str] = []
    warnings: list[str] = []
    if not result_path.is_file():
        return {
            "schema_version": "ai-deep-review-validation-result-0.1.0",
            "generated_at": now(),
            "status": "missing_result",
            "can_continue": False,
            "error_count": 1,
            "warning_count": 0,
            "item_count": 0,
            "errors": ["AI_DEEP_REVIEW_RESULT.json not found"],
            "warnings": [],
        }
    try:
        result = load_json(result_path)
    except Exception as exc:
        return {
            "schema_version": "ai-deep-review-validation-result-0.1.0",
            "generated_at": now(),
            "status": "failed",
            "can_continue": False,
            "error_count": 1,
            "warning_count": 0,
            "item_count": 0,
            "errors": [f"invalid json: {exc}"],
            "warnings": [],
        }
    if result.get("schema_version") != "ai-deep-review-result-0.1.0":
        errors.append(f"schema_version mismatch: {result.get('schema_version')}")
    if result.get("review_mode") != "AI_DEEP_REVIEW":
        errors.append(f"review_mode must be AI_DEEP_REVIEW, got {result.get('review_mode')}")
    items = result.get("items")
    if not isinstance(items, list):
        errors.append("items must be an array")
        items = []
    seen: set[str] = set()
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{idx}] must be object")
            continue
        validate_item(item, idx, seen, errors, warnings)
    status = "passed" if not errors else "failed"
    return {
        "schema_version": "ai-deep-review-validation-result-0.1.0",
        "generated_at": now(),
        "status": status,
        "can_continue": status == "passed",
        "result_ref": "ai/deep-review/AI_DEEP_REVIEW_RESULT.json",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "item_count": len(items),
        "errors": errors,
        "warnings": warnings,
        "notes": [
            "AI Deep Review result only creates candidate discoveries; it must not contain final audit decisions.",
            "Import into candidate pool is a later step and is intentionally not performed by this validator.",
        ],
    }


def render_md(result: dict[str, Any]) -> str:
    lines = [
        "# AI_DEEP_REVIEW_VALIDATION_RESULT", "",
        f"- Status: `{result.get('status')}`",
        f"- Can continue: `{result.get('can_continue')}`",
        f"- Items: {result.get('item_count')}",
        f"- Errors: {result.get('error_count')}",
        f"- Warnings: {result.get('warning_count')}", "",
    ]
    if result.get("errors"):
        lines.extend(["## Errors", ""])
        for item in result["errors"]:
            lines.append(f"- {item}")
        lines.append("")
    if result.get("warnings"):
        lines.extend(["## Warnings", ""])
        for item in result["warnings"][:80]:
            lines.append(f"- {item}")
        if len(result.get("warnings") or []) > 80:
            lines.append(f"- ... remaining warnings: {len(result['warnings']) - 80}")
        lines.append("")
    if result.get("notes"):
        lines.extend(["## Notes", ""])
        for note in result["notes"]:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    print("ai-deep-review-validate summary")
    print(f"  status: {result.get('status')}")
    print(f"  can_continue: {result.get('can_continue')}")
    print(f"  items: {result.get('item_count')}")
    print(f"  errors: {result.get('error_count')}")
    print(f"  warnings: {result.get('warning_count')}")
    for error in result.get("errors") or []:
        print(f"  error: {error}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate AI Deep Review result JSON.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    result = validate_result(run_root)
    out = run_root / "ai" / "deep-review"
    write_json(out / "AI_DEEP_REVIEW_VALIDATION_RESULT.json", result)
    (out / "AI_DEEP_REVIEW_VALIDATION_RESULT.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
