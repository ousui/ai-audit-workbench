#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

KNOWN_ARTIFACTS = [
    "meta/RUN_METADATA.json",
    "meta/PROJECT_PROFILE.json",
    "audit-map/AUDIT_MAP.json",
    "audit-map/AUDIT_MAP.md",
    "evidence/TOOL_PLAN.json",
    "evidence/TOOL_PLAN.md",
    "evidence/EVIDENCE_PACK.json",
    "evidence/EVIDENCE_PACK.md",
    "evidence/TOOL_RUN_RESULT.json",
    "evidence/TOOL_RUN_RESULT.md",
    "evidence/tool-outputs/STATIC_PATTERN_HITS.json",
    "candidates/CANDIDATE_POOL.json",
    "candidates/CANDIDATE_POOL.md",
    "ai/AI_TRIAGE_INPUT.json",
    "ai/AI_TRIAGE_RESULT.json",
    "ai/AI_TRIAGE_RAW.txt",
    "merge/MERGE_RESULT.json",
    "merge/MERGE_RESULT.md",
    "delivery/AUDIT_REPORT.md",
    "delivery/AUDIT_REPORT.html",
    "delivery/AUDIT_TRACKING.csv",
    "delivery/DELIVERY_RECORD.json",
    "validate/VALIDATION_RESULT.json",
    "validate/VALIDATION_RESULT.md",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_manifest(run_root: Path) -> dict[str, Any]:
    items = []
    for rel in KNOWN_ARTIFACTS:
        path = run_root / rel
        item = {
            "path": rel,
            "exists": path.is_file(),
            "size_bytes": path.stat().st_size if path.is_file() else None,
            "sha256": sha256(path) if path.is_file() else None,
        }
        items.append(item)
    return {
        "schema_version": "artifact-manifest-0.1.0",
        "artifact_count": len(items),
        "existing_count": sum(1 for item in items if item["exists"]),
        "missing_count": sum(1 for item in items if not item["exists"]),
        "items": items,
    }


def candidate_flow(run_root: Path) -> dict[str, Any]:
    pool_path = run_root / "candidates" / "CANDIDATE_POOL.json"
    triage_path = run_root / "ai" / "AI_TRIAGE_RESULT.json"
    merge_path = run_root / "merge" / "MERGE_RESULT.json"

    pool = load_json(pool_path) if pool_path.is_file() else {"candidates": []}
    triage = load_json(triage_path) if triage_path.is_file() else {"items": []}
    merge = load_json(merge_path) if merge_path.is_file() else {"id_map": []}

    triage_by_id = {item.get("candidate_id"): item for item in triage.get("items", []) if item.get("candidate_id")}
    merge_by_id = {item.get("candidate_id"): item for item in merge.get("id_map", []) if item.get("candidate_id")}

    flows = []
    for cand in pool.get("candidates", []):
        cid = cand.get("candidate_id")
        triage_item = triage_by_id.get(cid, {})
        merge_item = merge_by_id.get(cid, {})
        flows.append({
            "candidate_id": cid,
            "source": cand.get("source"),
            "recipe_id": cand.get("recipe_id"),
            "risk_type": cand.get("risk_type"),
            "initial_status": cand.get("status"),
            "ai_decision": triage_item.get("decision"),
            "merge_decision": merge_item.get("decision"),
            "target_id": merge_item.get("target_id"),
            "report_inclusion": merge_item.get("decision") in {"FIND", "REVIEW", "RUNTIME", "BLOCKED"},
        })

    return {
        "schema_version": "candidate-flow-trace-0.1.0",
        "candidate_count": len(flows),
        "flows": flows,
    }


def merge_trace(run_root: Path) -> dict[str, Any]:
    path = run_root / "merge" / "MERGE_RESULT.json"
    if not path.is_file():
        return {"schema_version": "merge-trace-0.1.0", "available": False}
    data = load_json(path)
    return {
        "schema_version": "merge-trace-0.1.0",
        "available": True,
        "triage_mode": data.get("triage_mode"),
        "summary": data.get("summary", {}),
        "notes": data.get("notes", []),
    }


def validation_trace(run_root: Path) -> dict[str, Any]:
    path = run_root / "validate" / "VALIDATION_RESULT.json"
    if not path.is_file():
        return {"schema_version": "validation-trace-0.1.0", "available": False}
    data = load_json(path)
    return {
        "schema_version": "validation-trace-0.1.0",
        "available": True,
        "status": data.get("status"),
        "error_count": data.get("error_count"),
        "warning_count": data.get("warning_count"),
        "errors": data.get("errors", []),
        "warnings": data.get("warnings", []),
    }


def debug_summary_md(run_root: Path, level: str, manifest: dict[str, Any], flow: dict[str, Any], merge: dict[str, Any], validation: dict[str, Any]) -> str:
    lines = [
        "# DEBUG_SUMMARY",
        "",
        f"- Debug level: `{level}`",
        f"- Run root: `{run_root.relative_to(ROOT) if run_root.is_relative_to(ROOT) else run_root}`",
        f"- Artifacts existing: {manifest.get('existing_count')}",
        f"- Artifacts missing: {manifest.get('missing_count')}",
        f"- Candidate flow count: {flow.get('candidate_count')}",
        f"- Merge triage mode: `{merge.get('triage_mode')}`",
        f"- Validation status: `{validation.get('status')}`",
        "",
        "## Merge summary",
        "",
    ]
    for key, value in (merge.get("summary") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Validation warnings", ""])
    warnings = validation.get("warnings") or []
    if warnings:
        for item in warnings:
            lines.append(f"- {item}")
    else:
        lines.append("- None")
    lines.extend(["", "## Notes", "", "- Debug artifacts are internal workflow artifacts and must not be included in business-facing reports by default.", "- Debug collection does not change audit conclusions.", ""])
    return "\n".join(lines)


def collect(run_root: Path, level: str) -> dict[str, Any]:
    debug_dir = run_root / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    manifest = artifact_manifest(run_root)
    flow = candidate_flow(run_root)
    merge = merge_trace(run_root)
    validation = validation_trace(run_root)

    write_json(debug_dir / "ARTIFACT_MANIFEST.json", manifest)
    write_json(debug_dir / "CANDIDATE_FLOW_TRACE.json", flow)
    write_json(debug_dir / "MERGE_TRACE.json", merge)
    write_json(debug_dir / "VALIDATION_TRACE.json", validation)
    (debug_dir / "DEBUG_SUMMARY.md").write_text(debug_summary_md(run_root, level, manifest, flow, merge, validation), encoding="utf-8")

    return {"manifest": manifest, "flow": flow, "merge": merge, "validation": validation}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Collect debug artifacts for one run.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--debug-level", default="basic", choices=["basic", "trace"])
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2

    result = collect(run_root, args.debug_level)
    if args.print_summary:
        print("debug summary")
        print(f"  artifacts_existing: {result['manifest'].get('existing_count')}")
        print(f"  artifacts_missing: {result['manifest'].get('missing_count')}")
        print(f"  candidate_flow_count: {result['flow'].get('candidate_count')}")
        print(f"  validation_status: {result['validation'].get('status')}")
    else:
        print(f"debug artifacts written to {run_root / 'debug'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
