#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


WORKBENCH_ROOT = Path(__file__).resolve().parents[1]
SMOKE_DIR = WORKBENCH_ROOT / "tmp" / "smoke"
ENV_CHECK_OUTPUT = SMOKE_DIR / "ENV_CHECK_RESULT.local.json"


GOVERNANCE_FILES = [
    "README.md",
    "CHANGE_POLICY.md",
    "CHANGELOG.md",
    "AGENTS.md",
]

ENV_FILES = [
    "env/TOOL_MATRIX.yaml",
    "env/INSTALL_GUIDE.md",
    "env/ENV_CHECK_SCHEMA.json",
    "env/ENV_CHECK_RESULT.example.json",
]

SCRIPT_FILES = [
    "scripts/00_env_check.py",
]

CORE_REQUIRED_TOOLS = [
    "git",
    "rg",
    "python3",
    "bash",
    "find",
    "grep",
    "sed",
    "awk",
]

RECOMMENDED_TOOLS = [
    "jq",
    "tar",
]


def ok(message: str) -> None:
    print(f"[OK] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")


def run_command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )


def require_files(paths: list[str], label: str) -> bool:
    missing = []
    for rel in paths:
        path = WORKBENCH_ROOT / rel
        if not path.is_file():
            missing.append(rel)

    if missing:
        fail(f"{label} missing: {', '.join(missing)}")
        return False

    ok(f"{label} exist")
    return True


def compile_python_script(path: Path) -> bool:
    result = run_command(
        [sys.executable, "-m", "py_compile", str(path)],
        cwd=WORKBENCH_ROOT,
    )

    if result.returncode != 0:
        fail(f"python compile failed: {path.relative_to(WORKBENCH_ROOT)}")
        if result.stdout.strip():
            print(result.stdout)
        if result.stderr.strip():
            print(result.stderr)
        return False

    ok(f"{path.relative_to(WORKBENCH_ROOT)} compiles")
    return True


def run_env_check() -> bool:
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)

    script = WORKBENCH_ROOT / "scripts" / "00_env_check.py"

    result = run_command(
        [
            sys.executable,
            str(script),
            "--output",
            str(ENV_CHECK_OUTPUT),
            "--print-summary",
        ],
        cwd=WORKBENCH_ROOT,
    )

    if result.stdout.strip():
        print(result.stdout)

    if result.returncode not in (0, 2):
        fail("env-check command failed unexpectedly")
        if result.stderr.strip():
            print(result.stderr)
        return False

    if result.returncode == 2:
        warn("env-check returned blocked status. Smoke check will inspect details.")

    if not ENV_CHECK_OUTPUT.is_file():
        fail(f"env-check output not found: {ENV_CHECK_OUTPUT}")
        return False

    ok("env-check command executed")
    return True


def load_env_result() -> dict[str, Any] | None:
    try:
        data = json.loads(ENV_CHECK_OUTPUT.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"cannot read env-check JSON: {exc}")
        return None

    if not isinstance(data, dict):
        fail("env-check result is not a JSON object")
        return None

    return data


def validate_env_structure(data: dict[str, Any]) -> bool:
    required_top_keys = [
        "schema_version",
        "checked_at",
        "workbench",
        "host",
        "summary",
        "tools",
    ]

    missing = [key for key in required_top_keys if key not in data]
    if missing:
        fail(f"env-check result missing top-level keys: {', '.join(missing)}")
        return False

    if data.get("schema_version") != "env-check-0.1.0":
        fail(f"unexpected schema_version: {data.get('schema_version')}")
        return False

    if not isinstance(data.get("tools"), dict):
        fail("env-check result field tools must be an object")
        return False

    if not isinstance(data.get("summary"), dict):
        fail("env-check result field summary must be an object")
        return False

    ok("env-check result structure is valid")
    return True


def validate_core_tools(data: dict[str, Any]) -> bool:
    tools = data.get("tools", {})
    summary = data.get("summary", {})

    missing_records = []
    unavailable_core = []

    for tool_id in CORE_REQUIRED_TOOLS:
        item = tools.get(tool_id)
        if not item:
            missing_records.append(tool_id)
            continue

        status = item.get("status")
        if status not in ("available", "available_multiple"):
            unavailable_core.append(f"{tool_id}:{status}")

    if missing_records:
        fail(f"core tool records missing from env-check result: {', '.join(missing_records)}")
        return False

    if unavailable_core:
        fail(f"required core tools unavailable: {', '.join(unavailable_core)}")
        print("")
        print("Install missing core tools before continuing.")
        print("See env/INSTALL_GUIDE.md.")
        return False

    if summary.get("core_ready") is not True:
        fail("summary.core_ready is not true")
        return False

    ok("core tools are ready")

    recommended_missing = []
    for tool_id in RECOMMENDED_TOOLS:
        item = tools.get(tool_id)
        if not item:
            continue
        if item.get("status") not in ("available", "available_multiple"):
            recommended_missing.append(tool_id)

    if recommended_missing:
        warn(f"recommended tools missing: {', '.join(recommended_missing)}")

    return True


def validate_path_redaction(data: dict[str, Any]) -> bool:
    tools = data.get("tools", {})
    warnings = []

    for tool_id, item in tools.items():
        resolved_path = item.get("resolved_path")
        resolved_path_redacted = item.get("resolved_path_redacted")

        if resolved_path and not resolved_path_redacted:
            warnings.append(tool_id)

    if warnings:
        warn(f"some tools have resolved_path but no resolved_path_redacted: {', '.join(warnings)}")
    else:
        ok("tool path redaction fields are present")

    return True


def print_artifact_summary() -> None:
    print("")
    print("Smoke artifacts:")
    print(f"  {ENV_CHECK_OUTPUT.relative_to(WORKBENCH_ROOT)}")


def main() -> int:
    all_ok = True

    print("AI Audit Workbench smoke check")
    print(f"Workbench root: {WORKBENCH_ROOT}")
    print("")

    all_ok = require_files(GOVERNANCE_FILES, "governance files") and all_ok
    all_ok = require_files(ENV_FILES, "env files") and all_ok
    all_ok = require_files(SCRIPT_FILES, "script files") and all_ok

    env_script = WORKBENCH_ROOT / "scripts" / "00_env_check.py"
    if env_script.is_file():
        all_ok = compile_python_script(env_script) and all_ok

    if all_ok:
        all_ok = run_env_check() and all_ok

    env_result = load_env_result() if ENV_CHECK_OUTPUT.is_file() else None
    if env_result is not None:
        all_ok = validate_env_structure(env_result) and all_ok
        all_ok = validate_core_tools(env_result) and all_ok
        all_ok = validate_path_redaction(env_result) and all_ok

    print_artifact_summary()

    print("")
    if all_ok:
        print("Smoke check passed.")
        return 0

    print("Smoke check failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())