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
STATUS_BY_RISK = {"sensitive_information": "REVIEW", "configuration_exposure": "REVIEW", "dependency_vulnerability": "CAND", "configuration_risk": "CAND", "static_analysis_finding": "CAND", "tool_output_parse_error": "REVIEW"}
TAXONOMY_BY_RISK_TYPE = {"sensitive_information": ("CRYPTOGRAPHY_SECRETS", "SECRET_LEAKAGE"), "dependency_vulnerability": ("VULNERABLE_DEPENDENCY", "KNOWN_CVE"), "configuration_risk": ("CONFIGURATION_EXPOSURE", "INSECURE_DEFAULT"), "static_analysis_finding": ("CODE_QUALITY_TECH_DEBT", "ERROR_HANDLING_WEAK"), "tool_output_parse_error": ("BUILD_ENGINEERING_GOVERNANCE", "SECURITY_TOOL_BLOCKED")}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fingerprint(parts: list[str]) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def uniq(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def taxonomy_for(item: dict[str, Any]) -> tuple[str | None, str | None]:
    parent = item.get("risk_parent")
    subtype = item.get("risk_subtype")
    if parent and subtype:
        return parent, subtype
    return TAXONOMY_BY_RISK_TYPE.get(item.get("risk_type") or "", (parent, subtype))


def status_for(item: dict[str, Any]) -> str:
    raw = str(item.get("status") or "").upper()
    if raw in INITIAL_AUDIT_STATUSES:
        return raw
    risk_type = item.get("risk_type") or "external_tool_candidate"
    severity = item.get("severity_hint") or "P2"
    if severity in {"P0", "P1"} and risk_type in {"sensitive_information", "dependency_vulnerability", "configuration_risk"}:
        return "REVIEW"
    return STATUS_BY_RISK.get(risk_type, "CAND")


def report_hint(status: str, severity: str) -> bool:
    return status in {"REVIEW", "RUNTIME", "BLOCKED"} and severity in {"P0", "P1", "P2"}


def candidate_key(item: dict[str, Any]) -> str:
    return fingerprint([str(item.get("risk_type") or ""), str(item.get("title") or ""), str(item.get("file_path") or ""), str(item.get("line_start") or ""), str(item.get("source_tool") or item.get("recipe_id") or item.get("source") or "")])


def created_event(candidate_id: str, item: dict[str, Any], status: str) -> dict[str, Any]:
    return {"event_type": "candidate_created", "stage": "candidate_pool", "actor": item.get("source_tool") or "external_tool", "to": {"status": status}, "reason": item.get("title") or "external tool candidate imported", "evidence_refs": [item.get("candidate_id") or ""]}


def normalize_external(item: dict[str, Any], cid: str) -> dict[str, Any]:
    severity = item.get("severity_hint") or "P2"
    status = status_for(item)
    fp = candidate_key(item)
    parent, subtype = taxonomy_for(item)
    tags = uniq([*(item.get("tags") or []), "external_tool", f"tool:{item.get('source_tool')}" if item.get("source_tool") else "", f"profile:{item.get('source_profile')}" if item.get("source_profile") else "", f"risk_parent:{parent}" if parent else "", f"risk_subtype:{subtype}" if subtype else ""])
    events = list(item.get("lifecycle_events") or [])
    events.append(created_event(cid, item, status))
    return {
        "candidate_id": cid,
        "fingerprint": fp,
        "status": status,
        "source": "external_tool",
        "source_hit_id": item.get("candidate_id"),
        "source_tool": item.get("source_tool"),
        "source_profile": item.get("source_profile"),
        "source_profiles": [item.get("source_profile")] if item.get("source_profile") else [],
        "recipe_id": None,
        "risk_type": item.get("risk_type") or "external_tool_candidate",
        "risk_parent": parent,
        "risk_subtype": subtype,
        "title": item.get("title") or "外部工具候选项",
        "severity_hint": severity,
        "confidence_hint": item.get("confidence_hint") or "medium",
        "file_path": item.get("file_path"),
        "line_start": item.get("line_start"),
        "line_end": item.get("line_end") or item.get("line_start"),
        "evidence": item.get("evidence"),
        "matched_pattern": None,
        "negative_evidence_required": item.get("negative_evidence_required") or [],
        "report_hint": report_hint(status, severity),
        "triage_required": True,
        "tags": tags,
        "lifecycle_events": events,
        "business_status": None,
        "verification_status": None,
        "resolution_reason": None,
        "notes": ["候选项由外部安全工具输出归一化生成，不代表漏洞成立。", "正式 FIND 必须经过 AI triage 或人工复核以及 merge 阶段。"],
    }


def ensure_lifecycle_fields(item: dict[str, Any]) -> dict[str, Any]:
    status = status_for(item)
    item["status"] = status
    parent, subtype = taxonomy_for(item)
    item.setdefault("risk_parent", parent)
    item.setdefault("risk_subtype", subtype)
    tags = list(item.get("tags") or [])
    if parent:
        tags.append(f"risk_parent:{parent}")
    if subtype:
        tags.append(f"risk_subtype:{subtype}")
    item["tags"] = uniq([str(x) for x in tags])
    item.setdefault("lifecycle_events", [created_event(item.get("candidate_id") or "", item, status)])
    item.setdefault("business_status", None)
    item.setdefault("verification_status", None)
    item.setdefault("resolution_reason", None)
    return item


def merge_pool(run_root: Path) -> dict[str, Any]:
    pool_path = run_root / "candidates" / "CANDIDATE_POOL.json"
    ext_path = run_root / "candidates" / "EXT_TOOL_CANDIDATES.json"
    pool = load_json(pool_path)
    ext = load_json(ext_path)
    base_candidates = [ensure_lifecycle_fields(dict(item)) for item in (pool.get("candidates") or [])]
    merged = []
    seen: dict[str, str] = {}
    duplicate_external = []
    for item in base_candidates:
        fp = item.get("fingerprint") or candidate_key(item)
        item["fingerprint"] = fp
        seen[fp] = item.get("candidate_id") or ""
        merged.append(item)
    next_index = len(merged) + 1
    imported_count = 0
    for item in ext.get("candidates") or []:
        fp = candidate_key(item)
        if fp in seen:
            duplicate_external.append({"external_candidate_id": item.get("candidate_id"), "merged_into": seen[fp], "fingerprint": fp, "source_tool": item.get("source_tool"), "source_profile": item.get("source_profile")})
            for existing in merged:
                if existing.get("fingerprint") == fp:
                    profiles = existing.setdefault("source_profiles", [])
                    if item.get("source_profile") and item.get("source_profile") not in profiles:
                        profiles.append(item.get("source_profile"))
                    tools = existing.setdefault("source_tools", [])
                    if item.get("source_tool") and item.get("source_tool") not in tools:
                        tools.append(item.get("source_tool"))
                    existing.setdefault("external_duplicate_refs", []).append(item.get("candidate_id"))
                    break
            continue
        cid = f"CAND-{next_index:05d}"
        next_index += 1
        normalized = normalize_external(item, cid)
        seen[normalized["fingerprint"]] = cid
        merged.append(normalized)
        imported_count += 1
    by_status: dict[str, int] = {}
    by_risk_type: dict[str, int] = {}
    by_risk_parent: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for item in merged:
        by_status[item.get("status") or "UNKNOWN"] = by_status.get(item.get("status") or "UNKNOWN", 0) + 1
        by_risk_type[item.get("risk_type") or "unknown"] = by_risk_type.get(item.get("risk_type") or "unknown", 0) + 1
        if item.get("risk_parent"):
            by_risk_parent[item["risk_parent"]] = by_risk_parent.get(item["risk_parent"], 0) + 1
        by_source[item.get("source") or "unknown"] = by_source.get(item.get("source") or "unknown", 0) + 1
    pool["schema_version"] = "candidate-pool-0.3.0"
    pool["lifecycle_spec_ref"] = "spec/rules/audit-lifecycle.yaml"
    pool["summary"] = {**(pool.get("summary") or {}), "total_candidates": len(merged), "base_candidate_count": len(base_candidates), "external_candidate_count": len(ext.get("candidates") or []), "external_candidates_imported": imported_count, "external_duplicates_dropped": len(duplicate_external), "by_status": by_status, "by_risk_type": by_risk_type, "by_risk_parent": by_risk_parent, "by_source": by_source, "find_count": 0, "fp_count": 0, "note": "Candidate pool never creates FIND/FP directly. External tool candidates require AI triage and merge."}
    pool["candidates"] = merged
    pool["external_tool_import"] = {"source_path": str(ext_path), "imported_count": imported_count, "duplicate_count": len(duplicate_external), "duplicates": duplicate_external}
    return pool


def render_md(pool: dict[str, Any]) -> str:
    s = pool["summary"]
    lines = ["# CANDIDATE_POOL", "", "## Summary", "", f"- Total candidates: {s['total_candidates']}", f"- Base candidates: {s.get('base_candidate_count', '-')}", f"- External candidates: {s.get('external_candidate_count', '-')}", f"- External imported: {s.get('external_candidates_imported', '-')}", f"- External duplicates dropped: {s.get('external_duplicates_dropped', '-')}", "- FIND count: 0", "- FP count: 0", "", "## By source", ""]
    for key, value in sorted(s.get("by_source", {}).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## By status", ""])
    for key, value in sorted(s.get("by_status", {}).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Candidates", ""])
    if not pool.get("candidates"):
        lines.append("- None")
    for item in pool.get("candidates", [])[:200]:
        loc = item.get("file_path") or "-"
        if item.get("line_start"):
            loc += f":{item.get('line_start')}"
        source = item.get("source") or "-"
        if item.get("source_tool"):
            source += f"/{item.get('source_tool')}"
        if item.get("source_profile"):
            source += f"/{item.get('source_profile')}"
        taxonomy = f"{item.get('risk_parent') or '-'}:{item.get('risk_subtype') or '-'}"
        lines.append(f"- `{item['candidate_id']}` `{item.get('status')}` `{taxonomy}` `{source}` `{loc}` {item.get('title')} — {item.get('evidence')}")
    return "\n".join(lines) + "\n"


def print_summary(pool: dict[str, Any]) -> None:
    s = pool["summary"]
    print("candidate-pool merge summary")
    print(f"  total_candidates: {s['total_candidates']}")
    print(f"  base_candidate_count: {s.get('base_candidate_count')}")
    print(f"  external_candidate_count: {s.get('external_candidate_count')}")
    print(f"  external_candidates_imported: {s.get('external_candidates_imported')}")
    print(f"  external_duplicates_dropped: {s.get('external_duplicates_dropped')}")
    print(f"  by_source: {s.get('by_source')}")
    print(f"  by_risk_type: {s.get('by_risk_type')}")
    print(f"  by_risk_parent: {s.get('by_risk_parent')}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Merge external tool candidates into the main candidate pool.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    pool_path = run_root / "candidates" / "CANDIDATE_POOL.json"
    ext_path = run_root / "candidates" / "EXT_TOOL_CANDIDATES.json"
    if not pool_path.is_file():
        print("[FAIL] CANDIDATE_POOL.json not found. Run candidates first.", file=sys.stderr)
        return 2
    if not ext_path.is_file():
        print("[FAIL] EXT_TOOL_CANDIDATES.json not found. Run ext-tool-candidates first.", file=sys.stderr)
        return 2
    original = load_json(pool_path)
    backup_path = run_root / "candidates" / "CANDIDATE_POOL.base.json"
    if not backup_path.is_file():
        write_json(backup_path, original)
    pool = merge_pool(run_root)
    write_json(pool_path, pool)
    (run_root / "candidates" / "CANDIDATE_POOL.md").write_text(render_md(pool), encoding="utf-8")
    write_json(run_root / "candidates" / "CANDIDATE_POOL_MERGE_TRACE.json", pool.get("external_tool_import") or {})
    if args.print_summary:
        print_summary(pool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
