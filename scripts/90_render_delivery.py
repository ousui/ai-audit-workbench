#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BUSINESS_BUCKETS = ["findings", "review_items", "runtime_items", "blocked_items"]
QUALITY_BUCKETS = ["fp_items", "candidate_items"]
BUCKET_LABELS = {
    "findings": "FIND 确认问题",
    "review_items": "REVIEW 需人工确认",
    "runtime_items": "RUNTIME 需运行时验证",
    "blocked_items": "BLOCKED 审计受阻",
    "fp_items": "FP 审计侧误报/排除项",
    "candidate_items": "CAND 候选池保留项",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict[str, Any]:
    return load_json(path) if path.is_file() else {}


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def bucket_items(result: dict[str, Any], buckets: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in buckets:
        items.extend(result.get(key) or [])
    return items


def business_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    return bucket_items(result, BUSINESS_BUCKETS)


def quality_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    return bucket_items(result, QUALITY_BUCKETS)


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


def count_bucket(result: dict[str, Any], bucket: str) -> int:
    return len(result.get(bucket) or [])


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


def render_item_detail(item: dict[str, Any]) -> list[str]:
    return [
        f"### {item.get('risk_id')} {item.get('title')}", "",
        f"- 审计状态：{item.get('status') or item.get('decision')}",
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


def render_report_md(result: dict[str, Any], audit_map: dict[str, Any], run_root: Path) -> str:
    project = result.get("project", {})
    run = result.get("run", {})
    summary = result.get("summary", {})
    stacks = audit_map.get("stacks", {}).get("detected_stack_ids") or []
    triage_source = detect_triage_source(result, run_root)
    lines = [
        f"# {project.get('project_name') or '项目'} 静态代码审计报告", "",
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
        "## 二、审计限制", "",
        "本次审计仅基于静态代码、审计地图、确定性扫描结果和候选判断结果。",
        "本次未进行动态测试、接口实测、生产探测或移动端逆向验证。",
        "因此报告中的问题状态仅表示静态审计结论或待确认事项，不代表动态可利用性验证。", "",
        "## 三、业务交付概览", "",
        "| 状态 | 数量 | 是否进入业务整改表 |", "|---|---:|---|",
        f"| FIND 确认问题 | {summary.get('find_count', 0)} | 是 |",
        f"| REVIEW 需人工确认 | {summary.get('review_count', 0)} | 是 |",
        f"| RUNTIME 需运行时验证 | {summary.get('runtime_count', 0)} | 是 |",
        f"| BLOCKED 审计受阻 | {summary.get('blocked_count', 0)} | 是 |", "",
        "## 四、审计质量概览", "",
        "| 状态 | 数量 | 说明 |", "|---|---:|---|",
        f"| FP 误报/排除项 | {summary.get('fp_count', 0)} | 不进入业务整改表，进入审计质量统计与知识库候选 |",
        f"| CAND 候选保留项 | {summary.get('candidate_count', 0)} | 不进入业务整改表，作为后续规则/证据优化输入 |",
        f"| Knowledge hits | {summary.get('knowledge_hit_count', 0)} | 只读知识命中，不自动覆盖当前判断 |", "",
    ]
    sections = [
        ("findings", "五、确认问题 FIND"),
        ("review_items", "六、需人工确认 REVIEW"),
        ("runtime_items", "七、需运行时验证 RUNTIME"),
        ("blocked_items", "八、审计受阻 BLOCKED"),
    ]
    for key, title in sections:
        lines.extend([f"## {title}", ""])
        items = result.get(key) or []
        if not items:
            lines.append("本节暂无记录。")
            lines.append("")
            continue
        for item in items:
            lines.extend(render_item_detail(item))
    lines.extend(["# 审计侧质量附录", ""])
    lines.extend(render_quality_table(result, "fp_items"))
    lines.extend(render_quality_table(result, "candidate_items"))
    if result.get("notes"):
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


def write_tracking_csv(path: Path, result: dict[str, Any]) -> int:
    items = business_items(result)
    headers = ["finding_id", "candidate_id", "audit_status", "business_status", "verification_status", "resolution_reason", "severity", "confidence", "risk_parent", "risk_subtype", "risk_type", "title", "file_path", "line", "evidence", "impact", "remediation_advice", "tags", "owner", "due_date", "business_comment", "audit_comment"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for item in items:
            writer.writerow([item.get("risk_id"), item.get("source_candidate_id"), item.get("status") or item.get("decision"), item.get("business_status") or ("PENDING" if item.get("decision") == "FIND" else ""), item.get("verification_status") or ("PENDING" if item.get("decision") == "FIND" else ""), item.get("resolution_reason") or "", item.get("severity"), item.get("confidence"), item.get("risk_parent"), item.get("risk_subtype"), item.get("risk_type"), item.get("title"), item.get("file_path"), item.get("line_start"), item.get("evidence"), item.get("impact"), item.get("recommendation"), tags_text(item), "", "", "", ""])
    return len(items)


def fp_qc_candidate_ids(run_root: Path) -> set[str]:
    quality = load_optional_json(run_root / "ai" / "AI_TRIAGE_QUALITY_RESULT.json")
    out = set()
    for item in quality.get("fp_qc_items") or []:
        cid = item.get("candidate_id")
        if cid:
            out.add(str(cid))
    return out


def write_quality_items_csv(path: Path, result: dict[str, Any], run_root: Path) -> int:
    items = quality_items(result)
    qc_ids = fp_qc_candidate_ids(run_root)
    headers = ["item_id", "candidate_id", "audit_status", "quality_scope", "severity", "confidence", "risk_parent", "risk_subtype", "risk_type", "title", "file_path", "line", "reason", "negative_evidence_checked", "missing_evidence", "tags", "knowledge_hit_count", "qc_required", "audit_comment"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for item in items:
            status = item.get("status") or item.get("decision")
            cid = str(item.get("source_candidate_id") or "")
            scope = "false_positive_or_suppressed" if status == "FP" else "candidate_backlog"
            writer.writerow([item.get("risk_id"), cid, status, scope, item.get("severity"), item.get("confidence"), item.get("risk_parent"), item.get("risk_subtype"), item.get("risk_type"), item.get("title"), item.get("file_path"), item.get("line_start"), item.get("reason"), text_list(item.get("negative_evidence_checked")), text_list(item.get("missing_evidence")), tags_text(item), len(item.get("knowledge_hits") or []), "yes" if cid in qc_ids else "", ""])
    return len(items)


def build_quality_summary(result: dict[str, Any], run_root: Path) -> dict[str, Any]:
    quality_gate = load_optional_json(run_root / "ai" / "AI_TRIAGE_QUALITY_RESULT.json")
    consensus = load_optional_json(run_root / "ai" / "consensus" / "AI_TRIAGE_CONSENSUS.json")
    finalization = load_optional_json(run_root / "ai" / "jury" / "AI_JURY_FINALIZATION_RESULT.json")
    summary = result.get("summary") or {}
    return {
        "schema_version": "audit-quality-summary-0.1.0",
        "triage_source": detect_triage_source(result, run_root),
        "business_delivery": {
            "tracking_policy": "AUDIT_TRACKING.csv contains only FIND/REVIEW/RUNTIME/BLOCKED items that need business-side action or confirmation.",
            "find_count": summary.get("find_count", 0),
            "review_count": summary.get("review_count", 0),
            "runtime_count": summary.get("runtime_count", 0),
            "blocked_count": summary.get("blocked_count", 0),
            "tracking_rows": len(business_items(result)),
        },
        "audit_quality": {
            "fp_count": summary.get("fp_count", 0),
            "candidate_count": summary.get("candidate_count", 0),
            "quality_item_rows": len(quality_items(result)),
            "knowledge_hit_count": summary.get("knowledge_hit_count", 0),
            "fp_qc_required_count": (quality_gate.get("summary") or {}).get("fp_qc_required_count", 0),
        },
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
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    merge_path = run_root / "merge" / "MERGE_RESULT.json"
    map_path = run_root / "audit-map" / "AUDIT_MAP.json"
    if not merge_path.is_file():
        print("[FAIL] MERGE_RESULT.json not found. Run make m8 first.", file=sys.stderr)
        return 2
    result = load_json(merge_path)
    audit_map = load_json(map_path) if map_path.is_file() else {}
    out = run_root / "delivery"
    out.mkdir(parents=True, exist_ok=True)
    md = render_report_md(result, audit_map, run_root)
    (out / "AUDIT_REPORT.md").write_text(md, encoding="utf-8")
    (out / "AUDIT_REPORT.html").write_text(md_to_html(md), encoding="utf-8")
    tracking_rows = write_tracking_csv(out / "AUDIT_TRACKING.csv", result)
    quality_rows = write_quality_items_csv(out / "AUDIT_QUALITY_ITEMS.csv", result, run_root)
    quality_summary = build_quality_summary(result, run_root)
    write_json(out / "AUDIT_QUALITY_SUMMARY.json", quality_summary)
    (out / "AUDIT_QUALITY_SUMMARY.md").write_text(render_quality_summary_md(quality_summary), encoding="utf-8")
    record = {
        "schema_version": "delivery-record-0.3.0",
        "run": result.get("run"),
        "source": "merge/MERGE_RESULT.json",
        "files": ["AUDIT_REPORT.md", "AUDIT_REPORT.html", "AUDIT_TRACKING.csv", "AUDIT_QUALITY_ITEMS.csv", "AUDIT_QUALITY_SUMMARY.json", "AUDIT_QUALITY_SUMMARY.md"],
        "tracking_policy": "business_action_items_only",
        "tracking_rows": tracking_rows,
        "business_tracking_rows": tracking_rows,
        "audit_quality_rows": quality_rows,
        "lifecycle_spec_ref": "spec/rules/audit-lifecycle.yaml",
    }
    write_json(out / "DELIVERY_RECORD.json", record)
    if args.print_summary:
        print("delivery summary")
        print(f"  report: {out / 'AUDIT_REPORT.md'}")
        print(f"  html: {out / 'AUDIT_REPORT.html'}")
        print(f"  business_tracking_rows: {tracking_rows}")
        print(f"  audit_quality_rows: {quality_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
