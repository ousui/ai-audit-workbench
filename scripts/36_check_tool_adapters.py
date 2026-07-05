#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "local" / "registry" / "hosts" / "current" / "TOOL_ADAPTER_STATUS.json"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize(text: str, max_len: int = 3000) -> str:
    value = (text or "").strip()
    if len(value) > max_len:
        return value[:max_len] + "..."
    return value


def run_command(command: str, timeout: int = 12) -> dict[str, Any]:
    started = dt.datetime.now()
    try:
        proc = subprocess.run(command, shell=True, text=True, capture_output=True, timeout=timeout)
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "exit_code": proc.returncode,
            "status": "success" if proc.returncode == 0 else "failed",
            "stdout": summarize(proc.stdout),
            "stderr": summarize(proc.stderr),
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "exit_code": None,
            "status": "timeout",
            "stdout": summarize(exc.stdout if isinstance(exc.stdout, str) else ""),
            "stderr": summarize(exc.stderr if isinstance(exc.stderr, str) else ""),
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "exit_code": None,
            "status": "failed",
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": duration_ms,
        }


def combined_text(record: dict[str, Any]) -> str:
    return "\n".join([record.get("stdout") or "", record.get("stderr") or ""])


def missing(tool_id: str) -> dict[str, Any]:
    return {
        "tool_id": tool_id,
        "status": "missing",
        "compatible": False,
        "reason": "tool is not available on PATH",
        "command_variant": None,
        "checks": [],
    }


def check_golangci_lint() -> dict[str, Any]:
    tool_id = "golangci-lint"
    if not shutil.which(tool_id):
        return missing(tool_id)
    help_record = run_command("golangci-lint run --help")
    text = combined_text(help_record)
    if "--output.json.path" in text:
        status = "compatible"
        variant = "output-json-path"
        reason = "supports --output.json.path"
    elif "--out-format" in text:
        status = "compatible"
        variant = "out-format"
        reason = "supports --out-format"
    else:
        status = "incompatible"
        variant = None
        reason = "neither --output.json.path nor --out-format found in help output"
    return {
        "tool_id": tool_id,
        "status": status,
        "compatible": status == "compatible",
        "reason": reason,
        "command_variant": variant,
        "checks": [help_record],
    }


def check_govulncheck() -> dict[str, Any]:
    tool_id = "govulncheck"
    if not shutil.which(tool_id):
        return missing(tool_id)
    help_record = run_command("govulncheck -h")
    text = combined_text(help_record)
    compatible = "-json" in text or "json" in text.lower()
    return {
        "tool_id": tool_id,
        "status": "compatible" if compatible else "incompatible",
        "compatible": compatible,
        "reason": "supports -json" if compatible else "-json option not found in help output",
        "command_variant": "json" if compatible else None,
        "checks": [help_record],
    }


def check_gitleaks() -> dict[str, Any]:
    tool_id = "gitleaks"
    if not shutil.which(tool_id):
        return missing(tool_id)
    help_record = run_command("gitleaks detect --help")
    text = combined_text(help_record)
    compatible = "--report-format" in text and "--report-path" in text
    return {
        "tool_id": tool_id,
        "status": "compatible" if compatible else "incompatible",
        "compatible": compatible,
        "reason": "supports report-format/report-path" if compatible else "report-format or report-path option not found",
        "command_variant": "report-json-path" if compatible else None,
        "checks": [help_record],
    }


def check_semgrep() -> dict[str, Any]:
    tool_id = "semgrep"
    if not shutil.which(tool_id):
        return missing(tool_id)
    help_record = run_command("semgrep --help")
    text = combined_text(help_record)
    compatible = "--json" in text or "json" in text.lower()
    return {
        "tool_id": tool_id,
        "status": "compatible" if compatible else "incompatible",
        "compatible": compatible,
        "reason": "json output appears supported" if compatible else "json output support not found in help output",
        "command_variant": "json-output" if compatible else None,
        "checks": [help_record],
    }


def check_trivy() -> dict[str, Any]:
    tool_id = "trivy"
    if not shutil.which(tool_id):
        return missing(tool_id)
    help_record = run_command("trivy fs --help")
    text = combined_text(help_record)
    compatible = "--format" in text and ("--output" in text or re.search(r"\s-o,\s*--output", text))
    return {
        "tool_id": tool_id,
        "status": "compatible" if compatible else "incompatible",
        "compatible": compatible,
        "reason": "supports fs --format and output" if compatible else "format/output options not found for trivy fs",
        "command_variant": "fs-json-output" if compatible else None,
        "checks": [help_record],
    }


def check_dependency_check() -> dict[str, Any]:
    tool_id = "dependency-check"
    if not shutil.which(tool_id):
        return missing(tool_id)
    help_record = run_command("dependency-check --help", timeout=20)
    text = combined_text(help_record)
    compatible = "--format" in text and "--out" in text
    return {
        "tool_id": tool_id,
        "status": "compatible" if compatible else "incompatible",
        "compatible": compatible,
        "reason": "supports --format and --out" if compatible else "--format or --out option not found",
        "command_variant": "format-out" if compatible else None,
        "checks": [help_record],
    }


def build_result() -> dict[str, Any]:
    checks = [
        check_golangci_lint(),
        check_govulncheck(),
        check_gitleaks(),
        check_semgrep(),
        check_trivy(),
        check_dependency_check(),
    ]
    by_id = {item["tool_id"]: item for item in checks}
    incompatible = [x for x in checks if x.get("status") == "incompatible"]
    missing_items = [x for x in checks if x.get("status") == "missing"]
    return {
        "schema_version": "tool-adapter-status-0.1.0",
        "generated_at": now(),
        "summary": {
            "status": "incompatible" if incompatible else "completed",
            "checked_tools": len(checks),
            "compatible_tools": sum(1 for x in checks if x.get("status") == "compatible"),
            "incompatible_tools": len(incompatible),
            "missing_tools": len(missing_items),
        },
        "tools": by_id,
        "notes": [
            "Adapter checks inspect local tool CLI help output and choose command variants for execution planning.",
            "Missing optional tools are not failures; incompatible installed tools should block the affected command template.",
        ],
    }


def render_md(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        "# TOOL_ADAPTER_STATUS", "",
        f"- Status: `{s['status']}`",
        f"- Checked tools: {s['checked_tools']}",
        f"- Compatible tools: {s['compatible_tools']}",
        f"- Incompatible tools: {s['incompatible_tools']}",
        f"- Missing tools: {s['missing_tools']}", "",
        "## Tools", "",
        "| Tool | Status | Variant | Reason |",
        "|---|---|---|---|",
    ]
    for tool_id, item in sorted(result.get("tools", {}).items()):
        lines.append(f"| `{tool_id}` | `{item.get('status')}` | `{item.get('command_variant') or '-'}` | {item.get('reason')} |")
    lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    s = result["summary"]
    print("tool-adapter-check summary")
    print(f"  status: {s['status']}")
    print(f"  checked_tools: {s['checked_tools']}")
    print(f"  compatible_tools: {s['compatible_tools']}")
    print(f"  incompatible_tools: {s['incompatible_tools']}")
    print(f"  missing_tools: {s['missing_tools']}")
    for tool_id, item in sorted(result.get("tools", {}).items()):
        print(f"  {tool_id}: {item.get('status')} variant={item.get('command_variant') or '-'}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check local tool CLI adapter compatibility.")
    parser.add_argument("--run-root", default="", help="If set, also write the result into this run's evidence directory.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    result = build_result()
    output = Path(args.output)
    if not output.is_absolute():
        output = (ROOT / output).resolve()
    write_json(output, result)
    output.with_suffix(".md").write_text(render_md(result), encoding="utf-8")

    if args.run_root:
        run_root = Path(args.run_root)
        if not run_root.is_absolute():
            run_root = (ROOT / run_root).resolve()
        run_output = run_root / "evidence" / "TOOL_ADAPTER_STATUS.json"
        write_json(run_output, result)
        (run_root / "evidence" / "TOOL_ADAPTER_STATUS.md").write_text(render_md(result), encoding="utf-8")

    if args.print_summary:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
