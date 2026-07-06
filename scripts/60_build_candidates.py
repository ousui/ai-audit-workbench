#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INITIAL_AUDIT_STATUSES = {"CAND", "REVIEW", "RUNTIME", "BLOCKED"}
REPORT_STATUSES = {"REVIEW", "RUNTIME", "BLOCKED"}
TAXONOMY_BY_RISK_TYPE = {
    "sensitive_information": ("CRYPTOGRAPHY_SECRETS", "SECRET_HARDCODED"),
    "configuration_exposure": ("CONFIGURATION_EXPOSURE", "CONFIG_FILE_EXPOSURE"),
    "sql_injection_candidate": ("INPUT_INJECTION", "SQL_INJECTION"),
    "client_storage_candidate": ("FRONTEND_CLIENT_SECURITY", "SENSITIVE_DATA_IN_CLIENT_STORAGE"),
    "file_io_candidate": ("FILE_OPERATION", "FILE_OPERATION_REVIEW"),
    "business_logic_review_candidate": ("BUSINESS_LOGIC", "BUSINESS_LOGIC_REVIEW"),
    "dependency_vulnerability": ("VULNERABLE_DEPENDENCY", "KNOWN_CVE"),
    "configuration_risk": ("CONFIGURATION_EXPOSURE", "INSECURE_DEFAULT"),
    "static_analysis_finding": ("CODE_QUALITY_TECH_DEBT", "ERROR_HANDLING_WEAK"),
    "build_engineering_governance": ("BUILD_ENGINEERING_GOVERNANCE", "BUILD_NOT_REPRODUCIBLE"),
    "tool_output_parse_error": ("BUILD_ENGINEERING_GOVERNANCE", "SECURITY_TOOL_BLOCKED"),
}


def load_json(path: Path) -> dict[str, Any] | list[Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fingerprint(parts: list[str]) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def uniq(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not value or value in result:
            continue
        result.append(value)
    return result


def taxonomy_for(item: dict[str, Any]) -> tuple[str | None, str | None]:
    risk_parent = item.get("risk_parent")
    risk_subtype = item.get("risk_subtype")
    if risk_parent and risk_subtype:
        return risk_parent, risk_subtype
    return TAXONOMY_BY_RISK_TYPE.get(item.get("risk_type") or "", (risk_parent, risk_subtype))


def initial_status(hit: dict[str, Any]) -> str:
    raw = str(hit.get("status") or "").upper()
    if raw in INITIAL_AUDIT_STATUSES:
        return raw
    risk_type = hit.get("risk_type") or ""
    if risk_type in {"sensitive_information", "configuration_exposure", "business_logic_review_candidate", "build_engineering_governance", "tool_output_parse_error"}:
        return "REVIEW"
    return "CAND"


def report_hint(status: str, severity: str) -> bool:
    return status in REPORT_STATUSES and severity in {"P0", "P1", "P2"}


def default_tags(item: dict[str, Any], status: str, risk_parent: str | None, risk_subtype: str | None) -> list[str]:
    tags = list(item.get("tags") or [])
    source = item.get("source") or "static_pattern_scan"
    tags.append(str(source))
    if item.get("source_tool"):
        tags.append(f"tool:{item.get('source_tool')}")
    if risk_parent:
        tags.append(f"risk_parent:{risk_parent}")
    if risk_subtype:
        tags.append(f"risk_subtype:{risk_subtype}")
    if status == "RUNTIME":
        tags.append("needs_runtime")
    if status == "BLOCKED":
        tags.append("tool_blocked")
    if risk_parent == "BUILD_ENGINEERING_GOVERNANCE":
        tags.append("engineering_governance")
    return uniq([str(x) for x in tags])


def created_event(candidate_id: str, source_item: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "event_type": "candidate_created",
        "stage": "candidate_pool",
        "actor": source_item.get("source") or source_item.get("source_tool") or "static_pattern_scan",
        "to": {"status": status},
        "reason": source_item.get("title") or "candidate generated from deterministic evidence",
        "evidence_refs": [source_item.get("hit_id") or source_item.get("candidate_id") or ""],
    }


def load_governance_candidates(run_root: Path) -> list[dict[str, Any]]:
    path = run_root / "candidates" / "ENGINEERING_GOVERNANCE_CANDIDATES.json"
    if not path.is_file():
        return []
    data = load_json(path)
    if isinstance(data, dict):
        return data.get("candidates") or []
    if isinstance(data, list):
        return data
    return []


def append_candidate(candidates: list[dict[str, Any]], seen: dict[str, str], source_item: dict[str, Any], fp_parts: list[str]) -> bool:
    fp = fingerprint(fp_parts)
    if fp in seen:
        return False
    cid = f"CAND-{len(candidates) + 1:05d}"
    seen[fp] = cid
    status = initial_status(source_item)
    severity = source_item.get("severity_hint") or "P2"
    risk_parent, risk_subtype = taxonomy_for(source_item)
    events = list(source_item.get("lifecycle_events") or [])
    events.append(created_event(cid, source_item, status))
    candidates.append({
        "candidate_id": cid,
        "fingerprint": fp,
        "status": status,
        "source": source_item.get("source") or "static_pattern_scan",
        "source_hit_id": source_item.get("hit_id") or source_item.get("candidate_id"),
        "recipe_id": source_item.get("recipe_id"),
        "risk_type": source_item.get("risk_type") or "static_candidate",
        "risk_parent": risk_parent,
        "risk_subtype": risk_subtype,
        "title": source_item.get("title") or "静态候选项",
        "severity_hint": severity,
        "confidence_hint": source_item.get("confidence_hint") or "medium",
        "file_path": source_item.get("file_path"),
        "line_start": source_item.get("line_start"),
        "line_end": source_item.get("line_end"),
        "evidence": source_item.get("evidence") or source_item.get("evidence_preview"),
        "matched_pattern": source_item.get("matched_pattern"),
        "negative_evidence_required": source_item.get("negative_evidence_required") or [],
        "report_hint": report_hint(status, severity),
        "triage_required": True,
        "tags": default_tags(source_item, status, risk_parent, risk_subtype),
        "lifecycle_events": events,
        "business_status": None,
        "verification_status": None,
        "resolution_reason": None,
        "notes": source_item.get("notes") or ["候选项由确定性扫描或流程证据生成，不代表漏洞成立。", "Candidate pool 初始阶段不得直接产生 FIND/FP。"],
        "references": {"assisted_change_log_ref": source_item.get("assisted_change_log_ref")} if source_item.get("assisted_change_log_ref") else {},
    })
    return True


def build_candidates(run_root: Path) -> dict[str, Any]:
    pack = load_json(run_root / "evidence" / "EVIDENCE_PACK.json")
    tool_result = load_json(run_root / "evidence" / "TOOL_RUN_RESULT.json")
    assert isinstance(pack, dict)
    assert isinstance(tool_result, dict)
    hits = tool_result.get("hits") or []
    governance_items = load_governance_candidates(run_root)
    candidates: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    duplicate_count = 0
    for hit in hits:
        ok = append_candidate(candidates, seen, hit, [str(hit.get("recipe_id") or ""), str(hit.get("risk_type") or ""), str(hit.get("file_path") or ""), str(hit.get("line_start") or ""), str(hit.get("matched_pattern") or "")])
        if not ok:
            duplicate_count += 1
    for item in governance_items:
        ok = append_candidate(candidates, seen, item, [str(item.get("source") or "engineering_governance"), str(item.get("risk_parent") or ""), str(item.get("risk_subtype") or ""), str(item.get("title") or ""), str(item.get("evidence") or "")])
        if not ok:
            duplicate_count += 1
    by_status: dict[str, int] = {}
    by_risk_type: dict[str, int] = {}
    by_risk_parent: dict[str, int] = {}
    for item in candidates:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
        by_risk_type[item["risk_type"]] = by_risk_type.get(item["risk_type"], 0) + 1
        if item.get("risk_parent"):
            by_risk_parent[item["risk_parent"]] = by_risk_parent.get(item["risk_parent"], 0) + 1
    return {
        "schema_version": "candidate-pool-0.3.0",
        "lifecycle_spec_ref": "spec/rules/audit-lifecycle.yaml",
        "run": pack.get("run"),
        "project": {"project_code": pack.get("project", {}).get("project_code"), "project_name": pack.get("project", {}).get("project_name")},
        "summary": {
            "total_candidates": len(candidates),
            "duplicate_hits_dropped": duplicate_count,
            "governance_candidates_imported": len(governance_items),
            "by_status": by_status,
            "by_risk_type": by_risk_type,
            "by_risk_parent": by_risk_parent,
            "find_count": 0,
            "fp_count": 0,
            "note": "Candidate pool never creates FIND/FP directly.",
        },
        "candidates": candidates,
        "not_reported_yet": {"reason": "Candidates require AI triage and merge before business delivery."},
    }


def render_md(pool: dict[str, Any]) -> str:
    lines = ["# CANDIDATE_POOL", "", "## Summary", "", f"- Total candidates: {pool['summary']['total_candidates']}", f"- Duplicate hits dropped: {pool['summary']['duplicate_hits_dropped']}", f"- Governance candidates imported: {pool['summary'].get('governance_candidates_imported', 0)}", "- FIND count: 0", "- FP count: 0", "", "## By status", ""]
    for key, value in sorted(pool["summary"].get("by_status", {}).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## By risk parent", ""])
    for key, value in sorted(pool["summary"].get("by_risk_parent", {}).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Candidates", ""])
    if not pool.get("candidates"):
        lines.append("- None")
    for item in pool.get("candidates", [])[:120]:
        loc = f"{item.get('file_path')}:{item.get('line_start')}" if item.get("file_path") else "-"
        taxonomy = f"{item.get('risk_parent') or '-'}:{item.get('risk_subtype') or '-'}"
        tags = ",".join(item.get("tags") or [])
        lines.append(f"- `{item['candidate_id']}` `{item.get('status')}` `{taxonomy}` `{loc}` {item.get('title')} — {item.get('evidence')} tags=[{tags}]")
    lines.append("")
    return "\n".join(lines)


def print_summary(pool: dict[str, Any]) -> None:
    print("candidate-pool summary")
    print(f"  total_candidates: {pool['summary']['total_candidates']}")
    print(f"  duplicate_hits_dropped: {pool['summary']['duplicate_hits_dropped']}")
    print(f"  governance_candidates_imported: {pool['summary'].get('governance_candidates_imported', 0)}")
    print(f"  by_status: {pool['summary'].get('by_status')}")
    print(f"  by_risk_type: {pool['summary'].get('by_risk_type')}")
    print(f"  by_risk_parent: {pool['summary'].get('by_risk_parent')}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build candidate pool from deterministic tool results.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    if not (run_root / "evidence" / "TOOL_RUN_RESULT.json").is_file():
        print("[FAIL] TOOL_RUN_RESULT.json not found. Run make m5 first.", file=sys.stderr)
        return 2
    pool = build_candidates(run_root)
    out = run_root / "candidates"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "CANDIDATE_POOL.json", pool)
    (out / "CANDIDATE_POOL.md").write_text(render_md(pool), encoding="utf-8")
    if args.print_summary:
        print_summary(pool)
    else:
        print(f"candidate pool written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
