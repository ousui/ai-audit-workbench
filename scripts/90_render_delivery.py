#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import csv
import html
import json
import sys
from pathlib import Path
from typing import Any, Callable

import yaml  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "spec" / "delivery" / "delivery-profile.default.yaml"
BUSINESS_BUCKETS = ["findings", "review_items", "runtime_items", "blocked_items"]
QUALITY_BUCKETS = ["fp_items", "candidate_items"]
ALL_BUCKETS = ["findings", "review_items", "runtime_items", "blocked_items", "fp_items", "candidate_items"]
BUCKET_LABELS = {
    "findings": "FIND 确认问题",
    "review_items": "REVIEW 需人工确认",
    "runtime_items": "RUNTIME 需运行时验证",
    "blocked_items": "BLOCKED 审计受阻",
    "fp_items": "FP 审计侧误报/排除项",
    "candidate_items": "CAND 候选池保留项",
}
STATUS_TO_BUCKET = {
    "FIND": "findings",
    "REVIEW": "review_items",
    "RUNTIME": "runtime_items",
    "BLOCKED": "blocked_items",
    "FP": "fp_items",
    "CAND": "candidate_items",
}
BUSINESS_STATUSES = {"FIND", "REVIEW", "RUNTIME", "BLOCKED"}
QUALITY_STATUSES = {"FP", "CAND"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict[str, Any]:
    return load_json(path) if path.is_file() else {}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_path(value: str) -> Path:
    raw = Path(value)
    return raw if raw.is_absolute() else ROOT / raw


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def load_profile(profile_path: Path) -> dict[str, Any]:
    if not profile_path.is_file():
        raise SystemExit(f"[FAIL] delivery profile not found: {profile_path}")
    profile = load_yaml(profile_path)
    if profile.get("schema_version") != "delivery-profile-0.1.0":
        raise SystemExit(f"[FAIL] delivery profile schema_version mismatch: {profile.get('schema_version')}")
    return profile


def item_status(item: dict[str, Any]) -> str:
    return str(item.get("status") or item.get("decision") or "")


def bucket_items(result: dict[str, Any], buckets: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in buckets:
        items.extend(result.get(key) or [])
    return items


def all_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    return bucket_items(result, ALL_BUCKETS)


def items_for_statuses(result: dict[str, Any], statuses: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for status in statuses:
        bucket = STATUS_TO_BUCKET.get(status)
        if bucket:
            out.extend(result.get(bucket) or [])
    return out


def business_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    return items_for_statuses(result, ["FIND", "REVIEW", "RUNTIME", "BLOCKED"])


def quality_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    return items_for_statuses(result, ["FP", "CAND"])


def loc(item: dict[str, Any]) -> str:
    return f"{item.get('file_path')}:{item.get('line_start')}" if item.get("file_path") else "-"


def taxonomy(item: dict[str, Any]) -> str:
    return f"{item.get('risk_parent') or '-'} / {item.get('risk_subtype') or '-'}"


def tags_text(item: dict[str, Any]) -> str:
    return ",".join(item.get("tags") or [])


def text_list(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(x) for x in value)
    if value is None:
        return ""
    return str(value)


def quality_scope(item: dict[str, Any]) -> str:
    status = item_status(item)
    return "false_positive_or_suppressed" if status == "FP" else "candidate_backlog"


def delivery_scope(item: dict[str, Any]) -> str:
    status = item_status(item)
    return "business_action" if status in BUSINESS_STATUSES else "audit_quality"


def fp_qc_candidate_ids(run_root: Path) -> set[str]:
    quality = load_optional_json(run_root / "ai" / "AI_TRIAGE_QUALITY_RESULT.json")
    out = set()
    for item in quality.get("fp_qc_items") or []:
        cid = item.get("candidate_id")
        if cid:
            out.add(str(cid))
    return out


def field_value(item: dict[str, Any], field: str, qc_ids: set[str]) -> Any:
    status = item_status(item)
    candidate_id = str(item.get("source_candidate_id") or "")
    mapping: dict[str, Callable[[], Any]] = {
        "finding_id": lambda: item.get("risk_id"),
        "item_id": lambda: item.get("risk_id"),
        "candidate_id": lambda: item.get("source_candidate_id"),
        "audit_status": lambda: status,
        "delivery_scope": lambda: delivery_scope(item),
        "quality_scope": lambda: quality_scope(item),
        "business_status": lambda: item.get("business_status") or ("PENDING" if status == "FIND" else ""),
        "verification_status": lambda: item.get("verification_status") or ("PENDING" if status == "FIND" else ""),
        "resolution_reason": lambda: item.get("resolution_reason") or "",
        "severity": lambda: item.get("severity"),
        "confidence": lambda: item.get("confidence"),
        "risk_parent": lambda: item.get("risk_parent"),
        "risk_subtype": lambda: item.get("risk_subtype"),
        "risk_type": lambda: item.get("risk_type"),
        "title": lambda: item.get("title"),
        "file_path": lambda: item.get("file_path"),
        "line": lambda: item.get("line_start"),
        "evidence": lambda: item.get("evidence"),
        "risk_chain": lambda: item.get("risk_chain"),
        "impact": lambda: item.get("impact"),
        "remediation_advice": lambda: item.get("recommendation"),
        "reason": lambda: item.get("reason"),
        "negative_evidence_checked": lambda: text_list(item.get("negative_evidence_checked")),
        "missing_evidence": lambda: text_list(item.get("missing_evidence")),
        "questions_for_human": lambda: text_list(item.get("questions_for_human")),
        "tags": lambda: tags_text(item),
        "owner": lambda: "",
        "due_date": lambda: "",
        "business_comment": lambda: "",
        "audit_comment": lambda: "",
        "knowledge_hit_count": lambda: len(item.get("knowledge_hits") or []),
        "qc_required": lambda: "yes" if candidate_id in qc_ids else "",
        "source_hit_id": lambda: item.get("source_hit_id"),
        "fingerprint": lambda: item.get("fingerprint"),
    }
    if field not in mapping:
        return ""
    return mapping[field]()


def write_profile_table_csv(path: Path, items: list[dict[str, Any]], fields: list[str], qc_ids: set[str]) -> int:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for item in items:
            writer.writerow([field_value(item, field, qc_ids) for field in fields])
    return len(items)


def stats_scope_items(result: dict[str, Any], scope: str) -> list[dict[str, Any]]:
    if scope == "business":
        return business_items(result)
    if scope == "audit_quality":
        return quality_items(result)
    return all_items(result)


def status_sort_key(status: str) -> int:
    order = {"FIND": 0, "REVIEW": 1, "RUNTIME": 2, "BLOCKED": 3, "FP": 4, "CAND": 5, "": 99}
    return order.get(status, 90)


def severity_sort_key(severity: str) -> int:
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "": 99}
    return order.get(severity, 90)


def count_by(items: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], tuple[str, ...]]) -> dict[tuple[str, ...], int]:
    counter: collections.Counter[tuple[str, ...]] = collections.Counter()
    for item in items:
        counter[key_fn(item)] += 1
    return dict(counter)


def build_stats(result: dict[str, Any], profile: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    stats_cfg = profile.get("stats") or {}
    scopes = stats_cfg.get("scopes") or ["all", "business", "audit_quality"]
    stats: dict[str, list[dict[str, Any]]] = {"by_status": [], "by_severity": [], "by_category": [], "by_category_severity": []}
    for scope in scopes:
        items = stats_scope_items(result, str(scope))
        for (status,), count in sorted(count_by(items, lambda x: (item_status(x),)).items(), key=lambda x: status_sort_key(x[0][0])):
            stats["by_status"].append({"scope": scope, "audit_status": status or "-", "count": count})
        for (severity,), count in sorted(count_by(items, lambda x: (str(x.get("severity") or "-"),)).items(), key=lambda x: severity_sort_key(x[0][0])):
            stats["by_severity"].append({"scope": scope, "severity": severity, "count": count})
        for (category,), count in sorted(count_by(items, lambda x: (str(x.get("risk_parent") or "-"),)).items(), key=lambda x: (x[0][0])):
            stats["by_category"].append({"scope": scope, "risk_parent": category, "count": count})
        for (category, severity), count in sorted(count_by(items, lambda x: (str(x.get("risk_parent") or "-"), str(x.get("severity") or "-"))).items(), key=lambda x: (x[0][0], severity_sort_key(x[0][1]))):
            stats["by_category_severity"].append({"scope": scope, "risk_parent": category, "severity": severity, "count": count})
    return stats


def write_stats_csv(path: Path, rows: list[dict[str, Any]]) -> int:
    headers = sorted({key for row in rows for key in row.keys()})
    preferred = ["scope", "audit_status", "severity", "risk_parent", "count"]
    headers = [h for h in preferred if h in headers] + [h for h in headers if h not in preferred]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def detect_triage_source(result: dict[str, Any], run_root: Path) -> dict[str, Any]:
    triage_mode = result.get("triage_mode") or ""
    finalization_path = run_root / "ai" / "jury" / "AI_JURY_FINALIZATION_RESULT.json"
    consensus_path = run_root / "ai" / "consensus" / "AI_TRIAGE_CONSENSUS.json"
    if finalization_path.is_file():
        finalization = load_optional_json(finalization_path)
        return {
            "source_type": "AI_JURY",
            "triage_mode": triage_mode,
            "profile": finalization.get("profile"),
            "finalization_status": finalization.get("status"),
            "decision_distribution": (finalization.get("summary") or {}).get("decision_distribution"),
            "adjudication_items": (finalization.get("summary") or {}).get("adjudication_items"),
        }
    if consensus_path.is_file():
        consensus = load_optional_json(consensus_path)
        return {"source_type": "AI_JURY_INCOMPLETE", "triage_mode": triage_mode, "consensus_status": consensus.get("status")}
    if triage_mode == "STUB":
        return {"source_type": "STUB", "triage_mode": triage_mode}
    return {"source_type": "FILE_BASED_AI", "triage_mode": triage_mode}


def section_enabled(profile: dict[str, Any], section: str) -> bool:
    sections = ((profile.get("report") or {}).get("sections") or [])
    return section in sections


def render_item_detail(item: dict[str, Any]) -> list[str]:
    return [
        f"### {item.get('risk_id')} {item.get('title')}", "",
        f"- 审计状态：{item_status(item)}",
        f"- 等级：{item.get('severity')}",
        f"- 置信度：{item.get('confidence')}",
        f"- 风险分类：{taxonomy(item)}",
        f"- 业务反馈状态：{item.get('business_status') or ''}",
        f"- 审计复核状态：{item.get('verification_status') or ''}",
        f"- 位置：{loc(item)}",
        f"- 标签：{tags_text(item)}",
        f"- 证据：{item.get('evidence') or ''}",
        f"- 风险链路：{item.get('risk_chain') or ''}",
        f"- 影响：{item.get('impact') or ''}",
        f"- 修复建议：{item.get('recommendation') or ''}",
        f"- 判断依据：{item.get('reason') or ''}", "",
    ]


def render_stats_table(title: str, rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    lines = [f"## {title}", ""]
    if not rows:
        lines.extend(["本节暂无统计。", ""])
        return lines
    zh = {"scope": "口径", "audit_status": "状态", "severity": "等级", "risk_parent": "风险大类", "count": "数量"}
    lines.append("| " + " | ".join(zh.get(col, col) for col in columns) + " |")
    lines.append("|" + "|".join("---" if col != "count" else "---:" for col in columns) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    lines.append("")
    return lines


def render_quality_table(result: dict[str, Any], bucket: str, limit: int = 80) -> list[str]:
    items = result.get(bucket) or []
    lines = [f"## {BUCKET_LABELS[bucket]}", ""]
    if not items:
        lines.extend(["本节暂无记录。", ""])
        return lines
    lines.extend(["| ID | 等级 | 风险分类 | 位置 | 标题 | 判断依据 |", "|---|---|---|---|---|---|"])
    for item in items[:limit]:
        reason = str(item.get("reason") or "").replace("\n", " ")[:180]
        lines.append(f"| `{item.get('risk_id')}` | `{item.get('severity')}` | `{taxonomy(item)}` | `{loc(item)}` | {item.get('title') or ''} | {reason} |")
    if len(items) > limit:
        lines.append(f"| ... | ... | ... | ... | 仅展示前 {limit} 条 | 剩余 {len(items) - limit} 条见 AUDIT_QUALITY_ITEMS.csv |")
    lines.append("")
    return lines


def render_report_md(result: dict[str, Any], audit_map: dict[str, Any], run_root: Path, profile: dict[str, Any], stats: dict[str, list[dict[str, Any]]]) -> str:
    project = result.get("project", {})
    run = result.get("run", {})
    summary = result.get("summary", {})
    stacks = audit_map.get("stacks", {}).get("detected_stack_ids") or []
    triage_source = detect_triage_source(result, run_root)
    title = (profile.get("report") or {}).get("title") or "静态代码审计报告"
    lines = [f"# {project.get('project_name') or '项目'} {title}", ""]
    if section_enabled(profile, "executive_summary"):
        lines.extend([
            "## 执行摘要", "",
            f"本轮业务侧需处理/确认项共 {len(business_items(result))} 条，其中 FIND={summary.get('find_count', 0)}，REVIEW={summary.get('review_count', 0)}，RUNTIME={summary.get('runtime_count', 0)}，BLOCKED={summary.get('blocked_count', 0)}。",
            f"审计侧质量项共 {len(quality_items(result))} 条，其中 FP={summary.get('fp_count', 0)}，CAND={summary.get('candidate_count', 0)}。", "",
        ])
    if section_enabled(profile, "audit_scope"):
        lines.extend([
            "## 一、审计基本信息", "",
            "| 项目 | 内容 |", "|---|---|",
            f"| 项目编号 | {project.get('project_code') or ''} |",
            f"| 项目名称 | {project.get('project_name') or ''} |",
            "| 审计方式 | 静态代码分析 + AI 辅助候选判断 |",
            f"| 审计模式 | {run.get('audit_mode') or ''} |",
            f"| AI 判断来源 | {triage_source.get('source_type')} / {triage_source.get('triage_mode') or '-'} |",
            f"| AI Jury Profile | {triage_source.get('profile') or '-'} |",
            "| 是否动态测试 | 否 |",
            "| 是否逆向分析 | 否 |",
            f"| 检测技术栈 | {', '.join(stacks) if stacks else '-'} |", "",
        ])
    if section_enabled(profile, "business_delivery_overview"):
        lines.extend([
            "## 二、业务交付概览", "",
            "| 状态 | 数量 | 是否进入业务整改表 |", "|---|---:|---|",
            f"| FIND 确认问题 | {summary.get('find_count', 0)} | 是 |",
            f"| REVIEW 需人工确认 | {summary.get('review_count', 0)} | 是 |",
            f"| RUNTIME 需运行时验证 | {summary.get('runtime_count', 0)} | 是 |",
            f"| BLOCKED 审计受阻 | {summary.get('blocked_count', 0)} | 是 |", "",
        ])
    if section_enabled(profile, "audit_quality_overview") or section_enabled(profile, "business_delivery_overview"):
        lines.extend([
            "## 三、审计质量概览", "",
            "| 状态 | 数量 | 说明 |", "|---|---:|---|",
            f"| FP 误报/排除项 | {summary.get('fp_count', 0)} | 不进入业务整改表，进入审计质量统计与知识库候选 |",
            f"| CAND 候选保留项 | {summary.get('candidate_count', 0)} | 不进入业务整改表，作为后续规则/证据优化输入 |",
            f"| Knowledge hits | {summary.get('knowledge_hit_count', 0)} | 只读知识命中，不自动覆盖当前判断 |", "",
        ])
    if section_enabled(profile, "stats_by_status"):
        lines.extend(render_stats_table("状态维度统计", stats.get("by_status", []), ["scope", "audit_status", "count"]))
    if section_enabled(profile, "stats_by_severity"):
        lines.extend(render_stats_table("风险级别维度统计", stats.get("by_severity", []), ["scope", "severity", "count"]))
    if section_enabled(profile, "stats_by_category"):
        lines.extend(render_stats_table("风险大类维度统计", stats.get("by_category", []), ["scope", "risk_parent", "count"]))
    if section_enabled(profile, "stats_by_category_severity"):
        lines.extend(render_stats_table("风险大类 + 级别交叉统计", stats.get("by_category_severity", []), ["scope", "risk_parent", "severity", "count"]))
    sections = [("findings", "findings"), ("review_items", "review_items"), ("runtime_items", "runtime_items"), ("blocked_items", "blocked_items")]
    for section_name, key in sections:
        if not section_enabled(profile, section_name):
            continue
        lines.extend([f"## {BUCKET_LABELS[key]}", ""])
        items = result.get(key) or []
        if not items:
            lines.append("本节暂无记录。")
            lines.append("")
            continue
        for item in items:
            lines.extend(render_item_detail(item))
    if section_enabled(profile, "audit_quality_appendix"):
        lines.extend(["# 审计侧质量附录", ""])
        lines.extend(render_quality_table(result, "fp_items"))
        lines.extend(render_quality_table(result, "candidate_items"))
    if section_enabled(profile, "limitations"):
        lines.extend([
            "## 审计限制", "",
            "本次审计仅基于静态代码、审计地图、确定性扫描结果和候选判断结果。",
            "本次未进行动态测试、接口实测、生产探测或移动端逆向验证。",
            "因此报告中的问题状态仅表示静态审计结论或待确认事项，不代表动态可利用性验证。", "",
        ])
    if result.get("notes") and section_enabled(profile, "process_notes"):
        lines.extend(["## 过程说明", ""])
        for note in result["notes"]:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines)


def md_to_html(md: str) -> str:
    body_lines = []
    in_table = False
    for line in md.splitlines():
        if line.startswith("# "):
            body_lines.append(f"<h1>{html.escape(line[2:].strip())}</h1>")
        elif line.startswith("## "):
            body_lines.append(f"<h2>{html.escape(line[3:].strip())}</h2>")
        elif line.startswith("### "):
            body_lines.append(f"<h3>{html.escape(line[4:].strip())}</h3>")
        elif line.startswith("|---"):
            continue
        elif line.startswith("|") and line.endswith("|"):
            cells = [html.escape(cell.strip()) for cell in line.strip("|").split("|")]
            tag = "th" if not in_table else "td"
            if not in_table:
                body_lines.append("<table>")
                in_table = True
            body_lines.append("<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in cells) + "</tr>")
        else:
            if in_table:
                body_lines.append("</table>")
                in_table = False
            if line.startswith("- "):
                body_lines.append(f"<p>• {html.escape(line[2:].strip())}</p>")
            elif line.strip():
                body_lines.append(f"<p>{html.escape(line.strip())}</p>")
    if in_table:
        body_lines.append("</table>")
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Audit Report</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.7;margin:40px;max-width:1200px;color:#1f2937}
h1,h2{color:#1f3a5f} h1{border-bottom:3px solid #d44a3a;padding-bottom:8px} h2{border-left:4px solid #d44a3a;padding-left:10px;margin-top:32px}
table{border-collapse:collapse;width:100%;margin:12px 0} th,td{border:1px solid #e5e7eb;padding:8px;text-align:left;vertical-align:top} th{background:#1f3a5f;color:white}
code{background:#f3f4f6;padding:1px 4px;border-radius:3px}
</style>
</head>
<body>
""" + "\n".join(body_lines) + "\n</body>\n</html>\n"


def render_profile_tables(result: dict[str, Any], out: Path, profile: dict[str, Any], run_root: Path) -> dict[str, int]:
    qc_ids = fp_qc_candidate_ids(run_root)
    tables = profile.get("tables") or {}
    counts: dict[str, int] = {}
    for table_name, table in tables.items():
        if not isinstance(table, dict) or table.get("enabled") is False:
            continue
        output = table.get("output")
        fields = table.get("fields") or []
        statuses = table.get("include_status") or []
        if not output or not fields or not statuses:
            continue
        items = items_for_statuses(result, [str(x) for x in statuses])
        counts[table_name] = write_profile_table_csv(out / str(output), items, [str(x) for x in fields], qc_ids)
    return counts


def render_stats_outputs(out: Path, stats: dict[str, list[dict[str, Any]]], profile: dict[str, Any]) -> dict[str, int]:
    stats_cfg = profile.get("stats") or {}
    if stats_cfg.get("enabled") is False:
        return {}
    outputs = stats_cfg.get("outputs") or {}
    counts: dict[str, int] = {}
    for stat_name, filename in outputs.items():
        if stat_name in stats and filename:
            counts[str(stat_name)] = write_stats_csv(out / str(filename), stats[stat_name])
    return counts


def build_quality_summary(result: dict[str, Any], run_root: Path, profile: dict[str, Any], stats_counts: dict[str, int], table_counts: dict[str, int]) -> dict[str, Any]:
    quality_gate = load_optional_json(run_root / "ai" / "AI_TRIAGE_QUALITY_RESULT.json")
    consensus = load_optional_json(run_root / "ai" / "consensus" / "AI_TRIAGE_CONSENSUS.json")
    finalization = load_optional_json(run_root / "ai" / "jury" / "AI_JURY_FINALIZATION_RESULT.json")
    summary = result.get("summary") or {}
    return {
        "schema_version": "audit-quality-summary-0.2.0",
        "delivery_profile_ref": profile.get("_profile_ref"),
        "triage_source": detect_triage_source(result, run_root),
        "business_delivery": {
            "tracking_policy": "AUDIT_TRACKING.csv contains only FIND/REVIEW/RUNTIME/BLOCKED items that need business-side action or confirmation.",
            "find_count": summary.get("find_count", 0),
            "review_count": summary.get("review_count", 0),
            "runtime_count": summary.get("runtime_count", 0),
            "blocked_count": summary.get("blocked_count", 0),
            "tracking_rows": table_counts.get("business_tracking", 0),
        },
        "audit_quality": {
            "fp_count": summary.get("fp_count", 0),
            "candidate_count": summary.get("candidate_count", 0),
            "quality_item_rows": table_counts.get("audit_quality_items", 0),
            "all_item_rows": table_counts.get("all_items", 0),
            "knowledge_hit_count": summary.get("knowledge_hit_count", 0),
            "fp_qc_required_count": (quality_gate.get("summary") or {}).get("fp_qc_required_count", 0),
        },
        "stats": stats_counts,
        "ai_quality_gate": {
            "status": quality_gate.get("status"),
            "decision_distribution": (quality_gate.get("summary") or {}).get("decision_distribution"),
            "reportable_count": (quality_gate.get("summary") or {}).get("reportable_count"),
            "warning_count": (quality_gate.get("summary") or {}).get("warning_count"),
            "error_count": (quality_gate.get("summary") or {}).get("error_count"),
        },
        "ai_jury": {
            "consensus_status": consensus.get("status"),
            "adjudication_required": (consensus.get("summary") or {}).get("adjudication_required"),
            "strong_disagreements": (consensus.get("summary") or {}).get("strong_disagreements"),
            "finalization_status": finalization.get("status"),
            "final_decision_distribution": (finalization.get("summary") or {}).get("decision_distribution"),
        },
        "notes": [
            "FP and CAND items are excluded from business remediation tracking by default.",
            "FP/CAND items are retained in AUDIT_QUALITY_ITEMS.csv for audit-side quality control, sampling, and knowledge-base suggestions.",
        ],
    }


def render_quality_summary_md(summary: dict[str, Any]) -> str:
    bd = summary.get("business_delivery") or {}
    aq = summary.get("audit_quality") or {}
    gate = summary.get("ai_quality_gate") or {}
    jury = summary.get("ai_jury") or {}
    lines = [
        "# AUDIT_QUALITY_SUMMARY", "",
        f"- Delivery profile: `{summary.get('delivery_profile_ref')}`", "",
        "## Business delivery", "",
        f"- Tracking policy: {bd.get('tracking_policy')}",
        f"- FIND: {bd.get('find_count')}",
        f"- REVIEW: {bd.get('review_count')}",
        f"- RUNTIME: {bd.get('runtime_count')}",
        f"- BLOCKED: {bd.get('blocked_count')}",
        f"- AUDIT_TRACKING rows: {bd.get('tracking_rows')}", "",
        "## Audit quality", "",
        f"- FP: {aq.get('fp_count')}",
        f"- CAND: {aq.get('candidate_count')}",
        f"- AUDIT_QUALITY_ITEMS rows: {aq.get('quality_item_rows')}",
        f"- AUDIT_ALL_ITEMS rows: {aq.get('all_item_rows')}",
        f"- Knowledge hits: {aq.get('knowledge_hit_count')}",
        f"- FP QC required: {aq.get('fp_qc_required_count')}", "",
        "## AI quality gate", "",
        f"- Status: `{gate.get('status')}`",
        f"- Decision distribution: `{gate.get('decision_distribution')}`",
        f"- Reportable count: {gate.get('reportable_count')}", "",
        "## AI Jury", "",
        f"- Consensus status: `{jury.get('consensus_status')}`",
        f"- Adjudication required: {jury.get('adjudication_required')}",
        f"- Strong disagreements: {jury.get('strong_disagreements')}",
        f"- Finalization status: `{jury.get('finalization_status')}`",
        f"- Final decision distribution: `{jury.get('final_decision_distribution')}`", "",
    ]
    if summary.get("notes"):
        lines.extend(["## Notes", ""])
        for note in summary["notes"]:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Render local delivery from merge result.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--delivery-profile", default=str(DEFAULT_PROFILE))
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    profile_path = resolve_path(args.delivery_profile)
    profile = load_profile(profile_path)
    profile["_profile_ref"] = rel(profile_path)
    merge_path = run_root / "merge" / "MERGE_RESULT.json"
    map_path = run_root / "audit-map" / "AUDIT_MAP.json"
    if not merge_path.is_file():
        print("[FAIL] MERGE_RESULT.json not found. Run make m8 first.", file=sys.stderr)
        return 2
    result = load_json(merge_path)
    audit_map = load_json(map_path) if map_path.is_file() else {}
    out = run_root / "delivery"
    out.mkdir(parents=True, exist_ok=True)
    stats = build_stats(result, profile)
    table_counts = render_profile_tables(result, out, profile, run_root)
    stats_counts = render_stats_outputs(out, stats, profile)
    md = render_report_md(result, audit_map, run_root, profile, stats)
    (out / "AUDIT_REPORT.md").write_text(md, encoding="utf-8")
    (out / "AUDIT_REPORT.html").write_text(md_to_html(md), encoding="utf-8")
    quality_summary = build_quality_summary(result, run_root, profile, stats_counts, table_counts)
    write_json(out / "AUDIT_QUALITY_SUMMARY.json", quality_summary)
    (out / "AUDIT_QUALITY_SUMMARY.md").write_text(render_quality_summary_md(quality_summary), encoding="utf-8")
    write_json(out / "DELIVERY_PROFILE_RESOLVED.json", profile)
    record = {
        "schema_version": "delivery-record-0.4.0",
        "run": result.get("run"),
        "source": "merge/MERGE_RESULT.json",
        "delivery_profile_ref": rel(profile_path),
        "files": [
            "AUDIT_REPORT.md", "AUDIT_REPORT.html", "AUDIT_TRACKING.csv", "AUDIT_QUALITY_ITEMS.csv",
            "AUDIT_QUALITY_SUMMARY.json", "AUDIT_QUALITY_SUMMARY.md", "DELIVERY_PROFILE_RESOLVED.json",
            *[str(v) for v in ((profile.get("stats") or {}).get("outputs") or {}).values()],
        ],
        "tracking_policy": "business_action_items_only",
        "tracking_rows": table_counts.get("business_tracking", 0),
        "business_tracking_rows": table_counts.get("business_tracking", 0),
        "audit_quality_rows": table_counts.get("audit_quality_items", 0),
        "all_item_rows": table_counts.get("all_items", 0),
        "stats_rows": stats_counts,
        "lifecycle_spec_ref": "spec/rules/audit-lifecycle.yaml",
    }
    write_json(out / "DELIVERY_RECORD.json", record)
    if args.print_summary:
        print("delivery summary")
        print(f"  profile: {rel(profile_path)}")
        print(f"  report: {out / 'AUDIT_REPORT.md'}")
        print(f"  html: {out / 'AUDIT_REPORT.html'}")
        print(f"  business_tracking_rows: {table_counts.get('business_tracking', 0)}")
        print(f"  audit_quality_rows: {table_counts.get('audit_quality_items', 0)}")
        print(f"  all_item_rows: {table_counts.get('all_items', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
