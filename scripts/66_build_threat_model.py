#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES = ROOT / "spec" / "rules" / "threat-model.yaml"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict[str, Any]:
    return load_json(path) if path.is_file() else {}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def bucket_items(audit_map: dict[str, Any], bucket: str) -> list[Any]:
    return (((audit_map.get("files") or {}).get(bucket) or {}).get("items") or [])


def bucket_count(audit_map: dict[str, Any], bucket: str) -> int:
    return int((((audit_map.get("files") or {}).get(bucket) or {}).get("count") or 0))


def signal_items(audit_map: dict[str, Any], signal: str) -> list[Any]:
    return (((audit_map.get("signals") or {}).get(signal) or {}).get("items") or [])


def signal_count(audit_map: dict[str, Any], signal: str) -> int:
    return int((((audit_map.get("signals") or {}).get(signal) or {}).get("count") or 0))


def evidence_paths(values: list[Any], limit: int = 20) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, str):
            path = value
        elif isinstance(value, dict):
            path = value.get("file_path") or value.get("path") or ""
        else:
            path = str(value)
        if path and path not in out:
            out.append(path)
        if len(out) >= limit:
            break
    return out


def text_hits(values: list[Any], keywords: list[str]) -> list[str]:
    hits: list[str] = []
    lowered = [x.lower() for x in keywords]
    for value in values:
        if isinstance(value, str):
            text = value.lower()
            path = value
        elif isinstance(value, dict):
            text = json.dumps(value, ensure_ascii=False).lower()
            path = value.get("file_path") or value.get("path") or text[:120]
        else:
            text = str(value).lower()
            path = str(value)
        if any(k in text for k in lowered) and path not in hits:
            hits.append(path)
    return hits[:20]


def risk_parent_summary(pool: dict[str, Any]) -> dict[str, int]:
    summary = (pool.get("summary") or {}).get("by_risk_parent")
    if isinstance(summary, dict):
        return {str(k): int(v) for k, v in summary.items()}
    out: dict[str, int] = {}
    for item in pool.get("candidates") or []:
        rp = item.get("risk_parent")
        if rp:
            out[str(rp)] = out.get(str(rp), 0) + 1
    return out


def detect_asset(asset_id: str, rule: dict[str, Any], audit_map: dict[str, Any], pool: dict[str, Any]) -> dict[str, Any] | None:
    triggers = rule.get("triggers") or {}
    evidence: list[str] = []
    evidence_count = 0
    for group in triggers.get("file_groups") or []:
        count = bucket_count(audit_map, str(group))
        evidence_count += count
        evidence.extend(evidence_paths(bucket_items(audit_map, str(group))))
    keyword_source: list[Any] = []
    for group_name in ["route_files", "auth_files", "data_access_files", "file_io_files", "high_risk_modules", "configs", "manifests"]:
        keyword_source.extend(bucket_items(audit_map, group_name))
    hits = text_hits(keyword_source, [str(x) for x in triggers.get("keywords") or []])
    evidence.extend(hits)
    evidence_count += len(hits)
    related_risk_parents = rule.get("default_risk_parents") or []
    rp_counts = risk_parent_summary(pool)
    candidate_count = sum(rp_counts.get(str(rp), 0) for rp in related_risk_parents)
    if evidence_count == 0 and candidate_count == 0:
        return None
    return {
        "asset_id": asset_id,
        "label_zh": rule.get("label_zh") or asset_id,
        "evidence_count": evidence_count,
        "evidence": evidence_paths(evidence, limit=30),
        "related_risk_parents": related_risk_parents,
        "related_candidate_count": candidate_count,
        "review_priority": "high" if candidate_count or evidence_count >= 5 else "medium",
    }


def detect_entrypoint(entrypoint_id: str, rule: dict[str, Any], audit_map: dict[str, Any]) -> dict[str, Any] | None:
    triggers = rule.get("triggers") or {}
    evidence: list[str] = []
    count = 0
    for group in triggers.get("file_groups") or []:
        count += bucket_count(audit_map, str(group))
        evidence.extend(evidence_paths(bucket_items(audit_map, str(group))))
    for signal in triggers.get("signal_groups") or []:
        count += signal_count(audit_map, str(signal))
        evidence.extend(evidence_paths(signal_items(audit_map, str(signal))))
    if triggers.get("keywords"):
        source: list[Any] = []
        for group_name in ["route_files", "high_risk_modules", "auth_files", "file_io_files"]:
            source.extend(bucket_items(audit_map, group_name))
        hits = text_hits(source, [str(x) for x in triggers.get("keywords") or []])
        count += len(hits)
        evidence.extend(hits)
    if count == 0:
        return None
    return {
        "entrypoint_id": entrypoint_id,
        "label_zh": rule.get("label_zh") or entrypoint_id,
        "evidence_count": count,
        "evidence": evidence_paths(evidence, limit=30),
        "review_focus": rule.get("review_focus") or [],
    }


def detect_boundary(boundary_id: str, rule: dict[str, Any], assets: list[dict[str, Any]], entrypoints: list[dict[str, Any]]) -> dict[str, Any] | None:
    evidence_from = {str(x) for x in rule.get("evidence_from") or []}
    asset_ids = {x.get("asset_id") for x in assets}
    entrypoint_ids = {x.get("entrypoint_id") for x in entrypoints}
    matched = sorted((asset_ids | entrypoint_ids) & evidence_from)
    if not matched:
        return None
    return {
        "boundary_id": boundary_id,
        "label_zh": rule.get("label_zh") or boundary_id,
        "evidence_from": matched,
        "review_priority": "high" if len(matched) >= 2 else "medium",
    }


def build_threat_model(run_root: Path, rules_path: Path) -> dict[str, Any]:
    audit_map = load_json(run_root / "audit-map" / "AUDIT_MAP.json")
    facts = load_optional_json(run_root / "audit-map" / "PROJECT_FACTS.json")
    doc_profile = load_optional_json(run_root / "audit-map" / "PROJECT_DOC_PROFILE.json")
    pool = load_optional_json(run_root / "candidates" / "CANDIDATE_POOL.json")
    rules = load_yaml(rules_path)
    assets: list[dict[str, Any]] = []
    for asset_id, rule in (rules.get("asset_rules") or {}).items():
        if isinstance(rule, dict):
            item = detect_asset(str(asset_id), rule, audit_map, pool)
            if item:
                assets.append(item)
    entrypoints: list[dict[str, Any]] = []
    for entrypoint_id, rule in (rules.get("entrypoint_rules") or {}).items():
        if isinstance(rule, dict):
            item = detect_entrypoint(str(entrypoint_id), rule, audit_map)
            if item:
                entrypoints.append(item)
    trust_boundaries: list[dict[str, Any]] = []
    for boundary_id, rule in (rules.get("trust_boundary_rules") or {}).items():
        if isinstance(rule, dict):
            item = detect_boundary(str(boundary_id), rule, assets, entrypoints)
            if item:
                trust_boundaries.append(item)
    stacks = (audit_map.get("stacks") or {}).get("detected_stack_ids") or []
    return {
        "schema_version": "threat-model-0.1.0",
        "generated_at": now(),
        "rules_ref": rel(rules_path),
        "run": audit_map.get("run") or facts.get("run") or {},
        "project": audit_map.get("project") or facts.get("project") or {},
        "sources": {
            "audit_map": "audit-map/AUDIT_MAP.json",
            "project_facts": "audit-map/PROJECT_FACTS.json" if facts else None,
            "project_doc_profile": "audit-map/PROJECT_DOC_PROFILE.json" if doc_profile else None,
            "candidate_pool": "candidates/CANDIDATE_POOL.json" if pool else None,
        },
        "summary": {
            "detected_stack_ids": stacks,
            "asset_count": len(assets),
            "entrypoint_count": len(entrypoints),
            "trust_boundary_count": len(trust_boundaries),
            "candidate_count": (pool.get("summary") or {}).get("total_candidates", 0),
        },
        "assets": assets,
        "entrypoints": entrypoints,
        "trust_boundaries": trust_boundaries,
        "review_focus": build_review_focus(assets, entrypoints, trust_boundaries),
        "notes": [
            "Threat model is generated from static project facts, audit map and candidate signals only.",
            "This output is a security-oriented map and does not prove vulnerabilities.",
            "It is intended to guide Coverage Map and later AI Deep Review.",
        ],
    }


def build_review_focus(assets: list[dict[str, Any]], entrypoints: list[dict[str, Any]], boundaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    focus: list[dict[str, Any]] = []
    for asset in sorted(assets, key=lambda x: x.get("review_priority") != "high"):
        focus.append({
            "focus_id": f"asset:{asset.get('asset_id')}",
            "priority": asset.get("review_priority") or "medium",
            "reason": f"资产 `{asset.get('label_zh')}` 有静态证据或候选命中，需要后续链路审计确认。",
            "evidence_count": asset.get("evidence_count"),
        })
    for entry in entrypoints:
        focus.append({
            "focus_id": f"entrypoint:{entry.get('entrypoint_id')}",
            "priority": "high" if entry.get("entrypoint_id") == "http_api" else "medium",
            "reason": f"入口 `{entry.get('label_zh')}` 需要确认鉴权、输入校验和敏感操作边界。",
            "evidence_count": entry.get("evidence_count"),
        })
    for boundary in boundaries:
        focus.append({
            "focus_id": f"boundary:{boundary.get('boundary_id')}",
            "priority": boundary.get("review_priority") or "medium",
            "reason": f"信任边界 `{boundary.get('label_zh')}` 需要确认控制点是否覆盖。",
            "evidence_from": boundary.get("evidence_from"),
        })
    return focus[:80]


def render_md(model: dict[str, Any]) -> str:
    lines = [
        "# THREAT_MODEL", "",
        f"- Run ID: `{(model.get('run') or {}).get('run_id')}`",
        f"- Project: `{(model.get('project') or {}).get('project_name') or ''}`",
        f"- Rules: `{model.get('rules_ref')}`", "",
        "## Summary", "",
        f"- Stacks: `{', '.join((model.get('summary') or {}).get('detected_stack_ids') or []) or '-'}`",
        f"- Assets: {(model.get('summary') or {}).get('asset_count')}",
        f"- Entrypoints: {(model.get('summary') or {}).get('entrypoint_count')}",
        f"- Trust boundaries: {(model.get('summary') or {}).get('trust_boundary_count')}",
        f"- Candidates: {(model.get('summary') or {}).get('candidate_count')}", "",
        "## Assets", "",
    ]
    if not model.get("assets"):
        lines.append("- None detected")
    for item in model.get("assets") or []:
        evidence = ", ".join(item.get("evidence") or []) or "-"
        lines.append(f"- `{item.get('asset_id')}` {item.get('label_zh')} priority={item.get('review_priority')} evidence_count={item.get('evidence_count')} candidates={item.get('related_candidate_count')} evidence=`{evidence}`")
    lines.extend(["", "## Entrypoints", ""])
    if not model.get("entrypoints"):
        lines.append("- None detected")
    for item in model.get("entrypoints") or []:
        evidence = ", ".join(item.get("evidence") or []) or "-"
        lines.append(f"- `{item.get('entrypoint_id')}` {item.get('label_zh')} evidence_count={item.get('evidence_count')} evidence=`{evidence}`")
    lines.extend(["", "## Trust boundaries", ""])
    if not model.get("trust_boundaries"):
        lines.append("- None detected")
    for item in model.get("trust_boundaries") or []:
        lines.append(f"- `{item.get('boundary_id')}` {item.get('label_zh')} priority={item.get('review_priority')} evidence_from=`{', '.join(item.get('evidence_from') or [])}`")
    lines.extend(["", "## Review focus", ""])
    if not model.get("review_focus"):
        lines.append("- None")
    for item in model.get("review_focus") or []:
        lines.append(f"- `{item.get('priority')}` `{item.get('focus_id')}` {item.get('reason')}")
    lines.extend(["", "## Notes", ""])
    for note in model.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def print_summary(model: dict[str, Any]) -> None:
    s = model.get("summary") or {}
    print("threat-model summary")
    print(f"  assets: {s.get('asset_count')}")
    print(f"  entrypoints: {s.get('entrypoint_count')}")
    print(f"  trust_boundaries: {s.get('trust_boundary_count')}")
    print(f"  candidates: {s.get('candidate_count')}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build static threat model from audit map and project facts.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--rules", default=str(DEFAULT_RULES))
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    rules_path = Path(args.rules)
    if not rules_path.is_absolute():
        rules_path = (ROOT / rules_path).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    if not (run_root / "audit-map" / "AUDIT_MAP.json").is_file():
        print("[FAIL] AUDIT_MAP.json not found. Run audit-map first.", file=sys.stderr)
        return 2
    model = build_threat_model(run_root, rules_path)
    out = run_root / "threat"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "THREAT_MODEL.json", model)
    (out / "THREAT_MODEL.md").write_text(render_md(model), encoding="utf-8")
    if args.print_summary:
        print_summary(model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
