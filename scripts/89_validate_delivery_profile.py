#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "spec" / "delivery" / "delivery-profile.default.yaml"
ALLOWED_STATUSES = {"FIND", "REVIEW", "RUNTIME", "BLOCKED", "FP", "CAND"}
BUSINESS_STATUSES = {"FIND", "REVIEW", "RUNTIME", "BLOCKED"}
QUALITY_STATUSES = {"FP", "CAND"}
ALLOWED_FIELDS = {
    "finding_id", "item_id", "candidate_id", "audit_status", "delivery_scope", "quality_scope",
    "business_status", "verification_status", "resolution_reason",
    "severity", "confidence", "risk_parent", "risk_subtype", "risk_type", "title",
    "file_path", "line", "evidence", "risk_chain", "impact", "remediation_advice",
    "reason", "negative_evidence_checked", "missing_evidence", "questions_for_human",
    "tags", "owner", "due_date", "business_comment", "audit_comment", "knowledge_hit_count",
    "qc_required", "source_hit_id", "fingerprint",
}
ALLOWED_STATS = {"by_status", "by_severity", "by_category", "by_category_severity"}
ALLOWED_SECTIONS = {
    "executive_summary", "audit_scope", "business_delivery_overview", "audit_quality_overview",
    "stats_by_status", "stats_by_severity", "stats_by_category", "stats_by_category_severity",
    "findings", "review_items", "runtime_items", "blocked_items", "audit_quality_appendix",
    "limitations", "process_notes",
}
SAFE_OUTPUT_RE = re.compile(r"^[A-Za-z0-9_.-]+\.csv$")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_path(value: str) -> Path:
    raw = Path(value)
    return raw if raw.is_absolute() else ROOT / raw


def validate_table(name: str, raw: Any, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(raw, dict):
        errors.append(f"tables.{name} must be object")
        return
    if raw.get("enabled") is False:
        return
    output = raw.get("output")
    if not isinstance(output, str) or not SAFE_OUTPUT_RE.match(output):
        errors.append(f"tables.{name}.output must be a safe csv filename")
    statuses = raw.get("include_status") or []
    if not isinstance(statuses, list) or not statuses:
        errors.append(f"tables.{name}.include_status must be non-empty list")
        statuses = []
    invalid_statuses = [str(x) for x in statuses if str(x) not in ALLOWED_STATUSES]
    if invalid_statuses:
        errors.append(f"tables.{name}.include_status has invalid statuses: {', '.join(invalid_statuses)}")
    status_set = {str(x) for x in statuses}
    if name == "business_tracking" and status_set - BUSINESS_STATUSES:
        errors.append("business_tracking must not include FP/CAND")
    if name == "audit_quality_items" and status_set - QUALITY_STATUSES:
        errors.append("audit_quality_items must only include FP/CAND")
    fields = raw.get("fields") or []
    if not isinstance(fields, list) or not fields:
        errors.append(f"tables.{name}.fields must be non-empty list")
        fields = []
    invalid_fields = [str(x) for x in fields if str(x) not in ALLOWED_FIELDS]
    if invalid_fields:
        errors.append(f"tables.{name}.fields has unsupported fields: {', '.join(invalid_fields)}")
    if name == "business_tracking" and "audit_status" not in fields:
        warnings.append("business_tracking.fields should include audit_status")
    if name == "audit_quality_items" and "quality_scope" not in fields:
        warnings.append("audit_quality_items.fields should include quality_scope")


def validate_stats(raw: Any, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(raw, dict):
        errors.append("stats must be object")
        return
    if raw.get("enabled") is False:
        return
    outputs = raw.get("outputs") or {}
    if not isinstance(outputs, dict) or not outputs:
        errors.append("stats.outputs must be non-empty object when stats is enabled")
        return
    invalid = [k for k in outputs.keys() if k not in ALLOWED_STATS]
    if invalid:
        errors.append("stats.outputs has unsupported stats: " + ", ".join(invalid))
    for key, value in outputs.items():
        if key in ALLOWED_STATS and (not isinstance(value, str) or not SAFE_OUTPUT_RE.match(value)):
            errors.append(f"stats.outputs.{key} must be a safe csv filename")
    scopes = raw.get("scopes") or []
    for scope in scopes:
        if scope not in {"all", "business", "audit_quality"}:
            warnings.append(f"stats.scopes has unknown scope: {scope}")


def validate_report(raw: Any, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(raw, dict):
        errors.append("report must be object")
        return
    sections = raw.get("sections") or []
    if not isinstance(sections, list) or not sections:
        errors.append("report.sections must be non-empty list")
        sections = []
    invalid = [str(x) for x in sections if str(x) not in ALLOWED_SECTIONS]
    if invalid:
        errors.append("report.sections has unsupported sections: " + ", ".join(invalid))
    for recommended in ["executive_summary", "business_delivery_overview", "findings", "limitations"]:
        if recommended not in sections:
            warnings.append(f"report.sections does not include recommended section: {recommended}")


def validate_profile(profile_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not profile_path.is_file():
        errors.append(f"profile file not found: {profile_path}")
        profile = {}
    else:
        try:
            profile = load_yaml(profile_path)
        except Exception as exc:
            errors.append(f"failed to parse profile yaml: {exc}")
            profile = {}
    if profile.get("schema_version") != "delivery-profile-0.1.0":
        errors.append(f"schema_version must be delivery-profile-0.1.0, got {profile.get('schema_version')}")
    tables = profile.get("tables") or {}
    if not isinstance(tables, dict):
        errors.append("tables must be object")
        tables = {}
    for name in ["business_tracking", "audit_quality_items", "all_items"]:
        if name in tables:
            validate_table(name, tables.get(name), errors, warnings)
        elif name in {"business_tracking", "audit_quality_items"}:
            errors.append(f"tables.{name} is required")
    validate_stats(profile.get("stats"), errors, warnings)
    validate_report(profile.get("report"), errors, warnings)
    return {
        "schema_version": "delivery-profile-validation-result-0.1.0",
        "generated_at": now(),
        "profile": str(profile_path),
        "status": "passed" if not errors else "failed",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def render_md(result: dict[str, Any]) -> str:
    lines = [
        "# DELIVERY_PROFILE_VALIDATION_RESULT", "",
        f"- Status: `{result['status']}`",
        f"- Profile: `{result.get('profile')}`",
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
    print("delivery-profile-validation summary")
    print(f"  status: {result['status']}")
    print(f"  profile: {result.get('profile')}")
    print(f"  errors: {result['error_count']}")
    print(f"  warnings: {result['warning_count']}")
    for error in result.get("errors") or []:
        print(f"  error: {error}")
    for warning in (result.get("warnings") or [])[:8]:
        print(f"  warning: {warning}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate delivery profile configuration.")
    parser.add_argument("--profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    profile_path = resolve_path(args.profile)
    result = validate_profile(profile_path)
    out = ROOT / "var" / "tmp" / "delivery-profile"
    write_json(out / "DELIVERY_PROFILE_VALIDATION_RESULT.json", result)
    (out / "DELIVERY_PROFILE_VALIDATION_RESULT.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
