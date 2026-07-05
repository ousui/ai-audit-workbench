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


def run_command(command: str, cwd: Path, timeout: int) -> dict[str, Any]:
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


def tool_available(env: dict[str, Any], tool_id: str) -> bool:
    item = (env.get("tools") or {}).get(tool_id) or {}
    return item.get("status") in {"available", "available_multiple"}


def go_recovery_hints(stderr: str, facts: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    go_codegen = facts.get("manifests", {}).get("go", {}).get("codegen", {})
    text = stderr or ""
    if go_codegen.get("has_docs_import") or re.search(r"package\s+.+/docs\s+is not in std|could not import .+/docs", text, re.I):
        hints.append("可能缺少 Swagger/swag 生成的 docs 包；后续 assisted-change 可在授权后尝试 swag init。")
    if "build constraints exclude all Go files" in text:
        hints.append("可能需要 build tags；需要人工或 AI 根据项目文档确认构建参数。")
    if "no required module provides package" in text or "cannot find module providing package" in text:
        hints.append("可能存在私有依赖、GOPRIVATE/GOPROXY 配置或依赖未下载问题。")
    if not hints:
        hints.append("需要根据 go.mod、main.go、README、Makefile 和 stderr 分析构建上下文。")
    return hints


def check_go_package_load(project_root: Path, facts: dict[str, Any], env: dict[str, Any], timeout: int) -> dict[str, Any]:
    go_facts = facts.get("manifests", {}).get("go", {})
    if not go_facts.get("has_go_mod"):
        return {"check_id": "go-package-load", "subject": "go", "status": "not_applicable_by_manifest", "reason": "go.mod not found", "required_for_tools": ["govulncheck", "golangci-lint"]}
    if not tool_available(env, "go"):
        return {"check_id": "go-package-load", "subject": "go", "status": "blocked_tool_missing", "reason": "go tool is not available", "required_for_tools": ["govulncheck", "golangci-lint"]}
    result = run_command("go list ./...", project_root, timeout)
    status = "completed" if result["exit_code"] == 0 else "blocked_requires_context"
    return {
        "check_id": "go-package-load",
        "subject": "go",
        "status": status,
        "reason": "go package graph loaded" if status == "completed" else "go package graph failed to load",
        "required_for_tools": ["govulncheck", "golangci-lint"],
        "command_result": result,
        "recovery_hints": [] if status == "completed" else go_recovery_hints(result.get("stderr") or "", facts),
    }


def manifest_check(check_id: str, subject: str, applicable: bool, reason_ok: str, reason_no: str, required_for: list[str], evidence: list[str]) -> dict[str, Any]:
    return {"check_id": check_id, "subject": subject, "status": "completed" if applicable else "not_applicable_by_manifest", "reason": reason_ok if applicable else reason_no, "required_for_tools": required_for, "evidence": evidence[:20]}


def build_preflight(run_root: Path, timeout: int) -> dict[str, Any]:
    run_meta = load_json(run_root / "meta" / "RUN_METADATA.json")
    profile = load_json(run_root / "meta" / "PROJECT_PROFILE.json")
    facts_path = run_root / "audit-map" / "PROJECT_FACTS.json"
    facts = load_json(facts_path)
    env_path = run_root / "evidence" / "STACK_ENV_CHECK_RESULT.json"
    env = load_json(env_path) if env_path.is_file() else {"tools": {}}
    project_root = Path(profile["project_path"]["resolved"])

    java = facts.get("manifests", {}).get("java", {})
    node = facts.get("manifests", {}).get("node", {})
    checks = [
        check_go_package_load(project_root, facts, env, timeout),
        manifest_check("maven-manifest", "java", bool(java.get("has_pom")), "pom.xml found", "pom.xml not found", ["mvn"], java.get("pom_files") or []),
        manifest_check("gradle-manifest", "java", bool(java.get("has_gradle") or java.get("has_gradle_wrapper")), "Gradle manifest or wrapper found", "Gradle manifest/wrapper not found", ["gradle"], (java.get("gradle_files") or []) + (java.get("gradle_wrapper_files") or [])),
        manifest_check("java-dependency-manifest", "java", bool(java.get("has_pom") or java.get("has_gradle") or java.get("has_gradle_wrapper")), "Java dependency manifest found", "supported Java dependency manifest not found", ["dependency-check"], (java.get("pom_files") or []) + (java.get("gradle_files") or []) + (java.get("gradle_wrapper_files") or [])),
        manifest_check("npm-manifest", "node", bool(node.get("has_package_json")), "package.json found", "package.json not found", ["npm", "retire"], node.get("package_json_files") or []),
        manifest_check("pnpm-lock", "node", bool(node.get("has_pnpm_lock")), "pnpm-lock.yaml found", "pnpm-lock.yaml not found", ["pnpm"], node.get("pnpm_lock_files") or []),
        manifest_check("yarn-lock", "node", bool(node.get("has_yarn_lock")), "yarn.lock found", "yarn.lock not found", ["yarn"], node.get("yarn_lock_files") or []),
    ]
    blocked = [x for x in checks if x.get("status") in {"blocked_requires_context", "blocked_tool_missing"}]
    not_app = [x for x in checks if x.get("status") == "not_applicable_by_manifest"]
    return {
        "schema_version": "preflight-result-0.1.1",
        "generated_at": now(),
        "run": {"run_id": run_meta.get("run_id"), "project_key": run_meta.get("project_key"), "audit_mode": run_meta.get("audit_mode")},
        "project": {"project_name": profile.get("project_name"), "project_path": str(project_root), "git": profile.get("git", {})},
        "inputs": {"project_facts_ref": "audit-map/PROJECT_FACTS.json", "stack_env_check_ref": "evidence/STACK_ENV_CHECK_RESULT.json" if env_path.is_file() else None},
        "summary": {"status": "blocked_requires_context" if blocked else "completed", "checks": len(checks), "blocked_checks": len(blocked), "not_applicable_checks": len(not_app)},
        "checks": checks,
    }


def render_md(result: dict[str, Any]) -> str:
    lines = [
        "# PREFLIGHT_RESULT", "",
        f"- Status: `{result['summary']['status']}`",
        f"- Checks: {result['summary']['checks']}",
        f"- Blocked checks: {result['summary']['blocked_checks']}",
        f"- Not applicable checks: {result['summary']['not_applicable_checks']}", "",
        "## Checks", "",
        "| Check | Status | Reason | Tools |",
        "|---|---|---|---|",
    ]
    hint_blocks: list[tuple[str, list[str]]] = []
    command_blocks: list[tuple[str, dict[str, Any]]] = []
    for item in result.get("checks", []):
        tools = ", ".join(item.get("required_for_tools") or []) or "-"
        lines.append(f"| `{item['check_id']}` | `{item['status']}` | {item.get('reason')} | `{tools}` |")
        if item.get("recovery_hints"):
            hint_blocks.append((item["check_id"], item["recovery_hints"]))
        if item.get("status") in {"blocked_requires_context", "blocked_tool_missing"} and item.get("command_result"):
            command_blocks.append((item["check_id"], item["command_result"]))
    lines.append("")
    if hint_blocks:
        lines.extend(["## Recovery hints", ""])
        for check_id, hints in hint_blocks:
            lines.append(f"### `{check_id}`")
            for hint in hints:
                lines.append(f"- {hint}")
            lines.append("")
    if command_blocks:
        lines.extend(["## Blocked command details", ""])
        for check_id, result_item in command_blocks:
            lines.append(f"### `{check_id}`")
            lines.append(f"- Command: `{result_item.get('command')}`")
            lines.append(f"- Exit code: `{result_item.get('exit_code')}`")
            stderr = (result_item.get("stderr") or "").strip()
            if stderr:
                lines.extend(["", "```text", stderr[:1200], "```", ""])
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    s = result["summary"]
    print("preflight summary")
    print(f"  status: {s['status']}")
    print(f"  checks: {s['checks']}")
    print(f"  blocked_checks: {s['blocked_checks']}")
    print(f"  not_applicable_checks: {s['not_applicable_checks']}")
    for item in result.get("checks", []):
        if item.get("status") in {"blocked_requires_context", "blocked_tool_missing"}:
            print(f"  blocked: {item['check_id']} - {item.get('reason')}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run project preflight checks for manifest-aware tool execution.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not (run_root / "audit-map" / "PROJECT_FACTS.json").is_file():
        print("[FAIL] PROJECT_FACTS.json not found. Run audit-map first.", file=sys.stderr)
        return 2
    result = build_preflight(run_root, args.timeout)
    out = run_root / "evidence"
    write_json(out / "PREFLIGHT_RESULT.json", result)
    (out / "PREFLIGHT_RESULT.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
