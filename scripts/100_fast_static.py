#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def slugify(value: str, default: str = "project") -> str:
    value = (value or "").strip()
    if not value:
        return default
    value = value.replace("\\", "/").rstrip("/").split("/")[-1]
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value or default


def resolve_output_root(project_path: str, output_root: str, workspace_mode: str) -> Path:
    raw = Path(output_root).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    if workspace_mode == "project":
        pp = Path(project_path).expanduser()
        if not pp.is_absolute():
            pp = (ROOT / pp).resolve()
        return (pp / raw).resolve()
    return (ROOT / raw).resolve()


def run(args: list[str]) -> int:
    print("$ " + " ".join(args))
    proc = subprocess.run(args, cwd=str(ROOT), text=True)
    return proc.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run FAST_STATIC MVP pipeline.")
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--project-code", default="")
    parser.add_argument("--project-name", default="")
    parser.add_argument("--round", default="R1")
    parser.add_argument("--debug-level", default="off")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--workspace-mode", default="workbench", choices=["workbench", "project"])
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--network-authorization", default="deny", choices=["deny", "once", "always"])
    parser.add_argument("--no-stub", action="store_true", help="Do not write stub AI triage result.")
    args = parser.parse_args(argv)

    project_key = slugify(args.project_code or args.project_name or Path(args.project_path).name)
    run_id = args.run_id or f"FAST_STATIC_{args.round}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_root = resolve_output_root(args.project_path, args.output_root, args.workspace_mode)
    run_root = output_root / project_key / run_id

    steps = [
        [sys.executable, "scripts/05_check_deps.py", "--strict", "--print-summary"],
        [sys.executable, "scripts/10_run_init.py", "--project-path", args.project_path, "--project-code", args.project_code, "--project-name", args.project_name, "--audit-mode", "FAST_STATIC", "--round", args.round, "--debug-level", args.debug_level, "--run-id", run_id, "--workspace-mode", args.workspace_mode, "--output-root", args.output_root, "--network-authorization", args.network_authorization, "--print-summary"],
        [sys.executable, "scripts/20_build_audit_map.py", "--run-root", str(run_root), "--print-summary"],
        [sys.executable, "scripts/31_stack_env_check.py", "--run-root", str(run_root), "--include-all-tools", "--print-summary"],
        [sys.executable, "scripts/30_build_tool_plan.py", "--run-root", str(run_root), "--env-result", str(run_root / "evidence" / "STACK_ENV_CHECK_RESULT.json"), "--print-summary"],
        [sys.executable, "scripts/32_build_tool_execution_plan.py", "--run-root", str(run_root), "--print-summary"],
        [sys.executable, "scripts/40_build_evidence_pack.py", "--run-root", str(run_root), "--print-summary"],
        [sys.executable, "scripts/50_run_static_tools.py", "--run-root", str(run_root), "--print-summary"],
        [sys.executable, "scripts/60_build_candidates.py", "--run-root", str(run_root), "--print-summary"],
        [sys.executable, "scripts/70_prepare_ai_triage.py", "--run-root", str(run_root), "--print-summary"] + ([] if args.no_stub else ["--write-stub"]),
        [sys.executable, "scripts/80_merge_results.py", "--run-root", str(run_root), "--print-summary"],
        [sys.executable, "scripts/90_render_delivery.py", "--run-root", str(run_root), "--print-summary"],
        [sys.executable, "scripts/95_validate_run.py", "--run-root", str(run_root), "--print-summary"],
    ]

    for step in steps:
        code = run(step)
        if code != 0:
            print(f"[FAIL] step failed with exit code {code}", file=sys.stderr)
            print(f"Run root: {run_root}", file=sys.stderr)
            return code

    print("")
    print("FAST_STATIC pipeline completed.")
    try:
        print(f"Run root: {run_root.relative_to(ROOT)}")
        print(f"Report: {(run_root / 'delivery' / 'AUDIT_REPORT.html').relative_to(ROOT)}")
        print(f"Tracking: {(run_root / 'delivery' / 'AUDIT_TRACKING.csv').relative_to(ROOT)}")
    except Exception:
        print(f"Run root: {run_root}")
        print(f"Report: {run_root / 'delivery' / 'AUDIT_REPORT.html'}")
        print(f"Tracking: {run_root / 'delivery' / 'AUDIT_TRACKING.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
