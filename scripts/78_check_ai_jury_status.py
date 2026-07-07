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


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def resolve_repo_path(value: str) -> Path:
    raw = Path(value)
    return raw if raw.is_absolute() else ROOT / raw


def candidate_ids(run_root: Path) -> set[str]:
    path = run_root / "candidates" / "CANDIDATE_POOL.json"
    if not path.is_file():
        return set()
    pool = load_json(path)
    return {str(item.get("candidate_id")) for item in pool.get("candidates") or [] if item.get("candidate_id")}


def decision_distribution(items: list[dict[str, Any]]) -> dict[str, int]:
    counter = collections.Counter(str(item.get("decision") or "") for item in items)
    return dict(sorted(counter.items(), key=lambda x: (-x[1], x[0])))


def validate_reviewer_result(path: Path, known_candidate_ids: set[str]) -> tuple[str, dict[str, Any]]:
    if not path.is_file():
        return "missing", {"error": "result file missing"}
    try:
        data = load_json(path)
    except Exception as exc:
        return "invalid", {"error": f"invalid json: {exc}"}
    items = data.get("items")
    if not isinstance(items, list):
        return "invalid", {"error": "items must be an array"}
    seen: set[str] = set()
    duplicates: list[str] = []
    unknown: list[str] = []
    invalid_decisions: list[str] = []
    valid_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("candidate_id") or "")
        decision = str(item.get("decision") or "")
        if cid in seen:
            duplicates.append(cid)
        elif cid:
            seen.add(cid)
        if known_candidate_ids and cid and cid not in known_candidate_ids:
            unknown.append(cid)
        if decision and decision not in ALLOWED_DECISIONS:
            invalid_decisions.append(f"{cid}:{decision}")
        if cid and decision in ALLOWED_DECISIONS:
            valid_items.append(item)
    errors = []
    if duplicates:
        errors.append("duplicate candidate_id: " + ", ".join(sorted(set(duplicates))[:20]))
    if unknown:
        errors.append("unknown candidate_id: " + ", ".join(sorted(set(unknown))[:20]))
    if invalid_decisions:
        errors.append("invalid decision: " + ", ".join(invalid_decisions[:20]))
    if errors:
        return "invalid", {"error": "; ".join(errors), "item_count": len(valid_items), "decision_distribution": decision_distribution(valid_items)}
    return "completed", {"item_count": len(valid_items), "decision_distribution": decision_distribution(valid_items), "schema_version": data.get("schema_version"), "triage_mode": data.get("triage_mode")}


def build_status(run_root: Path) -> dict[str, Any]:
    pack_path = run_root / "ai" / "jury" / "AI_JURY_PROMPT_PACK.json"
    if not pack_path.is_file():
        return {
            "schema_version": "ai-jury-status-0.1.0",
            "generated_at": now(),
            "status": "no_prompt_pack",
            "can_continue": False,
            "summary": {"expected_reviewers": 0, "completed_reviewers": 0, "missing_reviewers": 0, "invalid_reviewers": 0},
            "reviewers": [],
            "next_actions": ["Run: make ai-jury-prompts RUN_ROOT=... AI_JURY_PROFILE=balanced"],
        }
    pack = load_json(pack_path)
    known = candidate_ids(run_root)
    reviewers = []
    for reviewer in pack.get("reviewers") or []:
        result_path = resolve_repo_path(str(reviewer.get("result_path") or ""))
        prompt_path = resolve_repo_path(str(reviewer.get("prompt_path") or ""))
        status, details = validate_reviewer_result(result_path, known)
        reviewers.append({
            "reviewer_id": reviewer.get("reviewer_id"),
            "role": reviewer.get("role"),
            "reasoning": reviewer.get("reasoning"),
            "status": status,
            "prompt_path": rel(prompt_path),
            "result_path": rel(result_path),
            **details,
        })
    missing = [x for x in reviewers if x.get("status") == "missing"]
    invalid = [x for x in reviewers if x.get("status") == "invalid"]
    completed = [x for x in reviewers if x.get("status") == "completed"]
    if invalid:
        status = "invalid_reviewer_results"
    elif missing:
        status = "awaiting_reviewer_results"
    else:
        status = "ready_for_consensus"
    next_actions: list[str] = []
    if invalid:
        for item in invalid[:5]:
            next_actions.append(f"Fix or rerun reviewer `{item.get('reviewer_id')}` from prompt: {item.get('prompt_path')}")
    elif missing:
        for item in missing[:5]:
            next_actions.append(f"Run reviewer `{item.get('reviewer_id')}` from prompt: {item.get('prompt_path')}")
    else:
        next_actions.append("Run: make ai-jury-merge RUN_ROOT=...")
    return {
        "schema_version": "ai-jury-status-0.1.0",
        "generated_at": now(),
        "status": status,
        "can_continue": status == "ready_for_consensus",
        "profile": pack.get("profile"),
        "prompt_pack_ref": rel(pack_path),
        "summary": {
            "expected_reviewers": len(reviewers),
            "completed_reviewers": len(completed),
            "missing_reviewers": len(missing),
            "invalid_reviewers": len(invalid),
            "known_candidates": len(known),
        },
        "reviewers": reviewers,
        "next_actions": next_actions,
    }


def render_md(result: dict[str, Any]) -> str:
    s = result.get("summary") or {}
    lines = [
        "# AI_JURY_STATUS", "",
        f"- Status: `{result.get('status')}`",
        f"- Can continue: `{result.get('can_continue')}`",
        f"- Profile: `{result.get('profile')}`",
        f"- Expected reviewers: {s.get('expected_reviewers')}",
        f"- Completed reviewers: {s.get('completed_reviewers')}",
        f"- Missing reviewers: {s.get('missing_reviewers')}",
        f"- Invalid reviewers: {s.get('invalid_reviewers')}", "",
        "## Reviewers", "",
        "| Reviewer | Role | Status | Items | Decisions | Next file |",
        "|---|---|---|---:|---|---|",
    ]
    for item in result.get("reviewers") or []:
        decisions = json.dumps(item.get("decision_distribution") or {}, ensure_ascii=False)
        next_file = item.get("result_path") if item.get("status") == "completed" else item.get("prompt_path")
        lines.append(f"| `{item.get('reviewer_id')}` | `{item.get('role')}` | `{item.get('status')}` | {item.get('item_count', 0)} | `{decisions}` | `{next_file}` |")
    lines.extend(["", "## Next actions", ""])
    for action in result.get("next_actions") or []:
        lines.append(f"- {action}")
    if not result.get("next_actions"):
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    s = result.get("summary") or {}
    print("ai-jury-status summary")
    print(f"  status: {result.get('status')}")
    print(f"  can_continue: {result.get('can_continue')}")
    print(f"  reviewers: {s.get('completed_reviewers')}/{s.get('expected_reviewers')} completed")
    print(f"  missing: {s.get('missing_reviewers')}")
    print(f"  invalid: {s.get('invalid_reviewers')}")
    for action in result.get("next_actions") or []:
        print(f"  next: {action}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check AI Jury reviewer completion status and next actions.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    result = build_status(run_root)
    out = run_root / "ai" / "jury"
    write_json(out / "AI_JURY_STATUS.json", result)
    (out / "AI_JURY_STATUS.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 1 if result["status"] in {"no_prompt_pack", "invalid_reviewer_results"} else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
