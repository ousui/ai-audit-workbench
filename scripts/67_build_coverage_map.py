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
COVERAGE_DIMENSIONS = [
    "route_files",
    "auth_files",
    "data_access_files",
    "file_io_files",
    "high_risk_modules",
    "configs",
]
HIGH_VALUE_RISK_PARENTS = {
    "ACCESS_CONTROL",
    "AUTHENTICATION_SESSION",
    "BUSINESS_LOGIC",
    "INPUT_INJECTION",
    "FILE_OPERATION",
    "CRYPTOGRAPHY_SECRETS",
    "DATA_PROTECTION_PRIVACY",
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict[str, Any]:
    return load_json(path) if path.is_file() else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def bucket(audit_map: dict[str, Any], name: str) -> dict[str, Any]:
    return ((audit_map.get("files") or {}).get(name) or {})


def bucket_items(audit_map: dict[str, Any], name: str) -> list[Any]:
    return bucket(audit_map, name).get("items") or []


def bucket_count(audit_map: dict[str, Any], name: str) -> int:
    return int(bucket(audit_map, name).get("count") or 0)


def candidate_file(item: dict[str, Any]) -> str:
    return str(item.get("file_path") or "")


def candidate_status(item: dict[str, Any]) -> str:
    return str(item.get("status") or item.get("decision") or "")


def candidate_pool_items(pool: dict[str, Any]) -> list[dict[str, Any]]:
    return [x for x in pool.get("candidates") or [] if isinstance(x, dict)]


def index_candidates_by_file(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        path = candidate_file(item)
        if path:
            out.setdefault(path, []).append(item)
    return out


def path_from_map_item(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("file_path") or value.get("path") or "")
    return str(value)


def coverage_for_dimension(audit_map: dict[str, Any], candidates_by_file: dict[str, list[dict[str, Any]]], dimension: str) -> dict[str, Any]:
    items = bucket_items(audit_map, dimension)
    files = [path_from_map_item(x) for x in items]
    files = [x for x in files if x]
    candidate_count = 0
    matched_files = 0
    risk_parents: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for path in files:
        related = candidates_by_file.get(path) or []
        if related:
            matched_files += 1
        candidate_count += len(related)
        for candidate in related:
            rp = candidate.get("risk_parent") or "UNKNOWN"
            risk_parents[str(rp)] = risk_parents.get(str(rp), 0) + 1
            st = candidate_status(candidate) or "UNKNOWN"
            statuses[st] = statuses.get(st, 0) + 1
    total = bucket_count(audit_map, dimension)
    file_coverage_ratio = round(matched_files / len(files), 4) if files else 0.0
    coverage_level = "none"
    if candidate_count > 0 or matched_files > 0:
        coverage_level = "partial"
    if files and file_coverage_ratio >= 0.75:
        coverage_level = "broad"
    if total == 0:
        coverage_level = "not_applicable"
    return {
        "dimension": dimension,
        "evidence_file_count": total,
        "sampled_files": files[:30],
        "matched_files": matched_files,
        "candidate_count": candidate_count,
        "file_coverage_ratio": file_coverage_ratio,
        "coverage_level": coverage_level,
        "risk_parent_counts": dict(sorted(risk_parents.items())),
        "status_counts": dict(sorted(statuses.items())),
    }


def risk_parent_coverage(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: collections.Counter[str] = collections.Counter()
    status_counter: dict[str, collections.Counter[str]] = {}
    for item in candidates:
        rp = str(item.get("risk_parent") or "UNKNOWN")
        counter[rp] += 1
        status_counter.setdefault(rp, collections.Counter())[candidate_status(item) or "UNKNOWN"] += 1
    out = []
    for rp, count in sorted(counter.items(), key=lambda x: (-x[1], x[0])):
        out.append({
            "risk_parent": rp,
            "candidate_count": count,
            "status_counts": dict(sorted(status_counter.get(rp, {}).items())),
            "coverage_priority": "high" if rp in HIGH_VALUE_RISK_PARENTS else "medium",
        })
    return out


def build_gaps(audit_map: dict[str, Any], dimensions: list[dict[str, Any]], candidates: list[dict[str, Any]], threat_model: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    dim_by_id = {x["dimension"]: x for x in dimensions}
    for dim in dimensions:
        if dim.get("evidence_file_count", 0) > 0 and dim.get("candidate_count", 0) == 0:
            gaps.append({
                "gap_id": f"dimension:{dim['dimension']}:no_candidates",
                "severity": "medium",
                "dimension": dim["dimension"],
                "reason": "审计地图发现该类文件/模块，但当前候选池没有对应候选。",
                "suggested_next_step": "在 AI Deep Review 中优先抽样阅读该类文件，确认是否存在遗漏风险。",
            })
    route = dim_by_id.get("route_files", {})
    auth = dim_by_id.get("auth_files", {})
    if route.get("evidence_file_count", 0) > 0 and auth.get("evidence_file_count", 0) == 0:
        gaps.append({
            "gap_id": "boundary:http_api:no_auth_files",
            "severity": "high",
            "dimension": "route_files",
            "reason": "发现 API/路由入口，但未发现明显鉴权/权限文件。",
            "suggested_next_step": "AI Deep Review 应检查路由是否经过统一 middleware/filter/interceptor 鉴权。",
        })
    high_risk = dim_by_id.get("high_risk_modules", {})
    business_candidates = [x for x in candidates if x.get("risk_parent") in {"BUSINESS_LOGIC", "ACCESS_CONTROL"}]
    if high_risk.get("evidence_file_count", 0) > 0 and not business_candidates:
        gaps.append({
            "gap_id": "high_risk_modules:no_business_or_access_candidates",
            "severity": "high",
            "dimension": "high_risk_modules",
            "reason": "发现高风险业务模块，但当前候选池缺少业务逻辑或访问控制类候选。",
            "suggested_next_step": "AI Deep Review 应针对 order/pay/wallet/admin/callback 等模块做链路审计。",
        })
    if threat_model.get("summary", {}).get("trust_boundary_count", 0) and not candidates:
        gaps.append({
            "gap_id": "threat_boundaries:no_candidates",
            "severity": "medium",
            "dimension": "threat_model",
            "reason": "Threat Model 已识别信任边界，但候选池为空。",
            "suggested_next_step": "检查工具执行或候选生成是否过窄，并安排 AI Deep Review。",
        })
    return gaps


def build_coverage(run_root: Path) -> dict[str, Any]:
    audit_map = load_json(run_root / "audit-map" / "AUDIT_MAP.json")
    pool = load_optional_json(run_root / "candidates" / "CANDIDATE_POOL.json")
    threat_model = load_optional_json(run_root / "threat" / "THREAT_MODEL.json")
    kb_hits = load_optional_json(run_root / "knowledge" / "KB_HITS.json")
    candidates = candidate_pool_items(pool)
    candidates_by_file = index_candidates_by_file(candidates)
    dimensions = [coverage_for_dimension(audit_map, candidates_by_file, dim) for dim in COVERAGE_DIMENSIONS]
    risk_coverage = risk_parent_coverage(candidates)
    gaps = build_gaps(audit_map, dimensions, candidates, threat_model)
    return {
        "schema_version": "coverage-map-0.1.0",
        "generated_at": now(),
        "run": audit_map.get("run") or {},
        "project": audit_map.get("project") or {},
        "sources": {
            "audit_map": "audit-map/AUDIT_MAP.json",
            "candidate_pool": "candidates/CANDIDATE_POOL.json" if pool else None,
            "threat_model": "threat/THREAT_MODEL.json" if threat_model else None,
            "kb_hits": "knowledge/KB_HITS.json" if kb_hits else None,
        },
        "summary": {
            "dimension_count": len(dimensions),
            "candidate_count": len(candidates),
            "risk_parent_count": len(risk_coverage),
            "coverage_gap_count": len(gaps),
            "kb_hit_count": (kb_hits.get("summary") or {}).get("total_hits", 0),
        },
        "dimensions": dimensions,
        "risk_parent_coverage": risk_coverage,
        "coverage_gaps": gaps,
        "ai_deep_review_priorities": build_deep_review_priorities(dimensions, risk_coverage, gaps, threat_model),
        "notes": [
            "Coverage map is static and advisory only.",
            "Coverage gaps do not prove vulnerabilities; they identify where AI Deep Review should spend effort.",
            "Coverage is based on audit-map groups, candidate pool links, threat model and knowledge hits.",
        ],
    }


def build_deep_review_priorities(dimensions: list[dict[str, Any]], risk_coverage: list[dict[str, Any]], gaps: list[dict[str, Any]], threat_model: dict[str, Any]) -> list[dict[str, Any]]:
    priorities: list[dict[str, Any]] = []
    for gap in gaps:
        priorities.append({
            "priority": "high" if gap.get("severity") == "high" else "medium",
            "source": "coverage_gap",
            "target": gap.get("dimension"),
            "reason": gap.get("reason"),
            "suggested_next_step": gap.get("suggested_next_step"),
        })
    for item in risk_coverage[:20]:
        if item.get("risk_parent") in HIGH_VALUE_RISK_PARENTS:
            priorities.append({
                "priority": "high",
                "source": "risk_parent_coverage",
                "target": item.get("risk_parent"),
                "reason": f"高价值风险大类已有 {item.get('candidate_count')} 个候选，需要后续链路审计验证是否存在真实路径。",
                "suggested_next_step": "AI Deep Review 结合候选证据向上下游调用链扩展。",
            })
    for focus in threat_model.get("review_focus") or []:
        priorities.append({
            "priority": focus.get("priority") or "medium",
            "source": "threat_model",
            "target": focus.get("focus_id"),
            "reason": focus.get("reason"),
            "suggested_next_step": "在 AI Deep Review 中按 threat focus 抽样阅读相关入口、资产和边界。",
        })
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in sorted(priorities, key=lambda x: x.get("priority") != "high"):
        key = (str(item.get("source")), str(item.get("target")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= 80:
            break
    return out


def render_md(data: dict[str, Any]) -> str:
    lines = [
        "# COVERAGE_MAP", "",
        f"- Run ID: `{(data.get('run') or {}).get('run_id')}`",
        f"- Project: `{(data.get('project') or {}).get('project_name') or ''}`", "",
        "## Summary", "",
        f"- Dimensions: {(data.get('summary') or {}).get('dimension_count')}",
        f"- Candidates: {(data.get('summary') or {}).get('candidate_count')}",
        f"- Risk parents: {(data.get('summary') or {}).get('risk_parent_count')}",
        f"- Coverage gaps: {(data.get('summary') or {}).get('coverage_gap_count')}",
        f"- KB hits: {(data.get('summary') or {}).get('kb_hit_count')}", "",
        "## Dimensions", "",
        "| Dimension | Files | Matched files | Candidates | Ratio | Level |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in data.get("dimensions") or []:
        lines.append(f"| `{item.get('dimension')}` | {item.get('evidence_file_count')} | {item.get('matched_files')} | {item.get('candidate_count')} | {item.get('file_coverage_ratio')} | `{item.get('coverage_level')}` |")
    lines.extend(["", "## Risk parent coverage", ""])
    if not data.get("risk_parent_coverage"):
        lines.append("- None")
    for item in data.get("risk_parent_coverage") or []:
        lines.append(f"- `{item.get('risk_parent')}` candidates={item.get('candidate_count')} priority={item.get('coverage_priority')} statuses={item.get('status_counts')}")
    lines.extend(["", "## Coverage gaps", ""])
    if not data.get("coverage_gaps"):
        lines.append("- None")
    for gap in data.get("coverage_gaps") or []:
        lines.append(f"- `{gap.get('severity')}` `{gap.get('gap_id')}` {gap.get('reason')} Next: {gap.get('suggested_next_step')}")
    lines.extend(["", "## AI Deep Review priorities", ""])
    if not data.get("ai_deep_review_priorities"):
        lines.append("- None")
    for item in data.get("ai_deep_review_priorities") or []:
        lines.append(f"- `{item.get('priority')}` `{item.get('source')}` `{item.get('target')}` {item.get('reason')}")
    lines.extend(["", "## Notes", ""])
    for note in data.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def print_summary(data: dict[str, Any]) -> None:
    s = data.get("summary") or {}
    print("coverage-map summary")
    print(f"  dimensions: {s.get('dimension_count')}")
    print(f"  candidates: {s.get('candidate_count')}")
    print(f"  risk_parents: {s.get('risk_parent_count')}")
    print(f"  coverage_gaps: {s.get('coverage_gap_count')}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build static coverage map from audit map, candidates and threat model.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    if not (run_root / "audit-map" / "AUDIT_MAP.json").is_file():
        print("[FAIL] AUDIT_MAP.json not found. Run audit-map first.", file=sys.stderr)
        return 2
    data = build_coverage(run_root)
    out = run_root / "coverage"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "COVERAGE_MAP.json", data)
    (out / "COVERAGE_MAP.md").write_text(render_md(data), encoding="utf-8")
    if args.print_summary:
        print_summary(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
