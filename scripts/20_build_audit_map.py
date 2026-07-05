#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {
    ".git", ".idea", ".vscode", ".cache", ".venv", "venv", "var", "local",
    "node_modules", "vendor", "Pods", "build", "dist", "target", "coverage",
    "tmp", "logs", ".gradle", ".mvn", "DerivedData",
}

CODE_EXTS = {
    ".go", ".java", ".kt", ".kts", ".php", ".py", ".js", ".jsx", ".ts", ".tsx",
    ".vue", ".dart", ".swift", ".m", ".mm", ".cs", ".rs", ".rb",
}
TEXT_EXTS = CODE_EXTS | {".json", ".yaml", ".yml", ".xml", ".properties", ".toml", ".sql", ".md", ".txt", ".conf"}

MANIFESTS = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradlew", "gradlew.bat",
    "go.mod", "go.sum", "composer.json", "composer.lock", "pubspec.yaml", "pubspec.lock",
    "Podfile", "Podfile.lock", "Cargo.toml", "Cargo.lock", "requirements.txt", "pyproject.toml",
}

CONFIG_RE = [
    re.compile(r"^\.env(\..*)?$", re.I),
    re.compile(r"^application\.(ya?ml|properties)$", re.I),
    re.compile(r"^bootstrap\.(ya?ml|properties)$", re.I),
    re.compile(r"^config\.(js|ts|json|ya?ml|php|py)$", re.I),
    re.compile(r"^docker-compose\.ya?ml$", re.I),
    re.compile(r"^Dockerfile$", re.I),
]

STACK_MARKERS = {
    "go": {"files": {"go.mod", "go.sum"}, "exts": {".go"}},
    "java_jvm": {"files": {"pom.xml", "build.gradle", "build.gradle.kts"}, "exts": {".java", ".kt", ".kts"}},
    "node_frontend": {"files": {"package.json", "pnpm-lock.yaml", "yarn.lock"}, "exts": {".js", ".jsx", ".ts", ".tsx", ".vue"}},
    "php": {"files": {"composer.json", "composer.lock"}, "exts": {".php"}},
    "flutter_dart": {"files": {"pubspec.yaml", "pubspec.lock"}, "exts": {".dart"}},
    "ios_macos": {"files": {"Podfile", "Podfile.lock"}, "exts": {".swift", ".m", ".mm"}},
    "dotnet": {"files": set(), "exts": {".cs", ".csproj", ".sln"}},
    "rust": {"files": {"Cargo.toml", "Cargo.lock"}, "exts": {".rs"}},
    "python": {"files": {"requirements.txt", "pyproject.toml"}, "exts": {".py"}},
}

KEYWORD_GROUPS = {
    "route_files": ["controller", "route", "router", "handler", "endpoint", "api"],
    "auth_files": ["auth", "login", "jwt", "session", "security", "permission", "role", "rbac", "acl", "middleware", "interceptor", "filter", "guard"],
    "data_access_files": ["mapper", "repository", "repo", "dao", "entity", "model", "schema", "migration", "database"],
    "file_io_files": ["upload", "download", "file", "storage", "oss", "s3", "minio", "attachment"],
    "high_risk_modules": ["user", "account", "admin", "tenant", "order", "pay", "payment", "wallet", "withdraw", "refund", "coupon", "balance", "callback", "notify", "webhook", "export", "import"],
}

PATTERNS = {
    "route_hits": [
        re.compile(r"@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\("),
        re.compile(r"\b(router|group|app|server)\.(GET|POST|PUT|DELETE|PATCH|Any|Handle|get|post|put|delete|patch)\s*\("),
        re.compile(r"\bRoute::(get|post|put|delete|patch|any)\s*\("),
    ],
    "frontend_api_hits": [
        re.compile(r"\bfetch\s*\("),
        re.compile(r"\baxios\.(get|post|put|delete|patch|request)\s*\("),
        re.compile(r"\brequest\s*\("),
    ],
    "local_storage_hits": [
        re.compile(r"\blocalStorage\b"),
        re.compile(r"\bsessionStorage\b"),
        re.compile(r"\bdocument\.cookie\b"),
        re.compile(r"\bSharedPreferences\b"),
        re.compile(r"\bUserDefaults\b"),
        re.compile(r"\bKeychain\b"),
    ],
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except Exception:
        return str(path)


def excluded(path: Path, project: Path) -> bool:
    try:
        parts = path.resolve().relative_to(project.resolve()).parts
    except Exception:
        parts = path.parts
    return any(part in EXCLUDE_DIRS for part in parts)


def is_config(name: str) -> bool:
    return any(p.match(name) for p in CONFIG_RE)


def add_limited(bucket: dict[str, Any], item: Any, limit: int = 300) -> None:
    if len(bucket["items"]) < limit:
        bucket["items"].append(item)
    else:
        bucket["truncated_count"] += 1
    bucket["count"] += 1


def bucket() -> dict[str, Any]:
    return {"items": [], "count": 0, "emitted_count": 0, "truncated_count": 0}


def finish_bucket(b: dict[str, Any]) -> dict[str, Any]:
    b["emitted_count"] = len(b["items"])
    return b


def safe_read(path: Path, max_size: int) -> str | None:
    try:
        if path.stat().st_size > max_size:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def scan_text(text: str, path: Path, project: Path, patterns: list[re.Pattern[str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            if pattern.search(line):
                out.append({"file_path": rel(path, project), "line": line_no, "preview": line.strip()[:200]})
                if len(out) >= 10:
                    return out
    return out


def detect_stacks(files: list[Path], project: Path) -> dict[str, Any]:
    evidence: dict[str, list[str]] = {key: [] for key in STACK_MARKERS}
    for path in files:
        name = path.name
        suffix = path.suffix.lower()
        for stack, marker in STACK_MARKERS.items():
            if name in marker["files"] or suffix in marker["exts"]:
                evidence[stack].append(rel(path, project))
    detected = []
    for stack, items in evidence.items():
        if items:
            detected.append({
                "stack_id": stack,
                "confidence": "high" if any(Path(x).name in STACK_MARKERS[stack]["files"] for x in items) else "medium",
                "evidence": items[:20],
                "evidence_count": len(items),
            })
    return {"detected_stack_ids": [x["stack_id"] for x in detected], "detected_stacks": detected}


def by_name(files: list[Path], project: Path, names: set[str]) -> list[str]:
    return sorted(rel(path, project) for path in files if path.name in names)


def by_suffix(files: list[Path], project: Path, suffixes: set[str]) -> list[str]:
    return sorted(rel(path, project) for path in files if path.suffix.lower() in suffixes)


def gate(applicable: bool, reason: str, evidence: list[str]) -> dict[str, Any]:
    return {"applicable": applicable, "reason": reason, "evidence": evidence[:20]}


def scan_go_codegen(files: list[Path], project: Path, max_file_size: int) -> dict[str, Any]:
    docs_imports: list[dict[str, Any]] = []
    swag_markers: list[dict[str, Any]] = []
    for path in files:
        if path.suffix.lower() != ".go":
            continue
        text = safe_read(path, max_file_size)
        if not text:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if re.search(r'"[^"\n]*/docs"|"docs"', stripped):
                docs_imports.append({"file_path": rel(path, project), "line": line_no, "preview": stripped[:200]})
            if "github.com/swaggo" in stripped or re.search(r"//\s*@(?:title|version|description|host|BasePath|securityDefinitions)", stripped):
                swag_markers.append({"file_path": rel(path, project), "line": line_no, "preview": stripped[:200]})
        if len(docs_imports) >= 20 and len(swag_markers) >= 20:
            break
    return {
        "has_docs_import": bool(docs_imports),
        "docs_imports": docs_imports[:20],
        "has_swag_markers": bool(swag_markers),
        "swag_markers": swag_markers[:20],
        "swag_init_may_recover_go_list": bool(docs_imports or swag_markers),
    }


def build_project_facts(run_meta: dict[str, Any], profile: dict[str, Any], files: list[Path], project: Path, ext_counts: dict[str, int], max_file_size: int) -> dict[str, Any]:
    go_mod = by_name(files, project, {"go.mod"})
    go_sum = by_name(files, project, {"go.sum"})
    pom = by_name(files, project, {"pom.xml"})
    gradle = by_name(files, project, {"build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"})
    gradlew = by_name(files, project, {"gradlew", "gradlew.bat"})
    package_json = by_name(files, project, {"package.json"})
    package_lock = by_name(files, project, {"package-lock.json"})
    pnpm_lock = by_name(files, project, {"pnpm-lock.yaml"})
    yarn_lock = by_name(files, project, {"yarn.lock"})
    composer = by_name(files, project, {"composer.json", "composer.lock"})
    pyproject = by_name(files, project, {"pyproject.toml", "requirements.txt"})
    go_codegen = scan_go_codegen(files, project, max_file_size)

    build_systems: list[str] = []
    package_managers: list[str] = []
    if go_mod:
        build_systems.append("go_module")
        package_managers.append("go")
    if pom:
        build_systems.append("maven")
        package_managers.append("maven")
    if gradle or gradlew:
        build_systems.append("gradle")
        package_managers.append("gradle")
    if package_json:
        build_systems.append("node_package")
        package_managers.append("npm")
    if pnpm_lock:
        package_managers.append("pnpm")
    if yarn_lock:
        package_managers.append("yarn")
    if composer:
        build_systems.append("composer")
        package_managers.append("composer")
    if pyproject:
        build_systems.append("python")
        package_managers.append("python")

    has_go_code = bool(ext_counts.get(".go"))
    has_js_code = any(ext_counts.get(ext) for ext in [".js", ".jsx", ".ts", ".tsx", ".vue"])
    has_java_code = any(ext_counts.get(ext) for ext in [".java", ".kt", ".kts"])

    tool_gates = {
        "go": gate(bool(go_mod), "go.mod found" if go_mod else "go.mod not found", go_mod),
        "govulncheck": gate(bool(go_mod), "requires go.mod" if not go_mod else "go module manifest found", go_mod),
        "golangci-lint": gate(bool(go_mod), "requires go.mod" if not go_mod else "go module manifest found", go_mod),
        "swag": gate(has_go_code and go_codegen["swag_init_may_recover_go_list"], "go swagger codegen markers found" if go_codegen["swag_init_may_recover_go_list"] else "no Go Swagger codegen markers found", [x.get("file_path", "") for x in go_codegen.get("docs_imports", []) + go_codegen.get("swag_markers", []) if x.get("file_path")]),
        "mvn": gate(bool(pom), "requires pom.xml" if not pom else "pom.xml found", pom),
        "gradle": gate(bool(gradle or gradlew), "requires Gradle manifest or wrapper" if not (gradle or gradlew) else "Gradle manifest/wrapper found", gradle + gradlew),
        "dependency-check": gate(bool(pom or gradle or gradlew), "requires supported dependency manifest" if not (pom or gradle or gradlew) else "supported Java dependency manifest found", pom + gradle + gradlew),
        "npm": gate(bool(package_json), "requires package.json" if not package_json else "package.json found", package_json + package_lock),
        "pnpm": gate(bool(pnpm_lock), "requires pnpm-lock.yaml" if not pnpm_lock else "pnpm-lock.yaml found", pnpm_lock),
        "yarn": gate(bool(yarn_lock), "requires yarn.lock" if not yarn_lock else "yarn.lock found", yarn_lock),
        "retire": gate(bool(package_json or has_js_code), "requires package.json or JS/TS files" if not (package_json or has_js_code) else "Node/frontend evidence found", package_json),
    }

    return {
        "schema_version": "project-facts-0.1.0",
        "generated_at": now(),
        "source_priority": ["current_code_manifest", "current_tool_evidence", "ai_inference_from_current_code", "ai_extract_from_current_docs", "local_registry_history"],
        "run": {
            "run_id": run_meta.get("run_id"),
            "project_key": run_meta.get("project_key"),
            "audit_mode": run_meta.get("audit_mode"),
        },
        "project": {
            "project_code": profile.get("project_code"),
            "project_name": profile.get("project_name"),
            "project_path_relative_to_workbench": profile.get("project_path", {}).get("relative_to_workbench"),
            "git": profile.get("git", {}),
        },
        "language_summary": {
            "extension_counts": dict(sorted(ext_counts.items(), key=lambda x: (-x[1], x[0]))),
            "has_go_code": has_go_code,
            "has_java_jvm_code": has_java_code,
            "has_node_frontend_code": has_js_code,
        },
        "manifests": {
            "go": {"has_go_mod": bool(go_mod), "has_go_sum": bool(go_sum), "go_mod_files": go_mod, "go_sum_files": go_sum, "codegen": go_codegen},
            "java": {"has_pom": bool(pom), "has_gradle": bool(gradle), "has_gradle_wrapper": bool(gradlew), "pom_files": pom, "gradle_files": gradle, "gradle_wrapper_files": gradlew},
            "node": {"has_package_json": bool(package_json), "has_package_lock": bool(package_lock), "has_pnpm_lock": bool(pnpm_lock), "has_yarn_lock": bool(yarn_lock), "package_json_files": package_json, "package_lock_files": package_lock, "pnpm_lock_files": pnpm_lock, "yarn_lock_files": yarn_lock},
            "php": {"has_composer": bool(composer), "composer_files": composer},
            "python": {"has_python_manifest": bool(pyproject), "python_manifest_files": pyproject},
        },
        "build_systems": sorted(set(build_systems)),
        "package_managers": sorted(set(package_managers)),
        "tool_gates": tool_gates,
    }


def build_map(run_root: Path, max_files: int, max_file_size: int) -> dict[str, Any]:
    run_meta = load_json(run_root / "meta" / "RUN_METADATA.json")
    profile = load_json(run_root / "meta" / "PROJECT_PROFILE.json")
    project_path = Path(profile["project_path"]["resolved"])
    if not project_path.is_dir():
        raise FileNotFoundError(f"project path unavailable: {project_path}")

    files = []
    for path in project_path.rglob("*"):
        if len(files) >= max_files:
            break
        if path.is_file() and not excluded(path, project_path):
            files.append(path)

    groups = {name: bucket() for name in [
        "manifests", "configs", "route_files", "auth_files", "data_access_files",
        "file_io_files", "high_risk_modules", "skipped_large_files",
    ]}
    signals = {name: bucket() for name in PATTERNS}
    ext_counts: dict[str, int] = {}
    summary = {"total_files_sampled": len(files), "code_files": 0, "text_files": 0, "other_files": 0, "total_code_lines_sampled": 0}

    for path in files:
        name = path.name
        suffix = path.suffix.lower() or "<no_ext>"
        low = rel(path, project_path).lower()
        ext_counts[suffix] = ext_counts.get(suffix, 0) + 1
        if suffix in CODE_EXTS:
            summary["code_files"] += 1
        elif suffix in TEXT_EXTS or name in MANIFESTS:
            summary["text_files"] += 1
        else:
            summary["other_files"] += 1

        if name in MANIFESTS or suffix in {".csproj", ".sln"}:
            add_limited(groups["manifests"], rel(path, project_path))
        if is_config(name):
            add_limited(groups["configs"], rel(path, project_path))
        for group_name, keywords in KEYWORD_GROUPS.items():
            if any(k in low for k in keywords):
                add_limited(groups[group_name], rel(path, project_path))

        if suffix not in TEXT_EXTS and name not in MANIFESTS:
            continue
        text = safe_read(path, max_file_size)
        if text is None:
            add_limited(groups["skipped_large_files"], rel(path, project_path))
            continue
        if suffix in CODE_EXTS:
            summary["total_code_lines_sampled"] += text.count("\n") + 1
        for signal_name, patterns in PATTERNS.items():
            for item in scan_text(text, path, project_path, patterns):
                add_limited(signals[signal_name], item, limit=500)

    project_facts = build_project_facts(run_meta, profile, files, project_path, ext_counts, max_file_size)

    return {
        "schema_version": "audit-map-0.2.0",
        "generated_at": now(),
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
            "project_path_relative_to_workbench": profile.get("project_path", {}).get("relative_to_workbench"),
            "git": profile.get("git", {}),
        },
        "scan_policy": {
            "excluded_dir_names": sorted(EXCLUDE_DIRS),
            "max_files": max_files,
            "max_file_size_bytes": max_file_size,
            "no_dynamic_testing": True,
            "no_reverse_analysis": True,
            "read_only_project": True,
        },
        "summary": summary,
        "extension_counts": dict(sorted(ext_counts.items(), key=lambda x: (-x[1], x[0]))),
        "stacks": detect_stacks(files, project_path),
        "project_facts_ref": "audit-map/PROJECT_FACTS.json",
        "project_facts": project_facts,
        "files": {k: finish_bucket(v) for k, v in groups.items()},
        "signals": {k: finish_bucket(v) for k, v in signals.items()},
        "coverage_notes": [
            "Audit map is generated by static discovery only.",
            "Project facts are based on current code/manifests and must take precedence over stale documents.",
            "Audit map guides later evidence collection and AI triage, but does not prove risk by itself.",
        ],
    }


def list_block(title: str, data: dict[str, Any]) -> str:
    lines = [f"## {title}", "", f"Total: {data.get('count', 0)}", ""]
    items = data.get("items") or []
    if not items:
        lines.append("- None discovered")
    for item in items[:30]:
        if isinstance(item, str):
            lines.append(f"- `{item}`")
        elif isinstance(item, dict):
            path = item.get("file_path", "unknown")
            line = item.get("line")
            preview = item.get("preview", "")
            lines.append(f"- `{path}:{line}` {preview}".rstrip())
    lines.append("")
    return "\n".join(lines)


def render_md(data: dict[str, Any]) -> str:
    facts = data.get("project_facts", {})
    lines = [
        "# AUDIT_MAP", "",
        "## Run", "",
        f"- Run ID: `{data['run'].get('run_id')}`",
        f"- Project key: `{data['run'].get('project_key')}`",
        f"- Audit mode: `{data['run'].get('audit_mode')}`",
        f"- Round: `{data['run'].get('round')}`", "",
        "## Project", "",
        f"- Project code: `{data['project'].get('project_code') or ''}`",
        f"- Project name: `{data['project'].get('project_name') or ''}`",
        f"- Project path: `{data['project'].get('project_path_relative_to_workbench') or ''}`",
        f"- Git branch: `{data['project'].get('git', {}).get('branch') or ''}`",
        f"- Git commit: `{data['project'].get('git', {}).get('commit') or ''}`", "",
        "## Summary", "",
        f"- Total files sampled: {data['summary'].get('total_files_sampled')}",
        f"- Code files: {data['summary'].get('code_files')}",
        f"- Text files: {data['summary'].get('text_files')}",
        f"- Total code lines sampled: {data['summary'].get('total_code_lines_sampled')}", "",
        "## Project facts", "",
        f"- Build systems: `{', '.join(facts.get('build_systems') or []) or '-'}`",
        f"- Package managers: `{', '.join(facts.get('package_managers') or []) or '-'}`",
        f"- Project facts file: `{data.get('project_facts_ref')}`", "",
        "## Detected stacks", "",
    ]
    stacks = data["stacks"].get("detected_stacks") or []
    if stacks:
        for item in stacks:
            lines.append(f"- `{item['stack_id']}` confidence={item['confidence']} evidence_count={item['evidence_count']}")
    else:
        lines.append("- None detected")
    lines.append("")
    for key, title in [
        ("manifests", "Manifests"), ("configs", "Configs"), ("route_files", "Route files"),
        ("auth_files", "Auth / permission files"), ("data_access_files", "Data access files"),
        ("file_io_files", "File upload / download files"), ("high_risk_modules", "High-risk business modules"),
    ]:
        lines.append(list_block(title, data["files"][key]))
    for key, title in [
        ("route_hits", "Route / API pattern hits"), ("frontend_api_hits", "Frontend API call hits"),
        ("local_storage_hits", "Local storage hits"),
    ]:
        lines.append(list_block(title, data["signals"][key]))
    lines.append("## Coverage notes\n")
    for note in data.get("coverage_notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def render_project_facts_md(facts: dict[str, Any]) -> str:
    lines = [
        "# PROJECT_FACTS", "",
        f"- Run ID: `{facts.get('run', {}).get('run_id')}`",
        f"- Project: `{facts.get('project', {}).get('project_name') or ''}`",
        f"- Build systems: `{', '.join(facts.get('build_systems') or []) or '-'}`",
        f"- Package managers: `{', '.join(facts.get('package_managers') or []) or '-'}`", "",
        "## Manifest gates", "",
        "| Tool | Applicable | Reason | Evidence |",
        "|---|---:|---|---|",
    ]
    for tool_id, gate_item in sorted((facts.get("tool_gates") or {}).items()):
        evidence = ", ".join(gate_item.get("evidence") or []) or "-"
        lines.append(f"| `{tool_id}` | `{gate_item.get('applicable')}` | {gate_item.get('reason')} | `{evidence}` |")
    lines.extend(["", "## Go codegen", ""])
    go_codegen = facts.get("manifests", {}).get("go", {}).get("codegen", {})
    lines.append(f"- Docs import: `{go_codegen.get('has_docs_import')}`")
    lines.append(f"- Swag markers: `{go_codegen.get('has_swag_markers')}`")
    lines.append(f"- swag init may recover go list: `{go_codegen.get('swag_init_may_recover_go_list')}`")
    lines.append("")
    return "\n".join(lines)


def print_summary(data: dict[str, Any]) -> None:
    facts = data.get("project_facts", {})
    print("audit-map summary")
    print(f"  run_id: {data['run'].get('run_id')}")
    print(f"  project: {data['project'].get('project_name')}")
    print(f"  stacks: {', '.join(data['stacks'].get('detected_stack_ids', [])) or '-'}")
    print(f"  build_systems: {', '.join(facts.get('build_systems') or []) or '-'}")
    print(f"  package_managers: {', '.join(facts.get('package_managers') or []) or '-'}")
    print(f"  total_files_sampled: {data['summary'].get('total_files_sampled')}")
    print(f"  code_files: {data['summary'].get('code_files')}")
    print(f"  manifests: {data['files']['manifests'].get('count')}")
    print(f"  configs: {data['files']['configs'].get('count')}")
    print(f"  route_files: {data['files']['route_files'].get('count')}")
    print(f"  auth_files: {data['files']['auth_files'].get('count')}")
    print(f"  high_risk_modules: {data['files']['high_risk_modules'].get('count')}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build audit map for one run.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--max-files", type=int, default=20000)
    parser.add_argument("--max-file-size", type=int, default=1024 * 1024)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2

    data = build_map(run_root, args.max_files, args.max_file_size)
    out = run_root / "audit-map"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "AUDIT_MAP.json", data)
    write_json(out / "PROJECT_FACTS.json", data["project_facts"])
    (out / "AUDIT_MAP.md").write_text(render_md(data), encoding="utf-8")
    (out / "PROJECT_FACTS.md").write_text(render_project_facts_md(data["project_facts"]), encoding="utf-8")

    if args.print_summary:
        print_summary(data)
    else:
        print(f"audit map written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
