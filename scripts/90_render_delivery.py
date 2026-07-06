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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def report_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for key in ["findings", "review_items", "runtime_items", "blocked_items"]:
        items.extend(result.get(key) or [])
    return items


def loc(item: dict[str, Any]) -> str:
    return f"{item.get('file_path')}:{item.get('line_start')}" if item.get("file_path") else "-"


def taxonomy(item: dict[str, Any]) -> str:
    return f"{item.get('risk_parent') or '-'} / {item.get('risk_subtype') or '-'}"


def tags_text(item: dict[str, Any]) -> str:
    return ",".join(item.get("tags") or [])


def render_report_md(result: dict[str, Any], audit_map: dict[str, Any]) -> str:
    project = result.get("project", {})
    run = result.get("run", {})
    summary = result.get("summary", {})
    stacks = audit_map.get("stacks", {}).get("detected_stack_ids") or []
    lines = [
        f"# {project.get('project_name') or '项目'} 静态代码审计报告", "",
        "## 一、审计基本信息", "",
        "| 项目 | 内容 |", "|---|---|",
        f"| 项目编号 | {project.get('project_code') or ''} |",
        f"| 项目名称 | {project.get('project_name') or ''} |",
        "| 审计方式 | 静态代码分析 + AI 辅助候选判断 |",
        f"| 审计模式 | {run.get('audit_mode') or ''} |",
        "| 是否动态测试 | 否 |",
        "| 是否逆向分析 | 否 |",
        f"| 检测技术栈 | {', '.join(stacks) if stacks else '-'} |", "",
        "## 二、审计限制", "",
        "本次审计仅基于静态代码、审计地图、确定性扫描结果和候选判断结果。",
        "本次未进行动态测试、接口实测、生产探测或移动端逆向验证。",
        "因此报告中的问题状态仅表示静态审计结论或待确认事项，不代表动态可利用性验证。", "",
        "## 三、风险概览", "",
        "| 状态 | 数量 |", "|---|---:|",
        f"| FIND 确认问题 | {summary.get('find_count', 0)} |",
        f"| REVIEW 需人工确认 | {summary.get('review_count', 0)} |",
        f"| RUNTIME 需运行时验证 | {summary.get('runtime_count', 0)} |",
        f"| BLOCKED 审计受阻 | {summary.get('blocked_count', 0)} |", "",
    ]
    sections = [("findings", "四、确认问题 FIND"), ("review_items", "五、需人工确认 REVIEW"), ("runtime_items", "六、需运行时验证 RUNTIME"), ("blocked_items", "七、审计受阻 BLOCKED")]
    for key, title in sections:
        lines.extend([f"## {title}", ""])
        items = result.get(key) or []
        if not items:
            lines.append("本节暂无记录。")
            lines.append("")
            continue
        for item in items:
            lines.extend([
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
            ])
    if result.get("notes"):
        lines.extend(["## 八、过程说明", ""])
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
body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;line-height:1.7;margin:40px;max-width:1100px;color:#1f2937}
h1,h2{color:#1f3a5f} h1{border-bottom:3px solid #d44a3a;padding-bottom:8px} h2{border-left:4px solid #d44a3a;padding-left:10px;margin-top:32px}
table{border-collapse:collapse;width:100%;margin:12px 0} th,td{border:1px solid #e5e7eb;padding:8px;text-align:left} th{background:#1f3a5f;color:white}
code{background:#f3f4f6;padding:1px 4px;border-radius:3px}
</style>
</head>
<body>
""" + "\n".join(body_lines) + "\n</body>\n</html>\n"


def write_tracking_csv(path: Path, result: dict[str, Any]) -> int:
    items = report_items(result)
    headers = ["finding_id", "candidate_id", "audit_status", "business_status", "verification_status", "resolution_reason", "severity", "confidence", "risk_parent", "risk_subtype", "risk_type", "title", "file_path", "line", "evidence", "impact", "remediation_advice", "tags", "owner", "due_date", "business_comment", "audit_comment"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for item in items:
            writer.writerow([item.get("risk_id"), item.get("source_candidate_id"), item.get("status") or item.get("decision"), item.get("business_status") or ("PENDING" if item.get("decision") == "FIND" else ""), item.get("verification_status") or ("PENDING" if item.get("decision") == "FIND" else ""), item.get("resolution_reason") or "", item.get("severity"), item.get("confidence"), item.get("risk_parent"), item.get("risk_subtype"), item.get("risk_type"), item.get("title"), item.get("file_path"), item.get("line_start"), item.get("evidence"), item.get("impact"), item.get("recommendation"), tags_text(item), "", "", "", ""])
    return len(items)


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
    md = render_report_md(result, audit_map)
    (out / "AUDIT_REPORT.md").write_text(md, encoding="utf-8")
    (out / "AUDIT_REPORT.html").write_text(md_to_html(md), encoding="utf-8")
    row_count = write_tracking_csv(out / "AUDIT_TRACKING.csv", result)
    record = {"schema_version": "delivery-record-0.2.0", "run": result.get("run"), "source": "merge/MERGE_RESULT.json", "files": ["AUDIT_REPORT.md", "AUDIT_REPORT.html", "AUDIT_TRACKING.csv"], "tracking_rows": row_count, "lifecycle_spec_ref": "spec/rules/audit-lifecycle.yaml"}
    write_json(out / "DELIVERY_RECORD.json", record)
    if args.print_summary:
        print("delivery summary")
        print(f"  report: {out / 'AUDIT_REPORT.md'}")
        print(f"  html: {out / 'AUDIT_REPORT.html'}")
        print(f"  tracking_rows: {row_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
