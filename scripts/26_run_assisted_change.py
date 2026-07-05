#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
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


def summarize(text: str, max_len: int = 4000) -> str:
    value = (text or "").strip()
    if len(value) > max_len:
        return value[:max_len] + "..."
    return value


def run_command(command: str, cwd: Path, timeout: int = 120) -> dict[str, Any]:
    started = dt.datetime.now()
    try:
        proc = subprocess.run(command, cwd=str(cwd), shell=True, text=True, capture_output=True, timeout=timeout)
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "exit_code": proc.returncode,
            "status": "success" if proc.returncode == 0 else "failed",
            "stdout": summarize(proc.stdout),
            "stderr": summarize(proc.stderr),
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "exit_code": None,
            "status": "timeout",
            "stdout": summarize(exc.stdout if isinstance(exc.stdout, str) else ""),
            "stderr": summarize(exc.stderr if isinstance(exc.stderr, str) else ""),
            "duration_ms": duration_ms,
        }
    except Exception as exc:
        duration_ms = int((dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "exit_code": None,
            "status": "failed",
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": duration_ms,
        }


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


def git_diff_stat(project_root: Path) -> str:
    result = run_command("git diff --stat -- .", project_root, timeout=20)
    return result.get("stdout") or ""


def is_git_repo(project_root: Path) -> bool:
    return run_command("git rev-parse --is-inside-work-tree", project_root, timeout=10).get("exit_code") == 0


def tool_available(env: dict[str, Any], tool_id: str) -> bool:
    item = (env.get("tools") or {}).get(tool_id) or {}
    return item.get("status") in {"available", "available_multiple"}


def get_check(preflight: dict[str, Any], check_id: str) -> dict[str, Any] | None:
    for item in preflight.get("checks", []):
        if item.get("check_id") == check_id:
            return item
    return None


def should_try_swag(preflight: dict[str, Any], facts: dict[str, Any]) -> tuple[bool, list[str]]:
    check = get_check(preflight, "go-package-load")
    if not check or check.get("status") != "blocked_requires_context":
        return False, ["go-package-load is not blocked."]
    reasons: list[str] = []
    hints = "\n".join(check.get("recovery_hints") or [])
    stderr = (check.get("command_result") or {}).get("stderr") or ""
    codegen = facts.get("manifests", {}).get("go", {}).get("codegen", {})
    if "swag" in hints.lower() or "swagger" in hints.lower():
        reasons.append("preflight recovery hint mentions Swagger/swag.")
    if re.search(r"/docs\s+is not in std|could not import .+/docs", stderr, re.I):
        reasons.append("go list stderr indicates missing docs package.")
    if codegen.get("swag_init_may_recover_go_list"):
        reasons.append("PROJECT_FACTS detected Go Swagger docs/codegen markers.")
    return bool(reasons), reasons or ["No Swagger/swag recovery signal found."]


def build_governance_candidate(run_root: Path, log: dict[str, Any]) -> dict[str, Any] | None:
    if log.get("status") == "no_action":
        return None
    preflight_reason = "; ".join(log.get("selection_reasons") or [])
    status = "REVIEW"
    return {
        "schema_version": "engineering-governance-candidates-0.1.0",
        "candidates": [
            {
                "candidate_id": "ENG-GOV-00001",
                "status": status,
                "source": "assisted_change_preflight",
                "risk_type": "build_engineering_governance",
                "risk_parent": "BUILD_ENGINEERING_GOVERNANCE",
                "risk_subtype": "GENERATED_CODE_MISSING",
                "title": "Go 项目缺少生成代码导致安全工具无法完整执行",
                "severity_hint": "P3",
                "confidence_hint": "high" if log.get("status") == "applied_and_verified" else "medium",
                "evidence": preflight_reason or log.get("reason") or "preflight blocked Go package loading.",
                "negative_evidence_required": [
                    "是否项目文档明确要求先执行生成命令",
                    "生成文件是否应纳入仓库或 CI 初始化流程",
                    "业务方是否能提供可复现的构建/审计初始化步骤",
                ],
                "notes": [
                    "该候选属于工程治理风险，不代表业务漏洞成立。",
                    "安全工具执行受阻会影响审计覆盖率，应推动业务方补充可复现构建上下文。",
                ],
                "assisted_change_log_ref": "evidence/assisted-change/ASSISTED_CHANGE_LOG.json",
            }
        ],
    }


def render_log_md(log: dict[str, Any]) -> str:
    lines = [
        "# ASSISTED_CHANGE_LOG", "",
        f"- Status: `{log.get('status')}`",
        f"- Action: `{log.get('action')}`",
        f"- Reason: {log.get('reason')}",
        f"- Project clean before: `{log.get('project_clean_before')}`", "",
    ]
    if log.get("selection_reasons"):
        lines.extend(["## Selection reasons", ""])
        for item in log["selection_reasons"]:
            lines.append(f"- {item}")
        lines.append("")
    if log.get("commands"):
        lines.extend(["## Commands", ""])
        for item in log["commands"]:
            lines.append(f"### `{item.get('command')}`")
            lines.append(f"- Status: `{item.get('status')}`")
            lines.append(f"- Exit code: `{item.get('exit_code')}`")
            stderr = (item.get("stderr") or "").strip()
            if stderr:
                lines.extend(["", "```text", stderr[:1200], "```", ""])
    changed = log.get("changed_entries_after") or []
    if changed:
        lines.extend(["## Changed entries after assisted change", ""])
        for entry in changed:
            lines.append(f"- `{entry.get('code')}` `{entry.get('path')}`")
        lines.append("")
    return "\n".join(lines)


def print_summary(log: dict[str, Any]) -> None:
    print("assisted-change summary")
    print(f"  status: {log.get('status')}")
    print(f"  action: {log.get('action')}")
    print(f"  reason: {log.get('reason')}")
    print(f"  changed_entries_after: {len(log.get('changed_entries_after') or [])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run authorized audit assisted changes.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--allow", default="none", choices=["none", "swag_init"])
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    preflight_path = run_root / "evidence" / "PREFLIGHT_RESULT.json"
    facts_path = run_root / "audit-map" / "PROJECT_FACTS.json"
    env_path = run_root / "evidence" / "STACK_ENV_CHECK_RESULT.json"
    profile_path = run_root / "meta" / "PROJECT_PROFILE.json"
    if not preflight_path.is_file() or not facts_path.is_file() or not profile_path.is_file():
        print("[FAIL] preflight, project facts, or project profile missing.", file=sys.stderr)
        return 2

    preflight = load_json(preflight_path)
    facts = load_json(facts_path)
    env = load_json(env_path) if env_path.is_file() else {"tools": {}}
    profile = load_json(profile_path)
    project_root = Path(profile["project_path"]["resolved"])

    should_apply, reasons = should_try_swag(preflight, facts)
    log: dict[str, Any] = {
        "schema_version": "assisted-change-log-0.1.0",
        "generated_at": now(),
        "run_root": str(run_root),
        "project_root": str(project_root),
        "action": "swag_init",
        "allow": args.allow,
        "selection_reasons": reasons,
        "commands": [],
        "reset_required": False,
    }

    if not should_apply:
        log.update({"status": "no_action", "reason": "No applicable assisted-change recipe."})
    elif args.allow != "swag_init":
        log.update({"status": "blocked_requires_authorization", "reason": "swag_init assisted change is not authorized."})
    elif not tool_available(env, "swag"):
        log.update({"status": "blocked_tool_missing", "reason": "swag tool is not available."})
    elif not is_git_repo(project_root):
        log.update({"status": "blocked_not_git_repo", "reason": "Project is not inside a Git work tree; reset safety cannot be guaranteed."})
    else:
        before = git_status(project_root)
        log["changed_entries_before"] = before
        log["project_clean_before"] = not before
        if before:
            log.update({"status": "blocked_dirty_worktree", "reason": "Project worktree is not clean; assisted change refused to avoid destroying user changes."})
        else:
            command = run_command("swag init", project_root, timeout=args.timeout)
            log["commands"].append(command)
            changed_after = git_status(project_root)
            log["changed_entries_after"] = changed_after
            log["diff_stat_after"] = git_diff_stat(project_root)
            verify = run_command("go list ./...", project_root, timeout=60)
            log["commands"].append(verify)
            log["reset_required"] = bool(changed_after)
            if command.get("exit_code") == 0 and verify.get("exit_code") == 0:
                log.update({"status": "applied_and_verified", "reason": "swag init applied and go list ./... succeeded."})
            elif command.get("exit_code") == 0:
                log.update({"status": "applied_but_not_verified", "reason": "swag init executed but go list ./... still failed."})
            else:
                log.update({"status": "failed", "reason": "swag init command failed."})

    out = run_root / "evidence" / "assisted-change"
    write_json(out / "ASSISTED_CHANGE_LOG.json", log)
    (out / "ASSISTED_CHANGE_LOG.md").write_text(render_log_md(log), encoding="utf-8")
    candidate_data = build_governance_candidate(run_root, log)
    if candidate_data:
        cand_dir = run_root / "candidates"
        write_json(cand_dir / "ENGINEERING_GOVERNANCE_CANDIDATES.json", candidate_data)
        md_lines = ["# ENGINEERING_GOVERNANCE_CANDIDATES", ""]
        for item in candidate_data["candidates"]:
            md_lines.append(f"- `{item['candidate_id']}` `{item['risk_subtype']}` {item['title']} — {item['evidence']}")
        md_lines.append("")
        (cand_dir / "ENGINEERING_GOVERNANCE_CANDIDATES.md").write_text("\n".join(md_lines), encoding="utf-8")
    if args.print_summary:
        print_summary(log)
    return 0 if log.get("status") not in {"failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
