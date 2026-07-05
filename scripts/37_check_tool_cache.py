#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "local" / "registry" / "tools" / "TOOL_CACHE_STATUS.json"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_command(command: str, timeout: int = 12) -> dict[str, Any]:
    started = dt.datetime.now()
    try:
        proc = subprocess.run(command, shell=True, text=True, capture_output=True, timeout=timeout)
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "exit_code": proc.returncode,
            "status": "success" if proc.returncode == 0 else "failed",
            "stdout": (proc.stdout or "").strip()[:1000],
            "stderr": (proc.stderr or "").strip()[:1000],
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {"command": command, "exit_code": None, "status": "failed", "stdout": "", "stderr": str(exc), "duration_ms": duration_ms}


def existing_dirs(candidates: list[Path]) -> list[str]:
    found = []
    for path in candidates:
        try:
            if path.exists():
                found.append(str(path))
        except Exception:
            continue
    return found


def dir_size(path: Path, limit_files: int = 4000) -> int | None:
    if not path.exists():
        return None
    total = 0
    count = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
                count += 1
                if count >= limit_files:
                    break
        return total
    except Exception:
        return None


def cache_item(tool_id: str, command: str | None, paths: list[Path], update_commands: list[str]) -> dict[str, Any]:
    tool_present = bool(command and shutil.which(command))
    found = existing_dirs(paths)
    sizes = {p: dir_size(Path(p)) for p in found}
    if not tool_present:
        status = "tool_missing"
    elif found:
        status = "present"
    else:
        status = "not_found"
    return {
        "tool_id": tool_id,
        "tool_present": tool_present,
        "status": status,
        "cache_paths_checked": [str(x) for x in paths],
        "cache_paths_found": found,
        "cache_size_bytes_by_path": sizes,
        "update_commands": update_commands,
    }


def build_result() -> dict[str, Any]:
    home = Path.home()
    trivy_env = os.environ.get("TRIVY_CACHE_DIR")
    trivy_paths = [Path(trivy_env)] if trivy_env else []
    trivy_paths.extend([home / ".cache" / "trivy", home / "Library" / "Caches" / "trivy", home / "Library" / "Caches" / "aquasecurity" / "trivy"])
    depcheck_paths = [home / ".m2" / "repository" / "org" / "owasp", home / "Library" / "Caches" / "org.owasp.dependencycheck", home / ".local" / "share" / "dependency-check"]
    semgrep_paths = [home / ".semgrep", home / ".cache" / "semgrep", home / "Library" / "Caches" / "semgrep"]

    items = [
        cache_item("trivy", "trivy", trivy_paths, ["trivy image --download-db-only"]),
        cache_item("dependency-check", "dependency-check", depcheck_paths, ["dependency-check --updateonly"]),
        cache_item("semgrep", "semgrep", semgrep_paths, ["semgrep --config p/security-audit --dryrun ."]),
    ]
    by_id = {item["tool_id"]: item for item in items}
    missing = [x for x in items if x["status"] == "not_found"]
    present = [x for x in items if x["status"] == "present"]
    return {
        "schema_version": "tool-cache-status-0.1.0",
        "generated_at": now(),
        "summary": {
            "status": "completed",
            "checked_tools": len(items),
            "present_caches": len(present),
            "missing_caches": len(missing),
            "tool_missing": sum(1 for x in items if x["status"] == "tool_missing"),
        },
        "tools": by_id,
        "notes": [
            "Cache checks are conservative filesystem probes and do not prove freshness.",
            "Use tool-cache-update with explicit network authorization to initialize or refresh tool caches.",
        ],
    }


def render_md(result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        "# TOOL_CACHE_STATUS", "",
        f"- Status: `{s['status']}`",
        f"- Checked tools: {s['checked_tools']}",
        f"- Present caches: {s['present_caches']}",
        f"- Missing caches: {s['missing_caches']}",
        f"- Tool missing: {s['tool_missing']}", "",
        "## Tools", "",
        "| Tool | Tool present | Cache status | Found paths | Update command |",
        "|---|---:|---|---|---|",
    ]
    for tool_id, item in sorted(result.get("tools", {}).items()):
        found = ", ".join(item.get("cache_paths_found") or []) or "-"
        update = "; ".join(item.get("update_commands") or []) or "-"
        lines.append(f"| `{tool_id}` | `{item.get('tool_present')}` | `{item.get('status')}` | `{found}` | `{update}` |")
    lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    s = result["summary"]
    print("tool-cache-check summary")
    print(f"  checked_tools: {s['checked_tools']}")
    print(f"  present_caches: {s['present_caches']}")
    print(f"  missing_caches: {s['missing_caches']}")
    print(f"  tool_missing: {s['tool_missing']}")
    for tool_id, item in sorted(result.get("tools", {}).items()):
        print(f"  {tool_id}: {item.get('status')} found={len(item.get('cache_paths_found') or [])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check local security tool cache presence.")
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
        run_output = run_root / "evidence" / "TOOL_CACHE_STATUS.json"
        write_json(run_output, result)
        (run_root / "evidence" / "TOOL_CACHE_STATUS.md").write_text(render_md(result), encoding="utf-8")

    if args.print_summary:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
