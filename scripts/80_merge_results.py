#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DECISION_BUCKETS = {"FIND": "findings", "REVIEW": "review_items", "RUNTIME": "runtime_items", "CAND": "candidate_items", "FP": "fp_items", "BLOCKED": "blocked_items"}
REPORT_DECISIONS = {"FIND", "REVIEW", "RUNTIME", "BLOCKED"}
SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def candidate_by_id(pool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("candidate_id"): item for item in pool.get("candidates", []) if item.get("candidate_id")}


def uniq(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def audit_decision_event(candidate: dict[str, Any], triage: dict[str, Any], decision: str) -> dict[str, Any]:
    event = triage.get("lifecycle_event")
    if isinstance(event, dict):
        return event
    return {"event_type": "audit_decision", "stage": "merge", "actor": "merge", "from": {"status": candidate.get("status") or "CAND"}, "to": {"status": decision}, "reason": triage.get("reason") or "merged decision", "evidence_refs": [candidate.get("candidate_id") or ""]}


def default_business_status(decision: str) -> str | None:
    return "PENDING" if decision == "FIND" else None


def default_verification_status(decision: str) -> str | None:
    return "PENDING" if decision == "FIND" else None


def build_record(seq: int, decision: str, triage: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    risk_id = f"{decision}-{seq:05d}"
    tags = uniq([*(candidate.get("tags") or []), *(triage.get("tags") or [])])
    events = list(candidate.get("lifecycle_events") or [])
    events.append(audit_decision_event(candidate, triage, decision))
    severity = triage.get("severity") or candidate.get("severity_hint") or "P2"
    return {
        "risk_id": risk_id,
        "decision": decision,
        "status": decision,
        "source_candidate_id": candidate.get("candidate_id"),
        "source_hit_id": candidate.get("source_hit_id"),
        "fingerprint": candidate.get("fingerprint"),
        "title": triage.get("title") or candidate.get("title"),
        "risk_type": triage.get("risk_type") or candidate.get("risk_type"),
        "risk_parent": triage.get("risk_parent") or candidate.get("risk_parent"),
        "risk_subtype": triage.get("risk_subtype") or candidate.get("risk_subtype"),
        "severity": severity,
        "confidence": triage.get("confidence") or candidate.get("confidence_hint") or "low",
        "file_path": candidate.get("file_path"),
        "line_start": candidate.get("line_start"),
        "line_end": candidate.get("line_end"),
        "evidence": triage.get("evidence") or candidate.get("evidence"),
        "risk_chain": triage.get("risk_chain") or "",
        "negative_evidence_checked": triage.get("negative_evidence_checked") or [],
        "missing_evidence": triage.get("missing_evidence") or candidate.get("negative_evidence_required") or [],
        "impact": triage.get("impact") or "",
        "recommendation": triage.get("recommendation") or "",
        "reason": triage.get("reason") or "",
        "tags": tags,
        "business_status": candidate.get("business_status") or default_business_status(decision),
        "verification_status": candidate.get("verification_status") or default_verification_status(decision),
        "resolution_reason": candidate.get("resolution_reason"),
        "questions_for_human": triage.get("questions_for_human") or [],
        "knowledge_update_suggestions": triage.get("knowledge_update_suggestions") or [],
        "lifecycle_events": events,
        "report_include": decision in REPORT_DECISIONS,
    }


def sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda x: (SEVERITY_ORDER.get(x.get("severity") or "P4", 9), str(x.get("risk_parent") or "ZZZ"), str(x.get("risk_subtype") or "ZZZ"), str(x.get("risk_id") or "")))


def merge(run_root: Path) -> dict[str, Any]:
    pack = load_json(run_root / "evidence" / "EVIDENCE_PACK.json")
    pool = load_json(run_root / "candidates" / "CANDIDATE_POOL.json")
    triage = load_json(run_root / "ai" / "AI_TRIAGE_RESULT.json")
    candidates = candidate_by_id(pool)
    result: dict[str, Any] = {
        "schema_version": "merge-result-0.2.0",
        "lifecycle_spec_ref": "spec/rules/audit-lifecycle.yaml",
        "run": pack.get("run"),
        "project": {"project_code": pack.get("project", {}).get("project_code"), "project_name": pack.get("project", {}).get("project_name")},
        "triage_mode": triage.get("triage_mode"),
        "summary": {"find_count": 0, "review_count": 0, "runtime_count": 0, "candidate_count": 0, "fp_count": 0, "blocked_count": 0, "report_include_count": 0, "unknown_candidate_refs": 0},
        "findings": [],
        "review_items": [],
        "runtime_items": [],
        "candidate_items": [],
        "fp_items": [],
        "blocked_items": [],
        "id_map": [],
        "knowledge_update_suggestions": list(triage.get("knowledge_update_suggestions") or []),
        "notes": [],
    }
    seq_by_decision: dict[str, int] = {key: 0 for key in DECISION_BUCKETS}
    handled_candidates = set()
    for item in triage.get("items", []):
        cid = item.get("candidate_id")
        candidate = candidates.get(cid)
        if not candidate:
            result["summary"]["unknown_candidate_refs"] += 1
            continue
        handled_candidates.add(cid)
        decision = item.get("decision") or "CAND"
        if decision not in DECISION_BUCKETS:
            decision = "CAND"
        seq_by_decision[decision] += 1
        record = build_record(seq_by_decision[decision], decision, item, candidate)
        result[DECISION_BUCKETS[decision]].append(record)
        result["id_map"].append({"candidate_id": cid, "target_id": record["risk_id"], "decision": decision})
        result["knowledge_update_suggestions"].extend(record.get("knowledge_update_suggestions") or [])
    for cid, candidate in candidates.items():
        if cid in handled_candidates:
            continue
        seq_by_decision["CAND"] += 1
        record = build_record(seq_by_decision["CAND"], "CAND", {}, candidate)
        result["candidate_items"].append(record)
        result["id_map"].append({"candidate_id": cid, "target_id": record["risk_id"], "decision": "CAND"})
    for key in ["findings", "review_items", "runtime_items", "candidate_items", "fp_items", "blocked_items"]:
        result[key] = sort_items(result[key])
    result["summary"].update({"find_count": len(result["findings"]), "review_count": len(result["review_items"]), "runtime_count": len(result["runtime_items"]), "candidate_count": len(result["candidate_items"]), "fp_count": len(result["fp_items"]), "blocked_count": len(result["blocked_items"]), "report_include_count": len(result["findings"]) + len(result["review_items"]) + len(result["runtime_items"]) + len(result["blocked_items"])})
    if triage.get("triage_mode") == "STUB":
        result["notes"].append("AI triage result is STUB. Delivery is for pipeline validation only.")
    return result


def render_md(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = ["# MERGE_RESULT", "", "## Summary", "", f"- Triage mode: `{result.get('triage_mode')}`", f"- FIND: {s['find_count']}", f"- REVIEW: {s['review_count']}", f"- RUNTIME: {s['runtime_count']}", f"- CAND: {s['candidate_count']}", f"- FP: {s['fp_count']}", f"- BLOCKED: {s['blocked_count']}", ""]
    for key, title in [("findings", "FIND"), ("review_items", "REVIEW"), ("runtime_items", "RUNTIME"), ("blocked_items", "BLOCKED"), ("candidate_items", "CAND")]:
        lines.extend([f"## {title}", ""])
        items = result.get(key) or []
        if not items:
            lines.append("- None")
        for item in items[:80]:
            taxonomy = f"{item.get('risk_parent') or '-'}:{item.get('risk_subtype') or '-'}"
            lines.append(f"- `{item['risk_id']}` `{item.get('severity')}` `{taxonomy}` `{item.get('file_path')}:{item.get('line_start')}` {item.get('title')}")
        lines.append("")
    if result.get("notes"):
        lines.extend(["## Notes", ""])
        for note in result["notes"]:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    s = result["summary"]
    print("merge summary")
    print(f"  triage_mode: {result.get('triage_mode')}")
    print(f"  FIND: {s['find_count']}")
    print(f"  REVIEW: {s['review_count']}")
    print(f"  RUNTIME: {s['runtime_count']}")
    print(f"  CAND: {s['candidate_count']}")
    print(f"  FP: {s['fp_count']}")
    print(f"  BLOCKED: {s['blocked_count']}")
    print(f"  report_include_count: {s['report_include_count']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Merge candidate pool and AI triage result.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not (run_root / "ai" / "AI_TRIAGE_RESULT.json").is_file():
        print("[FAIL] AI_TRIAGE_RESULT.json not found. Run make m7 first or provide AI output.", file=sys.stderr)
        return 2
    result = merge(run_root)
    out = run_root / "merge"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "MERGE_RESULT.json", result)
    (out / "MERGE_RESULT.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    else:
        print(f"merge result written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
