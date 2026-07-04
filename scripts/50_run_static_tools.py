#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {
    ".git", ".idea", ".vscode", ".cache", ".venv", "venv",
    "node_modules", "vendor", "Pods", "build", "dist", "target", "coverage", "tmp", "logs",
}

FALLBACK_RECIPES = [
    {
        "recipe_id": "SECRET_KEYWORD",
        "title": "疑似敏感信息关键字",
        "risk_type": "sensitive_information",
        "severity_hint": "P1",
        "confidence_hint": "medium",
        "include_exts": [".env", ".properties", ".yml", ".yaml", ".json", ".js", ".ts", ".java", ".go", ".php", ".py", ".dart", ".swift", ".kt"],
        "patterns": ["password", "passwd", "pwd", "secret", "api_key", "apikey", "access_key", "private_key", "token", "jwt"],
        "negative_evidence_required": ["是否只是变量名、注释、示例或测试数据", "是否包含真实值或可用凭据", "是否已通过安全配置注入"],
    },
    {
        "recipe_id": "SQL_DYNAMIC_CONSTRUCTION",
        "title": "疑似动态 SQL 构造",
        "risk_type": "sql_injection_candidate",
        "severity_hint": "P1",
        "confidence_hint": "medium",
        "include_exts": [".go", ".java", ".xml", ".php", ".py", ".js", ".ts"],
        "patterns": ["fmt.Sprintf", "whereRaw", "DB::raw", "createNativeQuery", "Statement", "${", "ORDER BY"],
        "negative_evidence_required": ["参数是否来自用户输入", "是否使用参数化查询", "动态字段是否有白名单"],
    },
]

TEXT_EXTS = {
    ".go", ".java", ".kt", ".php", ".py", ".js", ".jsx", ".ts", ".tsx", ".vue",
    ".dart", ".swift", ".cs", ".rs", ".rb", ".json", ".yaml", ".yml", ".toml", ".xml",
    ".properties", ".env", ".ini", ".conf", ".config", ".sql", ".md", ".txt",
}

SENSITIVE_WORDS = ["password", "passwd", "pwd", "secret", "token", "api_key", "apikey", "access_key", "private_key", "authorization", "cookie", "session", "jwt"]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
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


def redact(text: str) -> str:
    value = text.strip()
    for word in SENSITIVE_WORDS:
        value = re.sub(rf"({re.escape(word)}\s*[:=]\s*)[^\s,;]+", rf"\1<REDACTED>", value, flags=re.I)
    value = re.sub(r"Bearer\s+[A-Za-z0-9._=-]+", "Bearer <REDACTED>", value, flags=re.I)
    return value[:260]


def safe_read(path: Path, max_size: int) -> str | None:
    try:
        if path.stat().st_size > max_size:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def load_recipes(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    if not path.is_file():
        return FALLBACK_RECIPES, ["rules/recipes.yaml not found; using fallback recipes."]
    try:
        import yaml  # type: ignore
    except Exception:
        return FALLBACK_RECIPES, ["PyYAML unavailable; using fallback recipes."]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    recipes = data.get("recipes") or []
    if not recipes:
        return FALLBACK_RECIPES, ["No recipes found; using fallback recipes."]
    return recipes, notes


def filename_matches(path: Path, patterns: list[str]) -> bool:
    return any(re.search(pattern, path.name) for pattern in patterns)


def recipe_applies(recipe: dict[str, Any], path: Path) -> bool:
    filename_patterns = recipe.get("filename_patterns") or []
    if filename_patterns and filename_matches(path, filename_patterns):
        return True
    include_exts = recipe.get("include_exts") or []
    if include_exts:
        return path.suffix.lower() in set(include_exts)
    return path.suffix.lower() in TEXT_EXTS or path.name.startswith(".env")


def scan_project(project: Path, recipes: list[dict[str, Any]], max_file_size: int, per_recipe_limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    recipe_counts = {recipe["recipe_id"]: {"matched_count": 0, "emitted_count": 0, "truncated_count": 0} for recipe in recipes}
    files_scanned = 0
    files_skipped = 0

    for path in project.rglob("*"):
        if not path.is_file() or excluded(path, project):
            continue
        if path.suffix.lower() not in TEXT_EXTS and not path.name.startswith(".env"):
            continue
        text = safe_read(path, max_file_size)
        if text is None:
            files_skipped += 1
            continue
        files_scanned += 1
        lines = text.splitlines()
        for recipe in recipes:
            if not recipe_applies(recipe, path):
                continue
            rid = recipe["recipe_id"]
            patterns = recipe.get("patterns") or []
            for line_no, line in enumerate(lines, start=1):
                matched_pattern = None
                for pattern in patterns:
                    if pattern == ".*" and path.name.startswith(".env"):
                        matched_pattern = pattern
                        break
                    if re.search(re.escape(str(pattern)), line, flags=re.I):
                        matched_pattern = pattern
                        break
                if matched_pattern is None:
                    continue
                recipe_counts[rid]["matched_count"] += 1
                if recipe_counts[rid]["emitted_count"] >= per_recipe_limit:
                    recipe_counts[rid]["truncated_count"] += 1
                    continue
                source = f"{rid}|{rel(path, project)}|{line_no}|{redact(line)}"
                hits.append({
                    "hit_id": "HIT-" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:12],
                    "recipe_id": rid,
                    "title": recipe.get("title"),
                    "risk_type": recipe.get("risk_type"),
                    "severity_hint": recipe.get("severity_hint", "P2"),
                    "confidence_hint": recipe.get("confidence_hint", "medium"),
                    "file_path": rel(path, project),
                    "line_start": line_no,
                    "line_end": line_no,
                    "matched_pattern": str(matched_pattern),
                    "evidence_preview": redact(line),
                    "negative_evidence_required": recipe.get("negative_evidence_required") or [],
                    "source": "static_pattern_scan",
                })
                recipe_counts[rid]["emitted_count"] += 1
    return hits, {"files_scanned": files_scanned, "files_skipped": files_skipped, "recipe_summary": recipe_counts}


def render_md(result: dict[str, Any]) -> str:
    lines = [
        "# TOOL_RUN_RESULT", "",
        "## Summary", "",
        f"- Status: `{result['summary']['status']}`",
        f"- Files scanned: {result['summary']['files_scanned']}",
        f"- Files skipped: {result['summary']['files_skipped']}",
        f"- Total hits: {result['summary']['total_hits']}", "",
        "## Recipe summary", "",
        "| Recipe | Matched | Emitted | Truncated |",
        "|---|---:|---:|---:|",
    ]
    for rid, item in result.get("recipe_summary", {}).items():
        lines.append(f"| `{rid}` | {item['matched_count']} | {item['emitted_count']} | {item['truncated_count']} |")
    lines.extend(["", "## Hit preview", ""])
    for hit in result.get("hits", [])[:80]:
        lines.append(f"- `{hit['hit_id']}` `{hit['file_path']}:{hit['line_start']}` {hit['title']} — {hit['evidence_preview']}")
    if not result.get("hits"):
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def print_summary(result: dict[str, Any]) -> None:
    print("tool-run summary")
    print(f"  status: {result['summary']['status']}")
    print(f"  files_scanned: {result['summary']['files_scanned']}")
    print(f"  files_skipped: {result['summary']['files_skipped']}")
    print(f"  total_hits: {result['summary']['total_hits']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic static pattern scan.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--recipes", default="rules/recipes.yaml")
    parser.add_argument("--max-file-size", type=int, default=1024 * 1024)
    parser.add_argument("--per-recipe-limit", type=int, default=300)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    pack_path = run_root / "evidence" / "EVIDENCE_PACK.json"
    if not pack_path.is_file():
        print("[FAIL] EVIDENCE_PACK.json not found. Run make m4 first.", file=sys.stderr)
        return 2
    pack = load_json(pack_path)
    project_path = Path(pack["project"]["project_path"]["resolved"])
    if not project_path.is_dir():
        print(f"[FAIL] project path unavailable: {project_path}", file=sys.stderr)
        return 2

    recipes, notes = load_recipes((ROOT / args.recipes).resolve() if not Path(args.recipes).is_absolute() else Path(args.recipes))
    hits, stats = scan_project(project_path, recipes, args.max_file_size, args.per_recipe_limit)
    out_dir = run_root / "evidence"
    raw_dir = out_dir / "tool-outputs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(raw_dir / "STATIC_PATTERN_HITS.json", hits)
    result = {
        "schema_version": "tool-run-result-0.1.0",
        "generated_at": now(),
        "run": pack.get("run"),
        "mode": "deterministic_static_pattern_scan",
        "summary": {"status": "completed", "files_scanned": stats["files_scanned"], "files_skipped": stats["files_skipped"], "total_hits": len(hits)},
        "recipe_summary": stats["recipe_summary"],
        "hits": hits,
        "notes": notes,
    }
    write_json(out_dir / "TOOL_RUN_RESULT.json", result)
    (out_dir / "TOOL_RUN_RESULT.md").write_text(render_md(result), encoding="utf-8")
    if args.print_summary:
        print_summary(result)
    else:
        print(f"tool run result written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
