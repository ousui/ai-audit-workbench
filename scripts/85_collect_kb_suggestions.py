#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_suggestion(raw: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    suggestion = dict(raw)
    suggestion.setdefault("scope", "run")
    suggestion.setdefault("confidence", "medium")
    suggestion["requires_human_approval"] = True
    suggestion.setdefault("source", source)
    return suggestion


def explicit_ai_suggestions(ai: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in ai.get("knowledge_update_suggestions") or []:
        if isinstance(raw, dict):
            out.append(normalize_suggestion(raw, {"from": "ai_triage_result"}))
    for item in ai.get("items") or []:
        for raw in item.get("knowledge_update_suggestions") or []:
            if isinstance(raw, dict):
                out.append(normalize_suggestion(raw, {"from": "ai_triage_item", "candidate_id": item.get("candidate_id"), "decision": item.get("decision")}))
    return out


def deterministic_suggestions(merge: dict[str, Any]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for item in merge.get("fp_items") or []:
        suggestions.append({
            "type": "false_positive_memory",
            "scope": "project",
            "summary": f"候选 {item.get('source_candidate_id')} 被判定为 FP：{item.get('reason') or item.get('title')}",
            "evidence_refs": [item.get("source_candidate_id") or item.get("risk_id") or ""],
            "confidence": item.get("confidence") or "medium",
            "requires_human_approval": True,
            "source": {"from": "merge_fp", "risk_id": item.get("risk_id"), "status": "FP"},
        })
    for item in merge.get("blocked_items") or []:
        suggestions.append({
            "type": "tool_note",
            "scope": "project",
            "summary": f"候选 {item.get('source_candidate_id')} 审计受阻：{item.get('reason') or item.get('title')}",
            "evidence_refs": [item.get("source_candidate_id") or item.get("risk_id") or ""],
            "confidence": item.get("confidence") or "medium",
            "requires_human_approval": True,
            "source": {"from": "merge_blocked", "risk_id": item.get("risk_id"), "status": "BLOCKED"},
        })
    for item in merge.get("findings") or []:
        if item.get("recommendation"):
            suggestions.append({
                "type": "remediation_note",
                "scope": "project",
                "summary": f"{item.get('risk_parent') or item.get('risk_type')}: {item.get('recommendation')}",
                "risk_parent": item.get("risk_parent"),
                "risk_subtype": item.get("risk_subtype"),
                "risk_type": item.get("risk_type"),
                "evidence_refs": [item.get("source_candidate_id") or item.get("risk_id") or ""],
                "confidence": item.get("confidence") or "medium",
                "requires_human_approval": True,
                "source": {"from": "merge_find", "risk_id": item.get("risk_id"), "status": "FIND"},
            })
    return suggestions


def dedupe(suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for item in suggestions:
        key = (item.get("type"), item.get("scope"), item.get("summary"), tuple(item.get("evidence_refs") or []))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    for idx, item in enumerate(out, start=1):
        item.setdefault("suggestion_id", f"KBSUG-{idx:05d}")
    return out


def collect(run_root: Path) -> dict[str, Any]:
    ai = load_json(run_root / "ai" / "AI_TRIAGE_RESULT.json")
    merge = load_json(run_root / "merge" / "MERGE_RESULT.json")
    explicit = explicit_ai_suggestions(ai)
    deterministic = deterministic_suggestions(merge)
    suggestions = dedupe(explicit + deterministic)
    by_type: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    for item in suggestions:
        by_type[item.get("type") or "unknown"] = by_type.get(item.get("type") or "unknown", 0) + 1
        by_scope[item.get("scope") or "unknown"] = by_scope.get(item.get("scope") or "unknown", 0) + 1
    return {
        "schema_version": "kb-update-suggestions-0.1.0",
        "generated_at": now(),
        "knowledge_spec_ref": "spec/rules/audit-knowledge.yaml",
        "run": merge.get("run"),
        "project": merge.get("project"),
        "summary": {
            "total_suggestions": len(suggestions),
            "explicit_ai_suggestions": len(explicit),
            "deterministic_suggestions": len(deterministic),
            "by_type": by_type,
            "by_scope": by_scope,
            "requires_human_approval": True,
        },
        "suggestions": suggestions,
        "notes": [
            "This file is advisory. It must not be promoted into AUDIT_KNOWLEDGE.yaml without human approval.",
            "Accepted-risk records must remain project/business scoped and must not become global false-positive rules.",
        ],
    }


def render_md(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        "# KB_UPDATE_SUGGESTIONS", "",
        f"- Total suggestions: {s['total_suggestions']}",
        f"- Explicit AI suggestions: {s['explicit_ai_suggestions']}",
        f"- Deterministic suggestions: {s['deterministic_suggestions']}",
        f"- Requires human approval: `{s['requires_human_approval']}`", "",
        "## Suggestions", "",
    ]
    if not result.get("suggestions"):
        lines.append("- None")
    for item in result.get("suggestions", [])[:120]:
        lines.append(f"- `{item.get('suggestion_id')}` `{item.get('type')}` `{item.get('scope')}` {item.get('summary')}")
    lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    print("kb-suggestions summary")
    print(f"  total_suggestions: {result['summary']['total_suggestions']}")
    print(f"  explicit_ai_suggestions: {result['summary']['explicit_ai_suggestions']}")
    print(f"  deterministic_suggestions: {result['summary']['deterministic_suggestions']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Collect knowledge update suggestions from AI triage and merge results.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not (run_root / "ai" / "AI_TRIAGE_RESULT.json").is_file():
        print("[FAIL] AI_TRIAGE_RESULT.json not found. Run ai-triage first.", file=sys.stderr)
        return 2
    if not (run_root / "merge" / "MERGE_RESULT.json").is_file():
        print("[FAIL] MERGE_RESULT.json not found. Run merge first.", file=sys.stderr)
        return 2
    result = collect(run_root)
    out = run_root / "knowledge"
    write_json(out / "KB_UPDATE_SUGGESTIONS.json", result)
    (out / "KB_UPDATE_SUGGESTIONS.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
