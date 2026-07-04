#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except Exception:
        return str(path)


def safe_text(text: str, max_len: int = 4000) -> str:
    value = text or ""
    if len(value) > max_len:
        return value[:max_len] + "\n...[truncated]"
    return value


def run_shell(command: str, cwd: Path, timeout: int) -> tuple[int | None, str, str, str | None]:
    try:
        proc = subprocess.run(command, shell=True, cwd=str(cwd), text=True, capture_output=True, timeout=timeout)
        return proc.returncode, proc.stdout or "", proc.stderr or "", None
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return None, stdout, stderr, "timeout"
    except Exception as exc:
        return None, "", str(exc), "execution_error"


def output_status(exit_code: int | None, expected_outputs: list[str]) -> str:
    outputs_existing = [Path(item).is_file() for item in expected_outputs]
    has_expected = bool(expected_outputs)
    any_output = any(outputs_existing) if has_expected else False
    all_output = all(outputs_existing) if has_expected else True
    if exit_code == 0 and all_output:
        return "completed"
    if exit_code == 0 and not all_output:
        return "completed_missing_output"
    if exit_code is None:
        return "failed"
    if any_output:
        return "completed_nonzero"
    return "failed_nonzero"


def run_command_item(item: dict[str, Any], command: dict[str, Any], run_root: Path, timeout: int) -> dict[str, Any]:
    command_id = command["command_id"]
    output_dir = Path(item.get("output_dir_abs") or item.get("output_dir") or run_root / "evidence" / "tool-outputs" / item["tool_id"] / item["profile"])
    if not output_dir.is_absolute():
        output_dir = (ROOT / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    command_dir = output_dir / "commands" / command_id
    command_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = command_dir / "stdout.txt"
    stderr_path = command_dir / "stderr.txt"
    meta_path = command_dir / "command.json"

    started_at = now()
    started = dt.datetime.now()
    exit_code, stdout, stderr, error_kind = run_shell(command["shell"], Path(item["cwd"]), timeout)
    duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
    finished_at = now()

    stdout_path.write_text(stdout, encoding="utf-8", errors="ignore")
    stderr_path.write_text(stderr, encoding="utf-8", errors="ignore")
    expected_outputs = [str(Path(x)) for x in command.get("output_files") or []]
    status = output_status(exit_code, expected_outputs)
    output_files = []
    for item_path in expected_outputs:
        p = Path(item_path)
        output_files.append({
            "path": item_path,
            "path_relative_to_workbench": rel(p),
            "exists": p.is_file(),
            "size_bytes": p.stat().st_size if p.is_file() else None,
        })

    meta = {
        "schema_version": "tool-command-result-0.1.0",
        "tool_id": item["tool_id"],
        "profile": item["profile"],
        "command_id": command_id,
        "command": command["shell"],
        "cwd": item["cwd"],
        "network_required": bool(command.get("network_required")),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "status": status,
        "error_kind": error_kind,
        "stdout_path": rel(stdout_path),
        "stderr_path": rel(stderr_path),
        "stdout_summary": safe_text(stdout, 1000),
        "stderr_summary": safe_text(stderr, 1000),
        "output_files": output_files,
    }
    write_json(meta_path, meta)
    return meta


def run_plan(run_root: Path, timeout: int, dry_run: bool) -> dict[str, Any]:
    plan_path = run_root / "evidence" / "tool-execution" / "TOOL_EXECUTION_PLAN.json"
    plan = load_json(plan_path)
    command_results: list[dict[str, Any]] = []
    item_results: list[dict[str, Any]] = []

    for item in plan.get("items", []):
        if item.get("status") != "planned":
            item_results.append({
                "tool_id": item.get("tool_id"),
                "profile": item.get("profile"),
                "status": item.get("status"),
                "reason": item.get("reason"),
                "commands": [],
            })
            continue
        if dry_run:
            item_results.append({
                "tool_id": item.get("tool_id"),
                "profile": item.get("profile"),
                "status": "dry_run",
                "reason": "execution_skipped_by_dry_run",
                "commands": [],
            })
            continue

        commands = []
        for command in item.get("commands") or []:
            result = run_command_item(item, command, run_root, timeout)
            commands.append(result)
            command_results.append(result)
        failed = [cmd for cmd in commands if str(cmd.get("status", "")).startswith("failed")]
        nonzero = [cmd for cmd in commands if cmd.get("status") == "completed_nonzero"]
        missing = [cmd for cmd in commands if cmd.get("status") == "completed_missing_output"]
        if failed:
            status = "failed"
        elif missing:
            status = "degraded_missing_output"
        elif nonzero:
            status = "completed_nonzero"
        else:
            status = "completed"
        item_results.append({
            "tool_id": item.get("tool_id"),
            "profile": item.get("profile"),
            "status": status,
            "reason": "executed",
            "commands": commands,
        })

    completed = [x for x in item_results if x.get("status") == "completed"]
    degraded = [x for x in item_results if x.get("status") in {"completed_nonzero", "degraded_missing_output"}]
    failed = [x for x in item_results if x.get("status") == "failed"]
    skipped = [x for x in item_results if x.get("status") in {"skipped_by_policy", "dry_run"}]
    status = "failed" if failed else ("degraded" if degraded else "completed")
    if dry_run:
        status = "dry_run"

    return {
        "schema_version": "tool-execution-result-0.1.0",
        "generated_at": now(),
        "run": plan.get("run"),
        "authorization": plan.get("authorization"),
        "summary": {
            "status": status,
            "items_total": len(item_results),
            "items_completed": len(completed),
            "items_degraded": len(degraded),
            "items_failed": len(failed),
            "items_skipped": len(skipped),
            "commands_total": len(command_results),
        },
        "items": item_results,
    }


def render_md(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        "# TOOL_EXECUTION_RESULT", "",
        f"- Status: `{s['status']}`",
        f"- Items total: {s['items_total']}",
        f"- Items completed: {s['items_completed']}",
        f"- Items degraded: {s['items_degraded']}",
        f"- Items failed: {s['items_failed']}",
        f"- Items skipped: {s['items_skipped']}",
        f"- Commands total: {s['commands_total']}", "",
        "## Items", "",
        "| Tool | Profile | Status | Commands |",
        "|---|---|---|---:|",
    ]
    for item in result.get("items", []):
        lines.append(f"| `{item.get('tool_id')}` | {item.get('profile')} | {item.get('status')} | {len(item.get('commands') or [])} |")
    return "\n".join(lines) + "\n"


def print_summary(result: dict[str, Any]) -> None:
    s = result["summary"]
    print("tool-execution-result summary")
    print(f"  status: {s['status']}")
    print(f"  items_total: {s['items_total']}")
    print(f"  items_completed: {s['items_completed']}")
    print(f"  items_degraded: {s['items_degraded']}")
    print(f"  items_failed: {s['items_failed']}")
    print(f"  commands_total: {s['commands_total']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Execute planned external tools and record command evidence.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    plan_path = run_root / "evidence" / "tool-execution" / "TOOL_EXECUTION_PLAN.json"
    if not plan_path.is_file():
        print("[FAIL] TOOL_EXECUTION_PLAN.json not found. Run tool-execution-plan first.", file=sys.stderr)
        return 2

    result = run_plan(run_root, timeout=args.timeout, dry_run=args.dry_run)
    out = run_root / "evidence" / "tool-execution"
    write_json(out / "TOOL_EXECUTION_RESULT.json", result)
    (out / "TOOL_EXECUTION_RESULT.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
