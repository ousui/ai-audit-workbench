#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


WORKBENCH_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_AUDIT_MODE = "FAST_STATIC"
DEFAULT_ROUND = "R1"
DEFAULT_DEBUG_LEVEL = "off"

RUN_SUBDIRS = [
    "meta",
    "audit-map",
    "evidence",
    "candidates",
    "ai",
    "merge",
    "delivery",
    "validate",
    "debug",
    "tmp",
]

AUTHORIZATION_PROFILES = {
    "deny": {
        "network_allowed": False,
        "online_rules_allowed": False,
        "external_tool_update_allowed": False,
        "remote_rule_sources_allowed": [],
    },
    "once": {
        "network_allowed": True,
        "online_rules_allowed": True,
        "external_tool_update_allowed": True,
        "remote_rule_sources_allowed": [
            "semgrep_registry",
            "trivy_db",
            "osv",
            "npm_audit",
            "govuln_db",
            "retirejs_db",
        ],
    },
    "always": {
        "network_allowed": True,
        "online_rules_allowed": True,
        "external_tool_update_allowed": True,
        "remote_rule_sources_allowed": [
            "semgrep_registry",
            "trivy_db",
            "osv",
            "npm_audit",
            "govuln_db",
            "retirejs_db",
        ],
    },
}


def now_local() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc).astimezone()


def now_iso() -> str:
    return now_local().isoformat(timespec="seconds")


def slugify(value: str, default: str = "unknown") -> str:
    value = (value or "").strip()
    if not value:
        return default

    value = value.replace("\\", "/").rstrip("/").split("/")[-1]
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    value = value.strip("-._")

    return value or default


def normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def run_command(args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=12,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def safe_relative(path: Path, base: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except Exception:
        return None


def path_display(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "input": str(path),
        "resolved": str(resolved),
        "relative_to_workbench": safe_relative(resolved, WORKBENCH_ROOT),
    }


def resolve_output_root(project_path: Path, output_root: str, workspace_mode: str) -> Path:
    raw = Path(output_root).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    if workspace_mode == "project":
        return (project_path / raw).resolve()
    return (WORKBENCH_ROOT / raw).resolve()


def read_git_info(project_path: Path) -> dict[str, Any]:
    git_info: dict[str, Any] = {
        "is_git_repo": False,
        "root": None,
        "root_relative_to_workbench": None,
        "branch": None,
        "commit": None,
        "remote_origin": None,
        "dirty": None,
        "status_porcelain_count": None,
        "errors": [],
    }

    code, stdout, stderr = run_command(["git", "rev-parse", "--show-toplevel"], cwd=project_path)
    if code != 0:
        git_info["errors"].append(stderr or "not a git repository")
        return git_info

    git_info["is_git_repo"] = True
    git_root = Path(stdout).resolve()
    git_info["root"] = str(git_root)
    git_info["root_relative_to_workbench"] = safe_relative(git_root, WORKBENCH_ROOT)

    code, stdout, stderr = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=project_path)
    if code == 0:
        git_info["branch"] = stdout
    else:
        git_info["errors"].append(stderr or "failed to read branch")

    code, stdout, stderr = run_command(["git", "rev-parse", "HEAD"], cwd=project_path)
    if code == 0:
        git_info["commit"] = stdout
    else:
        git_info["errors"].append(stderr or "failed to read commit")

    code, stdout, stderr = run_command(["git", "remote", "get-url", "origin"], cwd=project_path)
    if code == 0:
        git_info["remote_origin"] = stdout
    else:
        git_info["remote_origin"] = None

    code, stdout, stderr = run_command(["git", "status", "--porcelain"], cwd=project_path)
    if code == 0:
        lines = [line for line in stdout.splitlines() if line.strip()]
        git_info["status_porcelain_count"] = len(lines)
        git_info["dirty"] = len(lines) > 0
    else:
        git_info["dirty"] = None
        git_info["errors"].append(stderr or "failed to read git status")

    return git_info


def choose_project_key(project_path: Path, project_code: str | None, project_name: str | None) -> str:
    if project_code:
        return slugify(project_code, default="project")
    if project_name:
        return slugify(project_name, default="project")
    return slugify(project_path.name, default="project")


def next_run_root(output_root: Path, project_key: str, audit_mode: str, round_label: str, requested_run_id: str | None) -> tuple[str, Path]:
    project_runs_root = output_root / project_key
    project_runs_root.mkdir(parents=True, exist_ok=True)

    if requested_run_id:
        base_run_id = slugify(requested_run_id, default="run")
    else:
        stamp = now_local().strftime("%Y%m%d_%H%M%S")
        base_run_id = f"{slugify(audit_mode)}_{slugify(round_label)}_{stamp}"

    run_id = base_run_id
    run_root = project_runs_root / run_id

    index = 2
    while run_root.exists():
        run_id = f"{base_run_id}_{index:02d}"
        run_root = project_runs_root / run_id
        index += 1

    return run_id, run_root


def create_run_dirs(run_root: Path) -> None:
    run_root.mkdir(parents=True, exist_ok=False)
    for subdir in RUN_SUBDIRS:
        (run_root / subdir).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_authorization(mode: str, workspace_mode: str) -> dict[str, Any]:
    profile = AUTHORIZATION_PROFILES[mode]
    return {
        "schema_version": "authorization-0.1.0",
        "authorization_mode": mode,
        "confirmed_at": now_iso(),
        "confirmed_by": "run-init-argument",
        "workspace_mode": workspace_mode,
        "network": {
            "allowed": profile["network_allowed"],
            "scope": ["remote_rule_fetch", "vulnerability_db_update", "package_registry_audit"],
        },
        "online_rules": {
            "allowed": profile["online_rules_allowed"],
            "default_profile_behavior": "run_offline_and_online_when_allowed",
            "remote_rule_sources_allowed": profile["remote_rule_sources_allowed"],
        },
        "external_tool_update": {
            "allowed": profile["external_tool_update_allowed"],
            "notes": ["Only tool-managed rule/database updates are covered. Arbitrary upload or write-back remains denied."],
        },
        "denied": {
            "write_project_source": True,
            "start_service": True,
            "dynamic_request": True,
            "reverse_artifact": True,
            "upload_external": True,
            "write_external": True,
        },
    }


def write_run_readme(path: Path, metadata: dict[str, Any], authorization: dict[str, Any]) -> None:
    text = f"""# Audit Run

This directory contains one AI Audit Workbench run.

## Run

- Run ID: `{metadata["run_id"]}`
- Project key: `{metadata["project_key"]}`
- Audit mode: `{metadata["audit_mode"]}`
- Round: `{metadata["round"]}`
- Created at: `{metadata["created_at"]}`
- Workspace mode: `{metadata["workspace_mode"]}`
- Output root: `{metadata["output_root"]}`

## Authorization

- Network authorization mode: `{authorization["authorization_mode"]}`
- Online rules allowed: `{authorization["online_rules"]["allowed"]}`
- Network allowed: `{authorization["network"]["allowed"]}`

## Boundaries

- This run must not modify audited source code.
- This run is local workflow output and is not a business-facing delivery by itself.
- Business-facing delivery must be generated from merged results in later stages.
"""
    path.write_text(text, encoding="utf-8")


def build_metadata(
    project_path: Path,
    project_code: str | None,
    project_name: str | None,
    audit_mode: str,
    round_label: str,
    debug_level: str,
    run_id: str,
    run_root: Path,
    output_root: Path,
    workspace_mode: str,
    git_info: dict[str, Any],
    authorization: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    project_rel = safe_relative(project_path.resolve(), WORKBENCH_ROOT)
    project_key = run_root.parent.name

    project_profile = {
        "schema_version": "project-profile-0.1.0",
        "project_key": project_key,
        "project_code": project_code,
        "project_name": project_name or project_path.name,
        "project_path": path_display(project_path),
        "git": git_info,
        "audit_scope": {
            "mode": audit_mode,
            "round": round_label,
            "static_only_default": audit_mode in {"FAST_STATIC", "STANDARD_STATIC", "DEEP_STATIC_EXPLORE"},
            "dynamic_testing_enabled": False,
            "reverse_enabled": False,
        },
        "notes": [],
    }

    run_metadata = {
        "schema_version": "run-metadata-0.2.0",
        "run_id": run_id,
        "project_key": project_key,
        "project_code": project_code,
        "project_name": project_name or project_path.name,
        "audit_mode": audit_mode,
        "round": round_label,
        "debug_level": debug_level,
        "created_at": now_iso(),
        "workspace_mode": workspace_mode,
        "workbench_root": str(WORKBENCH_ROOT),
        "output_root": str(output_root),
        "output_root_relative_to_workbench": safe_relative(output_root, WORKBENCH_ROOT),
        "run_root": str(run_root),
        "run_root_relative_to_workbench": safe_relative(run_root, WORKBENCH_ROOT),
        "project_entry_relative_to_workbench": project_rel,
        "directories": {
            name: safe_relative(run_root / name, WORKBENCH_ROOT) or str(run_root / name)
            for name in RUN_SUBDIRS
        },
        "source_baseline": {
            "git_branch": git_info.get("branch"),
            "git_commit": git_info.get("commit"),
            "git_remote_origin": git_info.get("remote_origin"),
            "git_dirty": git_info.get("dirty"),
            "git_status_porcelain_count": git_info.get("status_porcelain_count"),
        },
        "authorization_ref": safe_relative(run_root / "meta" / "AUTHORIZATION.json", WORKBENCH_ROOT) or str(run_root / "meta" / "AUTHORIZATION.json"),
        "permissions": {
            "read_project": True,
            "write_project_source": False,
            "write_run_output": True,
            "network": bool(authorization["network"]["allowed"]),
            "online_rules": bool(authorization["online_rules"]["allowed"]),
            "start_service": False,
            "dynamic_request": False,
            "reverse_artifact": False,
            "upload_external": False,
            "write_external": False,
        },
    }

    return run_metadata, project_profile


def print_summary(run_metadata: dict[str, Any], project_profile: dict[str, Any], authorization: dict[str, Any]) -> None:
    print("run-init summary")
    print(f"  run_id: {run_metadata['run_id']}")
    print(f"  project_key: {run_metadata['project_key']}")
    print(f"  project_name: {run_metadata['project_name']}")
    print(f"  audit_mode: {run_metadata['audit_mode']}")
    print(f"  round: {run_metadata['round']}")
    print(f"  workspace_mode: {run_metadata['workspace_mode']}")
    print(f"  run_root: {run_metadata['run_root_relative_to_workbench'] or run_metadata['run_root']}")
    print(f"  network_authorization: {authorization['authorization_mode']}")
    print(f"  online_rules_allowed: {authorization['online_rules']['allowed']}")
    print("")
    git_info = project_profile.get("git") or {}
    print("source baseline")
    print(f"  git_repo: {git_info.get('is_git_repo')}")
    print(f"  branch: {git_info.get('branch') or '-'}")
    print(f"  commit: {git_info.get('commit') or '-'}")
    print(f"  dirty: {git_info.get('dirty')}")
    if git_info.get("errors"):
        print("  git_notes:")
        for item in git_info["errors"]:
            print(f"    - {item}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Initialize one audit run directory.")
    parser.add_argument("--project-path", required=True, help="Path to audited project directory or symlink.")
    parser.add_argument("--project-code", default=None, help="Optional project code.")
    parser.add_argument("--project-name", default=None, help="Optional project name.")
    parser.add_argument("--audit-mode", default=DEFAULT_AUDIT_MODE, choices=["FAST_STATIC", "STANDARD_STATIC", "DEEP_STATIC_EXPLORE", "DAST", "REVERSE"])
    parser.add_argument("--round", default=DEFAULT_ROUND, help="Round label, for example R1.")
    parser.add_argument("--debug-level", default=DEFAULT_DEBUG_LEVEL, choices=["off", "basic", "trace", "replay"])
    parser.add_argument("--run-id", default=None, help="Optional explicit run id. Must be unique under output-root/<project_key>.")
    parser.add_argument("--workspace-mode", default="workbench", choices=["workbench", "project"], help="Where relative output-root is resolved.")
    parser.add_argument("--output-root", default="runs", help="Run output root. Relative paths are resolved by workspace-mode.")
    parser.add_argument("--network-authorization", default="deny", choices=["deny", "once", "always"], help="Authorize online rule/database/package-registry access for this run.")
    parser.add_argument("--print-summary", action="store_true", help="Print human-readable summary.")
    args = parser.parse_args(argv)

    project_path = Path(args.project_path).expanduser()
    if not project_path.is_absolute():
        project_path = (WORKBENCH_ROOT / project_path).resolve()

    if not project_path.exists():
        print(f"[FAIL] project path does not exist: {project_path}", file=sys.stderr)
        return 2

    if not project_path.is_dir():
        print(f"[FAIL] project path is not a directory: {project_path}", file=sys.stderr)
        return 2

    output_root = resolve_output_root(project_path, args.output_root, args.workspace_mode)
    project_code = normalize_optional(args.project_code)
    project_name = normalize_optional(args.project_name)
    project_key = choose_project_key(project_path, project_code, project_name)
    run_id, run_root = next_run_root(output_root, project_key, args.audit_mode, args.round, normalize_optional(args.run_id))

    git_info = read_git_info(project_path)
    authorization = build_authorization(args.network_authorization, args.workspace_mode)

    create_run_dirs(run_root)

    run_metadata, project_profile = build_metadata(
        project_path=project_path,
        project_code=project_code,
        project_name=project_name,
        audit_mode=args.audit_mode,
        round_label=args.round,
        debug_level=args.debug_level,
        run_id=run_id,
        run_root=run_root,
        output_root=output_root,
        workspace_mode=args.workspace_mode,
        git_info=git_info,
        authorization=authorization,
    )

    write_json(run_root / "meta" / "RUN_METADATA.json", run_metadata)
    write_json(run_root / "meta" / "PROJECT_PROFILE.json", project_profile)
    write_json(run_root / "meta" / "AUTHORIZATION.json", authorization)
    write_run_readme(run_root / "README.md", run_metadata, authorization)

    if args.print_summary:
        print_summary(run_metadata, project_profile, authorization)
    else:
        print(f"run initialized: {run_metadata['run_root_relative_to_workbench'] or run_metadata['run_root']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
