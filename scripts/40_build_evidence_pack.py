#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def trim_bucket(bucket: dict[str, Any], limit: int) -> dict[str, Any]:
    items = bucket.get("items") or []
    return {
        "items": items[:limit],
        "count": bucket.get("count", len(items)),
        "emitted_count": min(len(items), limit),
        "truncated_count": max(0, int(bucket.get("count", len(items))) - min(len(items), limit)),
    }


def build_evidence_pack(run_root: Path) -> dict[str, Any]:
    run_meta = load_json(run_root / "meta" / "RUN_METADATA.json")
    profile = load_json(run_root / "meta" / "PROJECT_PROFILE.json")
    audit_map = load_json(run_root / "audit-map" / "AUDIT_MAP.json")
    tool_plan_path = run_root / "evidence" / "TOOL_PLAN.json"
    tool_plan = load_json(tool_plan_path) if tool_plan_path.is_file() else None

    files = audit_map.get("files", {})
    signals = audit_map.get("signals", {})

    return {
        "schema_version": "evidence-pack-0.1.0",
        "run": {
            "run_id": run_meta.get("run_id"),
            "project_key": run_meta.get("project_key"),
            "audit_mode": run_meta.get("audit_mode"),
            "round": run_meta.get("round"),
            "run_root_relative_to_workbench": run_meta.get("run_root_relative_to_workbench"),
        },
        "project": {
            "project_code": profile.get("project_code"),
            "project_name": profile.get("project_name"),
            "project_path": profile.get("project_path", {}),
            "git": profile.get("git", {}),
        },
        "scope": {
            "static_only": True,
            "dynamic_testing": False,
            "reverse_analysis": False,
            "read_only_project": True,
            "source": "audit-map + tool-plan",
        },
        "audit_map_summary": {
            "summary": audit_map.get("summary", {}),
            "extension_counts": audit_map.get("extension_counts", {}),
            "detected_stacks": audit_map.get("stacks", {}).get("detected_stacks", []),
            "detected_stack_ids": audit_map.get("stacks", {}).get("detected_stack_ids", []),
        },
        "tool_plan_summary": tool_plan.get("summary", {}) if tool_plan else {
            "status": "missing",
            "note": "TOOL_PLAN.json not found. Run tool-plan before evidence-pack for full context.",
        },
        "key_files": {
            "manifests": trim_bucket(files.get("manifests", {}), 80),
            "configs": trim_bucket(files.get("configs", {}), 100),
            "route_files": trim_bucket(files.get("route_files", {}), 120),
            "auth_files": trim_bucket(files.get("auth_files", {}), 120),
            "data_access_files": trim_bucket(files.get("data_access_files", {}), 120),
            "file_io_files": trim_bucket(files.get("file_io_files", {}), 120),
            "high_risk_modules": trim_bucket(files.get("high_risk_modules", {}), 180),
        },
        "signals": {
            "route_hits": trim_bucket(signals.get("route_hits", {}), 120),
            "frontend_api_hits": trim_bucket(signals.get("frontend_api_hits", {}), 120),
            "local_storage_hits": trim_bucket(signals.get("local_storage_hits", {}), 120),
        },
        "notes": [
            "Evidence pack contains deterministic facts and static signals only.",
            "It must not be treated as a vulnerability report.",
            "AI triage and later merge stages must not create final findings without candidate traceability.",
        ],
    }


def list_items(title: str, bucket: dict[str, Any]) -> list[str]:
    lines = [f"## {title}", "", f"Total: {bucket.get('count', 0)}", ""]
    items = bucket.get("items") or []
    if not items:
        lines.append("- None")
    for item in items[:40]:
        if isinstance(item, str):
            lines.append(f"- `{item}`")
        elif isinstance(item, dict):
            path = item.get("file_path") or "unknown"
            line = item.get("line")
            preview = item.get("preview") or ""
            if line:
                lines.append(f"- `{path}:{line}` {preview}".rstrip())
            else:
                lines.append(f"- `{path}` {preview}".rstrip())
    lines.append("")
    return lines


def render_md(pack: dict[str, Any]) -> str:
    lines = [
        "# EVIDENCE_PACK", "",
        "## Run", "",
        f"- Run ID: `{pack['run'].get('run_id')}`",
        f"- Project key: `{pack['run'].get('project_key')}`",
        f"- Audit mode: `{pack['run'].get('audit_mode')}`",
        "",
        "## Project", "",
        f"- Project code: `{pack['project'].get('project_code') or ''}`",
        f"- Project name: `{pack['project'].get('project_name') or ''}`",
        f"- Git branch: `{pack['project'].get('git', {}).get('branch') or ''}`",
        f"- Git commit: `{pack['project'].get('git', {}).get('commit') or ''}`",
        "",
        "## Detected stacks", "",
    ]
    stacks = pack.get("audit_map_summary", {}).get("detected_stack_ids") or []
    lines.append("- " + (", ".join(stacks) if stacks else "None"))
    lines.append("")
    for key, title in [
        ("manifests", "Manifests"),
        ("configs", "Configs"),
        ("route_files", "Route files"),
        ("auth_files", "Auth / permission files"),
        ("data_access_files", "Data access files"),
        ("file_io_files", "File upload / download files"),
        ("high_risk_modules", "High-risk business modules"),
    ]:
        lines.extend(list_items(title, pack["key_files"].get(key, {})))
    for key, title in [
        ("route_hits", "Route / API hits"),
        ("frontend_api_hits", "Frontend API call hits"),
        ("local_storage_hits", "Local storage hits"),
    ]:
        lines.extend(list_items(title, pack["signals"].get(key, {})))
    lines.extend(["## Notes", ""])
    for note in pack.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def print_summary(pack: dict[str, Any]) -> None:
    print("evidence-pack summary")
    print(f"  run_id: {pack['run'].get('run_id')}")
    print(f"  project: {pack['project'].get('project_name')}")
    print(f"  stacks: {', '.join(pack['audit_map_summary'].get('detected_stack_ids') or []) or '-'}")
    print(f"  tool_plan_status: {pack['tool_plan_summary'].get('status')}")
    print(f"  route_files: {pack['key_files']['route_files'].get('count')}")
    print(f"  auth_files: {pack['key_files']['auth_files'].get('count')}")
    print(f"  high_risk_modules: {pack['key_files']['high_risk_modules'].get('count')}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build evidence pack for one run.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    if not (run_root / "audit-map" / "AUDIT_MAP.json").is_file():
        print("[FAIL] AUDIT_MAP.json not found. Run make m2 first.", file=sys.stderr)
        return 2

    pack = build_evidence_pack(run_root)
    out = run_root / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "EVIDENCE_PACK.json", pack)
    (out / "EVIDENCE_PACK.md").write_text(render_md(pack), encoding="utf-8")

    if args.print_summary:
        print_summary(pack)
    else:
        print(f"evidence pack written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
