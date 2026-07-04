#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

SEVERITY_MAP = {
    "CRITICAL": "P0",
    "HIGH": "P1",
    "ERROR": "P1",
    "MEDIUM": "P2",
    "WARNING": "P2",
    "LOW": "P3",
    "INFO": "P3",
    "INFORMATIONAL": "P3",
}


def load_json_any(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel_to_project(path: str, project_root: Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        return path
    try:
        return str(p.resolve().relative_to(project_root.resolve()))
    except Exception:
        return path


def redact(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key)(\s*[:=]\s*)[^\s,;]+", r"\1\2<REDACTED>", value)
    value = re.sub(r"Bearer\s+[A-Za-z0-9._=-]+", "Bearer <REDACTED>", value, flags=re.I)
    return value[:500]


def sev(value: str | None, default: str = "P2") -> str:
    if not value:
        return default
    return SEVERITY_MAP.get(str(value).upper(), default)


def base_candidate(tool_id: str, profile: str, risk_type: str, title: str, severity_hint: str, evidence: str, file_path: str | None = None, line_start: int | None = None) -> dict[str, Any]:
    return {
        "source": "external_tool",
        "source_tool": tool_id,
        "source_profile": profile,
        "risk_type": risk_type,
        "title": title,
        "severity_hint": severity_hint,
        "confidence_hint": "medium",
        "file_path": file_path,
        "line_start": line_start,
        "line_end": line_start,
        "evidence": redact(evidence),
        "negative_evidence_required": [
            "确认工具输出是否适用于当前项目上下文",
            "确认是否为测试、示例、模板或不可达代码",
            "确认是否存在补偿性控制或安全配置",
        ],
    }


def parse_semgrep(path: Path, tool_id: str, profile: str, project_root: Path) -> list[dict[str, Any]]:
    data = load_json_any(path)
    results = data.get("results") or [] if isinstance(data, dict) else []
    candidates = []
    for item in results:
        extra = item.get("extra") or {}
        start = item.get("start") or {}
        file_path = rel_to_project(item.get("path") or "", project_root)
        check_id = item.get("check_id") or "semgrep"
        message = extra.get("message") or check_id
        severity = extra.get("severity") or "WARNING"
        candidates.append(base_candidate(
            tool_id, profile, "static_analysis_finding", f"Semgrep: {check_id}", sev(severity),
            f"{message}; check_id={check_id}", file_path, start.get("line"),
        ))
    return candidates


def parse_gitleaks(path: Path, tool_id: str, profile: str, project_root: Path) -> list[dict[str, Any]]:
    data = load_json_any(path)
    items = data if isinstance(data, list) else []
    candidates = []
    for item in items:
        rule = item.get("RuleID") or item.get("Rule") or "gitleaks"
        file_path = rel_to_project(item.get("File") or "", project_root)
        line = item.get("StartLine") or item.get("Line")
        candidates.append(base_candidate(
            tool_id, profile, "sensitive_information", f"gitleaks: {rule}", "P1",
            f"Rule={rule}; Description={item.get('Description') or ''}; Secret=<REDACTED>", file_path, line,
        ))
    return candidates


def parse_trivy(path: Path, tool_id: str, profile: str, project_root: Path) -> list[dict[str, Any]]:
    data = load_json_any(path)
    candidates = []
    for result in data.get("Results") or []:
        target = result.get("Target") or ""
        for vuln in result.get("Vulnerabilities") or []:
            vid = vuln.get("VulnerabilityID") or "vulnerability"
            pkg = vuln.get("PkgName") or "package"
            severity = vuln.get("Severity") or "UNKNOWN"
            evidence = f"{pkg} {vuln.get('InstalledVersion') or ''} affected by {vid}; fixed={vuln.get('FixedVersion') or '-'}; target={target}"
            candidates.append(base_candidate(
                tool_id, profile, "dependency_vulnerability", f"{vid} in {pkg}", sev(severity), evidence, target or None, None,
            ))
        for misconf in result.get("Misconfigurations") or []:
            mid = misconf.get("ID") or "misconfiguration"
            title = misconf.get("Title") or mid
            severity = misconf.get("Severity") or "UNKNOWN"
            candidates.append(base_candidate(
                tool_id, profile, "configuration_risk", f"{mid}: {title}", sev(severity), misconf.get("Message") or title, target or None, None,
            ))
    return candidates


def parse_npm_audit(path: Path, tool_id: str, profile: str, project_root: Path) -> list[dict[str, Any]]:
    data = load_json_any(path)
    vulnerabilities = data.get("vulnerabilities") or {}
    candidates = []
    for name, item in vulnerabilities.items():
        severity = item.get("severity") or "medium"
        via = item.get("via") or []
        via_summary = []
        for entry in via[:5] if isinstance(via, list) else []:
            if isinstance(entry, dict):
                via_summary.append(entry.get("title") or entry.get("source") or "advisory")
            else:
                via_summary.append(str(entry))
        evidence = f"package={name}; severity={severity}; via={'; '.join(via_summary)}"
        candidates.append(base_candidate(tool_id, profile, "dependency_vulnerability", f"npm audit: {name}", sev(severity), evidence, "package.json", None))
    return candidates


def parse_retire(path: Path, tool_id: str, profile: str, project_root: Path) -> list[dict[str, Any]]:
    data = load_json_any(path)
    items = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
    candidates = []
    for item in items:
        file_path = rel_to_project(item.get("file") or item.get("fileName") or "", project_root) if isinstance(item, dict) else None
        results = item.get("results") or [] if isinstance(item, dict) else []
        for result in results:
            component = result.get("component") or "component"
            version = result.get("version") or ""
            for vuln in result.get("vulnerabilities") or []:
                severity = vuln.get("severity") or "medium"
                identifiers = vuln.get("identifiers") or {}
                cve = ",".join(identifiers.get("CVE") or []) if isinstance(identifiers, dict) else ""
                evidence = f"component={component}; version={version}; cve={cve}; info={vuln.get('info') or []}"
                candidates.append(base_candidate(tool_id, profile, "dependency_vulnerability", f"retire.js: {component}", sev(severity), evidence, file_path, None))
    return candidates


def parse_jsonl_generic(path: Path, tool_id: str, profile: str, project_root: Path) -> list[dict[str, Any]]:
    candidates = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip().startswith("{"):
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if "osv" in item or "finding" in item or "vulnerability" in item:
            evidence = json.dumps(item, ensure_ascii=False)[:500]
            candidates.append(base_candidate(tool_id, profile, "dependency_vulnerability", f"{tool_id}: vulnerability finding", "P2", evidence, None, None))
    return candidates


def parse_file(path: Path, tool_id: str, profile: str, project_root: Path) -> list[dict[str, Any]]:
    name = path.name.lower()
    try:
        if tool_id == "semgrep" or name.startswith("semgrep"):
            return parse_semgrep(path, tool_id, profile, project_root)
        if tool_id == "gitleaks" or name.startswith("gitleaks"):
            return parse_gitleaks(path, tool_id, profile, project_root)
        if tool_id == "trivy" or name.startswith("trivy"):
            return parse_trivy(path, tool_id, profile, project_root)
        if tool_id in {"npm", "pnpm", "yarn"} or "audit" in name:
            return parse_npm_audit(path, tool_id, profile, project_root)
        if tool_id == "retire" or name.startswith("retire"):
            return parse_retire(path, tool_id, profile, project_root)
        if tool_id == "govulncheck" or name.startswith("govulncheck"):
            return parse_jsonl_generic(path, tool_id, profile, project_root)
        if tool_id in {"dependency-check", "mvn", "gradle"} or "dependency-check" in name:
            return parse_trivy(path, tool_id, profile, project_root)
    except Exception as exc:
        return [base_candidate(tool_id, profile, "tool_output_parse_error", f"Failed to parse {path.name}", "P3", str(exc), None, None)]
    return []


def unique_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = (item.get("source_tool"), item.get("source_profile"), item.get("risk_type"), item.get("title"), item.get("file_path"), item.get("line_start"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    for idx, item in enumerate(result, start=1):
        item["candidate_id"] = f"EXT-CAND-{idx:05d}"
        item["status"] = "candidate"
    return result


def import_candidates(run_root: Path) -> dict[str, Any]:
    project = load_json_any(run_root / "meta" / "PROJECT_PROFILE.json")
    execution = load_json_any(run_root / "evidence" / "tool-execution" / "TOOL_EXECUTION_RESULT.json")
    project_root = Path(project["project_path"]["resolved"])
    items: list[dict[str, Any]] = []
    parsed_files = []

    for item in execution.get("items") or []:
        tool_id = item.get("tool_id") or "unknown"
        profile = item.get("profile") or "unknown"
        for cmd in item.get("commands") or []:
            for output in cmd.get("output_files") or []:
                if not output.get("exists"):
                    continue
                path = Path(output["path"])
                if not path.is_file():
                    continue
                parsed = parse_file(path, tool_id, profile, project_root)
                items.extend(parsed)
                parsed_files.append({"tool_id": tool_id, "profile": profile, "path": str(path), "candidate_count": len(parsed)})

    candidates = unique_candidates(items)
    return {
        "schema_version": "external-tool-candidates-0.1.0",
        "run": execution.get("run"),
        "summary": {
            "candidate_count": len(candidates),
            "parsed_files": len(parsed_files),
            "source_tools": sorted({c.get("source_tool") for c in candidates if c.get("source_tool")}),
        },
        "parsed_files": parsed_files,
        "candidates": candidates,
        "notes": ["External tool candidates are not final findings. They must enter AI triage / merge before delivery."],
    }


def render_md(result: dict[str, Any]) -> str:
    lines = [
        "# EXT_TOOL_CANDIDATES", "",
        f"- Candidate count: {result['summary']['candidate_count']}",
        f"- Parsed files: {result['summary']['parsed_files']}",
        f"- Source tools: {', '.join(result['summary']['source_tools']) or '-'}", "",
        "## Candidates", "",
    ]
    for item in result.get("candidates", [])[:200]:
        loc = item.get("file_path") or "-"
        if item.get("line_start"):
            loc += f":{item.get('line_start')}"
        lines.append(f"- `{item['candidate_id']}` `{item.get('severity_hint')}` `{item.get('source_tool')}/{item.get('source_profile')}` {item.get('title')} — {loc}")
    if not result.get("candidates"):
        lines.append("- None")
    return "\n".join(lines) + "\n"


def print_summary(result: dict[str, Any]) -> None:
    print("external-tool-candidates summary")
    print(f"  candidate_count: {result['summary']['candidate_count']}")
    print(f"  parsed_files: {result['summary']['parsed_files']}")
    print(f"  source_tools: {', '.join(result['summary']['source_tools']) or '-'}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Import external tool outputs into candidate format.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not (run_root / "evidence" / "tool-execution" / "TOOL_EXECUTION_RESULT.json").is_file():
        print("[FAIL] TOOL_EXECUTION_RESULT.json not found. Run ext-tool-run first.", file=sys.stderr)
        return 2

    result = import_candidates(run_root)
    out = run_root / "candidates"
    write_json(out / "EXT_TOOL_CANDIDATES.json", result)
    (out / "EXT_TOOL_CANDIDATES.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
