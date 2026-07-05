#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_ENV = ROOT / "spec" / "env"
SPEC_RULES = ROOT / "spec" / "rules"
DEFAULT_OUTPUT_ROOT = "var/runs"


def slugify(value: str, default: str = "project") -> str:
    value = (value or "").strip()
    if not value:
        return default
    value = value.replace("\\", "/").rstrip("/").split("/")[-1]
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value or default


def resolve_project_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    return p


def resolve_output_root(project_path: Path, output_root: str, workspace_mode: str) -> Path:
    raw = Path(output_root).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    if workspace_mode == "project":
        return (project_path / raw).resolve()
    return (ROOT / raw).resolve()


def run(args: list[str]) -> int:
    print("$ " + " ".join(args))
    proc = subprocess.run(args, cwd=str(ROOT), text=True)
    return proc.returncode


def write_flow_record(run_root: Path, record: dict) -> None:
    out = run_root / "debug"
    out.mkdir(parents=True, exist_ok=True)
    (out / "AUDIT_STATIC_FLOW.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# AUDIT_STATIC_FLOW", "",
        f"- Status: `{record['status']}`",
        f"- Run root: `{record['run_root']}`",
        f"- Network authorization: `{record['network_authorization']}`",
        f"- Dry run external tools: `{record['dry_run_external_tools']}`",
        f"- Assisted change: `{record.get('assisted_change')}`", "",
        "## Steps", "",
        "| Step | Status | Exit code |",
        "|---|---|---:|",
    ]
    for item in record.get("steps", []):
        lines.append(f"| {item['name']} | {item['status']} | {item.get('exit_code', '-')} |")
    (out / "AUDIT_STATIC_FLOW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def reset_if_needed(run_root: Path, flow_record: dict) -> None:
    code = run([sys.executable, "scripts/27_reset_assisted_change.py", "--run-root", str(run_root), "--print-summary"])
    flow_record["steps"].append({"name": "assisted-change-reset-on-failure", "status": "completed" if code == 0 else "failed", "exit_code": code})


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run formal static audit flow in the intended audit order.")
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--project-code", default="")
    parser.add_argument("--project-name", default="")
    parser.add_argument("--round", default="R1")
    parser.add_argument("--debug-level", default="off", choices=["off", "basic", "trace", "replay"])
    parser.add_argument("--run-id", default="")
    parser.add_argument("--workspace-mode", default="workbench", choices=["workbench", "project"])
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--network-authorization", default="deny", choices=["deny", "once", "always"])
    parser.add_argument("--tool-timeout", type=int, default=900)
    parser.add_argument("--dry-run-external-tools", action="store_true")
    parser.add_argument("--assisted-change", default="none", choices=["none", "swag_init"])
    parser.add_argument("--no-stub", action="store_true", help="Do not write stub AI triage result.")
    args = parser.parse_args(argv)

    project_path = resolve_project_path(args.project_path)
    project_key = slugify(args.project_code or args.project_name or project_path.name)
    run_id = args.run_id or f"FAST_STATIC_{args.round}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_root = resolve_output_root(project_path, args.output_root, args.workspace_mode)
    run_root = output_root / project_key / run_id

    tool_matrix = str(SPEC_ENV / "TOOL_MATRIX.yaml")
    tool_matrix_ext = str(SPEC_ENV / "TOOL_MATRIX_EXTENSIONS.yaml")
    recipes = str(SPEC_RULES / "candidate-recipes.yaml")
    assisted_enabled = args.assisted_change != "none"

    steps: list[tuple[str, list[str]]] = [
        ("check-deps", [sys.executable, "scripts/05_check_deps.py", "--strict", "--print-summary"]),
        ("run-init", [sys.executable, "scripts/10_run_init.py", "--project-path", str(project_path), "--project-code", args.project_code, "--project-name", args.project_name, "--audit-mode", "FAST_STATIC", "--round", args.round, "--debug-level", args.debug_level, "--run-id", run_id, "--workspace-mode", args.workspace_mode, "--output-root", args.output_root, "--network-authorization", args.network_authorization, "--print-summary"]),
        ("audit-map", [sys.executable, "scripts/20_build_audit_map.py", "--run-root", str(run_root), "--print-summary"]),
        ("stack-env-check", [sys.executable, "scripts/31_stack_env_check.py", "--run-root", str(run_root), "--include-all-tools", "--tool-matrix", tool_matrix, "--tool-matrix-extensions", tool_matrix_ext, "--print-summary"]),
        ("tool-adapter-check", [sys.executable, "scripts/36_check_tool_adapters.py", "--run-root", str(run_root), "--print-summary"]),
        ("tool-cache-check", [sys.executable, "scripts/37_check_tool_cache.py", "--run-root", str(run_root), "--print-summary"]),
        ("tool-plan", [sys.executable, "scripts/30_build_tool_plan.py", "--run-root", str(run_root), "--env-result", str(run_root / "evidence" / "STACK_ENV_CHECK_RESULT.json"), "--tool-matrix", tool_matrix, "--tool-matrix-extensions", tool_matrix_ext, "--print-summary"]),
        ("preflight", [sys.executable, "scripts/25_run_preflight.py", "--run-root", str(run_root), "--print-summary"]),
    ]
    if assisted_enabled:
        steps.extend([
            ("assisted-change", [sys.executable, "scripts/26_run_assisted_change.py", "--run-root", str(run_root), "--allow", args.assisted_change, "--print-summary"]),
            ("preflight-after-assisted-change", [sys.executable, "scripts/25_run_preflight.py", "--run-root", str(run_root), "--print-summary"]),
        ])
    steps.extend([
        ("tool-execution-plan", [sys.executable, "scripts/32_build_tool_execution_plan.py", "--run-root", str(run_root), "--print-summary"]),
        ("ext-tool-run", [sys.executable, "scripts/33_run_tool_execution_plan.py", "--run-root", str(run_root), "--timeout", str(args.tool_timeout), "--print-summary"] + (["--dry-run"] if args.dry_run_external_tools else [])),
    ])
    if assisted_enabled:
        steps.append(("assisted-change-reset", [sys.executable, "scripts/27_reset_assisted_change.py", "--run-root", str(run_root), "--print-summary"]))
    steps.extend([
        ("ext-tool-candidates", [sys.executable, "scripts/34_import_tool_candidates.py", "--run-root", str(run_root), "--print-summary"]),
        ("evidence-pack", [sys.executable, "scripts/40_build_evidence_pack.py", "--run-root", str(run_root), "--print-summary"]),
        ("built-in-tool-run", [sys.executable, "scripts/50_run_static_tools.py", "--run-root", str(run_root), "--recipes", recipes, "--print-summary"]),
        ("candidate-pool", [sys.executable, "scripts/60_build_candidates.py", "--run-root", str(run_root), "--print-summary"]),
        ("merge-external-candidates", [sys.executable, "scripts/35_merge_external_candidates.py", "--run-root", str(run_root), "--print-summary"]),
        ("ai-triage", [sys.executable, "scripts/70_prepare_ai_triage.py", "--run-root", str(run_root), "--print-summary"] + ([] if args.no_stub else ["--write-stub"])),
        ("merge", [sys.executable, "scripts/80_merge_results.py", "--run-root", str(run_root), "--print-summary"]),
        ("delivery", [sys.executable, "scripts/90_render_delivery.py", "--run-root", str(run_root), "--print-summary"]),
        ("validate", [sys.executable, "scripts/95_validate_run.py", "--run-root", str(run_root), "--print-summary"]),
    ])
    if args.debug_level != "off":
        steps.append(("debug-trace", [sys.executable, "scripts/110_collect_debug.py", "--run-root", str(run_root), "--debug-level", args.debug_level, "--print-summary"]))

    flow_record = {
        "schema_version": "audit-static-flow-0.5.0",
        "status": "running",
        "run_root": str(run_root),
        "project_path": str(project_path),
        "network_authorization": args.network_authorization,
        "dry_run_external_tools": args.dry_run_external_tools,
        "assisted_change": args.assisted_change,
        "steps": [],
    }

    for name, command in steps:
        code = run(command)
        flow_record["steps"].append({"name": name, "status": "completed" if code == 0 else "failed", "exit_code": code})
        if code != 0:
            flow_record["status"] = "failed"
            if assisted_enabled and name != "assisted-change-reset":
                reset_if_needed(run_root, flow_record)
            write_flow_record(run_root, flow_record)
            print(f"[FAIL] step failed: {name} exit={code}", file=sys.stderr)
            print(f"Run root: {run_root}", file=sys.stderr)
            return code

    flow_record["status"] = "completed"
    write_flow_record(run_root, flow_record)
    print("")
    print("AUDIT_STATIC flow completed.")
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
