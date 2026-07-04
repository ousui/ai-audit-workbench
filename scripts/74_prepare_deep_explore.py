#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

RISK_PRIORITY = [
    "sensitive_information",
    "configuration_exposure",
    "sql_injection_candidate",
    "file_io_candidate",
    "client_storage_candidate",
    "business_logic_review_candidate",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def bucket_items(bucket: dict[str, Any], limit: int) -> list[Any]:
    return (bucket.get("items") or [])[:limit]


def summarize_candidates(pool: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    candidates = pool.get("candidates") or []
    def rank(item: dict[str, Any]) -> tuple[int, str]:
        risk = item.get("risk_type") or ""
        priority = RISK_PRIORITY.index(risk) if risk in RISK_PRIORITY else 99
        return priority, item.get("candidate_id") or ""
    selected = sorted(candidates, key=rank)[:limit]
    return [
        {
            "candidate_id": item.get("candidate_id"),
            "status": item.get("status"),
            "risk_type": item.get("risk_type"),
            "title": item.get("title"),
            "file_path": item.get("file_path"),
            "line_start": item.get("line_start"),
            "evidence": item.get("evidence"),
            "negative_evidence_required": item.get("negative_evidence_required") or [],
        }
        for item in selected
    ]


def build_deep_input(run_root: Path, max_candidates: int) -> dict[str, Any]:
    pack = load_json(run_root / "evidence" / "EVIDENCE_PACK.json")
    audit_map = load_json(run_root / "audit-map" / "AUDIT_MAP.json")
    pool_path = run_root / "candidates" / "CANDIDATE_POOL.json"
    pool = load_json(pool_path) if pool_path.is_file() else {"candidates": [], "summary": {}}

    files = audit_map.get("files", {})
    signals = audit_map.get("signals", {})

    suggested_scopes = [
        {
            "scope_id": "SCOPE-SENSITIVE-RESPONSE",
            "title": "用户、账号、鉴权、响应字段泄露语义探索",
            "focus": ["DTO/VO/Entity 复用", "响应脱敏", "认证凭据字段别名", "用户详情/列表/导出接口"],
            "candidate_risk_types": ["sensitive_information", "configuration_exposure"],
            "files": bucket_items(files.get("auth_files", {}), 80) + bucket_items(files.get("route_files", {}), 80),
        },
        {
            "scope_id": "SCOPE-AUTHZ-CHAIN",
            "title": "鉴权与资源归属链路语义探索",
            "focus": ["水平越权", "垂直越权", "多租户隔离", "管理员接口"],
            "candidate_risk_types": ["business_logic_review_candidate"],
            "files": bucket_items(files.get("auth_files", {}), 100) + bucket_items(files.get("data_access_files", {}), 100),
        },
        {
            "scope_id": "SCOPE-BUSINESS-STATE",
            "title": "支付、订单、钱包、回调等业务状态机探索",
            "focus": ["幂等", "状态流转", "签名校验", "金额边界", "回调来源校验"],
            "candidate_risk_types": ["business_logic_review_candidate"],
            "files": bucket_items(files.get("high_risk_modules", {}), 160),
        },
        {
            "scope_id": "SCOPE-FILE-IO",
            "title": "文件上传下载与路径处理探索",
            "focus": ["扩展名白名单", "路径穿越", "原始文件名", "Web 根目录写入"],
            "candidate_risk_types": ["file_io_candidate"],
            "files": bucket_items(files.get("file_io_files", {}), 120),
        },
    ]

    return {
        "schema_version": "deep-explore-input-0.1.0",
        "mode": "DEEP_STATIC_EXPLORE",
        "run": pack.get("run"),
        "project": {
            "project_code": pack.get("project", {}).get("project_code"),
            "project_name": pack.get("project", {}).get("project_name"),
            "git": pack.get("project", {}).get("git", {}),
        },
        "boundaries": {
            "read_only_project": True,
            "no_dynamic_testing": True,
            "no_service_start": True,
            "no_external_request": True,
            "new_findings_must_be_candidates": True,
            "output_schema_ref": "schemas/AI_DISCOVERED_CANDIDATES.schema.json",
        },
        "audit_map_summary": pack.get("audit_map_summary", {}),
        "candidate_summary": pool.get("summary", {}),
        "priority_candidates": summarize_candidates(pool, max_candidates),
        "suggested_scopes": suggested_scopes,
        "signal_preview": {
            "route_hits": bucket_items(signals.get("route_hits", {}), 80),
            "frontend_api_hits": bucket_items(signals.get("frontend_api_hits", {}), 80),
            "local_storage_hits": bucket_items(signals.get("local_storage_hits", {}), 80),
        },
        "instructions": {
            "prompt_ref": "prompts/deep/DEEP_STATIC_EXPLORE.md",
            "result_must_not_be_written_to_delivery_directly": True,
            "result_must_be_imported_as_candidates_later": True,
        },
    }


def render_md(data: dict[str, Any]) -> str:
    lines = [
        "# DEEP_EXPLORE_INPUT",
        "",
        f"- Mode: `{data.get('mode')}`",
        f"- Project: `{data.get('project', {}).get('project_name')}`",
        f"- Priority candidates: {len(data.get('priority_candidates') or [])}",
        f"- Suggested scopes: {len(data.get('suggested_scopes') or [])}",
        "",
        "## Boundaries",
        "",
    ]
    for key, value in data.get("boundaries", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Suggested scopes", ""])
    for scope in data.get("suggested_scopes", []):
        lines.append(f"### {scope.get('scope_id')} {scope.get('title')}")
        for focus in scope.get("focus", []):
            lines.append(f"- {focus}")
        lines.append("")
    return "\n".join(lines)


def print_summary(data: dict[str, Any]) -> None:
    print("deep-explore input summary")
    print(f"  mode: {data.get('mode')}")
    print(f"  project: {data.get('project', {}).get('project_name')}")
    print(f"  priority_candidates: {len(data.get('priority_candidates') or [])}")
    print(f"  suggested_scopes: {len(data.get('suggested_scopes') or [])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Prepare DEEP_STATIC_EXPLORE input package.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--max-candidates", type=int, default=80)
    parser.add_argument("--write-empty-discovered", action="store_true")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    if not (run_root / "evidence" / "EVIDENCE_PACK.json").is_file():
        print("[FAIL] EVIDENCE_PACK.json not found. Run make m4 first.", file=sys.stderr)
        return 2

    data = build_deep_input(run_root, args.max_candidates)
    out = run_root / "ai"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "DEEP_EXPLORE_INPUT.json", data)
    (out / "DEEP_EXPLORE_INPUT.md").write_text(render_md(data), encoding="utf-8")

    if args.write_empty_discovered:
        write_json(run_root / "candidates" / "AI_DISCOVERED_CANDIDATES.json", {
            "schema_version": "ai-discovered-candidates-0.1.0",
            "mode": "DEEP_STATIC_EXPLORE",
            "new_candidates": [],
            "notes": ["Empty placeholder for pipeline validation. Real deep exploration output must be reviewed before import."],
        })

    if args.print_summary:
        print_summary(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
