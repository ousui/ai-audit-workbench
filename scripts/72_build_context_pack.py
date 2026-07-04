#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_BYTES = 50000


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_relative(path: Path, base: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except Exception:
        return None


def example_request() -> dict[str, Any]:
    return {
        "schema_version": "context-request-0.1.0",
        "mode": "STANDARD_STATIC",
        "requests": [
            {
                "request_id": "CTX-0001",
                "candidate_id": "CAND-00001",
                "reason": "示例：需要确认候选项上下文和反证。复制为 ai/CONTEXT_REQUEST.json 后按需修改。",
                "files": [
                    {"path": "src/example/File.java", "line_start": 1, "line_end": 120, "max_bytes": 50000}
                ],
            }
        ],
        "notes": ["This is an example request. It is not used unless copied to ai/CONTEXT_REQUEST.json."],
    }


def read_requested_file(project_root: Path, file_req: dict[str, Any]) -> dict[str, Any]:
    rel_path = str(file_req.get("path") or "")
    max_bytes = int(file_req.get("max_bytes") or DEFAULT_MAX_BYTES)
    line_start = file_req.get("line_start")
    line_end = file_req.get("line_end")

    result: dict[str, Any] = {
        "path": rel_path,
        "status": "unknown",
        "line_start": line_start,
        "line_end": line_end,
        "content": "",
        "error": None,
    }

    if not rel_path:
        result.update({"status": "blocked", "error": "empty path"})
        return result

    target = (project_root / rel_path).resolve()
    if safe_relative(target, project_root) is None:
        result.update({"status": "blocked", "error": "path outside project root"})
        return result
    if not target.is_file():
        result.update({"status": "missing", "error": "file not found"})
        return result
    if target.stat().st_size > max_bytes and line_start is None:
        result.update({"status": "blocked", "error": f"file exceeds max_bytes={max_bytes}; request line range instead"})
        return result

    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        result.update({"status": "error", "error": str(exc)})
        return result

    lines = text.splitlines()
    if line_start is not None:
        start = max(1, int(line_start))
        end = int(line_end) if line_end is not None else min(len(lines), start + 120)
        end = max(start, min(len(lines), end))
        snippet = lines[start - 1:end]
        result["content"] = "\n".join(f"{idx}: {line}" for idx, line in enumerate(snippet, start=start))
        result["line_start"] = start
        result["line_end"] = end
    else:
        result["content"] = text[:max_bytes]
        result["line_start"] = 1 if lines else None
        result["line_end"] = len(lines) if len(text.encode("utf-8", errors="ignore")) <= max_bytes else None

    result["status"] = "included"
    return result


def build_context_pack(run_root: Path) -> dict[str, Any]:
    profile = load_json(run_root / "meta" / "PROJECT_PROFILE.json")
    pool_path = run_root / "candidates" / "CANDIDATE_POOL.json"
    pool = load_json(pool_path) if pool_path.is_file() else {"candidates": []}
    project_root = Path(profile["project_path"]["resolved"])
    ai_dir = run_root / "ai"
    request_path = ai_dir / "CONTEXT_REQUEST.json"
    example_path = ai_dir / "CONTEXT_REQUEST.example.json"
    ai_dir.mkdir(parents=True, exist_ok=True)

    if not example_path.is_file():
        write_json(example_path, example_request())

    if not request_path.is_file():
        return {
            "schema_version": "context-pack-0.1.0",
            "mode": "STANDARD_STATIC",
            "status": "no_request",
            "request_path": str(request_path.relative_to(ROOT)),
            "example_request_path": str(example_path.relative_to(ROOT)),
            "candidate_count": len(pool.get("candidates", [])),
            "contexts": [],
            "notes": ["No ai/CONTEXT_REQUEST.json found. Example request has been written for later use."],
        }

    request = load_json(request_path)
    contexts = []
    for req in request.get("requests", []):
        files = [read_requested_file(project_root, item) for item in req.get("files", [])]
        contexts.append({
            "request_id": req.get("request_id"),
            "candidate_id": req.get("candidate_id"),
            "reason": req.get("reason"),
            "files": files,
        })

    return {
        "schema_version": "context-pack-0.1.0",
        "mode": "STANDARD_STATIC",
        "status": "completed",
        "request_path": str(request_path.relative_to(ROOT)),
        "candidate_count": len(pool.get("candidates", [])),
        "contexts": contexts,
        "notes": ["Context pack is read-only and must not be treated as an audit conclusion."],
    }


def render_md(pack: dict[str, Any]) -> str:
    lines = ["# CONTEXT_PACK", "", f"- Mode: `{pack.get('mode')}`", f"- Status: `{pack.get('status')}`", f"- Candidate count: {pack.get('candidate_count')}", ""]
    if pack.get("notes"):
        lines.append("## Notes")
        lines.append("")
        for note in pack["notes"]:
            lines.append(f"- {note}")
        lines.append("")
    for ctx in pack.get("contexts", []):
        lines.extend([f"## {ctx.get('request_id')} candidate={ctx.get('candidate_id')}", "", f"Reason: {ctx.get('reason')}", ""])
        for item in ctx.get("files", []):
            lines.append(f"### {item.get('path')} [{item.get('status')}]")
            if item.get("error"):
                lines.append(f"Error: {item.get('error')}")
            if item.get("content"):
                lines.append("")
                lines.append("```text")
                lines.append(str(item.get("content")))
                lines.append("```")
            lines.append("")
    return "\n".join(lines)


def print_summary(pack: dict[str, Any]) -> None:
    print("context-pack summary")
    print(f"  status: {pack.get('status')}")
    print(f"  candidate_count: {pack.get('candidate_count')}")
    print(f"  contexts: {len(pack.get('contexts') or [])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build STANDARD_STATIC context pack from AI context request.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2

    pack = build_context_pack(run_root)
    out = run_root / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "CONTEXT_PACK.json", pack)
    (out / "CONTEXT_PACK.md").write_text(render_md(pack), encoding="utf-8")
    if args.print_summary:
        print_summary(pack)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
