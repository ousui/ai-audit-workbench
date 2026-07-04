#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "env-check-0.1.0"
DEFAULT_MATRIX_PATH = "env/TOOL_MATRIX.yaml"
DEFAULT_OUTPUT_PATH = "env/ENV_CHECK_RESULT.local.json"


FALLBACK_CORE_TOOLS: dict[str, dict[str, Any]] = {
    "git": {
        "display_name": "Git",
        "category": "core",
        "required_level": "required_for_workbench",
        "missing_policy": "block_workbench",
        "commands": ["git --version"],
        "locate_commands": ["git"],
        "missing_impact": "Cannot confirm repository state, branch, commit, or audit baseline.",
        "install_ref": "env/INSTALL_GUIDE.md",
        "permissions": {
            "read_project": True,
            "write_project": False,
            "write_run_output": False,
            "network": False
        }
    },
    "rg": {
        "display_name": "ripgrep",
        "category": "core",
        "required_level": "required_for_workbench",
        "missing_policy": "block_workbench",
        "commands": ["rg --version"],
        "locate_commands": ["rg"],
        "missing_impact": "Cannot efficiently build audit map or candidate pool.",
        "install_ref": "env/INSTALL_GUIDE.md",
        "permissions": {
            "read_project": True,
            "write_project": False,
            "write_run_output": True,
            "network": False
        }
    },
    "python3": {
        "display_name": "Python 3",
        "category": "core",
        "required_level": "required_for_workbench",
        "missing_policy": "block_workbench",
        "commands": ["python3 --version", "python --version"],
        "locate_commands": ["python3", "python"],
        "missing_impact": "Cannot run workbench automation scripts.",
        "install_ref": "env/INSTALL_GUIDE.md",
        "permissions": {
            "read_project": True,
            "write_project": False,
            "write_run_output": True,
            "write_cache": True,
            "network": False
        }
    },
    "bash": {
        "display_name": "Bash",
        "category": "core",
        "required_level": "required_for_workbench",
        "missing_policy": "block_workbench",
        "commands": ["bash --version"],
        "locate_commands": ["bash"],
        "missing_impact": "Some helper scripts may not run.",
        "install_ref": "env/INSTALL_GUIDE.md",
        "permissions": {
            "read_project": True,
            "write_project": False,
            "write_run_output": True,
            "network": False
        }
    },
    "find": {
        "display_name": "find",
        "category": "core",
        "required_level": "required_for_workbench",
        "missing_policy": "block_workbench",
        "commands": ["find --version"],
        "locate_commands": ["find"],
        "missing_impact": "Cannot reliably enumerate source files.",
        "install_ref": "env/INSTALL_GUIDE.md",
        "permissions": {
            "read_project": True,
            "write_project": False,
            "write_run_output": True,
            "network": False
        }
    },
    "grep": {
        "display_name": "grep",
        "category": "core",
        "required_level": "required_for_workbench",
        "missing_policy": "block_workbench",
        "commands": ["grep --version"],
        "locate_commands": ["grep"],
        "missing_impact": "Fallback text scanning is unavailable.",
        "install_ref": "env/INSTALL_GUIDE.md",
        "permissions": {
            "read_project": True,
            "write_project": False,
            "write_run_output": True,
            "network": False
        }
    },
    "sed": {
        "display_name": "sed",
        "category": "core",
        "required_level": "required_for_workbench",
        "missing_policy": "block_workbench",
        "commands": ["sed --version"],
        "locate_commands": ["sed"],
        "missing_impact": "Some shell-based normalization steps may fail.",
        "install_ref": "env/INSTALL_GUIDE.md",
        "permissions": {
            "read_project": True,
            "write_project": False,
            "write_run_output": True,
            "network": False
        }
    },
    "awk": {
        "display_name": "awk",
        "category": "core",
        "required_level": "required_for_workbench",
        "missing_policy": "block_workbench",
        "commands": ["awk --version"],
        "locate_commands": ["awk"],
        "missing_impact": "Some shell-based statistics or normalization steps may fail.",
        "install_ref": "env/INSTALL_GUIDE.md",
        "permissions": {
            "read_project": True,
            "write_project": False,
            "write_run_output": True,
            "network": False
        }
    },
    "jq": {
        "display_name": "jq",
        "category": "core",
        "required_level": "recommended_for_static",
        "missing_policy": "record_missing_not_blocking",
        "commands": ["jq --version"],
        "locate_commands": ["jq"],
        "missing_impact": "JSON outputs can still be processed by Python, but manual inspection is less convenient.",
        "install_ref": "env/INSTALL_GUIDE.md",
        "permissions": {
            "read_project": False,
            "write_project": False,
            "write_run_output": True,
            "network": False
        }
    },
    "tar": {
        "display_name": "tar",
        "category": "core",
        "required_level": "recommended_for_static",
        "missing_policy": "record_missing_not_blocking",
        "commands": ["tar --version"],
        "locate_commands": ["tar"],
        "missing_impact": "Artifact packaging may be unavailable.",
        "install_ref": "env/INSTALL_GUIDE.md",
        "permissions": {
            "read_project": False,
            "write_project": False,
            "write_run_output": True,
            "network": False
        }
    }
}


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def detect_os() -> str:
    name = platform.system().lower()
    if name == "darwin":
        return "macos"
    if name == "windows":
        return "windows"
    if name == "linux":
        try:
            proc_version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
            if "microsoft" in proc_version or "wsl" in proc_version:
                return "wsl"
        except Exception:
            pass
        return "linux"
    return "unknown"


def detect_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return machine
    if machine in {"x86", "i386", "i686"}:
        return "x86"
    return "unknown"


def current_shell() -> str:
    return os.environ.get("SHELL") or os.environ.get("COMSPEC") or "unknown"


def path_separator() -> str:
    return ";" if os.name == "nt" else ":"


def redact_path(value: str | None) -> str | None:
    if not value:
        return value

    home = str(Path.home())
    redacted = value

    if home and home in redacted:
        redacted = redacted.replace(home, "<LOCAL_USER_PATH>")

    redacted = re.sub(r"/Users/[^/]+", "<LOCAL_USER_PATH>", redacted)
    redacted = re.sub(r"/home/[^/]+", "<LOCAL_USER_PATH>", redacted)
    redacted = re.sub(r"C:\\Users\\[^\\]+", r"<LOCAL_USER_PATH>", redacted, flags=re.IGNORECASE)

    if redacted.startswith("/usr/bin/") or redacted.startswith("/bin/") or redacted.startswith("/usr/sbin/") or redacted.startswith("/sbin/"):
        redacted = re.sub(r"^/(usr/)?(s)?bin", "<SYSTEM_PATH>", redacted)

    if "/opt/homebrew/bin/" in redacted or "/usr/local/bin/" in redacted:
        redacted = re.sub(r"^/opt/homebrew/bin", "<USER_TOOL_PATH>", redacted)
        redacted = re.sub(r"^/usr/local/bin", "<USER_TOOL_PATH>", redacted)

    return redacted


def summarize_output(text: str, max_len: int = 240) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def run_command(command: str, timeout: int = 8) -> dict[str, Any]:
    started = _dt.datetime.now()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout
        )
        duration_ms = int((_dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "command_redacted": redact_path(command),
            "exit_code": proc.returncode,
            "status": "success" if proc.returncode == 0 else "failed",
            "stdout_summary": summarize_output(proc.stdout),
            "stderr_summary": summarize_output(proc.stderr),
            "duration_ms": duration_ms,
            "notes": []
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((_dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "command_redacted": redact_path(command),
            "exit_code": None,
            "status": "timeout",
            "stdout_summary": summarize_output(exc.stdout if isinstance(exc.stdout, str) else ""),
            "stderr_summary": summarize_output(exc.stderr if isinstance(exc.stderr, str) else ""),
            "duration_ms": duration_ms,
            "notes": ["Command timed out."]
        }
    except Exception as exc:
        duration_ms = int((_dt.datetime.now() - started).total_seconds() * 1000)
        return {
            "command": command,
            "command_redacted": redact_path(command),
            "exit_code": None,
            "status": "failed",
            "stdout_summary": None,
            "stderr_summary": str(exc),
            "duration_ms": duration_ms,
            "notes": ["Command execution failed."]
        }


def find_all_on_path(command: str) -> list[str]:
    found: list[str] = []
    path_value = os.environ.get("PATH", "")
    if not path_value:
        return found

    suffixes = [""]
    if os.name == "nt":
        pathext = os.environ.get("PATHEXT", ".EXE;.BAT;.CMD;.COM")
        suffixes = [ext.lower() for ext in pathext.split(";") if ext] + [""]

    seen = set()
    for directory in path_value.split(os.pathsep):
        if not directory:
            continue
        base = Path(directory)
        for suffix in suffixes:
            candidate = base / f"{command}{suffix}"
            try:
                if candidate.exists() and os.access(candidate, os.X_OK):
                    resolved = str(candidate.resolve())
                    if resolved not in seen:
                        found.append(resolved)
                        seen.add(resolved)
            except Exception:
                continue

    return found


def infer_manager(path: str | None) -> str:
    if not path:
        return "not_installed"

    lower = path.lower()

    if ".local/share/mise" in lower or "/mise/" in lower:
        return "mise"
    if ".asdf" in lower:
        return "asdf"
    if ".sdkman" in lower:
        return "sdkman"
    if ".nvm" in lower:
        return "nvm"
    if ".pyenv" in lower:
        return "pyenv"
    if "/opt/homebrew/" in lower or "/homebrew/" in lower:
        return "brew"
    if "/usr/bin/" in lower or "/bin/" in lower or "/usr/sbin/" in lower:
        return "system"
    if "python" in lower and "windowsapps" in lower:
        return "winget"

    return "unknown"


def infer_install_scope(path: str | None) -> str:
    if not path:
        return "not_installed"

    lower = path.lower()
    home = str(Path.home()).lower()

    if home and lower.startswith(home):
        return "user"
    if lower.startswith("/usr/") or lower.startswith("/bin/") or lower.startswith("/sbin/"):
        return "system"
    if "/opt/homebrew/" in lower or "/usr/local/" in lower:
        return "user"
    if "wsl" in lower:
        return "wsl"

    return "unknown"


def extract_version_from_records(records: list[dict[str, Any]]) -> str | None:
    for record in records:
        if record.get("status") == "success":
            value = record.get("stdout_summary") or record.get("stderr_summary")
            if value:
                return value
    return None


def version_ok(tool_id: str, version: str | None) -> bool | None:
    if not version:
        return None

    if tool_id == "python3":
        match = re.search(r"Python\s+(\d+)\.(\d+)", version)
        if not match:
            return None
        major = int(match.group(1))
        minor = int(match.group(2))
        return (major, minor) >= (3, 10)

    return True


def load_tool_matrix(path: Path) -> tuple[str, dict[str, dict[str, Any]], list[str]]:
    notes: list[str] = []
    matrix_version = "tool-matrix-0.1.0"

    if path.exists():
        text = path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r'^\s*schema_version:\s*["\']?([^"\']+)["\']?\s*$', text, re.MULTILINE)
        if match:
            matrix_version = match.group(1).strip()

    try:
        import yaml  # type: ignore
    except Exception:
        notes.append("PyYAML is not installed. Falling back to built-in core tool definitions.")
        return matrix_version, FALLBACK_CORE_TOOLS, notes

    if not path.exists():
        notes.append(f"Tool matrix not found at {path}. Falling back to built-in core tool definitions.")
        return matrix_version, FALLBACK_CORE_TOOLS, notes

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tools = data.get("tools") or {}
        parsed: dict[str, dict[str, Any]] = {}

        for tool_id, raw in tools.items():
            detection = raw.get("detection") or {}
            commands = detection.get("commands") or []
            locate_raw = detection.get("locate") or []

            locate_commands: list[str] = []
            for item in locate_raw:
                item = str(item)
                if item.startswith("command -v "):
                    locate_commands.append(item.split("command -v ", 1)[1].strip())
                else:
                    locate_commands.append(item.strip())

            permissions = dict(raw.get("permissions") or {})
            default_permissions = data.get("default_permissions") or {}
            merged_permissions = dict(default_permissions)
            merged_permissions.update(permissions)

            parsed[str(tool_id)] = {
                "display_name": raw.get("display_name") or str(tool_id),
                "category": raw.get("category") or "other",
                "required_level": raw.get("required_level") or "optional",
                "missing_policy": raw.get("missing_policy") or policy_from_required_level(raw.get("required_level") or "optional"),
                "commands": [str(x) for x in commands],
                "locate_commands": locate_commands or [str(tool_id)],
                "missing_impact": raw.get("missing_impact"),
                "install_ref": "env/INSTALL_GUIDE.md",
                "permissions": merged_permissions
            }

        if not parsed:
            notes.append("Tool matrix contains no tools. Falling back to built-in core tool definitions.")
            return matrix_version, FALLBACK_CORE_TOOLS, notes

        return matrix_version, parsed, notes
    except Exception as exc:
        notes.append(f"Failed to parse TOOL_MATRIX.yaml with PyYAML: {exc}. Falling back to built-in core tool definitions.")
        return matrix_version, FALLBACK_CORE_TOOLS, notes


def policy_from_required_level(required_level: str) -> str:
    if required_level == "required_for_workbench":
        return "block_workbench"
    if required_level == "required_for_stack":
        return "block_stack_scan"
    if required_level == "future_stage":
        return "future_stage_not_blocking"
    if required_level in {"recommended_for_static", "optional"}:
        return "record_missing_not_blocking"
    return "record_missing_not_blocking"


def normalize_permissions(raw: dict[str, Any]) -> dict[str, bool]:
    return {
        "read_project": bool(raw.get("read_project", True)),
        "write_project": bool(raw.get("write_project", False)),
        "write_run_output": bool(raw.get("write_run_output", True)),
        "write_cache": bool(raw.get("write_cache", True)),
        "network": bool(raw.get("network", False)),
        "start_service": bool(raw.get("start_service", False)),
        "dynamic_request": bool(raw.get("dynamic_request", False)),
        "reverse_artifact": bool(raw.get("reverse_artifact", False)),
        "upload_external": bool(raw.get("upload_external", False)),
        "write_external": bool(raw.get("write_external", False))
    }


def detect_tool(tool_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    locate_commands = spec.get("locate_commands") or [tool_id]

    resolved_command: str | None = None
    resolved_path: str | None = None
    all_instances: list[dict[str, Any]] = []

    for command_name in locate_commands:
        command_name = str(command_name).strip()
        if not command_name:
            continue

        path = shutil.which(command_name)
        if path and not resolved_command:
            resolved_command = command_name
            resolved_path = str(Path(path).resolve())

        for idx, instance_path in enumerate(find_all_on_path(command_name), start=1):
            instance_id = f"{tool_id}-{idx:03d}"
            all_instances.append({
                "instance_id": instance_id,
                "command": command_name,
                "path": instance_path,
                "path_redacted": redact_path(instance_path),
                "version": None,
                "manager": infer_manager(instance_path),
                "install_scope": infer_install_scope(instance_path),
                "is_active": resolved_path == instance_path,
                "extra": {}
            })

    detection_records: list[dict[str, Any]] = []

    for command_name in locate_commands:
        command_name = str(command_name).strip()
        if not command_name:
            continue

        located = shutil.which(command_name)
        detection_records.append({
            "command": f"command -v {command_name}",
            "command_redacted": f"command -v {command_name}",
            "exit_code": 0 if located else 1,
            "status": "success" if located else "failed",
            "stdout_summary": str(Path(located).resolve()) if located else None,
            "stderr_summary": None,
            "duration_ms": None,
            "notes": []
        })

    command_records: list[dict[str, Any]] = []
    if resolved_command:
        for command in spec.get("commands") or []:
            command = str(command)
            preferred_command = command
            first_word = command.split()[0] if command.split() else ""
            if first_word and first_word != resolved_command and first_word in locate_commands:
                preferred_command = command.replace(first_word, resolved_command, 1)
            record = run_command(preferred_command)
            command_records.append(record)

    detection_records.extend(command_records)

    version = extract_version_from_records(command_records)
    active_instance_id = None

    if all_instances:
        for instance in all_instances:
            if instance.get("is_active"):
                active_instance_id = instance["instance_id"]
                instance["version"] = version
                break
        if not active_instance_id:
            active_instance_id = all_instances[0]["instance_id"]
            all_instances[0]["is_active"] = True
            all_instances[0]["version"] = version

    if resolved_path:
        status = "available_multiple" if len(all_instances) > 1 else "available"
    else:
        status = "missing"

    missing_policy = spec.get("missing_policy") or policy_from_required_level(spec.get("required_level", "optional"))

    return {
        "tool_id": tool_id,
        "display_name": spec.get("display_name") or tool_id,
        "category": spec.get("category") or "other",
        "required_level": spec.get("required_level") or "optional",
        "status": status,
        "missing_policy": missing_policy,
        "version": version,
        "version_ok": version_ok(tool_id, version),
        "resolved_command": resolved_command,
        "resolved_path": resolved_path,
        "resolved_path_redacted": redact_path(resolved_path),
        "install_scope": infer_install_scope(resolved_path),
        "manager": infer_manager(resolved_path),
        "instances": all_instances,
        "active_instance_id": active_instance_id,
        "detection_records": detection_records,
        "permissions": normalize_permissions(spec.get("permissions") or {}),
        "missing_impact": None if resolved_path else spec.get("missing_impact"),
        "blocked_reason": None,
        "skipped_reason": None,
        "install_recommendation_ref": spec.get("install_ref") or "env/INSTALL_GUIDE.md",
        "notes": []
    }


def build_stack_summary(tool_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    required = [
        "git",
        "rg",
        "python3",
        "bash",
        "find",
        "grep",
        "sed",
        "awk"
    ]
    recommended = [
        "jq",
        "tar"
    ]

    available_required = [
        tool_id for tool_id in required
        if tool_results.get(tool_id, {}).get("status") in {"available", "available_multiple"}
    ]
    missing_required = [
        tool_id for tool_id in required
        if tool_results.get(tool_id, {}).get("status") not in {"available", "available_multiple"}
    ]

    available_recommended = [
        tool_id for tool_id in recommended
        if tool_results.get(tool_id, {}).get("status") in {"available", "available_multiple"}
    ]
    missing_recommended = [
        tool_id for tool_id in recommended
        if tool_results.get(tool_id, {}).get("status") not in {"available", "available_multiple"}
    ]

    if missing_required:
        status = "blocked"
        impact = "Core tools are missing. Workbench cannot start."
    elif missing_recommended:
        status = "degraded"
        impact = "Workbench can start. Some convenience or packaging features may be unavailable."
    else:
        status = "usable"
        impact = "Core tools are available."

    return {
        "all": {
            "stack_id": "all",
            "status": status,
            "required_tools": required,
            "available_required_tools": available_required,
            "missing_required_tools": missing_required,
            "recommended_tools": recommended,
            "missing_recommended_tools": missing_recommended,
            "impact": impact
        }
    }


def build_summary(tool_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    available_count = sum(1 for item in tool_results.values() if item["status"] in {"available", "available_multiple"})
    missing = [tool_id for tool_id, item in tool_results.items() if item["status"] == "missing"]
    blocked = [
        tool_id for tool_id, item in tool_results.items()
        if item["status"] == "missing" and item["missing_policy"] in {"block_workbench", "block_stack_scan"}
    ]
    required_missing = [
        tool_id for tool_id, item in tool_results.items()
        if item["status"] == "missing" and item["required_level"] == "required_for_workbench"
    ]
    recommended_missing = [
        tool_id for tool_id, item in tool_results.items()
        if item["status"] == "missing" and item["required_level"] == "recommended_for_static"
    ]
    skipped = [tool_id for tool_id, item in tool_results.items() if item["status"] == "skipped"]
    errors = [tool_id for tool_id, item in tool_results.items() if item["status"] == "error"]

    if required_missing:
        status = "blocked"
    elif recommended_missing or errors:
        status = "degraded"
    else:
        status = "usable"

    confirmation_items = []
    for tool_id in required_missing:
        confirmation_items.append({
            "item_id": f"missing-core-{tool_id}",
            "type": "missing_core_tool",
            "message": f"Required core tool is missing: {tool_id}",
            "affected_tools": [tool_id],
            "recommended_action": "Install the missing core tool before starting audit workflow."
        })

    return {
        "status": status,
        "core_ready": not required_missing,
        "available_tools": available_count,
        "missing_tools": len(missing),
        "blocked_tools": len(blocked),
        "skipped_tools": len(skipped),
        "error_tools": len(errors),
        "required_for_workbench_missing": required_missing,
        "recommended_missing": recommended_missing,
        "confirmation_items": confirmation_items
    }


def build_result(matrix_path: Path, mode: str, debug: bool) -> dict[str, Any]:
    matrix_version, tool_specs, notes = load_tool_matrix(matrix_path)

    if mode == "core_only":
        tool_specs = {
            key: value
            for key, value in tool_specs.items()
            if value.get("category") == "core"
        }

    tool_results: dict[str, dict[str, Any]] = {}
    for tool_id, spec in tool_specs.items():
        tool_results[tool_id] = detect_tool(tool_id, spec)

    summary = build_summary(tool_results)

    return {
        "schema_version": SCHEMA_VERSION,
        "checked_at": utc_now_iso(),
        "workbench": {
            "tool_matrix_version": matrix_version,
            "tool_matrix_path": str(matrix_path),
            "env_check_mode": mode,
            "debug_enabled": debug,
            "notes": notes
        },
        "host": {
            "os": detect_os(),
            "os_version": platform.platform(),
            "arch": detect_arch(),
            "shell": current_shell(),
            "path_separator": path_separator(),
            "path_entries_count": len(os.environ.get("PATH", "").split(os.pathsep)) if os.environ.get("PATH") else 0,
            "home_path_record_policy": "local_only",
            "runtime_context": "user"
        },
        "summary": summary,
        "tools": tool_results,
        "stacks": build_stack_summary(tool_results),
        "permission_summary": {
            "network_default_allowed": False,
            "write_project_default_allowed": False,
            "start_service_default_allowed": False,
            "dynamic_request_default_allowed": False,
            "reverse_artifact_default_allowed": False,
            "upload_external_default_allowed": False,
            "write_external_default_allowed": False
        },
        "redaction": {
            "local_paths_redacted": False,
            "secrets_redacted": True,
            "redaction_warnings": [
                "Local result may contain resolved_path values. Do not commit *.local.json files.",
                "Use resolved_path_redacted in workflow summaries and business-facing outputs."
            ]
        }
    }


def print_summary(result: dict[str, Any]) -> None:
    summary = result["summary"]
    print("env-check summary")
    print(f"  status: {summary['status']}")
    print(f"  core_ready: {summary['core_ready']}")
    print(f"  available_tools: {summary['available_tools']}")
    print(f"  missing_tools: {summary['missing_tools']}")
    print(f"  required_missing: {', '.join(summary['required_for_workbench_missing']) or '-'}")
    print(f"  recommended_missing: {', '.join(summary['recommended_missing']) or '-'}")
    print("")
    print("tools")
    for tool_id, item in result["tools"].items():
        status = item["status"]
        command = item.get("resolved_command") or "-"
        version = item.get("version") or "-"
        print(f"  {tool_id}: {status} | {command} | {version}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="AI Audit Workbench env-check.")
    parser.add_argument("--matrix", default=DEFAULT_MATRIX_PATH, help="Path to TOOL_MATRIX.yaml.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Output path for local env-check result.")
    parser.add_argument(
        "--mode",
        default="core_only",
        choices=["full", "core_only", "stack_partial", "debug"],
        help="Env check mode."
    )
    parser.add_argument("--debug", action="store_true", help="Mark debug_enabled=true in the result.")
    parser.add_argument("--print-summary", action="store_true", help="Print a human-readable summary.")
    args = parser.parse_args(argv)

    matrix_path = Path(args.matrix)
    output_path = Path(args.output)

    result = build_result(matrix_path=matrix_path, mode=args.mode, debug=args.debug)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    if args.print_summary:
        print_summary(result)
    else:
        print(f"env-check result written to {output_path}")

    if result["summary"]["status"] == "blocked":
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))