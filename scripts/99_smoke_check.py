#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKBENCH_ROOT = Path(__file__).resolve().parents[1]
SMOKE_DIR = WORKBENCH_ROOT / "var" / "tmp" / "smoke"
ENV_CHECK_OUTPUT = SMOKE_DIR / "ENV_CHECK_RESULT.local.json"

REQUIRED_FILES = [
    "README.md", "CHANGE_POLICY.md", "CHANGELOG.md", "AGENTS.md",
    "conf/README.md", "docs/README.md", "local/README.md", "var/README.md",
    "spec/README.md", "spec/env/TOOL_MATRIX.yaml", "spec/env/TOOL_MATRIX_EXTENSIONS.yaml",
    "spec/rules/candidate-recipes.yaml", "spec/prompts/triage/FAST_STATIC.md",
    "spec/schemas/AI_TRIAGE_RESULT.schema.json", "scripts/00_env_check.py",
]
CORE_REQUIRED_TOOLS = ["git", "rg", "python3", "bash", "find", "grep", "sed", "awk"]


def ok(message: str) -> None:
    print(f"[OK] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(WORKBENCH_ROOT), text=True, capture_output=True)


def require_files() -> bool:
    missing = [rel for rel in REQUIRED_FILES if not (WORKBENCH_ROOT / rel).is_file()]
    if missing:
        fail("required files missing: " + ", ".join(missing))
        return False
    ok("required files exist")
    return True


def compile_env_script() -> bool:
    result = run_command([sys.executable, "-m", "py_compile", "scripts/00_env_check.py"])
    if result.returncode != 0:
        fail("scripts/00_env_check.py compile failed")
        print(result.stderr)
        return False
    ok("scripts/00_env_check.py compiles")
    return True


def run_env_check() -> bool:
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    result = run_command([
        sys.executable,
        "scripts/00_env_check.py",
        "--matrix",
        "spec/env/TOOL_MATRIX.yaml",
        "--output",
        str(ENV_CHECK_OUTPUT),
        "--print-summary",
    ])
    if result.stdout.strip():
        print(result.stdout)
    if result.returncode not in (0, 2):
        fail("env-check command failed unexpectedly")
        if result.stderr.strip():
            print(result.stderr)
        return False
    if not ENV_CHECK_OUTPUT.is_file():
        fail(f"env-check output not found: {ENV_CHECK_OUTPUT}")
        return False
    ok("env-check command executed")
    return True


def validate_env_result() -> bool:
    try:
        data = json.loads(ENV_CHECK_OUTPUT.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"cannot read env-check JSON: {exc}")
        return False
    for key in ["schema_version", "checked_at", "workbench", "host", "summary", "tools"]:
        if key not in data:
            fail(f"env-check result missing key: {key}")
            return False
    missing_records = [tool for tool in CORE_REQUIRED_TOOLS if tool not in data.get("tools", {})]
    if missing_records:
        fail("core tool records missing: " + ", ".join(missing_records))
        return False
    unavailable = [f"{tool}:{data['tools'][tool].get('status')}" for tool in CORE_REQUIRED_TOOLS if data["tools"][tool].get("status") not in {"available", "available_multiple"}]
    if unavailable:
        fail("required core tools unavailable: " + ", ".join(unavailable))
        return False
    ok("env-check result structure and core tools are valid")
    return True


def main() -> int:
    print("AI Audit Workbench smoke check")
    print(f"Workbench root: {WORKBENCH_ROOT}")
    print("")
    checks = [require_files(), compile_env_script(), run_env_check(), validate_env_result()]
    print("")
    print("Smoke artifacts:")
    print(f"  {ENV_CHECK_OUTPUT.relative_to(WORKBENCH_ROOT)}")
    print("")
    if all(checks):
        print("Smoke check passed.")
        return 0
    print("Smoke check failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
