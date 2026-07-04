#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOOL_MATRIX = ROOT / "env" / "TOOL_MATRIX.yaml"
DEFAULT_TOOL_MATRIX_EXTENSIONS = ROOT / "env" / "TOOL_MATRIX_EXTENSIONS.yaml"
AVAILABLE_STATUSES = {"available", "available_multiple"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def redact_path(value: str | None) -> str | None:
    if not value:
        return value
    home = str(Path.home())
    text = value
    if home:
        text = text.replace(home, "<LOCAL_USER_PATH>")
    text = re.sub(r"/Users/[^/]+", "<LOCAL_USER_PATH>", text)
    text = re.sub(r"/home/[^/]+", "<LOCAL_USER_PATH>", text)
    text = re.sub(r"C:\\Users\\[^\\]+", r"<LOCAL_USER_PATH>", text, flags=re.I)
    text = re.sub(r"^/opt/homebrew/bin", "<USER_TOOL_PATH>", text)
    text = re.sub(r"^/usr/local/bin", "<USER_TOOL_PATH>", text)
    text = re.sub(r"^/(usr/)?(s)?bin", "<SYSTEM_PATH>", text)
    return text


def summarize(text: str, max_len: int = 240) -> str | None:
    value = re.sub(r"\s+", " ", (text or "").strip())
    if not value:
        return None
    return value[:max_len] + ("..." if len(value) > max_len else "")


def run_command(command: str, timeout: int = 8) -> dict[str, Any]:
    started = dt.datetime.now()
    try:
        proc = subprocess.run(command, shell=True, text=True, capture_output=True, timeout=timeout)
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "command_redacted": redact_path(command),
            "exit_code": proc.returncode,
            "status": "success" if proc.returncode == 0 else "failed",
            "stdout_summary": summarize(proc.stdout),
            "stderr_summary": summarize(proc.stderr),
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "command_redacted": redact_path(command),
            "exit_code": None,
            "status": "timeout",
            "stdout_summary": summarize(exc.stdout if isinstance(exc.stdout, str) else ""),
            "stderr_summary": summarize(exc.stderr if isinstance(exc.stderr, str) else ""),
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "command_redacted": redact_path(command),
            "exit_code": None,
            "status": "failed",
            "stdout_summary": None,
            "stderr_summary": str(exc),
            "duration_ms": duration_ms,
        }


def detect_os() -> str:
    name = platform.system().lower()
    if name == "darwin":
        return "macos"
    if name == "windows":
        return "windows"
    if name == "linux":
        try:
            proc_version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
            if "microsoft" in proc_version or "wsl" in proc_version:
                return "wsl"
        except Exception:
            pass
        return "linux"
    return "unknown"


def arch() -> str:
    value = platform.machine().lower()
    if value in {"x86_64", "amd64"}:
        return "x86_64"
    if value in {"arm64", "aarch64"}:
        return value
    return value or "unknown"


def locate_commands(raw: dict[str, Any], tool_id: str) -> list[str]:
    detection = raw.get("detection") or {}
    locate = detection.get("locate") or []
    result: list[str] = []
    for item in locate:
        value = str(item)
        if value.startswith("command -v "):
            result.append(value.split("command -v ", 1)[1].strip())
        else:
            result.append(value.strip())
    return result or [tool_id]


def normalize_tool(tool_id: str, raw: dict[str, Any], default_permissions: dict[str, Any]) -> dict[str, Any]:
    detection = raw.get("detection") or {}
    permissions = dict(default_permissions)
    permissions.update(raw.get("permissions") or {})
    return {
        "tool_id": tool_id,
        "display_name": raw.get("display_name") or tool_id,
        "category": raw.get("category") or "other",
        "required_level": raw.get("required_level") or "optional",
        "stacks": raw.get("stacks") or ["all"],
        "stages": raw.get("stages") or [],
        "commands": [str(x) for x in detection.get("commands") or []],
        "locate_commands": locate_commands(raw, tool_id),
        "missing_impact": raw.get("missing_impact"),
        "missing_policy": raw.get("missing_policy") or "record_missing_not_blocking",
        "permissions": permissions,
    }


def load_tools(matrix_path: Path, extension_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        import yaml  # type: ignore
    except Exception:
        raise SystemExit("[FAIL] PyYAML is required. Run make install-deps first.")

    notes: list[str] = []
    tools: dict[str, dict[str, Any]] = {}
    for path in [matrix_path, extension_path]:
        if not path.is_file():
            notes.append(f"matrix not found: {path}")
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        default_permissions = data.get("default_permissions") or {}
        for tool_id, raw in (data.get("tools") or {}).items():
            tools[str(tool_id)] = normalize_tool(str(tool_id), raw or {}, default_permissions)
        notes.append(f"loaded matrix: {path}")
    return list(tools.values()), notes


def relevant(tool: dict[str, Any], stacks: list[str], include_all: bool) -> bool:
    tool_stacks = tool.get("stacks") or ["all"]
    if "all" in tool_stacks:
        return include_all
    return bool(set(tool_stacks) & set(stacks))


def detect_tool(tool: dict[str, Any]) -> dict[str, Any]:
    resolved_command = None
    resolved_path = None
    instances = []
    for command_name in tool["locate_commands"]:
        path = shutil.which(command_name)
        if path and not resolved_command:
            resolved_command = command_name
            resolved_path = str(Path(path).resolve())
        if path:
            instances.append({"command": command_name, "path_redacted": redact_path(str(Path(path).resolve()))})

    detection_records = []
    for command_name in tool["locate_commands"]:
        located = shutil.which(command_name)
        detection_records.append({
            "command": f"command -v {command_name}",
            "exit_code": 0 if located else 1,
            "status": "success" if located else "failed",
            "stdout_summary": redact_path(str(Path(located).resolve())) if located else None,
        })

    command_records = []
    if resolved_command:
        for command in tool.get("commands") or []:
            command_records.append(run_command(str(command)))

    version = None
    for record in command_records:
        if record.get("status") == "success":
            version = record.get("stdout_summary") or record.get("stderr_summary")
            break

    status = "available_multiple" if resolved_path and len(instances) > 1 else ("available" if resolved_path else "missing")
    return {
        "tool_id": tool["tool_id"],
        "display_name": tool.get("display_name"),
        "category": tool.get("category"),
        "required_level": tool.get("required_level"),
        "stacks": tool.get("stacks"),
        "stages": tool.get("stages"),
        "status": status,
        "version": version,
        "resolved_command": resolved_command,
        "resolved_path_redacted": redact_path(resolved_path),
        "instances": instances,
        "detection_records": detection_records + command_records,
        "missing_impact": None if resolved_path else tool.get("missing_impact"),
        "missing_policy": tool.get("missing_policy"),
        "permissions": tool.get("permissions") or {},
    }


def build_result(run_root: Path, include_all: bool, matrix_path: Path, extension_path: Path) -> dict[str, Any]:
    audit_map = load_json(run_root / "audit-map" / "AUDIT_MAP.json")
    run_meta = load_json(run_root / "meta" / "RUN_METADATA.json")
    stacks = audit_map.get("stacks", {}).get("detected_stack_ids") or []
    tools, notes = load_tools(matrix_path, extension_path)
    selected_tools = [tool for tool in tools if relevant(tool, stacks, include_all=include_all)]
    results = {tool["tool_id"]: detect_tool(tool) for tool in selected_tools}
    missing = [tid for tid, item in results.items() if item.get("status") == "missing"]
    available = [tid for tid, item in results.items() if item.get("status") in AVAILABLE_STATUSES]
    required_missing = [tid for tid, item in results.items() if item.get("status") == "missing" and item.get("required_level") in {"required_for_workbench", "required_for_stack"}]
    status = "blocked" if required_missing else ("degraded" if missing else "usable")
    return {
        "schema_version": "stack-env-check-0.1.0",
        "checked_at": now(),
        "run": {
            "run_id": run_meta.get("run_id"),
            "project_key": run_meta.get("project_key"),
            "audit_mode": run_meta.get("audit_mode"),
        },
        "host": {
            "os": detect_os(),
            "os_version": platform.platform(),
            "arch": arch(),
            "shell": os.environ.get("SHELL") or os.environ.get("COMSPEC") or "unknown",
            "runtime_context": "user",
        },
        "project_stacks": stacks,
        "summary": {
            "status": status,
            "selected_tools": len(selected_tools),
            "available_tools": len(available),
            "missing_tools": len(missing),
            "blocked_tools": len(required_missing),
            "available_tool_ids": available,
            "missing_tool_ids": missing,
            "blocked_tool_ids": required_missing,
        },
        "tools": results,
        "notes": notes,
    }


def render_md(result: dict[str, Any]) -> str:
    lines = [
        "# STACK_ENV_CHECK_RESULT", "",
        f"- Status: `{result['summary']['status']}`",
        f"- Stacks: `{', '.join(result.get('project_stacks') or []) or '-'}`",
        f"- Selected tools: {result['summary']['selected_tools']}",
        f"- Available tools: {result['summary']['available_tools']}",
        f"- Missing tools: {result['summary']['missing_tools']}",
        "",
        "## Tools", "",
        "| Tool | Status | Version | Missing impact |",
        "|---|---|---|---|",
    ]
    for tid, item in sorted(result.get("tools", {}).items()):
        lines.append(f"| `{tid}` | {item.get('status')} | {item.get('version') or '-'} | {item.get('missing_impact') or '-'} |")
    return "\n".join(lines) + "\n"


def print_summary(result: dict[str, Any]) -> None:
    s = result["summary"]
    print("stack-env-check summary")
    print(f"  status: {s['status']}")
    print(f"  stacks: {', '.join(result.get('project_stacks') or []) or '-'}")
    print(f"  selected_tools: {s['selected_tools']}")
    print(f"  available_tools: {s['available_tools']}")
    print(f"  missing_tools: {s['missing_tools']}")
    print(f"  blocked_tools: {s['blocked_tools']}")
    if s.get("missing_tool_ids"):
        print(f"  missing_tool_ids: {', '.join(s['missing_tool_ids'])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run stack-aware env-check for a specific audit run.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--include-all-tools", action="store_true", help="Include tools with stacks: all in addition to detected stack tools.")
    parser.add_argument("--tool-matrix", default=str(DEFAULT_TOOL_MATRIX))
    parser.add_argument("--tool-matrix-extensions", default=str(DEFAULT_TOOL_MATRIX_EXTENSIONS))
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not (run_root / "audit-map" / "AUDIT_MAP.json").is_file():
        print("[FAIL] AUDIT_MAP.json not found. Run make m2 first.", file=sys.stderr)
        return 2

    matrix_path = Path(args.tool_matrix)
    if not matrix_path.is_absolute():
        matrix_path = (ROOT / matrix_path).resolve()
    extension_path = Path(args.tool_matrix_extensions)
    if not extension_path.is_absolute():
        extension_path = (ROOT / extension_path).resolve()

    result = build_result(run_root, args.include_all_tools, matrix_path, extension_path)
    output = Path(args.output) if args.output else run_root / "evidence" / "STACK_ENV_CHECK_RESULT.json"
    if not output.is_absolute():
        output = (ROOT / output).resolve()
    write_json(output, result)
    output.with_suffix(".md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 2 if result["summary"]["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
