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
DEFAULT_KB = ROOT / "local" / "registry" / "knowledge" / "AUDIT_KNOWLEDGE.yaml"
SECTIONS = ["risk_patterns", "false_positive_memories", "remediation_notes", "tool_notes", "project_lessons"]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": "audit-knowledge-0.1.0", **{section: [] for section in SECTIONS}}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"schema_version": "audit-knowledge-0.1.0", **{section: [] for section in SECTIONS}}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def text_blob(item: dict[str, Any]) -> str:
    parts = [
        item.get("candidate_id"), item.get("title"), item.get("risk_type"), item.get("risk_parent"), item.get("risk_subtype"),
        item.get("file_path"), item.get("evidence"), item.get("matched_pattern"), item.get("source_tool"), item.get("source"),
        " ".join(item.get("tags") or []),
    ]
    return "\n".join(str(x or "") for x in parts).lower()


def entry_match_values(entry: dict[str, Any]) -> dict[str, list[str]]:
    match = entry.get("match") if isinstance(entry.get("match"), dict) else {}
    keywords = as_list(entry.get("keywords")) + as_list(match.get("keywords"))
    tags = as_list(entry.get("tags")) + as_list(match.get("tags"))
    source_tools = as_list(entry.get("source_tool")) + as_list(match.get("source_tools")) + as_list(match.get("source_tool"))
    return {
        "keywords": [str(x).lower() for x in keywords if x],
        "tags": [str(x) for x in tags if x],
        "source_tools": [str(x) for x in source_tools if x],
    }


def score_entry(candidate: dict[str, Any], entry: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if entry.get("risk_parent") and entry.get("risk_parent") == candidate.get("risk_parent"):
        score += 2
        reasons.append("risk_parent_exact")
    if entry.get("risk_subtype") and entry.get("risk_subtype") == candidate.get("risk_subtype"):
        score += 3
        reasons.append("risk_subtype_exact")
    if entry.get("risk_type") and entry.get("risk_type") == candidate.get("risk_type"):
        score += 2
        reasons.append("risk_type_exact")
    values = entry_match_values(entry)
    candidate_tags = set(str(x) for x in (candidate.get("tags") or []))
    for tag in values["tags"]:
        if tag in candidate_tags:
            score += 1
            reasons.append(f"tag:{tag}")
    source_tool = candidate.get("source_tool")
    for tool in values["source_tools"]:
        if tool and tool == source_tool:
            score += 2
            reasons.append(f"source_tool:{tool}")
    blob = text_blob(candidate)
    for keyword in values["keywords"]:
        if keyword and re.search(re.escape(keyword), blob, flags=re.I):
            score += 1
            reasons.append(f"keyword:{keyword}")
    return score, reasons


def iter_entries(kb: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for section in SECTIONS:
        for raw in kb.get(section) or []:
            if isinstance(raw, dict):
                out.append((section, raw))
    return out


def build_hit(hit_no: int, candidate: dict[str, Any], section: str, entry: dict[str, Any], score: int, reasons: list[str]) -> dict[str, Any]:
    knowledge_id = entry.get("id") or f"{section}:{hit_no}"
    return {
        "hit_id": f"KBHIT-{hit_no:05d}",
        "candidate_id": candidate.get("candidate_id"),
        "knowledge_id": knowledge_id,
        "knowledge_type": section,
        "score": score,
        "match_reasons": reasons,
        "scope": entry.get("scope") or "global",
        "confidence": entry.get("confidence") or "medium",
        "summary": entry.get("summary") or entry.get("title") or knowledge_id,
        "recommendation": entry.get("recommendation") or "",
        "tags": entry.get("tags") or [],
    }


def match_knowledge(run_root: Path, kb_path: Path, min_score: int, max_hits_per_candidate: int) -> dict[str, Any]:
    pool = load_json(run_root / "candidates" / "CANDIDATE_POOL.json")
    kb = load_yaml(kb_path)
    entries = iter_entries(kb)
    hits: list[dict[str, Any]] = []
    candidate_hits: dict[str, list[dict[str, Any]]] = {}
    by_type: dict[str, int] = {}
    hit_no = 0
    for candidate in pool.get("candidates") or []:
        scored: list[tuple[int, list[str], str, dict[str, Any]]] = []
        for section, entry in entries:
            score, reasons = score_entry(candidate, entry)
            if score >= min_score:
                scored.append((score, reasons, section, entry))
        scored.sort(key=lambda x: (-x[0], str(x[2]), str(x[3].get("id") or x[3].get("summary") or "")))
        for score, reasons, section, entry in scored[:max_hits_per_candidate]:
            hit_no += 1
            hit = build_hit(hit_no, candidate, section, entry, score, reasons)
            hits.append(hit)
            candidate_hits.setdefault(candidate.get("candidate_id") or "", []).append({
                "hit_id": hit["hit_id"],
                "knowledge_id": hit["knowledge_id"],
                "knowledge_type": hit["knowledge_type"],
                "score": hit["score"],
                "summary": hit["summary"],
            })
            by_type[section] = by_type.get(section, 0) + 1
    return {
        "schema_version": "kb-hits-0.1.0",
        "generated_at": now(),
        "knowledge_spec_ref": "spec/rules/audit-knowledge.yaml",
        "knowledge_base": {"path": str(kb_path), "exists": kb_path.is_file(), "schema_version": kb.get("schema_version")},
        "summary": {
            "knowledge_entries": len(entries),
            "total_hits": len(hits),
            "candidates_with_hits": len(candidate_hits),
            "by_type": by_type,
            "min_score": min_score,
            "max_hits_per_candidate": max_hits_per_candidate,
        },
        "candidate_hits": candidate_hits,
        "hits": hits,
        "notes": [
            "Knowledge hits are advisory only and must not override current code evidence.",
            "Missing local knowledge base is valid; the workflow continues with zero hits.",
        ],
    }


def render_md(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        "# KB_HITS", "",
        f"- Knowledge base exists: `{result['knowledge_base']['exists']}`",
        f"- Knowledge entries: {s['knowledge_entries']}",
        f"- Total hits: {s['total_hits']}",
        f"- Candidates with hits: {s['candidates_with_hits']}", "",
        "## Hits", "",
    ]
    if not result.get("hits"):
        lines.append("- None")
    for hit in result.get("hits", [])[:120]:
        lines.append(f"- `{hit['hit_id']}` `{hit['candidate_id']}` `{hit['knowledge_type']}` score={hit['score']} {hit['summary']}")
    lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    print("knowledge-match summary")
    print(f"  kb_exists: {result['knowledge_base']['exists']}")
    print(f"  knowledge_entries: {result['summary']['knowledge_entries']}")
    print(f"  total_hits: {result['summary']['total_hits']}")
    print(f"  candidates_with_hits: {result['summary']['candidates_with_hits']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Match local audit knowledge against candidate pool.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KB))
    parser.add_argument("--min-score", type=int, default=2)
    parser.add_argument("--max-hits-per-candidate", type=int, default=5)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    kb_path = Path(args.knowledge_base)
    if not kb_path.is_absolute():
        kb_path = (ROOT / kb_path).resolve()
    if not (run_root / "candidates" / "CANDIDATE_POOL.json").is_file():
        print("[FAIL] CANDIDATE_POOL.json not found. Run candidates first.", file=sys.stderr)
        return 2
    result = match_knowledge(run_root, kb_path, args.min_score, args.max_hits_per_candidate)
    out = run_root / "knowledge"
    write_json(out / "KB_HITS.json", result)
    (out / "KB_HITS.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
