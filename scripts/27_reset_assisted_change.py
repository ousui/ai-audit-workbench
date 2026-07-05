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
APPLIED_STATUSES = {"applied_and_verified", "applied_but_not_verified", "failed"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_command(command: str, cwd: Path, timeout: int = 60) -> dict[str, Any]:
    started = dt.datetime.now()
    try:
        proc = subprocess.run(command, cwd=str(cwd), shell=True, text=True, capture_output=True, timeout=timeout)
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {"command": command, "exit_code": proc.returncode, "status": "success" if proc.returncode == 0 else "failed", "stdout": proc.stdout.strip()[:4000], "stderr": proc.stderr.strip()[:4000], "duration_ms": duration_ms}
    except Exception as exc:
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {"command": command, "exit_code": None, "status": "failed", "stdout": "", "stderr": str(exc), "duration_ms": duration_ms}


def git_status(project_root: Path) -> list[dict[str, str]]:
    result = run_command("git status --porcelain=v1 --untracked-files=all", project_root, timeout=20)
    entries: list[dict[str, str]] = []
    for line in (result.get("stdout") or "").splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        raw_path = line[3:]
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1]
        entries.append({"code": code, "path": raw_path})
    return entries


def safe_project_path(project_root: Path, rel_path: str) -> Path:
    target = (project_root / rel_path).resolve()
    project_resolved = project_root.resolve()
    if target == project_resolved or project_resolved not in target.parents:
        raise ValueError(f"unsafe path outside project: {rel_path}")
    return target


def reset_from_log(project_root: Path, log: dict[str, Any]) -> dict[str, Any]:
    changed = log.get("changed_entries_after") or []
    removed: list[str] = []
    restored: list[str] = []
    errors: list[str] = []

    tracked_paths = []
    for entry in changed:
        code = entry.get("code") or ""
        path = entry.get("path") or ""
        if not path:
            continue
        try:
            target = safe_project_path(project_root, path)
        except Exception as exc:
            errors.append(str(exc))
            continue
        if code == "??":
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
                removed.append(path)
            except Exception as exc:
                errors.append(f"remove {path}: {exc}")
        else:
            tracked_paths.append(path)

    if tracked_paths:
        quoted = " ".join(["'" + p.replace("'", "'\\''") + "'" for p in tracked_paths])
        result = run_command(f"git restore -- {quoted}", project_root, timeout=60)
        if result.get("exit_code") == 0:
            restored.extend(tracked_paths)
        else:
            errors.append(f"git restore failed: {result.get('stderr')}")

    return {"removed_untracked": removed, "restored_tracked": restored, "errors": errors}


def render_md(result: dict[str, Any]) -> str:
    lines = ["# ASSISTED_CHANGE_RESET", "", f"- Status: `{result.get('status')}`", f"- Reason: {result.get('reason')}", ""]
    if result.get("removed_untracked"):
        lines.extend(["## Removed untracked", ""])
        for item in result["removed_untracked"]:
            lines.append(f"- `{item}`")
        lines.append("")
    if result.get("restored_tracked"):
        lines.extend(["## Restored tracked", ""])
        for item in result["restored_tracked"]:
            lines.append(f"- `{item}`")
        lines.append("")
    if result.get("final_status_entries"):
        lines.extend(["## Final git status", ""])
        for item in result["final_status_entries"]:
            lines.append(f"- `{item.get('code')}` `{item.get('path')}`")
        lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    print("assisted-change-reset summary")
    print(f"  status: {result.get('status')}")
    print(f"  reason: {result.get('reason')}")
    print(f"  removed_untracked: {len(result.get('removed_untracked') or [])}")
    print(f"  restored_tracked: {len(result.get('restored_tracked') or [])}")
    print(f"  final_dirty_entries: {len(result.get('final_status_entries') or [])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Reset audit assisted changes after tool execution.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    log_path = run_root / "evidence" / "assisted-change" / "ASSISTED_CHANGE_LOG.json"
    result: dict[str, Any] = {"schema_version": "assisted-change-reset-0.1.0", "generated_at": now(), "run_root": str(run_root)}
    if not log_path.is_file():
        result.update({"status": "no_action", "reason": "ASSISTED_CHANGE_LOG.json not found."})
    else:
        log = load_json(log_path)
        project_root = Path(log.get("project_root") or "")
        if log.get("status") not in APPLIED_STATUSES or not log.get("reset_required"):
            result.update({"status": "no_action", "reason": "No applied assisted change requires reset."})
        elif not project_root.is_dir():
            result.update({"status": "failed", "reason": "project root not found."})
        else:
            reset_result = reset_from_log(project_root, log)
            final_status = git_status(project_root)
            result.update(reset_result)
            result["final_status_entries"] = final_status
            if reset_result.get("errors"):
                result.update({"status": "failed", "reason": "reset encountered errors."})
            elif final_status:
                result.update({"status": "failed", "reason": "project worktree is still dirty after reset."})
            else:
                result.update({"status": "completed", "reason": "assisted changes reset successfully."})

    out = run_root / "evidence" / "assisted-change"
    write_json(out / "ASSISTED_CHANGE_RESET.json", result)
    (out / "ASSISTED_CHANGE_RESET.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0 if result.get("status") in {"completed", "no_action"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
