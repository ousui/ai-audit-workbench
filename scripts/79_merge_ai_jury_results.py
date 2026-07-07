#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
JURY_SPEC = ROOT / "spec" / "ai" / "jury-profiles.yaml"
HIGH_RISK_PARENTS = {
    "CRYPTOGRAPHY_SECRETS",
    "INPUT_INJECTION",
    "ACCESS_CONTROL",
    "AUTHENTICATION_SESSION",
    "BUSINESS_LOGIC",
    "FILE_OPERATION",
    "DATA_PROTECTION_PRIVACY",
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def candidate_map(run_root: Path) -> dict[str, dict[str, Any]]:
    path = run_root / "candidates" / "CANDIDATE_POOL.json"
    if not path.is_file():
        return {}
    pool = load_json(path)
    return {item.get("candidate_id"): item for item in pool.get("candidates", []) if item.get("candidate_id")}


def read_prompt_pack(run_root: Path) -> dict[str, Any]:
    path = run_root / "ai" / "jury" / "AI_JURY_PROMPT_PACK.json"
    if not path.is_file():
        raise SystemExit("[FAIL] AI_JURY_PROMPT_PACK.json not found. Run ai-jury-prompts first.")
    return load_json(path)


def read_reviewer_result(run_root: Path, reviewer: dict[str, Any]) -> dict[str, Any]:
    result_path = ROOT / reviewer["result_path"] if not Path(reviewer["result_path"]).is_absolute() else Path(reviewer["result_path"])
    if not result_path.is_file():
        return {"reviewer_id": reviewer["reviewer_id"], "status": "missing", "result_path": reviewer["result_path"], "items": {}, "error": "result file missing"}
    try:
        data = load_json(result_path)
    except Exception as exc:
        return {"reviewer_id": reviewer["reviewer_id"], "status": "invalid", "result_path": reviewer["result_path"], "items": {}, "error": str(exc)}
    items: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        cid = item.get("candidate_id")
        if not cid:
            continue
        if cid in items:
            duplicates.append(cid)
        items[cid] = item
    status = "completed" if not duplicates else "invalid"
    error = "duplicate candidate_id: " + ", ".join(sorted(set(duplicates))[:20]) if duplicates else ""
    return {"reviewer_id": reviewer["reviewer_id"], "status": status, "result_path": reviewer["result_path"], "schema_version": data.get("schema_version"), "triage_mode": data.get("triage_mode"), "item_count": len(items), "items": items, "error": error}


def decision_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counter = collections.Counter(str(item.get("decision") or "") for item in items)
    return dict(sorted(counter.items(), key=lambda x: (-x[1], x[0])))


def collect_candidate_ids(reviewer_results: list[dict[str, Any]]) -> list[str]:
    ids: set[str] = set()
    for result in reviewer_results:
        if result.get("status") != "completed":
            continue
        ids.update(result.get("items", {}).keys())
    return sorted(ids)


def first_non_empty(values: list[Any]) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def classify_item(candidate_id: str, expected_reviewers: int, reviewer_results: list[dict[str, Any]], candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    reviewer_decisions: list[dict[str, Any]] = []
    source_items: list[dict[str, Any]] = []
    for result in reviewer_results:
        if result.get("status") != "completed":
            continue
        item = result.get("items", {}).get(candidate_id)
        if not item:
            reviewer_decisions.append({"reviewer_id": result["reviewer_id"], "decision": "MISSING_ITEM", "confidence": None, "reason": "reviewer did not include this candidate"})
            continue
        source_items.append(item)
        reviewer_decisions.append({
            "reviewer_id": result["reviewer_id"],
            "decision": item.get("decision"),
            "severity": item.get("severity"),
            "confidence": item.get("confidence"),
            "reason": item.get("reason"),
        })
    present_decisions = [x for x in reviewer_decisions if x.get("decision") != "MISSING_ITEM"]
    counts = decision_counts(present_decisions)
    total_present = len(present_decisions)
    top_decision = next(iter(counts.keys())) if counts else ""
    top_count = counts.get(top_decision, 0)
    candidate = candidates.get(candidate_id, {})
    risk_parent = first_non_empty([*(item.get("risk_parent") for item in source_items), candidate.get("risk_parent")])
    severity = first_non_empty([*(item.get("severity") for item in source_items), candidate.get("severity_hint")])
    has_find = counts.get("FIND", 0) > 0
    has_fp = counts.get("FP", 0) > 0
    has_runtime = counts.get("RUNTIME", 0) > 0
    has_review = counts.get("REVIEW", 0) > 0
    has_missing_item = any(x.get("decision") == "MISSING_ITEM" for x in reviewer_decisions)
    high_risk = risk_parent in HIGH_RISK_PARENTS or severity in {"P0", "P1"}
    unanimous = total_present > 0 and top_count == total_present and not has_missing_item
    majority = total_present > 0 and top_count > (total_present / 2)
    reasons: list[str] = []
    needs_adjudication = False
    suggested_decision = "REVIEW"
    disagreement_level = "none"
    if has_find and has_fp:
        needs_adjudication = True
        suggested_decision = "REVIEW"
        disagreement_level = "strong"
        reasons.append("FIND vs FP disagreement")
    elif not unanimous and total_present > 1:
        needs_adjudication = True
        suggested_decision = top_decision if majority and top_decision not in {"FP"} else "REVIEW"
        disagreement_level = "medium"
        reasons.append("reviewer disagreement")
    elif has_missing_item and total_present > 0:
        needs_adjudication = True
        suggested_decision = top_decision if top_decision else "REVIEW"
        disagreement_level = "medium"
        reasons.append("reviewer omitted candidate")
    elif unanimous:
        suggested_decision = top_decision
        if top_decision == "FP" and high_risk:
            needs_adjudication = True
            disagreement_level = "qc"
            reasons.append("high-risk unanimous FP requires QC")
    if high_risk and suggested_decision in {"FP", "CAND"}:
        needs_adjudication = True
        reasons.append("high-risk low-action decision")
    if has_runtime or has_review:
        reasons.append("review/runtime decision present")
    agreement = f"{top_count}/{total_present}" if total_present else "0/0"
    return {
        "candidate_id": candidate_id,
        "risk_parent": risk_parent,
        "severity": severity,
        "decision_counts": counts,
        "reviewer_decisions": reviewer_decisions,
        "agreement": agreement,
        "unanimous": unanimous,
        "majority_decision": top_decision if majority else None,
        "suggested_decision": suggested_decision,
        "needs_adjudication": needs_adjudication,
        "disagreement_level": disagreement_level,
        "reasons": reasons,
    }


def build_consensus(run_root: Path) -> dict[str, Any]:
    pack = read_prompt_pack(run_root)
    expected = pack.get("reviewers") or []
    candidates = candidate_map(run_root)
    reviewer_results = [read_reviewer_result(run_root, reviewer) for reviewer in expected]
    missing = [r for r in reviewer_results if r.get("status") == "missing"]
    invalid = [r for r in reviewer_results if r.get("status") == "invalid"]
    completed = [r for r in reviewer_results if r.get("status") == "completed"]
    consensus_items = [classify_item(cid, len(expected), reviewer_results, candidates) for cid in collect_candidate_ids(reviewer_results)]
    adjudication_items = [x for x in consensus_items if x.get("needs_adjudication")]
    strong_disagreements = [x for x in consensus_items if x.get("disagreement_level") == "strong"]
    if invalid:
        status = "failed"
    elif missing:
        status = "awaiting_reviewer_results"
    elif adjudication_items:
        status = "ready_for_adjudication"
    else:
        status = "consensus_ready"
    return {
        "schema_version": "ai-jury-consensus-0.1.0",
        "generated_at": now(),
        "status": status,
        "can_continue": status in {"ready_for_adjudication", "consensus_ready"},
        "profile": pack.get("profile"),
        "prompt_pack_ref": rel(run_root / "ai" / "jury" / "AI_JURY_PROMPT_PACK.json"),
        "summary": {
            "expected_reviewers": len(expected),
            "completed_reviewers": len(completed),
            "missing_reviewers": len(missing),
            "invalid_reviewers": len(invalid),
            "consensus_items": len(consensus_items),
            "adjudication_required": len(adjudication_items),
            "strong_disagreements": len(strong_disagreements),
        },
        "reviewers": [{k: v for k, v in r.items() if k != "items"} for r in reviewer_results],
        "items": consensus_items,
        "adjudication_items": adjudication_items,
        "notes": [
            "This step compares independent reviewer outputs; it does not write final AI_TRIAGE_RESULT.json.",
            "If status is ready_for_adjudication, copy AI_TRIAGE_ADJUDICATION_PROMPT.md to a high-reasoning reviewer.",
            "If status is consensus_ready, a later finalization step can convert consensus to AI_TRIAGE_RESULT.json.",
        ],
    }


def render_consensus_md(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        "# AI_TRIAGE_CONSENSUS", "",
        f"- Status: `{result['status']}`",
        f"- Can continue: `{result['can_continue']}`",
        f"- Profile: `{result.get('profile')}`",
        f"- Expected reviewers: {s['expected_reviewers']}",
        f"- Completed reviewers: {s['completed_reviewers']}",
        f"- Missing reviewers: {s['missing_reviewers']}",
        f"- Invalid reviewers: {s['invalid_reviewers']}",
        f"- Consensus items: {s['consensus_items']}",
        f"- Adjudication required: {s['adjudication_required']}",
        f"- Strong disagreements: {s['strong_disagreements']}", "",
        "## Reviewers", "",
        "| Reviewer | Status | Items | Result | Error |",
        "|---|---|---:|---|---|",
    ]
    for r in result.get("reviewers", []):
        lines.append(f"| `{r.get('reviewer_id')}` | `{r.get('status')}` | {r.get('item_count', 0)} | `{r.get('result_path')}` | {r.get('error') or ''} |")
    lines.extend(["", "## Adjudication items", ""])
    if not result.get("adjudication_items"):
        lines.append("- None")
    for item in result.get("adjudication_items", [])[:120]:
        lines.append(f"- `{item['candidate_id']}` suggested={item.get('suggested_decision')} agreement={item.get('agreement')} counts={item.get('decision_counts')} reasons={', '.join(item.get('reasons') or [])}")
    lines.append("")
    return "\n".join(lines)


def render_disagreements_md(result: dict[str, Any]) -> str:
    lines = ["# AI_TRIAGE_DISAGREEMENTS", ""]
    items = result.get("adjudication_items") or []
    if not items:
        lines.append("No disagreements or QC items require adjudication.")
        return "\n".join(lines) + "\n"
    for item in items:
        lines.extend([f"## {item['candidate_id']}", "", f"- Suggested decision: `{item.get('suggested_decision')}`", f"- Agreement: `{item.get('agreement')}`", f"- Decision counts: `{item.get('decision_counts')}`", f"- Reasons: {', '.join(item.get('reasons') or [])}", "", "| Reviewer | Decision | Severity | Confidence | Reason |", "|---|---|---|---|---|"])
        for r in item.get("reviewer_decisions", []):
            reason = str(r.get("reason") or "").replace("\n", " ")[:240]
            lines.append(f"| `{r.get('reviewer_id')}` | `{r.get('decision')}` | `{r.get('severity')}` | `{r.get('confidence')}` | {reason} |")
        lines.append("")
    return "\n".join(lines)


def render_adjudication_prompt(result: dict[str, Any], run_root: Path) -> str:
    lines = [
        "# AI Jury Adjudication Prompt", "",
        f"RUN_ROOT={run_root}", "",
        "你是 AI Jury 仲裁员。只处理下面列出的分歧项 / 高风险 FP QC 项，不要重新全量审计。", "",
        "## Files to read", "", "```text",
        rel(run_root / "ai" / "AI_TRIAGE_INPUT.json"),
        rel(run_root / "ai" / "consensus" / "AI_TRIAGE_CONSENSUS.json"),
        rel(run_root / "ai" / "consensus" / "AI_TRIAGE_DISAGREEMENTS.md"),
        "spec/schemas/AI_TRIAGE_RESULT.schema.json",
        "spec/rules/audit-lifecycle.yaml",
        "spec/ai/jury-profiles.yaml",
        "```", "",
        "## Output", "", "只允许写入：", "", "```text",
        rel(run_root / "ai" / "consensus" / "AI_TRIAGE_ADJUDICATION_RESULT.json"),
        "```", "",
    ]
    items = result.get("adjudication_items") or []
    if result.get("status") == "awaiting_reviewer_results":
        lines.extend(["## Status", "", "Reviewer result files are missing. Do not adjudicate yet.", ""])
        return "\n".join(lines)
    if not items:
        lines.extend(["## Status", "", "No adjudication required. Do not write an adjudication result unless you find a serious issue in the consensus.", ""])
        return "\n".join(lines)
    lines.extend(["## Items to adjudicate", ""])
    for item in items[:200]:
        lines.append(f"- `{item['candidate_id']}` decision_counts={item.get('decision_counts')} reasons={', '.join(item.get('reasons') or [])}")
    lines.extend([
        "", "## Rules", "",
        "1. 只能裁决上面列出的 candidate_id。",
        "2. decision 只能是 FIND / REVIEW / RUNTIME / CAND / FP / BLOCKED。",
        "3. FIND 必须包含 evidence、risk_chain、impact、recommendation、negative_evidence_checked、reason。",
        "4. FP 必须包含明确反证，不能只写证据不足。",
        "5. RUNTIME 必须说明缺什么运行时证据。",
        "6. 不得输出 business_status、verification_status、resolution_reason。", "",
        "## Expected JSON", "", "```json",
        "{",
        "  \"schema_version\": \"ai-jury-adjudication-result-0.1.0\",",
        "  \"items\": []",
        "}",
        "```", "",
    ])
    return "\n".join(lines)


def write_outputs(run_root: Path, result: dict[str, Any]) -> None:
    out = run_root / "ai" / "consensus"
    write_json(out / "AI_TRIAGE_CONSENSUS.json", result)
    write_text(out / "AI_TRIAGE_CONSENSUS.md", render_consensus_md(result))
    write_text(out / "AI_TRIAGE_DISAGREEMENTS.md", render_disagreements_md(result))
    write_text(out / "AI_TRIAGE_ADJUDICATION_PROMPT.md", render_adjudication_prompt(result, run_root))


def print_summary(result: dict[str, Any]) -> None:
    s = result["summary"]
    print("ai-jury-merge summary")
    print(f"  status: {result['status']}")
    print(f"  profile: {result.get('profile')}")
    print(f"  reviewers: {s['completed_reviewers']}/{s['expected_reviewers']} completed")
    print(f"  consensus_items: {s['consensus_items']}")
    print(f"  adjudication_required: {s['adjudication_required']}")
    print(f"  strong_disagreements: {s['strong_disagreements']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Merge independent AI Jury reviewer outputs into consensus and adjudication prompts.")
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
        result = build_consensus(run_root)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    write_outputs(run_root, result)
    if args.print_summary:
        print_summary(result)
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
