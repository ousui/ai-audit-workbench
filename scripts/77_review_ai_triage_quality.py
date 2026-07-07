#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HIGH_RISK_PARENTS = {
    "CRYPTOGRAPHY_SECRETS",
    "INPUT_INJECTION",
    "ACCESS_CONTROL",
    "AUTHENTICATION_SESSION",
    "BUSINESS_LOGIC",
    "FILE_OPERATION",
    "DATA_PROTECTION_PRIVACY",
}
REPORT_DECISIONS = {"FIND", "REVIEW", "RUNTIME", "BLOCKED"}
LOW_VALUE_ONLY_DECISIONS = {"CAND", "REVIEW"}
COUNTEREVIDENCE_KEYWORDS = [
    "反证", "非", "不是", "未进入", "没有", "不构成", "不可达", "无", "缺少", "not", "no ", "non-", "without", "not a", "no sql", "no sink", "non sql", "non-sql", "not reachable",
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def text_len(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value.strip())
    if isinstance(value, list):
        return sum(text_len(x) for x in value)
    if isinstance(value, dict):
        return sum(text_len(x) for x in value.values())
    return len(str(value).strip())


def normalize_reason(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"\s+", " ", value.strip().lower())
    return value


def has_counterevidence(item: dict[str, Any]) -> bool:
    fields = [
        item.get("reason"),
        item.get("negative_evidence_checked"),
        item.get("missing_evidence"),
        item.get("evidence"),
        item.get("risk_chain"),
    ]
    blob = "\n".join(json.dumps(x, ensure_ascii=False) if not isinstance(x, str) else x for x in fields if x)
    blob_l = blob.lower()
    return bool(item.get("negative_evidence_checked")) or any(k.lower() in blob_l for k in COUNTEREVIDENCE_KEYWORDS)


def candidate_map(pool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("candidate_id"): item for item in pool.get("candidates", []) if item.get("candidate_id")}


def distribution(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter = collections.Counter(str(item.get(key) or "") for item in items)
    return dict(sorted(counter.items(), key=lambda x: (-x[1], x[0])))


def top_reason_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = [normalize_reason(item.get("reason")) for item in items if normalize_reason(item.get("reason"))]
    if not reasons:
        return {"unique": 0, "total": 0, "top_reason_ratio": 0.0, "top_reason": ""}
    counts = collections.Counter(reasons)
    top, n = counts.most_common(1)[0]
    return {"unique": len(counts), "total": len(reasons), "top_reason_ratio": round(n / len(reasons), 4), "top_reason": top[:240]}


def initial_status_match_ratio(items: list[dict[str, Any]], candidates: dict[str, dict[str, Any]]) -> float:
    total = 0
    matched = 0
    for item in items:
        cid = item.get("candidate_id")
        if cid not in candidates:
            continue
        total += 1
        if str(item.get("decision") or "") == str(candidates[cid].get("status") or ""):
            matched += 1
    return round(matched / total, 4) if total else 0.0


def quality_issue(code: str, severity: str, message: str, candidate_id: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if candidate_id:
        item["candidate_id"] = candidate_id
    if details:
        item["details"] = details
    return item


def review_find(item: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    cid = item.get("candidate_id")
    required = {
        "evidence": 20,
        "risk_chain": 30,
        "impact": 20,
        "recommendation": 20,
        "reason": 30,
    }
    for field, minimum in required.items():
        if text_len(item.get(field)) < minimum:
            issues.append(quality_issue("find_weak_field", "error", f"FIND has weak or missing {field}", cid, {"field": field, "min_length": minimum, "actual_length": text_len(item.get(field))}))
    if not item.get("negative_evidence_checked"):
        issues.append(quality_issue("find_missing_negative_evidence", "error", "FIND must include negative_evidence_checked", cid))


def review_fp(item: dict[str, Any], candidate: dict[str, Any] | None, issues: list[dict[str, Any]], fp_qc_items: list[dict[str, Any]]) -> None:
    cid = item.get("candidate_id")
    risk_parent = item.get("risk_parent") or (candidate or {}).get("risk_parent")
    severity = item.get("severity") or (candidate or {}).get("severity_hint")
    confidence = item.get("confidence")
    score = 0
    reasons: list[str] = []
    if severity in {"P0", "P1"}:
        score += 3
        reasons.append(f"severity={severity}")
    if risk_parent in HIGH_RISK_PARENTS:
        score += 3
        reasons.append(f"high_risk_parent={risk_parent}")
    if confidence == "low":
        score += 3
        reasons.append("confidence=low")
    elif confidence == "medium":
        score += 1
        reasons.append("confidence=medium")
    if text_len(item.get("reason")) < 30:
        score += 2
        reasons.append("short_reason")
        issues.append(quality_issue("fp_reason_too_short", "error", "FP reason is too short", cid, {"actual_length": text_len(item.get("reason"))}))
    if not has_counterevidence(item):
        score += 2
        reasons.append("missing_counterevidence")
        issues.append(quality_issue("fp_missing_counterevidence", "error", "FP must include clear counterevidence or negative_evidence_checked", cid))
    if score >= 3:
        fp_qc_items.append({
            "candidate_id": cid,
            "decision": "FP",
            "severity": severity,
            "confidence": confidence,
            "risk_parent": risk_parent,
            "fp_review_score": score,
            "qc_required": True,
            "reasons": reasons,
        })


def review_runtime(item: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    cid = item.get("candidate_id")
    if not item.get("missing_evidence") and not item.get("questions_for_human"):
        issues.append(quality_issue("runtime_missing_validation_gap", "error", "RUNTIME must include missing_evidence or questions_for_human", cid))


def review_distribution(items: list[dict[str, Any]], candidates: dict[str, dict[str, Any]], triage_mode: str, issues: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    total = len(items)
    if not total:
        issues.append(quality_issue("empty_triage_result", "error", "AI_TRIAGE_RESULT contains no items"))
        return
    decisions = distribution(items, "decision")
    decision_keys = {k for k in decisions if k}
    top_decision, top_count = next(iter(decisions.items()))
    top_ratio = top_count / total
    match_ratio = initial_status_match_ratio(items, candidates)
    if triage_mode == "STUB":
        warnings.append(quality_issue("stub_triage", "warning", "STUB triage result is accepted for pipeline validation only", details={"items": total}))
        return
    if total >= 50 and decision_keys.issubset(LOW_VALUE_ONLY_DECISIONS) and not (decision_keys & {"FIND", "FP", "RUNTIME", "BLOCKED"}):
        issues.append(quality_issue("low_value_decision_distribution", "error", "Large triage result only contains CAND/REVIEW and has no FIND/FP/RUNTIME/BLOCKED", details={"decisions": decisions}))
    if total >= 50 and top_ratio >= 0.92:
        warnings.append(quality_issue("excessive_single_decision_ratio", "warning", "One decision dominates the result; review for template output", details={"top_decision": top_decision, "ratio": round(top_ratio, 4)}))
    if total >= 50 and match_ratio >= 0.85:
        issues.append(quality_issue("mirrors_initial_status", "error", "AI decisions closely mirror candidate initial statuses", details={"match_ratio": match_ratio}))


def review_reason_quality(items: list[dict[str, Any]], triage_mode: str, issues: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    stats = top_reason_stats(items)
    if triage_mode == "STUB":
        return
    total = stats["total"]
    if total >= 50:
        unique_ratio = stats["unique"] / total if total else 0.0
        if stats["top_reason_ratio"] >= 0.5 and unique_ratio < 0.1:
            issues.append(quality_issue("template_reason_pattern", "error", "Reason text appears highly templated", details=stats))
        elif stats["top_reason_ratio"] >= 0.35:
            warnings.append(quality_issue("possible_template_reason_pattern", "warning", "Reason text may be templated", details=stats))


def review_items(items: list[dict[str, Any]], candidates: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    fp_qc_items: list[dict[str, Any]] = []
    for item in items:
        decision = item.get("decision")
        candidate = candidates.get(item.get("candidate_id"))
        if decision == "FIND":
            review_find(item, issues)
        elif decision == "FP":
            review_fp(item, candidate, issues, fp_qc_items)
        elif decision == "RUNTIME":
            review_runtime(item, issues)
    return issues, fp_qc_items


def build_result(run_root: Path) -> dict[str, Any]:
    pool = load_json(run_root / "candidates" / "CANDIDATE_POOL.json")
    triage = load_json(run_root / "ai" / "AI_TRIAGE_RESULT.json")
    items = triage.get("items") or []
    if not isinstance(items, list):
        items = []
    candidates = candidate_map(pool)
    triage_mode = triage.get("triage_mode") or ""
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    fp_qc_items: list[dict[str, Any]] = []

    review_distribution(items, candidates, triage_mode, issues, warnings)
    review_reason_quality(items, triage_mode, issues, warnings)
    item_issues, fp_qc_items = review_items(items, candidates)
    issues.extend(item_issues)

    decision_dist = distribution(items, "decision")
    severity_dist = distribution(items, "severity")
    confidence_dist = distribution(items, "confidence")
    reportable_count = sum(v for k, v in decision_dist.items() if k in REPORT_DECISIONS)
    error_count = sum(1 for x in issues if x.get("severity") == "error")
    warning_count = len(warnings) + sum(1 for x in issues if x.get("severity") == "warning")
    status = "passed" if error_count == 0 else "failed"
    return {
        "schema_version": "ai-triage-quality-result-0.1.0",
        "generated_at": now(),
        "status": status,
        "can_continue": status == "passed",
        "triage_mode": triage_mode,
        "summary": {
            "candidate_count": len(pool.get("candidates") or []),
            "triage_items": len(items),
            "decision_distribution": decision_dist,
            "severity_distribution": severity_dist,
            "confidence_distribution": confidence_dist,
            "reportable_count": reportable_count,
            "fp_qc_required_count": len(fp_qc_items),
            "error_count": error_count,
            "warning_count": warning_count,
            "initial_status_match_ratio": initial_status_match_ratio(items, candidates),
            "reason_stats": top_reason_stats(items),
        },
        "blocking_issues": [x for x in issues if x.get("severity") == "error"],
        "warnings": warnings + [x for x in issues if x.get("severity") == "warning"],
        "fp_qc_items": fp_qc_items,
        "notes": [
            "This quality gate detects obvious invalid AI triage patterns; it does not replace human security review.",
            "FP QC items are not sent to business delivery by default, but should be sampled or reviewed inside audit quality control.",
            "STUB triage is accepted only for pipeline validation and must not be treated as an audit conclusion.",
        ],
    }


def render_md(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        "# AI_TRIAGE_QUALITY_RESULT", "",
        f"- Status: `{result['status']}`",
        f"- Can continue: `{result['can_continue']}`",
        f"- Triage mode: `{result.get('triage_mode')}`",
        f"- Candidate count: {s['candidate_count']}",
        f"- Triage items: {s['triage_items']}",
        f"- Reportable count: {s['reportable_count']}",
        f"- FP QC required: {s['fp_qc_required_count']}",
        f"- Errors: {s['error_count']}",
        f"- Warnings: {s['warning_count']}",
        f"- Initial status match ratio: {s['initial_status_match_ratio']}", "",
        "## Decision distribution", "",
    ]
    for key, value in s.get("decision_distribution", {}).items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Blocking issues", ""])
    if not result.get("blocking_issues"):
        lines.append("- None")
    for item in result.get("blocking_issues", [])[:80]:
        cid = f" `{item.get('candidate_id')}`" if item.get("candidate_id") else ""
        lines.append(f"- `{item.get('code')}`{cid}: {item.get('message')}")
    lines.extend(["", "## FP QC items", ""])
    if not result.get("fp_qc_items"):
        lines.append("- None")
    for item in result.get("fp_qc_items", [])[:120]:
        reasons = ", ".join(item.get("reasons") or [])
        lines.append(f"- `{item.get('candidate_id')}` score={item.get('fp_review_score')} severity={item.get('severity')} confidence={item.get('confidence')} risk_parent={item.get('risk_parent')} reasons={reasons}")
    lines.extend(["", "## Warnings", ""])
    if not result.get("warnings"):
        lines.append("- None")
    for item in result.get("warnings", [])[:80]:
        cid = f" `{item.get('candidate_id')}`" if item.get("candidate_id") else ""
        lines.append(f"- `{item.get('code')}`{cid}: {item.get('message')}")
    lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    s = result["summary"]
    print("ai-triage-quality summary")
    print(f"  status: {result['status']}")
    print(f"  can_continue: {result['can_continue']}")
    print(f"  triage_mode: {result.get('triage_mode')}")
    print(f"  triage_items: {s['triage_items']}")
    print(f"  decisions: {s['decision_distribution']}")
    print(f"  errors: {s['error_count']}")
    print(f"  warnings: {s['warning_count']}")
    print(f"  fp_qc_required: {s['fp_qc_required_count']}")
    for item in result.get("blocking_issues", [])[:5]:
        cid = f" {item.get('candidate_id')}" if item.get("candidate_id") else ""
        print(f"  error:{cid} {item.get('code')} - {item.get('message')}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Review AI triage result quality beyond schema validation.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not (run_root / "ai" / "AI_TRIAGE_RESULT.json").is_file():
        print("[FAIL] AI_TRIAGE_RESULT.json not found", file=sys.stderr)
        return 2
    if not (run_root / "candidates" / "CANDIDATE_POOL.json").is_file():
        print("[FAIL] CANDIDATE_POOL.json not found", file=sys.stderr)
        return 2
    result = build_result(run_root)
    out = run_root / "ai"
    write_json(out / "AI_TRIAGE_QUALITY_RESULT.json", result)
    (out / "AI_TRIAGE_QUALITY_RESULT.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
