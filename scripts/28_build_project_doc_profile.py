#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_ROOT = ROOT / "local" / "registry" / "projects"
HISTORY_LIMIT = 20
EXCLUDE_DIRS = {".git", ".venv", "venv", "node_modules", "vendor", "target", "dist", "build", "coverage", "var", "local"}
DOC_NAMES = {"README", "README.md", "README.txt", "CHANGELOG", "CHANGELOG.md", "CONTRIBUTING.md", "Makefile", "Taskfile.yml", "Taskfile.yaml", "Dockerfile", "docker-compose.yml", "docker-compose.yaml"}
DOC_EXTS = {".md", ".txt", ".rst", ".adoc", ".yml", ".yaml"}
COMMAND_RE = re.compile(r"\b((?:make|go|npm|pnpm|yarn|mvn|gradle|./gradlew|docker|docker-compose|swag)\s+[^\n`;&|]+)")
URL_RE = re.compile(r"https?://[^\s)>'\"]+")

FIELD_LABELS = {
    "project_code": "项目代码", "project_name_cn": "项目中文名", "project_name_en": "项目英文名",
    "business_domain": "业务域", "repo_url": "仓库地址", "main_language": "主语言", "frameworks": "框架与版本",
    "build_systems": "构建系统", "package_managers": "包管理器", "build_commands": "构建命令",
    "run_commands": "启动命令", "test_commands": "测试命令", "api_docs": "API 文档", "ops_docs": "运维文档",
    "external_services": "外部服务", "known_limitations": "已知限制", "known_risks": "已知风险",
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False) + "\n", encoding="utf-8")


def rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except Exception:
        return str(path)


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def sha256_short(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:length]


def slugify(value: str, default: str = "manual-project") -> str:
    value = (value or "").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value or default


def run_command(args: list[str], cwd: Path, timeout: int = 8) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(args, cwd=str(cwd), text=True, capture_output=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def normalize_remote_url(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().replace("\\", "/")
    if text.startswith("git@") and ":" in text:
        host, path = text[4:].split(":", 1)
        text = f"{host}/{path}"
    text = re.sub(r"^(ssh|https?|git)://", "", text, flags=re.I)
    text = re.sub(r"^[^/@]+@", "", text)
    text = text.rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    return text.lower()


def git_registry_identity(project_root: Path, profile: dict[str, Any]) -> dict[str, Any] | None:
    git = profile.get("git") or {}
    remote = normalize_remote_url(git.get("remote_origin"))
    git_root_raw = git.get("root")
    if not remote or not git_root_raw:
        return None
    git_root = Path(git_root_raw).resolve()
    try:
        repo_rel = str(project_root.resolve().relative_to(git_root)) or "."
    except Exception:
        repo_rel = "."
    if repo_rel == "":
        repo_rel = "."
    hash_input = f"git:{remote}#{repo_rel}"
    return {"project_id": f"git-{sha256_short(hash_input)}", "strategy": "git-remote-subpath-hash", "requested_strategy": "auto", "hash_algorithm": "sha256", "hash_length": 16, "hash_input": hash_input, "vcs": {"type": "git", "remote_url_normalized": remote, "repo_relative_path": repo_rel}}


def svn_registry_identity(project_root: Path) -> dict[str, Any] | None:
    code, url, _ = run_command(["svn", "info", "--show-item", "url"], cwd=project_root)
    if code != 0 or not url:
        return None
    code, root_url, _ = run_command(["svn", "info", "--show-item", "repos-root-url"], cwd=project_root)
    root_url = root_url or url
    url_norm = url.strip().rstrip("/").lower()
    root_norm = root_url.strip().rstrip("/").lower()
    subpath = "."
    if url_norm.startswith(root_norm):
        subpath = url_norm[len(root_norm):].strip("/") or "."
    hash_input = f"svn:{root_norm}#{subpath}"
    return {"project_id": f"svn-{sha256_short(hash_input)}", "strategy": "svn-url-subpath-hash", "requested_strategy": "auto", "hash_algorithm": "sha256", "hash_length": 16, "hash_input": hash_input, "vcs": {"type": "svn", "remote_url_normalized": root_norm, "repo_relative_path": subpath}}


def dir_registry_identity(project_root: Path) -> dict[str, Any]:
    path = str(project_root.resolve())
    hash_input = f"dir:{path}"
    return {"project_id": f"dir-{sha256_short(hash_input)}", "strategy": "dir-hash", "requested_strategy": "auto", "hash_algorithm": "sha256", "hash_length": 16, "hash_input": hash_input, "vcs": {"type": "none", "remote_url_normalized": None, "repo_relative_path": path}}


def build_registry_identity(project_root: Path, profile: dict[str, Any], strategy: str, manual_id: str | None) -> dict[str, Any]:
    requested = strategy or "auto"
    if requested == "manual":
        if not manual_id:
            raise SystemExit("[FAIL] --registry-project-id is required when --registry-id-strategy=manual")
        return {"project_id": slugify(manual_id), "strategy": "manual", "requested_strategy": requested, "hash_algorithm": None, "hash_length": None, "hash_input": None, "vcs": {"type": "manual", "remote_url_normalized": None, "repo_relative_path": None}}
    if requested in {"auto", "git-hash"}:
        identity = git_registry_identity(project_root, profile)
        if identity:
            identity["requested_strategy"] = requested
            return identity
        if requested == "git-hash":
            raise SystemExit("[FAIL] git identity unavailable for --registry-id-strategy=git-hash")
    if requested in {"auto", "svn-hash"}:
        identity = svn_registry_identity(project_root)
        if identity:
            identity["requested_strategy"] = requested
            return identity
        if requested == "svn-hash":
            raise SystemExit("[FAIL] svn identity unavailable for --registry-id-strategy=svn-hash")
    if requested in {"auto", "dir-hash"}:
        identity = dir_registry_identity(project_root)
        identity["requested_strategy"] = requested
        return identity
    raise SystemExit(f"[FAIL] unsupported registry id strategy: {requested}")


def excluded(path: Path, project: Path) -> bool:
    try:
        parts = path.resolve().relative_to(project.resolve()).parts
    except Exception:
        parts = path.parts
    return any(part in EXCLUDE_DIRS for part in parts)


def is_doc_candidate(path: Path, project: Path) -> bool:
    if excluded(path, project) or not path.is_file():
        return False
    name = path.name
    low = rel(path, project).lower()
    if name in DOC_NAMES:
        return True
    if path.suffix.lower() in DOC_EXTS and ("doc" in low or "readme" in low or path.parent == project):
        return True
    if ".github/workflows" in low and path.suffix.lower() in {".yml", ".yaml"}:
        return True
    return False


def safe_read(path: Path, max_size: int) -> str | None:
    try:
        if path.stat().st_size > max_size:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def discover_docs(project: Path, max_docs: int, max_file_size: int) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for path in sorted(project.rglob("*")):
        if len(docs) >= max_docs:
            break
        if not is_doc_candidate(path, project):
            continue
        text = safe_read(path, max_file_size)
        if text is None:
            docs.append({"path": rel(path, project), "readable": False, "size_bytes": path.stat().st_size if path.exists() else None})
            continue
        first_heading = None
        for line in text.splitlines()[:80]:
            if line.strip().startswith("#"):
                first_heading = line.strip("# ").strip()
                if first_heading:
                    break
        docs.append({"path": rel(path, project), "readable": True, "size_bytes": path.stat().st_size, "sha1": sha1(text), "first_heading": first_heading, "excerpt": text[:1200], "full_text": text})
    return docs


def uniq(values: list[str], limit: int = 30) -> list[str]:
    out: list[str] = []
    seen = set()
    for value in values:
        value = re.sub(r"\s+", " ", str(value).strip().strip("`"))
        if not value or value in seen:
            continue
        out.append(value)
        seen.add(value)
        if len(out) >= limit:
            break
    return out


def make_field(field_id: str, value: Any, source_type: str, confidence: str, source_file: str | None = None, evidence: str | None = None, notes: list[str] | None = None) -> dict[str, Any]:
    return {"field_id": field_id, "label_zh": FIELD_LABELS.get(field_id, field_id), "value": value, "source_type": source_type, "confidence": confidence, "source_file": source_file, "evidence_excerpt": evidence, "verified_by_human": False, "notes": notes or []}


def classify_commands(commands: list[str]) -> dict[str, list[str]]:
    build: list[str] = []
    run: list[str] = []
    test: list[str] = []
    for command in commands:
        low = command.lower()
        if any(token in low for token in [" test", "go test", "npm test", "yarn test", "pnpm test", "mvn test", "gradle test"]):
            test.append(command)
        elif any(token in low for token in [" run", "go run", "npm start", "yarn start", "pnpm start", "docker compose up", "docker-compose up"]):
            run.append(command)
        elif any(token in low for token in [" build", "package", "install", "swag init", "generate"]):
            build.append(command)
    return {"build_commands": uniq(build), "run_commands": uniq(run), "test_commands": uniq(test)}


def infer_doc_fields(docs: list[dict[str, Any]], profile: dict[str, Any], facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    fields["project_code"] = make_field("project_code", profile.get("project_code"), "current_code_manifest", "high", notes=["from PROJECT_PROFILE"])
    fields["repo_url"] = make_field("repo_url", profile.get("git", {}).get("remote_origin"), "current_code_manifest", "medium", notes=["from git remote origin"])
    fields["build_systems"] = make_field("build_systems", facts.get("build_systems", []), "current_code_manifest", "high", notes=["from PROJECT_FACTS"])
    fields["package_managers"] = make_field("package_managers", facts.get("package_managers", []), "current_code_manifest", "high", notes=["from PROJECT_FACTS"])
    language = []
    lang_summary = facts.get("language_summary", {})
    if lang_summary.get("has_go_code"):
        language.append("Go")
    if lang_summary.get("has_java_jvm_code"):
        language.append("Java/JVM")
    if lang_summary.get("has_node_frontend_code"):
        language.append("Node/Frontend")
    fields["main_language"] = make_field("main_language", language, "current_code_manifest", "high", notes=["from PROJECT_FACTS language_summary"])
    headings = [x.get("first_heading") for x in docs if x.get("first_heading")]
    if headings:
        fields["project_name_cn"] = make_field("project_name_cn", headings[0], "current_project_docs_extract", "low", docs[0].get("path"), headings[0], ["first heading from project document; may be stale"])
    all_text = "\n".join(x.get("full_text") or "" for x in docs if x.get("readable"))
    categorized = classify_commands(uniq(COMMAND_RE.findall(all_text), limit=80))
    for field_id, values in categorized.items():
        if values:
            fields[field_id] = make_field(field_id, values, "current_project_docs_extract", "medium", evidence="; ".join(values[:5]), notes=["deterministic command extraction from docs/workflow files"])
    urls = uniq(URL_RE.findall(all_text), limit=50)
    api_urls = [u for u in urls if any(k in u.lower() for k in ["swagger", "openapi", "api-doc", "docs", "doc.html"])]
    if api_urls:
        fields["api_docs"] = make_field("api_docs", api_urls, "current_project_docs_extract", "medium", evidence="; ".join(api_urls[:5]))
    external = [u for u in urls if not any(k in u.lower() for k in ["github.com", "swagger", "openapi"])]
    if external:
        fields["external_services"] = make_field("external_services", external[:20], "current_project_docs_extract", "low", evidence="; ".join(external[:5]), notes=["URLs extracted from docs; may include examples"])
    ops_paths = [x["path"] for x in docs if any(k in x["path"].lower() for k in ["deploy", "docker", "k8s", "kubernetes", "helm", "ops", "workflow", "ci"])]
    if ops_paths:
        fields["ops_docs"] = make_field("ops_docs", ops_paths, "current_project_docs_extract", "medium", evidence="; ".join(ops_paths[:10]))
    risk_lines = []
    for doc in docs:
        text = doc.get("full_text") or ""
        for line in text.splitlines():
            low = line.lower()
            if any(k in low for k in ["todo", "fixme", "risk", "风险", "注意", "限制", "warning", "known issue"]):
                risk_lines.append(f"{doc['path']}: {line.strip()[:180]}")
    if risk_lines:
        fields["known_risks"] = make_field("known_risks", uniq(risk_lines, 20), "current_project_docs_extract", "low", evidence="; ".join(risk_lines[:3]), notes=["keyword extraction; requires review"])
    return fields


def build_profile(run_root: Path, max_docs: int, max_file_size: int, registry_id_strategy: str, registry_project_id: str | None) -> dict[str, Any]:
    run_meta = load_json(run_root / "meta" / "RUN_METADATA.json")
    profile = load_json(run_root / "meta" / "PROJECT_PROFILE.json")
    facts_path = run_root / "audit-map" / "PROJECT_FACTS.json"
    facts = load_json(facts_path) if facts_path.is_file() else {}
    project_root = Path(profile["project_path"]["resolved"])
    registry_identity = build_registry_identity(project_root, profile, registry_id_strategy, registry_project_id)
    docs = discover_docs(project_root, max_docs, max_file_size)
    fields = infer_doc_fields(docs, profile, facts)
    doc_sources = [{k: v for k, v in item.items() if k != "full_text"} for item in docs]
    return {"schema_version": "project-doc-profile-0.3.0", "generated_at": now(), "source_priority": ["human_current_run_confirmation", "current_code_manifest", "current_tool_evidence", "ai_inference_from_current_code", "current_project_docs_extract", "local_registry_history", "stale_or_unknown_docs"], "run": {"run_id": run_meta.get("run_id"), "project_key": run_meta.get("project_key"), "project_code": run_meta.get("project_code"), "project_name": run_meta.get("project_name"), "audit_mode": run_meta.get("audit_mode"), "created_at": run_meta.get("created_at")}, "project": {"project_code": profile.get("project_code"), "project_name": profile.get("project_name"), "project_path_relative_to_workbench": profile.get("project_path", {}).get("relative_to_workbench"), "project_directory_name": project_root.name, "git": profile.get("git", {})}, "registry_identity": registry_identity, "summary": {"doc_sources_discovered": len(doc_sources), "fields_extracted": len(fields), "status": "completed"}, "doc_sources": doc_sources, "fields": fields, "notes": ["Project document profile is advisory and may be stale.", "Current code manifests and tool evidence take priority over documentation-derived fields.", "Human confirmation should be recorded in registry manual section when field accuracy matters."]}


def field_value(fields: dict[str, Any], field_id: str, default: Any = None) -> Any:
    item = fields.get(field_id) or {}
    return item.get("value", default)


def limit_list(value: Any, limit: int = 20) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return value[:limit]


def new_aliases(doc_profile: dict[str, Any]) -> dict[str, list[str]]:
    project = doc_profile.get("project", {})
    out = {"project_codes": [], "project_names": [], "directory_names": []}
    if project.get("project_code"):
        out["project_codes"].append(str(project["project_code"]))
    if project.get("project_name"):
        out["project_names"].append(str(project["project_name"]))
    if project.get("project_directory_name"):
        out["directory_names"].append(str(project["project_directory_name"]))
    return out


def merge_aliases(existing: dict[str, Any], fresh: dict[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for key in sorted(set(existing.keys()) | set(fresh.keys())):
        old_values = existing.get(key) or []
        if not isinstance(old_values, list):
            old_values = [old_values]
        merged[key] = uniq([str(x) for x in old_values] + [str(x) for x in fresh.get(key, []) if x], limit=50)
    return merged


def manual_template(existing_manual: Any) -> dict[str, Any]:
    default = {"business_domain": None, "owners": [], "dev_team": None, "ops_team": None, "security_contact": None, "build_commands": [], "run_commands": [], "test_commands": [], "api_docs": [], "ops_docs": [], "notes": []}
    if isinstance(existing_manual, dict):
        for key, value in default.items():
            existing_manual.setdefault(key, value)
        return existing_manual
    return default


def generated_section(doc_profile: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    fields = doc_profile.get("fields") or {}
    return {"updated_at": now(), "latest_run": doc_profile.get("run"), "latest_facts": {"build_systems": facts.get("build_systems", []), "package_managers": facts.get("package_managers", []), "main_language": limit_list(field_value(fields, "main_language"))}, "doc_profile": doc_profile.get("summary", {}), "doc_fields": {"build_commands": limit_list(field_value(fields, "build_commands")), "run_commands": limit_list(field_value(fields, "run_commands")), "test_commands": limit_list(field_value(fields, "test_commands")), "api_docs": limit_list(field_value(fields, "api_docs")), "ops_docs": limit_list(field_value(fields, "ops_docs")), "external_services": limit_list(field_value(fields, "external_services"), 10), "known_risks": limit_list(field_value(fields, "known_risks"), 10)}}


def update_history(existing_history: dict[str, Any], doc_profile: dict[str, Any]) -> dict[str, Any]:
    old_runs = existing_history.get("latest_runs") if isinstance(existing_history, dict) else []
    if not isinstance(old_runs, list):
        old_runs = []
    project = doc_profile.get("project", {})
    run = doc_profile.get("run", {})
    entry = {"run_id": run.get("run_id"), "created_at": run.get("created_at"), "audit_mode": run.get("audit_mode"), "git_commit": (project.get("git") or {}).get("commit"), "git_branch": (project.get("git") or {}).get("branch")}
    merged = [entry]
    for item in old_runs:
        if not isinstance(item, dict):
            continue
        if item.get("run_id") == entry.get("run_id") and item.get("git_commit") == entry.get("git_commit"):
            continue
        merged.append(item)
        if len(merged) >= HISTORY_LIMIT:
            break
    return {"latest_runs": merged}


def build_project_index(doc_profile: dict[str, Any], facts: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "project-index-0.2.0", "identity": doc_profile.get("registry_identity", {}), "aliases": merge_aliases(existing.get("aliases") or {}, new_aliases(doc_profile)), "generated": generated_section(doc_profile, facts), "manual": manual_template(existing.get("manual")), "history": update_history(existing.get("history") or {}, doc_profile)}


def render_profile_md(profile: dict[str, Any]) -> str:
    identity = profile.get("registry_identity", {})
    lines = ["# PROJECT_DOC_PROFILE", "", f"- Status: `{profile['summary']['status']}`", f"- Registry project ID: `{identity.get('project_id')}`", f"- Registry strategy: `{identity.get('strategy')}`", f"- Document sources: {profile['summary']['doc_sources_discovered']}", f"- Fields extracted: {profile['summary']['fields_extracted']}", "", "## Fields", "", "| Field | Source | Confidence | Value |", "|---|---|---|---|"]
    for field_id, item in sorted((profile.get("fields") or {}).items()):
        value = item.get("value")
        value_text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        lines.append(f"| `{field_id}` | `{item.get('source_type')}` | `{item.get('confidence')}` | {value_text[:240]} |")
    lines.extend(["", "## Document sources", ""])
    for item in profile.get("doc_sources", [])[:80]:
        lines.append(f"- `{item.get('path')}` readable={item.get('readable')} heading={item.get('first_heading') or '-'}")
    lines.extend(["", "## Notes", ""])
    for note in profile.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def print_summary(profile: dict[str, Any], index_path: Path) -> None:
    print("project-doc-profile summary")
    print(f"  status: {profile['summary']['status']}")
    print(f"  registry_project_id: {profile.get('registry_identity', {}).get('project_id')}")
    print(f"  registry_strategy: {profile.get('registry_identity', {}).get('strategy')}")
    print(f"  doc_sources_discovered: {profile['summary']['doc_sources_discovered']}")
    print(f"  fields_extracted: {profile['summary']['fields_extracted']}")
    print(f"  project_index: {index_path}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build project document profile and local project index.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--max-docs", type=int, default=80)
    parser.add_argument("--max-file-size", type=int, default=256 * 1024)
    parser.add_argument("--registry-root", default=str(REGISTRY_ROOT))
    parser.add_argument("--registry-id-strategy", default="auto", choices=["auto", "git-hash", "svn-hash", "dir-hash", "manual"])
    parser.add_argument("--registry-project-id", default="")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not (run_root / "meta" / "PROJECT_PROFILE.json").is_file():
        print("[FAIL] PROJECT_PROFILE.json not found. Run run-init first.", file=sys.stderr)
        return 2

    profile = build_profile(run_root, args.max_docs, args.max_file_size, args.registry_id_strategy, args.registry_project_id or None)
    facts_path = run_root / "audit-map" / "PROJECT_FACTS.json"
    facts = load_json(facts_path) if facts_path.is_file() else {}
    out = run_root / "audit-map"
    write_json(out / "PROJECT_DOC_PROFILE.json", profile)
    (out / "PROJECT_DOC_PROFILE.md").write_text(render_profile_md(profile), encoding="utf-8")

    registry_root = Path(args.registry_root)
    if not registry_root.is_absolute():
        registry_root = (ROOT / registry_root).resolve()
    project_id = profile.get("registry_identity", {}).get("project_id") or "unknown"
    index_path = registry_root / str(project_id) / "PROJECT_INDEX.yaml"
    existing = load_yaml(index_path)
    index = build_project_index(profile, facts, existing)
    write_yaml(index_path, index)

    if args.print_summary:
        print_summary(profile, index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
