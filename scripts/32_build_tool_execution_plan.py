#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AVAILABLE_STATUSES = {"available", "available_multiple"}


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


def command(tool_id: str, profile: str, output_dir: str) -> list[dict[str, Any]]:
    out = output_dir
    templates: dict[tuple[str, str], list[dict[str, Any]]] = {
        ("semgrep", "offline"): [
            {"command_id": "semgrep-offline-auto", "shell": f"semgrep --config auto --json -o {out}/semgrep.json .", "output_files": [f"{out}/semgrep.json"], "network_required": False},
        ],
        ("semgrep", "online"): [
            {"command_id": "semgrep-online-secrets", "shell": f"semgrep --config p/secrets --json -o {out}/semgrep-secrets.json .", "output_files": [f"{out}/semgrep-secrets.json"], "network_required": True},
            {"command_id": "semgrep-online-security-audit", "shell": f"semgrep --config p/security-audit --json -o {out}/semgrep-security-audit.json .", "output_files": [f"{out}/semgrep-security-audit.json"], "network_required": True},
        ],
        ("gitleaks", "offline"): [
            {"command_id": "gitleaks-detect", "shell": f"gitleaks detect --source . --report-format json --report-path {out}/gitleaks.json", "output_files": [f"{out}/gitleaks.json"], "network_required": False},
        ],
        ("trivy", "offline"): [
            {"command_id": "trivy-fs-offline", "shell": f"trivy fs --skip-db-update --format json -o {out}/trivy-fs.json .", "output_files": [f"{out}/trivy-fs.json"], "network_required": False},
        ],
        ("trivy", "online"): [
            {"command_id": "trivy-fs-online", "shell": f"trivy fs --format json -o {out}/trivy-fs.json .", "output_files": [f"{out}/trivy-fs.json"], "network_required": True},
        ],
        ("govulncheck", "online"): [
            {"command_id": "govulncheck", "shell": f"govulncheck -json ./... > {out}/govulncheck.json", "output_files": [f"{out}/govulncheck.json"], "network_required": True},
        ],
        ("golangci-lint", "offline"): [
            {"command_id": "golangci-lint", "shell": f"golangci-lint run --out-format json > {out}/golangci-lint.json", "output_files": [f"{out}/golangci-lint.json"], "network_required": False},
        ],
        ("npm", "online"): [
            {"command_id": "npm-audit", "shell": f"npm audit --json > {out}/npm-audit.json", "output_files": [f"{out}/npm-audit.json"], "network_required": True},
        ],
        ("pnpm", "online"): [
            {"command_id": "pnpm-audit", "shell": f"pnpm audit --json > {out}/pnpm-audit.json", "output_files": [f"{out}/pnpm-audit.json"], "network_required": True},
        ],
        ("yarn", "online"): [
            {"command_id": "yarn-audit", "shell": f"yarn npm audit --json > {out}/yarn-audit.json", "output_files": [f"{out}/yarn-audit.json"], "network_required": True},
        ],
        ("retire", "online"): [
            {"command_id": "retire-js", "shell": f"retire --outputformat json --outputpath {out}/retire.json", "output_files": [f"{out}/retire.json"], "network_required": True},
        ],
        ("dependency-check", "online"): [
            {"command_id": "dependency-check", "shell": f"dependency-check --scan . --format JSON --out {out}", "output_files": [f"{out}/dependency-check-report.json"], "network_required": True},
        ],
        ("mvn", "online"): [
            {"command_id": "mvn-dependency-check", "shell": f"mvn dependency-check:check -Dformat=JSON -DoutputDirectory={out}", "output_files": [f"{out}/dependency-check-report.json"], "network_required": True},
        ],
        ("gradle", "online"): [
            {"command_id": "gradle-dependency-check", "shell": "./gradlew dependencyCheckAnalyze || gradle dependencyCheckAnalyze", "output_files": [], "network_required": True},
        ],
    }
    return templates.get((tool_id, profile), [])


def tool_network_allowed(authorization: dict[str, Any]) -> bool:
    """Tool-network policy is intentionally separate from AI-agent network authorization.

    NETWORK_AUTHORIZATION is kept as an AI/agent authorization record. External security tools are allowed to use the network by default because their online profiles are part of the audit toolchain.
    A future personal config can add an explicit tool_network_policy=deny switch.
    """
    if "tool_network" in authorization:
        return bool(authorization.get("tool_network", {}).get("allowed", True))
    return True


def build_plan(run_root: Path) -> dict[str, Any]:
    run_meta = load_json(run_root / "meta" / "RUN_METADATA.json")
    project = load_json(run_root / "meta" / "PROJECT_PROFILE.json")
    authorization_path = run_root / "meta" / "AUTHORIZATION.json"
    authorization = load_json(authorization_path) if authorization_path.is_file() else {
        "authorization_mode": "deny",
        "network": {"allowed": False},
        "online_rules": {"allowed": False},
    }
    tool_plan = load_json(run_root / "evidence" / "TOOL_PLAN.json")

    project_root = Path(project["project_path"]["resolved"])
    base_output = run_root / "evidence" / "tool-outputs"
    online_allowed = tool_network_allowed(authorization)

    items: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for tool in tool_plan.get("tools", []):
        if not tool.get("selected"):
            continue
        tool_id = tool["tool_id"]
        if tool.get("plan_status") != "available" or tool.get("env_status") not in AVAILABLE_STATUSES:
            skipped.append({
                "tool_id": tool_id,
                "reason": "tool_not_available",
                "plan_status": tool.get("plan_status"),
                "env_status": tool.get("env_status"),
            })
            continue
        for profile in ["offline", "online"]:
            out_dir = (base_output / tool_id / profile).resolve()
            output_dir_rel = rel(out_dir)
            commands = command(tool_id, profile, str(out_dir))
            if not commands:
                continue
            if profile == "online" and not online_allowed:
                items.append({
                    "tool_id": tool_id,
                    "profile": profile,
                    "status": "skipped_by_policy",
                    "reason": "online_profile_requires_tool_network_policy",
                    "network_required": True,
                    "authorization_status": authorization.get("authorization_mode", "deny"),
                    "tool_network_policy": "deny",
                    "commands": commands,
                    "cwd": str(project_root),
                    "output_dir": output_dir_rel,
                    "output_dir_abs": str(out_dir),
                })
                continue
            items.append({
                "tool_id": tool_id,
                "profile": profile,
                "status": "planned",
                "reason": "ready",
                "network_required": profile == "online",
                "authorization_status": authorization.get("authorization_mode", "deny"),
                "tool_network_policy": "allow" if online_allowed else "deny",
                "commands": commands,
                "cwd": str(project_root),
                "output_dir": output_dir_rel,
                "output_dir_abs": str(out_dir),
                "result_parser": f"{tool_id}:{profile}",
                "candidate_mapping": "tool-output-normalization",
            })

    planned = [x for x in items if x["status"] == "planned"]
    skipped_by_policy = [x for x in items if x["status"] == "skipped_by_policy"]
    return {
        "schema_version": "tool-execution-plan-0.2.0",
        "run": {
            "run_id": run_meta.get("run_id"),
            "project_key": run_meta.get("project_key"),
            "audit_mode": run_meta.get("audit_mode"),
        },
        "project": {
            "project_path": str(project_root),
            "project_name": project.get("project_name"),
            "git": project.get("git", {}),
        },
        "authorization": {
            "agent_network_authorization_mode": authorization.get("authorization_mode", "deny"),
            "tool_online_allowed": online_allowed,
            "authorization_ref": rel(authorization_path),
            "note": "Agent network authorization and external-tool network usage are separate concerns. Tools are allowed by default unless an explicit tool network policy denies them.",
        },
        "policy": {
            "default_profiles": ["offline", "online"],
            "missing_tool_behavior": "skip_and_record",
            "online_failure_behavior": "degrade_not_block",
            "offline_failure_behavior": "degrade_not_block",
            "write_project_source": False,
        },
        "summary": {
            "status": "planned" if planned else "no_executable_tools",
            "planned_items": len(planned),
            "skipped_by_policy_items": len(skipped_by_policy),
            "skipped_missing_tools": len(skipped),
        },
        "items": items,
        "skipped_tools": skipped,
    }


def render_md(plan: dict[str, Any]) -> str:
    lines = [
        "# TOOL_EXECUTION_PLAN", "",
        f"- Status: `{plan['summary']['status']}`",
        f"- Planned items: {plan['summary']['planned_items']}",
        f"- Skipped by policy: {plan['summary']['skipped_by_policy_items']}",
        f"- Skipped missing tools: {plan['summary']['skipped_missing_tools']}",
        f"- Tool online allowed: {plan['authorization']['tool_online_allowed']}", "",
        "## Items", "",
        "| Tool | Profile | Status | Network | Commands |",
        "|---|---|---|---:|---:|",
    ]
    for item in plan.get("items", []):
        lines.append(f"| `{item['tool_id']}` | {item['profile']} | {item['status']} | {item['network_required']} | {len(item.get('commands') or [])} |")
    if plan.get("skipped_tools"):
        lines.extend(["", "## Skipped missing tools", ""])
        for item in plan["skipped_tools"]:
            lines.append(f"- `{item['tool_id']}`: {item['reason']} ({item.get('env_status')})")
    return "\n".join(lines) + "\n"


def print_summary(plan: dict[str, Any]) -> None:
    s = plan["summary"]
    print("tool-execution-plan summary")
    print(f"  status: {s['status']}")
    print(f"  planned_items: {s['planned_items']}")
    print(f"  skipped_by_policy_items: {s['skipped_by_policy_items']}")
    print(f"  skipped_missing_tools: {s['skipped_missing_tools']}")
    print(f"  tool_online_allowed: {plan['authorization']['tool_online_allowed']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build offline/online tool execution plan.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not (run_root / "evidence" / "TOOL_PLAN.json").is_file():
        print("[FAIL] TOOL_PLAN.json not found. Run tool-plan first.", file=sys.stderr)
        return 2

    plan = build_plan(run_root)
    out = run_root / "evidence" / "tool-execution"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "TOOL_EXECUTION_PLAN.json", plan)
    (out / "TOOL_EXECUTION_PLAN.md").write_text(render_md(plan), encoding="utf-8")
    if args.print_summary:
        print_summary(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
