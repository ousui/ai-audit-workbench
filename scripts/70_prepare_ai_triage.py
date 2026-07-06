#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AI_ALLOWED_AUDIT_STATUS = {"FIND", "REVIEW", "RUNTIME", "CAND", "FP", "BLOCKED"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def lifecycle_policy() -> dict[str, Any]:
    return {
        "spec_ref": "spec/rules/audit-lifecycle.yaml",
        "audit_status_allowed": sorted(AI_ALLOWED_AUDIT_STATUS),
        "business_status_allowed_for_ai": [],
        "verification_status_allowed_for_ai": [],
        "must_not_create_unreferenced_findings": True,
        "must_not_set_business_status": True,
        "must_not_set_verification_status": True,
        "must_not_use_accepted_risk_as_audit_status": True,
        "candidate_pool_initial_statuses": ["CAND", "REVIEW", "RUNTIME", "BLOCKED"],
    }


def build_input(run_root: Path, max_candidates: int) -> dict[str, Any]:
    pack = load_json(run_root / "evidence" / "EVIDENCE_PACK.json")
    pool = load_json(run_root / "candidates" / "CANDIDATE_POOL.json")
    candidates = pool.get("candidates") or []
    return {
        "schema_version": "ai-triage-input-0.3.0",
        "triage_mode": "FAST_STATIC",
        "run": pack.get("run"),
        "project": pack.get("project"),
        "lifecycle_policy": lifecycle_policy(),
        "evidence_pack_summary": {
            "audit_map_summary": pack.get("audit_map_summary", {}),
            "project_facts_summary": pack.get("project_facts_summary", {}),
            "project_doc_profile_summary": pack.get("project_doc_profile_summary", {}),
            "tool_plan_summary": pack.get("tool_plan_summary", {}),
            "preflight_summary": pack.get("preflight_summary", {}),
            "key_files": pack.get("key_files", {}),
            "signals": pack.get("signals", {}),
        },
        "candidate_summary": pool.get("summary", {}),
        "candidates": candidates[:max_candidates],
        "instructions": {
            "prompt_ref": "spec/prompts/triage/FAST_STATIC.md",
            "output_schema_ref": "spec/schemas/AI_TRIAGE_RESULT.schema.json",
            "lifecycle_spec_ref": "spec/rules/audit-lifecycle.yaml",
            "must_not_create_unreferenced_findings": True,
            "current_stage_dynamic_testing": False,
        },
    }


def audit_decision_event(candidate: dict[str, Any], decision: str, reason: str) -> dict[str, Any]:
    return {
        "event_type": "audit_decision",
        "stage": "ai_triage_stub",
        "actor": "stub",
        "from": {"status": candidate.get("status") or "CAND"},
        "to": {"status": decision},
        "reason": reason,
        "evidence_refs": [candidate.get("candidate_id") or ""],
    }


def stub_decision(candidate: dict[str, Any]) -> dict[str, Any]:
    status = str(candidate.get("status") or "CAND").upper()
    decision = status if status in {"REVIEW", "RUNTIME", "CAND", "FP", "BLOCKED"} else "CAND"
    reason = "stub result generated for deterministic pipeline validation. It must not be treated as final audit conclusion."
    tags = list(candidate.get("tags") or [])
    if "stub_triage" not in tags:
        tags.append("stub_triage")
    return {
        "candidate_id": candidate.get("candidate_id"),
        "decision": decision,
        "severity": candidate.get("severity_hint") or "P2",
        "confidence": candidate.get("confidence_hint") or "low",
        "title": candidate.get("title") or "静态候选项",
        "risk_type": candidate.get("risk_type") or "static_candidate",
        "risk_parent": candidate.get("risk_parent"),
        "risk_subtype": candidate.get("risk_subtype"),
        "evidence": candidate.get("evidence") or "",
        "risk_chain": "STUB 模式未执行 AI 语义判断，仅保留候选状态。",
        "negative_evidence_checked": [],
        "missing_evidence": candidate.get("negative_evidence_required") or [],
        "impact": "待 AI 或人工复核后确认。",
        "recommendation": "后续执行 AI triage 或人工复核。",
        "tags": tags,
        "lifecycle_event": audit_decision_event(candidate, decision, reason),
        "questions_for_human": [],
        "knowledge_update_suggestions": [],
        "reason": reason,
    }


def build_stub_result(triage_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ai-triage-result-0.2.0",
        "triage_mode": "STUB",
        "items": [stub_decision(item) for item in triage_input.get("candidates", [])],
        "knowledge_update_suggestions": [],
        "notes": ["This is a stub triage result for pipeline validation.", "Replace it with real AI triage output before treating results as audit conclusions."],
    }


def print_summary(triage_input: dict[str, Any], stub_result: dict[str, Any] | None) -> None:
    print("ai-triage input summary")
    print(f"  run_id: {triage_input.get('run', {}).get('run_id')}")
    print(f"  candidates: {len(triage_input.get('candidates') or [])}")
    print(f"  mode: {triage_input.get('triage_mode')}")
    print(f"  lifecycle_spec: {triage_input.get('lifecycle_policy', {}).get('spec_ref')}")
    if stub_result is not None:
        print(f"  stub_items: {len(stub_result.get('items') or [])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Prepare AI triage input for one run.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--max-candidates", type=int, default=200)
    parser.add_argument("--write-stub", action="store_true", help="Write stub AI_TRIAGE_RESULT.json for pipeline validation.")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    if not (run_root / "candidates" / "CANDIDATE_POOL.json").is_file():
        print("[FAIL] CANDIDATE_POOL.json not found. Run make m6 first.", file=sys.stderr)
        return 2
    out = run_root / "ai"
    out.mkdir(parents=True, exist_ok=True)
    triage_input = build_input(run_root, args.max_candidates)
    write_json(out / "AI_TRIAGE_INPUT.json", triage_input)
    stub = None
    if args.write_stub:
        stub = build_stub_result(triage_input)
        write_json(out / "AI_TRIAGE_RESULT.json", stub)
        (out / "AI_TRIAGE_RAW.txt").write_text("Stub AI triage result generated by scripts/70_prepare_ai_triage.py\n", encoding="utf-8")
    if args.print_summary:
        print_summary(triage_input, stub)
    else:
        print(f"ai triage input written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
