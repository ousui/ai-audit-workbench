#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_DECISIONS = {"FIND", "REVIEW", "RUNTIME", "CAND", "FP", "BLOCKED"}
ALLOWED_SEVERITY = {"P0", "P1", "P2", "P3", "P4"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
LOW_VALUE_ONLY_DECISIONS = {"REVIEW", "CAND"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict[str, Any]:
    return load_json(path) if path.is_file() else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def decision_distribution(items: list[dict[str, Any]]) -> dict[str, int]:
    counter = collections.Counter(str(item.get("decision") or "") for item in items)
    return dict(sorted(counter.items(), key=lambda x: (-x[1], x[0])))


def is_low_value_distribution(dist: dict[str, int], total: int) -> bool:
    decisions = {k for k, v in dist.items() if v > 0}
    return total >= 50 and decisions.issubset(LOW_VALUE_ONLY_DECISIONS) and not decisions.intersection({"FIND", "FP", "RUNTIME", "BLOCKED"})


def candidate_map(run_root: Path) -> dict[str, dict[str, Any]]:
    pool = load_json(run_root / "candidates" / "CANDIDATE_POOL.json")
    return {item.get("candidate_id"): item for item in pool.get("candidates", []) if item.get("candidate_id")}


def read_prompt_pack(run_root: Path) -> dict[str, Any]:
    path = run_root / "ai" / "jury" / "AI_JURY_PROMPT_PACK.json"
    if not path.is_file():
        raise SystemExit("[FAIL] AI_JURY_PROMPT_PACK.json not found. Run ai-jury-prompts first.")
    return load_json(path)


def reviewer_result_path(reviewer: dict[str, Any]) -> Path:
    raw = Path(reviewer["result_path"])
    return raw if raw.is_absolute() else ROOT / raw


def read_reviewer_items(run_root: Path, pack: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for reviewer in pack.get("reviewers") or []:
        path = reviewer_result_path(reviewer)
        if not path.is_file():
            continue
        try:
            result = load_json(path)
        except Exception:
            continue
        reviewer_id = reviewer.get("reviewer_id") or path.parent.name
        for item in result.get("items") or []:
            if not isinstance(item, dict):
                continue
            cid = item.get("candidate_id")
            if not cid:
                continue
            copy = dict(item)
            copy["_reviewer_id"] = reviewer_id
            by_candidate.setdefault(cid, []).append(copy)
    return by_candidate


def read_consensus(run_root: Path) -> dict[str, Any]:
    path = run_root / "ai" / "consensus" / "AI_TRIAGE_CONSENSUS.json"
    if not path.is_file():
        raise SystemExit("[FAIL] AI_TRIAGE_CONSENSUS.json not found. Run ai-jury-merge first.")
    return load_json(path)


def read_adjudication(run_root: Path) -> dict[str, Any]:
    return load_optional_json(run_root / "ai" / "consensus" / "AI_TRIAGE_ADJUDICATION_RESULT.json")


def adjudication_items_by_candidate(adjudication: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in adjudication.get("items") or []:
        if not isinstance(item, dict):
            continue
        cid = item.get("candidate_id")
        if cid:
            out[cid] = item
    return out


def audit_decision_event(candidate: dict[str, Any], item: dict[str, Any], decision: str) -> dict[str, Any]:
    event = item.get("lifecycle_event")
    if isinstance(event, dict):
        return event
    return {
        "event_type": "audit_decision",
        "stage": "ai_jury_finalizer",
        "actor": "ai_jury_finalizer",
        "from": {"status": candidate.get("status") or "CAND"},
        "to": {"status": decision},
        "reason": item.get("reason") or "AI Jury finalized decision",
        "evidence_refs": [candidate.get("candidate_id") or ""],
    }


def pick_source_item(candidate_id: str, consensus_item: dict[str, Any], reviewer_items: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    source_items = reviewer_items.get(candidate_id) or []
    suggested = consensus_item.get("suggested_decision")
    for item in source_items:
        if item.get("decision") == suggested:
            return item
    return source_items[0] if source_items else {}


def normalize_decision(value: Any) -> str:
    value_s = str(value or "REVIEW")
    return value_s if value_s in ALLOWED_DECISIONS else "REVIEW"


def normalize_severity(value: Any, fallback: Any = None) -> str:
    for raw in [value, fallback, "P2"]:
        raw_s = str(raw or "")
        if raw_s in ALLOWED_SEVERITY:
            return raw_s
    return "P2"


def normalize_confidence(value: Any, fallback: Any = None) -> str:
    for raw in [value, fallback, "medium"]:
        raw_s = str(raw or "")
        if raw_s in ALLOWED_CONFIDENCE:
            return raw_s
    return "medium"


def normalize_item(candidate_id: str, raw_item: dict[str, Any], candidate: dict[str, Any], source: str) -> dict[str, Any]:
    decision = normalize_decision(raw_item.get("decision"))
    severity = normalize_severity(raw_item.get("severity"), candidate.get("severity_hint"))
    confidence = normalize_confidence(raw_item.get("confidence"), candidate.get("confidence_hint"))
    evidence = as_str(raw_item.get("evidence") or candidate.get("evidence") or candidate.get("title") or candidate_id)
    reason = as_str(raw_item.get("reason") or f"finalized by AI Jury from {source}")
    title = as_str(raw_item.get("title") or candidate.get("title") or candidate_id)
    risk_type = as_str(raw_item.get("risk_type") or candidate.get("risk_type") or "ai_jury_review")
    item = {
        "candidate_id": candidate_id,
        "decision": decision,
        "severity": severity,
        "confidence": confidence,
        "title": title,
        "risk_type": risk_type,
        "risk_parent": raw_item.get("risk_parent") if raw_item.get("risk_parent") is not None else candidate.get("risk_parent"),
        "risk_subtype": raw_item.get("risk_subtype") if raw_item.get("risk_subtype") is not None else candidate.get("risk_subtype"),
        "evidence": evidence,
        "risk_chain": as_str(raw_item.get("risk_chain") or ""),
        "negative_evidence_checked": [str(x) for x in as_list(raw_item.get("negative_evidence_checked"))],
        "missing_evidence": [str(x) for x in as_list(raw_item.get("missing_evidence"))],
        "impact": as_str(raw_item.get("impact") or ""),
        "recommendation": as_str(raw_item.get("recommendation") or ""),
        "tags": [str(x) for x in as_list(raw_item.get("tags"))],
        "questions_for_human": [str(x) for x in as_list(raw_item.get("questions_for_human"))],
        "knowledge_update_suggestions": [x for x in as_list(raw_item.get("knowledge_update_suggestions")) if isinstance(x, dict)],
        "reason": reason,
    }
    if "ai_jury" not in item["tags"]:
        item["tags"].append("ai_jury")
    if source == "adjudication" and "ai_jury_adjudicated" not in item["tags"]:
        item["tags"].append("ai_jury_adjudicated")
    elif source == "consensus" and "ai_jury_consensus" not in item["tags"]:
        item["tags"].append("ai_jury_consensus")
    item["lifecycle_event"] = audit_decision_event(candidate, raw_item, decision)
    return item


def validate_ready(consensus: dict[str, Any], adjudication: dict[str, Any], errors: list[str]) -> None:
    status = consensus.get("status")
    if status == "failed":
        errors.append("consensus status is failed")
    if status == "awaiting_reviewer_results":
        errors.append("consensus is still awaiting reviewer results")
    required = {item.get("candidate_id") for item in consensus.get("adjudication_items") or [] if item.get("candidate_id")}
    if required:
        if not adjudication:
            errors.append("adjudication is required but AI_TRIAGE_ADJUDICATION_RESULT.json is missing")
            return
        if adjudication.get("schema_version") != "ai-jury-adjudication-result-0.1.0":
            errors.append("AI_TRIAGE_ADJUDICATION_RESULT schema_version mismatch")
        actual = set(adjudication_items_by_candidate(adjudication))
        missing = sorted(required - actual)
        if missing:
            errors.append("adjudication result missing candidate_id: " + ", ".join(missing[:30]))


def finalize(run_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    pack = read_prompt_pack(run_root)
    consensus = read_consensus(run_root)
    adjudication = read_adjudication(run_root)
    errors: list[str] = []
    warnings: list[str] = []
    recommended_next_steps: list[str] = []
    validate_ready(consensus, adjudication, errors)
    candidates = candidate_map(run_root)
    reviewer_items = read_reviewer_items(run_root, pack)
    adjudication_by_candidate = adjudication_items_by_candidate(adjudication)
    final_items: list[dict[str, Any]] = []
    source_counts = {"consensus": 0, "adjudication": 0}
    if not errors:
        for consensus_item in consensus.get("items") or []:
            cid = consensus_item.get("candidate_id")
            if not cid:
                continue
            candidate = candidates.get(cid, {})
            if cid in adjudication_by_candidate:
                final_items.append(normalize_item(cid, adjudication_by_candidate[cid], candidate, "adjudication"))
                source_counts["adjudication"] += 1
            else:
                source = pick_source_item(cid, consensus_item, reviewer_items)
                final_items.append(normalize_item(cid, source, candidate, "consensus"))
                source_counts["consensus"] += 1
    dist = decision_distribution(final_items)
    if is_low_value_distribution(dist, len(final_items)):
        warnings.append("Final AI Jury result only contains REVIEW/CAND. This is usually a low-value audit result and may fail ai-triage-quality.")
        recommended_next_steps.extend([
            "Inspect reviewer distributions with make ai-jury-status RUN_ROOT=...",
            "If reviewers are low-value, rerun ai-jury-prompts with a stronger profile/model.",
            "If only adjudication is low-value, rerun AI_TRIAGE_ADJUDICATION_PROMPT.md with stronger guardrails.",
        ])
    triage_result = {
        "schema_version": "ai-triage-result-0.2.0",
        "triage_mode": "FAST_STATIC",
        "items": final_items,
        "knowledge_update_suggestions": [x for x in as_list(adjudication.get("knowledge_update_suggestions")) if isinstance(x, dict)],
        "notes": [
            "Generated by AI Jury finalizer.",
            f"AI Jury profile: {pack.get('profile')}",
            f"Consensus status: {consensus.get('status')}",
            f"Final items: {len(final_items)}",
            f"Decision distribution: {dist}",
            f"Source counts: consensus={source_counts['consensus']}, adjudication={source_counts['adjudication']}",
        ],
    }
    finalization = {
        "schema_version": "ai-jury-finalization-result-0.2.0",
        "generated_at": now(),
        "status": "passed" if not errors else "failed",
        "can_continue": not errors,
        "profile": pack.get("profile"),
        "consensus_ref": rel(run_root / "ai" / "consensus" / "AI_TRIAGE_CONSENSUS.json"),
        "adjudication_ref": rel(run_root / "ai" / "consensus" / "AI_TRIAGE_ADJUDICATION_RESULT.json") if adjudication else None,
        "output_ref": rel(run_root / "ai" / "AI_TRIAGE_RESULT.json"),
        "summary": {
            "consensus_items": len(consensus.get("items") or []),
            "adjudication_required": len(consensus.get("adjudication_items") or []),
            "adjudication_items": len(adjudication_by_candidate),
            "final_items": len(final_items),
            "decision_distribution": dist,
            "source_counts": source_counts,
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "errors": errors,
        "warnings": warnings,
        "recommended_next_steps": recommended_next_steps,
        "notes": [
            "This step writes final ai/AI_TRIAGE_RESULT.json only when consensus/adjudication inputs are complete.",
            "Run ai-triage-validate and ai-triage-quality after finalization.",
        ],
    }
    return triage_result, finalization


def render_md(result: dict[str, Any]) -> str:
    s = result.get("summary") or {}
    lines = [
        "# AI_JURY_FINALIZATION_RESULT", "",
        f"- Status: `{result.get('status')}`",
        f"- Can continue: `{result.get('can_continue')}`",
        f"- Profile: `{result.get('profile')}`",
        f"- Consensus items: {s.get('consensus_items')}",
        f"- Adjudication required: {s.get('adjudication_required')}",
        f"- Adjudication items: {s.get('adjudication_items')}",
        f"- Final items: {s.get('final_items')}",
        f"- Decision distribution: `{s.get('decision_distribution')}`",
        f"- Output: `{result.get('output_ref')}`", "",
    ]
    if result.get("errors"):
        lines.extend(["## Errors", ""])
        for err in result["errors"]:
            lines.append(f"- {err}")
        lines.append("")
    if result.get("warnings"):
        lines.extend(["## Warnings", ""])
        for warning in result["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")
    if result.get("recommended_next_steps"):
        lines.extend(["## Recommended next steps", ""])
        for step in result["recommended_next_steps"]:
            lines.append(f"- {step}")
        lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    s = result.get("summary") or {}
    print("ai-jury-finalize summary")
    print(f"  status: {result.get('status')}")
    print(f"  can_continue: {result.get('can_continue')}")
    print(f"  final_items: {s.get('final_items')}")
    print(f"  decisions: {s.get('decision_distribution')}")
    print(f"  adjudication_items: {s.get('adjudication_items')}")
    for err in result.get("errors") or []:
        print(f"  error: {err}")
    for warning in result.get("warnings") or []:
        print(f"  warning: {warning}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Finalize AI Jury consensus/adjudication into ai/AI_TRIAGE_RESULT.json.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    try:
        triage_result, finalization = finalize(run_root)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    out = run_root / "ai" / "jury"
    write_json(out / "AI_JURY_FINALIZATION_RESULT.json", finalization)
    write_text(out / "AI_JURY_FINALIZATION_RESULT.md", render_md(finalization))
    if finalization["status"] == "passed":
        write_json(run_root / "ai" / "AI_TRIAGE_RESULT.json", triage_result)
    if args.print_summary:
        print_summary(finalization)
    return 0 if finalization["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
