#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "local" / "registry" / "tools" / "TOOL_CACHE_UPDATE_RESULT.json"

COMMANDS = {
    "trivy": ["trivy image --download-db-only"],
    "dependency-check": ["dependency-check --updateonly"],
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_command(command: str, timeout: int) -> dict[str, Any]:
    started = dt.datetime.now()
    try:
        proc = subprocess.run(command, shell=True, text=True, capture_output=True, timeout=timeout)
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "exit_code": proc.returncode,
            "status": "success" if proc.returncode == 0 else "failed",
            "stdout": (proc.stdout or "").strip()[:4000],
            "stderr": (proc.stderr or "").strip()[:4000],
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "exit_code": None,
            "status": "timeout",
            "stdout": (exc.stdout if isinstance(exc.stdout, str) else "")[:4000],
            "stderr": (exc.stderr if isinstance(exc.stderr, str) else "")[:4000],
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {"command": command, "exit_code": None, "status": "failed", "stdout": "", "stderr": str(exc), "duration_ms": duration_ms}


def selected_tools(tool: str) -> list[str]:
    if tool == "all":
        return sorted(COMMANDS)
    return [tool]


def build_result(tool: str, allow_network: bool, timeout: int, dry_run: bool) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for tool_id in selected_tools(tool):
        command_names = COMMANDS.get(tool_id)
        if not command_names:
            results.append({"tool_id": tool_id, "status": "unsupported", "commands": [], "reason": "no cache update command is defined"})
            continue
        executable = command_names[0].split()[0]
        if not shutil.which(executable):
            results.append({"tool_id": tool_id, "status": "tool_missing", "commands": [], "reason": f"{executable} not found on PATH"})
            continue
        if not allow_network:
            results.append({"tool_id": tool_id, "status": "blocked_requires_network_authorization", "commands": command_names, "reason": "cache update requires explicit network authorization"})
            continue
        if dry_run:
            results.append({"tool_id": tool_id, "status": "dry_run", "commands": command_names, "reason": "execution skipped by dry-run"})
            continue
        command_results = [run_command(cmd, timeout=timeout) for cmd in command_names]
        status = "completed" if all(item.get("exit_code") == 0 for item in command_results) else "failed"
        results.append({"tool_id": tool_id, "status": status, "commands": command_results})
    return {
        "schema_version": "tool-cache-update-result-0.1.0",
        "generated_at": now(),
        "allow_network": allow_network,
        "dry_run": dry_run,
        "summary": {
            "status": "completed" if all(x.get("status") in {"completed", "dry_run", "blocked_requires_network_authorization", "tool_missing", "unsupported"} for x in results) else "failed",
            "items": len(results),
            "completed": sum(1 for x in results if x.get("status") == "completed"),
            "blocked": sum(1 for x in results if str(x.get("status", "")).startswith("blocked")),
            "failed": sum(1 for x in results if x.get("status") == "failed"),
        },
        "items": results,
    }


def render_md(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        "# TOOL_CACHE_UPDATE_RESULT", "",
        f"- Status: `{s['status']}`",
        f"- Allow network: `{result.get('allow_network')}`",
        f"- Dry run: `{result.get('dry_run')}`",
        f"- Items: {s['items']}",
        f"- Completed: {s['completed']}",
        f"- Blocked: {s['blocked']}",
        f"- Failed: {s['failed']}", "",
        "## Items", "",
        "| Tool | Status | Reason |",
        "|---|---|---|",
    ]
    for item in result.get("items", []):
        lines.append(f"| `{item.get('tool_id')}` | `{item.get('status')}` | {item.get('reason') or '-'} |")
    lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    s = result["summary"]
    print("tool-cache-update summary")
    print(f"  status: {s['status']}")
    print(f"  allow_network: {result.get('allow_network')}")
    print(f"  dry_run: {result.get('dry_run')}")
    print(f"  completed: {s['completed']}")
    print(f"  blocked: {s['blocked']}")
    print(f"  failed: {s['failed']}")
    for item in result.get("items", []):
        print(f"  {item.get('tool_id')}: {item.get('status')}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Update security tool caches with explicit network authorization.")
    parser.add_argument("--tool", default="all", choices=["all", "trivy", "dependency-check"])
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    result = build_result(args.tool, args.allow_network, args.timeout, args.dry_run)
    output = Path(args.output)
    if not output.is_absolute():
        output = (ROOT / output).resolve()
    write_json(output, result)
    output.with_suffix(".md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0 if result.get("summary", {}).get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
