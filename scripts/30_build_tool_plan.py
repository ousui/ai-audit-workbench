#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_RESULT = "env/ENV_CHECK_RESULT.local.json"
DEFAULT_TOOL_MATRIX = "env/TOOL_MATRIX.yaml"

FALLBACK_TOOLS: dict[str, dict[str, Any]] = {
    "git": {"display_name": "Git", "category": "core", "required_level": "required_for_workbench", "stacks": ["all"], "stages": ["run-init", "audit-map"]},
    "rg": {"display_name": "ripgrep", "category": "core", "required_level": "required_for_workbench", "stacks": ["all"], "stages": ["audit-map", "candidate-build"]},
    "python3": {"display_name": "Python 3", "category": "core", "required_level": "required_for_workbench", "stacks": ["all"], "stages": ["tool-plan", "merge", "delivery", "validate"]},
    "bash": {"display_name": "Bash", "category": "core", "required_level": "required_for_workbench", "stacks": ["all"], "stages": ["script-runner"]},
    "find": {"display_name": "find", "category": "core", "required_level": "required_for_workbench", "stacks": ["all"], "stages": ["audit-map"]},
    "grep": {"display_name": "grep", "category": "core", "required_level": "required_for_workbench", "stacks": ["all"], "stages": ["evidence-collection"]},
    "sed": {"display_name": "sed", "category": "core", "required_level": "required_for_workbench", "stacks": ["all"], "stages": ["evidence-collection"]},
    "awk": {"display_name": "awk", "category": "core", "required_level": "required_for_workbench", "stacks": ["all"], "stages": ["evidence-collection"]},
    "jq": {"display_name": "jq", "category": "core", "required_level": "recommended_for_static", "stacks": ["all"], "stages": ["validation"]},
    "tar": {"display_name": "tar", "category": "core", "required_level": "recommended_for_static", "stacks": ["all"], "stages": ["archive", "delivery"]},
}

REQUIRED_LEVEL_ORDER = {
    "required_for_workbench": 0,
    "required_for_stack": 1,
    "recommended_for_static": 2,
    "optional": 3,
    "future_stage": 4,
}

AVAILABLE_STATUSES = {"available", "available_multiple"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_from_run(run_meta: dict[str, Any]) -> str | None:
    return run_meta.get("created_at")


def parse_inline_list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"\'') for item in inner.split(",") if item.strip()]
    return []


def parse_tool_matrix_without_yaml(path: Path) -> tuple[str, dict[str, dict[str, Any]], list[str]]:
    notes = ["PyYAML is unavailable; using lightweight YAML parser for TOOL_MATRIX.yaml."]
    if not path.is_file():
        notes.append("TOOL_MATRIX.yaml not found; using fallback core tools.")
        return "tool-matrix-0.1.0", FALLBACK_TOOLS, notes

    text = path.read_text(encoding="utf-8", errors="ignore")
    version_match = re.search(r"^schema_version:\s*[\"']?([^\"'\n]+)[\"']?\s*$", text, re.M)
    version = version_match.group(1).strip() if version_match else "tool-matrix-0.1.0"

    lines = text.splitlines()
    in_tools = False
    current: str | None = None
    tools: dict[str, dict[str, Any]] = {}
    list_key: str | None = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "tools:":
            in_tools = True
            current = None
            continue
        if not in_tools:
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent == 2 and stripped.endswith(":"):
            current = stripped[:-1].strip()
            tools[current] = {}
            list_key = None
            continue
        if current is None:
            continue
        if indent == 4 and ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            list_key = None
            if not value:
                if key in {"stages", "stacks"}:
                    tools[current][key] = []
                    list_key = key
                continue
            tools[current][key] = value.strip('"\'')
            if key in {"stages", "stacks"} and value.startswith("["):
                tools[current][key] = parse_inline_list(value)
            continue
        if indent == 6 and list_key and stripped.startswith("-"):
            item = stripped[1:].strip().strip('"\'')
            tools[current].setdefault(list_key, []).append(item)

    if not tools:
        notes.append("No tools parsed from TOOL_MATRIX.yaml; using fallback core tools.")
        return version, FALLBACK_TOOLS, notes

    for tool_id, spec in tools.items():
        spec.setdefault("display_name", tool_id)
        spec.setdefault("category", "other")
        spec.setdefault("required_level", "optional")
        spec.setdefault("stacks", ["all"])
        spec.setdefault("stages", [])

    return version, tools, notes


def load_tool_matrix(path: Path) -> tuple[str, dict[str, dict[str, Any]], list[str]]:
    try:
        import yaml  # type: ignore
    except Exception:
        return parse_tool_matrix_without_yaml(path)

    if not path.is_file():
        return "tool-matrix-0.1.0", FALLBACK_TOOLS, ["TOOL_MATRIX.yaml not found; using fallback core tools."]

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    version = str(data.get("schema_version") or "tool-matrix-0.1.0")
    raw_tools = data.get("tools") or {}
    tools: dict[str, dict[str, Any]] = {}
    for tool_id, raw in raw_tools.items():
        tools[str(tool_id)] = {
            "display_name": raw.get("display_name") or str(tool_id),
            "category": raw.get("category") or "other",
            "required_level": raw.get("required_level") or "optional",
            "stacks": raw.get("stacks") or ["all"],
            "stages": raw.get("stages") or [],
            "missing_policy": raw.get("missing_policy"),
            "purpose": raw.get("purpose") or [],
        }
    return version, tools or FALLBACK_TOOLS, []


def relevant_to_stack(tool: dict[str, Any], detected_stacks: list[str]) -> bool:
    stacks = tool.get("stacks") or ["all"]
    if "all" in stacks:
        return True
    return bool(set(stacks) & set(detected_stacks))


def should_select_tool(tool: dict[str, Any], detected_stacks: list[str], audit_mode: str) -> tuple[bool, str]:
    required_level = tool.get("required_level") or "optional"
    category = tool.get("category") or "other"

    if category in {"dast", "reverse"} and audit_mode in {"FAST_STATIC", "STANDARD_STATIC", "DEEP_STATIC_EXPLORE"}:
        return False, "future_stage_not_required_for_current_mode"
    if required_level == "future_stage":
        return False, "future_stage_not_required_for_current_mode"
    if not relevant_to_stack(tool, detected_stacks):
        return False, "not_required_for_detected_stack"
    return True, "selected"


def status_from_env(tool_id: str, env_result: dict[str, Any] | None) -> dict[str, Any]:
    if not env_result:
        return {"status": "unknown", "version": None, "resolved_command": None, "resolved_path_redacted": None}
    return env_result.get("tools", {}).get(tool_id) or {"status": "unknown", "version": None, "resolved_command": None, "resolved_path_redacted": None}


def decision_for(tool: dict[str, Any], env_item: dict[str, Any], selected: bool, reason: str) -> tuple[str, bool, str]:
    required_level = tool.get("required_level") or "optional"
    status = env_item.get("status") or "unknown"

    if not selected:
        return "skipped", False, reason
    if status in AVAILABLE_STATUSES:
        return "available", False, "tool_available"
    if required_level == "required_for_workbench":
        return "blocked", True, "required_workbench_tool_missing"
    if required_level == "required_for_stack":
        return "blocked", True, "required_stack_tool_missing"
    if required_level == "recommended_for_static":
        return "missing", False, "recommended_tool_missing"
    return "missing", False, "optional_tool_missing"


def build_tool_plan(run_root: Path, env_path: Path, matrix_path: Path) -> dict[str, Any]:
    run_meta = load_json(run_root / "meta" / "RUN_METADATA.json")
    audit_map = load_json(run_root / "audit-map" / "AUDIT_MAP.json")
    env_result = load_json(env_path) if env_path.is_file() else None
    matrix_version, tools, matrix_notes = load_tool_matrix(matrix_path)

    detected_stacks = audit_map.get("stacks", {}).get("detected_stack_ids") or []
    audit_mode = str(run_meta.get("audit_mode") or "FAST_STATIC")

    plan_items = []
    blocked_items = []
    missing_items = []
    available_items = []
    skipped_items = []

    for tool_id, tool in sorted(tools.items(), key=lambda item: (REQUIRED_LEVEL_ORDER.get(item[1].get("required_level", "optional"), 9), item[0])):
        selected, selection_reason = should_select_tool(tool, detected_stacks, audit_mode)
        env_item = status_from_env(tool_id, env_result)
        plan_status, blocking, decision_reason = decision_for(tool, env_item, selected, selection_reason)
        item = {
            "tool_id": tool_id,
            "display_name": tool.get("display_name") or tool_id,
            "category": tool.get("category") or "other",
            "required_level": tool.get("required_level") or "optional",
            "stacks": tool.get("stacks") or ["all"],
            "stages": tool.get("stages") or [],
            "selected": selected,
            "plan_status": plan_status,
            "blocking": blocking,
            "selection_reason": selection_reason,
            "decision_reason": decision_reason,
            "env_status": env_item.get("status"),
            "version": env_item.get("version"),
            "resolved_command": env_item.get("resolved_command"),
            "resolved_path_redacted": env_item.get("resolved_path_redacted"),
            "missing_impact": env_item.get("missing_impact") or tool.get("missing_impact"),
        }
        plan_items.append(item)
        if plan_status == "available":
            available_items.append(tool_id)
        elif plan_status == "blocked":
            blocked_items.append(tool_id)
        elif plan_status == "missing":
            missing_items.append(tool_id)
        elif plan_status == "skipped":
            skipped_items.append(tool_id)

    if blocked_items:
        plan_status = "blocked"
    elif missing_items:
        plan_status = "degraded"
    else:
        plan_status = "usable"

    return {
        "schema_version": "tool-plan-0.1.0",
        "generated_from_run_created_at": now_from_run(run_meta),
        "run": {
            "run_id": run_meta.get("run_id"),
            "project_key": run_meta.get("project_key"),
            "audit_mode": audit_mode,
            "round": run_meta.get("round"),
            "run_root_relative_to_workbench": run_meta.get("run_root_relative_to_workbench"),
        },
        "inputs": {
            "tool_matrix_path": str(matrix_path),
            "tool_matrix_version": matrix_version,
            "env_check_path": str(env_path),
            "env_check_available": env_result is not None,
            "audit_map_path": str(run_root / "audit-map" / "AUDIT_MAP.json"),
        },
        "project_stacks": detected_stacks,
        "summary": {
            "status": plan_status,
            "selected_tools": len([x for x in plan_items if x["selected"]]),
            "available_tools": len(available_items),
            "missing_tools": len(missing_items),
            "blocked_tools": len(blocked_items),
            "skipped_tools": len(skipped_items),
            "blocked_tool_ids": blocked_items,
            "missing_tool_ids": missing_items,
            "available_tool_ids": available_items,
        },
        "tools": plan_items,
        "notes": matrix_notes + (["env-check result not found; tool availability is unknown."] if env_result is None else []),
    }


def render_md(plan: dict[str, Any]) -> str:
    lines = [
        "# TOOL_PLAN", "",
        "## Summary", "",
        f"- Status: `{plan['summary']['status']}`",
        f"- Audit mode: `{plan['run']['audit_mode']}`",
        f"- Project stacks: `{', '.join(plan.get('project_stacks') or []) or '-'}`",
        f"- Selected tools: {plan['summary']['selected_tools']}",
        f"- Available tools: {plan['summary']['available_tools']}",
        f"- Missing tools: {plan['summary']['missing_tools']}",
        f"- Blocked tools: {plan['summary']['blocked_tools']}",
        "",
        "## Tools", "",
        "| Tool | Level | Status | Env | Reason |",
        "|---|---|---|---|---|",
    ]
    for item in plan["tools"]:
        lines.append(
            f"| `{item['tool_id']}` | {item['required_level']} | {item['plan_status']} | {item.get('env_status') or '-'} | {item['decision_reason']} |"
        )
    lines.append("")
    if plan.get("notes"):
        lines.extend(["## Notes", ""])
        for note in plan["notes"]:
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines)


def print_summary(plan: dict[str, Any]) -> None:
    summary = plan["summary"]
    print("tool-plan summary")
    print(f"  run_id: {plan['run'].get('run_id')}")
    print(f"  status: {summary['status']}")
    print(f"  stacks: {', '.join(plan.get('project_stacks') or []) or '-'}")
    print(f"  selected_tools: {summary['selected_tools']}")
    print(f"  available_tools: {summary['available_tools']}")
    print(f"  missing_tools: {summary['missing_tools']}")
    print(f"  blocked_tools: {summary['blocked_tools']}")
    if summary.get("blocked_tool_ids"):
        print(f"  blocked_tool_ids: {', '.join(summary['blocked_tool_ids'])}")
    if summary.get("missing_tool_ids"):
        print(f"  missing_tool_ids: {', '.join(summary['missing_tool_ids'])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build per-run tool plan.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--env-result", default=DEFAULT_ENV_RESULT)
    parser.add_argument("--tool-matrix", default=DEFAULT_TOOL_MATRIX)
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

    env_path = Path(args.env_result)
    if not env_path.is_absolute():
        env_path = (ROOT / env_path).resolve()
    matrix_path = Path(args.tool_matrix)
    if not matrix_path.is_absolute():
        matrix_path = (ROOT / matrix_path).resolve()

    plan = build_tool_plan(run_root=run_root, env_path=env_path, matrix_path=matrix_path)
    out_dir = run_root / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "TOOL_PLAN.json", plan)
    (out_dir / "TOOL_PLAN.md").write_text(render_md(plan), encoding="utf-8")

    if args.print_summary:
        print_summary(plan)
    else:
        print(f"tool plan written to {out_dir}")

    return 2 if plan["summary"]["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
