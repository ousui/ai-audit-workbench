#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any] | list[Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fingerprint(parts: list[str]) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def initial_status(hit: dict[str, Any]) -> str:
    risk_type = hit.get("risk_type") or ""
    if risk_type in {"sensitive_information", "configuration_exposure", "business_logic_review_candidate"}:
        return "REVIEW"
    return "CAND"


def report_hint(status: str, severity: str) -> bool:
    if status in {"FIND", "REVIEW", "RUNTIME", "BLOCKED"} and severity in {"P0", "P1", "P2"}:
        return True
    return False


def build_candidates(run_root: Path) -> dict[str, Any]:
    pack = load_json(run_root / "evidence" / "EVIDENCE_PACK.json")
    tool_result = load_json(run_root / "evidence" / "TOOL_RUN_RESULT.json")
    assert isinstance(pack, dict)
    assert isinstance(tool_result, dict)

    hits = tool_result.get("hits") or []
    candidates: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    duplicate_count = 0

    for hit in hits:
        fp = fingerprint([
            str(hit.get("recipe_id") or ""),
            str(hit.get("risk_type") or ""),
            str(hit.get("file_path") or ""),
            str(hit.get("line_start") or ""),
            str(hit.get("matched_pattern") or ""),
        ])
        if fp in seen:
            duplicate_count += 1
            continue
        cid = f"CAND-{len(candidates) + 1:05d}"
        seen[fp] = cid
        status = initial_status(hit)
        severity = hit.get("severity_hint") or "P2"
        candidates.append({
            "candidate_id": cid,
            "fingerprint": fp,
            "status": status,
            "source": hit.get("source") or "static_pattern_scan",
            "source_hit_id": hit.get("hit_id"),
            "recipe_id": hit.get("recipe_id"),
            "risk_type": hit.get("risk_type") or "static_candidate",
            "title": hit.get("title") or "静态候选项",
            "severity_hint": severity,
            "confidence_hint": hit.get("confidence_hint") or "medium",
            "file_path": hit.get("file_path"),
            "line_start": hit.get("line_start"),
            "line_end": hit.get("line_end"),
            "evidence": hit.get("evidence_preview"),
            "matched_pattern": hit.get("matched_pattern"),
            "negative_evidence_required": hit.get("negative_evidence_required") or [],
            "report_hint": report_hint(status, severity),
            "triage_required": True,
            "notes": [
                "候选项由确定性静态扫描生成，不代表漏洞成立。",
                "正式 FIND 必须经过 AI triage 或人工复核以及 merge 阶段。",
            ],
        })

    by_status: dict[str, int] = {}
    by_risk_type: dict[str, int] = {}
    for item in candidates:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
        by_risk_type[item["risk_type"]] = by_risk_type.get(item["risk_type"], 0) + 1

    return {
        "schema_version": "candidate-pool-0.1.0",
        "run": pack.get("run"),
        "project": {
            "project_code": pack.get("project", {}).get("project_code"),
            "project_name": pack.get("project", {}).get("project_name"),
        },
        "summary": {
            "total_candidates": len(candidates),
            "duplicate_hits_dropped": duplicate_count,
            "by_status": by_status,
            "by_risk_type": by_risk_type,
            "find_count": 0,
            "note": "Candidate pool never creates FIND directly.",
        },
        "candidates": candidates,
        "not_reported_yet": {
            "reason": "Candidates require AI triage and merge before business delivery.",
        },
    }


def render_md(pool: dict[str, Any]) -> str:
    lines = [
        "# CANDIDATE_POOL", "",
        "## Summary", "",
        f"- Total candidates: {pool['summary']['total_candidates']}",
        f"- Duplicate hits dropped: {pool['summary']['duplicate_hits_dropped']}",
        "- FIND count: 0", "",
        "## By status", "",
    ]
    for key, value in sorted(pool["summary"].get("by_status", {}).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Candidates", ""])
    if not pool.get("candidates"):
        lines.append("- None")
    for item in pool.get("candidates", [])[:120]:
        lines.append(f"- `{item['candidate_id']}` `{item.get('status')}` `{item.get('file_path')}:{item.get('line_start')}` {item.get('title')} — {item.get('evidence')}")
    lines.append("")
    return "\n".join(lines)


def print_summary(pool: dict[str, Any]) -> None:
    print("candidate-pool summary")
    print(f"  total_candidates: {pool['summary']['total_candidates']}")
    print(f"  duplicate_hits_dropped: {pool['summary']['duplicate_hits_dropped']}")
    print(f"  by_status: {pool['summary'].get('by_status')}")
    print(f"  by_risk_type: {pool['summary'].get('by_risk_type')}")


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
