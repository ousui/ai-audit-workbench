#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict[str, Any]:
    return load_json(path) if path.is_file() else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def limited(items: Any, limit: int = 80) -> list[Any]:
    if not isinstance(items, list):
        return []
    return items[:limit]


def file_bucket(audit_map: dict[str, Any], name: str, limit: int = 80) -> dict[str, Any]:
    raw = ((audit_map.get("files") or {}).get(name) or {})
    return {
        "count": raw.get("count", 0),
        "emitted_count": raw.get("emitted_count", len(raw.get("items") or [])),
        "items": limited(raw.get("items") or [], limit),
    }


def signal_bucket(audit_map: dict[str, Any], name: str, limit: int = 80) -> dict[str, Any]:
    raw = ((audit_map.get("signals") or {}).get(name) or {})
    return {
        "count": raw.get("count", 0),
        "emitted_count": raw.get("emitted_count", len(raw.get("items") or [])),
        "items": limited(raw.get("items") or [], limit),
    }


def candidate_summary(pool: dict[str, Any]) -> dict[str, Any]:
    summary = pool.get("summary") or {}
    candidates = pool.get("candidates") or []
    focus = []
    for item in candidates[:120]:
        focus.append({
            "candidate_id": item.get("candidate_id"),
            "status": item.get("status"),
            "risk_parent": item.get("risk_parent"),
            "risk_subtype": item.get("risk_subtype"),
            "severity_hint": item.get("severity_hint"),
            "title": item.get("title"),
            "file_path": item.get("file_path"),
            "line_start": item.get("line_start"),
            "evidence": item.get("evidence"),
        })
    return {
        "total_candidates": summary.get("total_candidates", len(candidates)),
        "by_status": summary.get("by_status") or {},
        "by_risk_parent": summary.get("by_risk_parent") or {},
        "focus_candidates": focus,
    }


def build_input(run_root: Path, max_new_candidates: int) -> dict[str, Any]:
    audit_map = load_json(run_root / "audit-map" / "AUDIT_MAP.json")
    facts = load_optional_json(run_root / "audit-map" / "PROJECT_FACTS.json")
    doc_profile = load_optional_json(run_root / "audit-map" / "PROJECT_DOC_PROFILE.json")
    pool = load_optional_json(run_root / "candidates" / "CANDIDATE_POOL.json")
    kb_hits = load_optional_json(run_root / "knowledge" / "KB_HITS.json")
    threat_model = load_optional_json(run_root / "threat" / "THREAT_MODEL.json")
    coverage = load_optional_json(run_root / "coverage" / "COVERAGE_MAP.json")
    return {
        "schema_version": "ai-deep-review-input-0.1.0",
        "generated_at": now(),
        "review_mode": "AI_DEEP_REVIEW",
        "scope": "static_deep_review_candidate_discovery_only",
        "run": audit_map.get("run") or {},
        "project": audit_map.get("project") or {},
        "source_refs": {
            "audit_map": "audit-map/AUDIT_MAP.json",
            "project_facts": "audit-map/PROJECT_FACTS.json" if facts else None,
            "project_doc_profile": "audit-map/PROJECT_DOC_PROFILE.json" if doc_profile else None,
            "candidate_pool": "candidates/CANDIDATE_POOL.json" if pool else None,
            "kb_hits": "knowledge/KB_HITS.json" if kb_hits else None,
            "threat_model": "threat/THREAT_MODEL.json" if threat_model else None,
            "coverage_map": "coverage/COVERAGE_MAP.json" if coverage else None,
            "result_schema": "spec/schemas/AI_DEEP_REVIEW_RESULT.schema.json",
        },
        "policy": {
            "static_only": True,
            "no_dynamic_testing": True,
            "no_reverse_analysis": True,
            "read_only_project": True,
            "do_not_modify_code": True,
            "output_candidates_only": True,
            "must_not_output_final_find_or_fp": True,
            "max_new_candidates": max_new_candidates,
        },
        "review_scope": {
            "primary_goal": "像人工审计一样主动翻阅代码、接口、上下游链路和关键业务模块，补充工具未发现的潜在候选风险。",
            "not_goal": "不要对已有候选做最终 FIND/FP 裁决；不要输出业务整改结论；不要执行 PoC 或动态验证。",
            "focus_directions": [
                "入口与路由：controller / handler / router / api / rpc / admin",
                "鉴权与权限：login / token / session / middleware / permission / role / rbac",
                "敏感业务链路：order / payment / wallet / user / admin / callback / approve",
                "输入到危险 sink：SQL / command / template / file / upload / download / redirect",
                "文件与对象存储：path / upload / download / unzip / oss / s3 / minio",
                "外部回调与异步任务：webhook / mq / cron / callback / consumer",
                "配置与密钥：config / env / secret / token / ak / sk",
            ],
        },
        "threat_model_summary": {
            "summary": threat_model.get("summary") or {},
            "assets": limited(threat_model.get("assets") or [], 60),
            "entrypoints": limited(threat_model.get("entrypoints") or [], 60),
            "trust_boundaries": limited(threat_model.get("trust_boundaries") or [], 60),
            "review_focus": limited(threat_model.get("review_focus") or [], 80),
        },
        "coverage_summary": {
            "summary": coverage.get("summary") or {},
            "dimensions": limited(coverage.get("dimensions") or [], 80),
            "risk_parent_coverage": limited(coverage.get("risk_parent_coverage") or [], 80),
            "coverage_gaps": limited(coverage.get("coverage_gaps") or [], 80),
            "ai_deep_review_priorities": limited(coverage.get("ai_deep_review_priorities") or [], 80),
        },
        "candidate_summary": candidate_summary(pool),
        "audit_map_focus": {
            "route_files": file_bucket(audit_map, "route_files"),
            "auth_files": file_bucket(audit_map, "auth_files"),
            "data_access_files": file_bucket(audit_map, "data_access_files"),
            "file_io_files": file_bucket(audit_map, "file_io_files"),
            "high_risk_modules": file_bucket(audit_map, "high_risk_modules"),
            "configs": file_bucket(audit_map, "configs"),
            "route_hits": signal_bucket(audit_map, "route_hits"),
            "frontend_api_hits": signal_bucket(audit_map, "frontend_api_hits"),
            "local_storage_hits": signal_bucket(audit_map, "local_storage_hits"),
        },
        "knowledge_summary": {
            "total_hits": (kb_hits.get("summary") or {}).get("total_hits", 0),
            "hits_by_candidate": limited(kb_hits.get("hits") or [], 80),
        },
        "expected_output": {
            "path": "ai/deep-review/AI_DEEP_REVIEW_RESULT.json",
            "schema_version": "ai-deep-review-result-0.1.0",
            "validator": "make ai-deep-review-validate RUN_ROOT=...",
        },
    }


def render_prompt(run_root: Path, data: dict[str, Any]) -> str:
    input_ref = rel(run_root / "ai" / "deep-review" / "AI_DEEP_REVIEW_INPUT.json")
    output_ref = rel(run_root / "ai" / "deep-review" / "AI_DEEP_REVIEW_RESULT.json")
    schema_ref = "spec/schemas/AI_DEEP_REVIEW_RESULT.schema.json"
    return f"""# AI Deep Review Prompt

RUN_ROOT={run_root}

你现在执行 **AI Deep Review / AI 静态深度审计 / AI 链路审计**。

## 目标

像人工安全审计一样主动翻阅项目代码、接口、上下游调用链、关键业务模块和安全控制点，发现工具扫描没有覆盖到的潜在候选风险。

这是 **候选发现阶段**，不是最终审计裁决阶段。

## 必读文件

```text
{input_ref}
{schema_ref}
```

你可以根据 `AI_DEEP_REVIEW_INPUT.json` 中的 `source_refs`、`audit_map_focus`、`threat_model_summary`、`coverage_summary` 和 `candidate_summary` 去读取项目源码和相关产物。

## 输出文件

只允许写入：

```text
{output_ref}
```

## 强约束

1. 只做静态代码审计，不做动态请求、不执行 PoC、不改代码。
2. 只输出新的候选风险，不输出最终 FIND / FP / REVIEW / RUNTIME 裁决。
3. 不要复述所有已有候选；只有当你通过链路阅读发现了新的风险主张或明显加强了已有线索，才输出 item。
4. 每个 item 必须包含 `claim`、`evidence`、`evidence_for`、`proof_gaps`。
5. 如果只是可疑但缺关键证据，也可以输出候选，但必须写清楚 `proof_gaps`。
6. 不要把覆盖不足本身当漏洞；覆盖不足只能作为你深入阅读的方向。
7. 输出必须是合法 JSON，不能在 JSON 外写解释。

## 优先审计方向

- HTTP/API 入口到鉴权/权限边界。
- 管理后台、用户、订单、支付、钱包、提现、回调等高风险业务链路。
- 外部输入进入 SQL、文件、命令、模板、重定向、对象存储等 sink 的路径。
- 上传、下载、解压、导入导出和对象存储路径处理。
- webhook、callback、consumer、cron、MQ 等异步入口。
- 配置、密钥、token、AK/SK、环境变量和默认配置。

## 输出 JSON 骨架

```json
{{
  "schema_version": "ai-deep-review-result-0.1.0",
  "review_mode": "AI_DEEP_REVIEW",
  "items": [
    {{
      "deep_review_id": "DR-00001",
      "risk_type": "ai_deep_review_candidate",
      "risk_parent": "ACCESS_CONTROL",
      "risk_subtype": "AUTHORIZATION_BYPASS_REVIEW",
      "title": "候选标题",
      "severity_hint": "P2",
      "confidence_hint": "medium",
      "file_path": "path/to/file.go",
      "line_start": 123,
      "line_end": 123,
      "claim": "风险主张：攻击者可能通过...",
      "entrypoint": "入口点或调用链起点",
      "attacker_source": "攻击者可控输入来源",
      "trust_boundary": "跨越的信任边界",
      "sink": "危险操作或安全控制点",
      "evidence": "核心证据摘要",
      "risk_chain": "source -> trust_boundary/control -> sink -> impact",
      "impact": "潜在影响",
      "evidence_for": ["支持风险成立的证据"],
      "evidence_against": ["已检查但削弱风险的反证"],
      "proof_gaps": ["还缺什么证据"],
      "suggested_validation_method": "后续如何验证",
      "tags": ["ai_deep_review", "chain_analysis"],
      "notes": []
    }}
  ],
  "knowledge_update_suggestions": [],
  "notes": []
}}
```

完成后停止，不要运行 merge，不要运行 delivery。
"""


def print_summary(data: dict[str, Any]) -> None:
    coverage = data.get("coverage_summary") or {}
    print("ai-deep-review-input summary")
    print(f"  output: ai/deep-review/AI_DEEP_REVIEW_INPUT.json")
    print(f"  prompt: ai/deep-review/AI_DEEP_REVIEW_PROMPT.md")
    print(f"  max_new_candidates: {(data.get('policy') or {}).get('max_new_candidates')}")
    print(f"  priorities: {len(coverage.get('ai_deep_review_priorities') or [])}")
    print(f"  coverage_gaps: {len(coverage.get('coverage_gaps') or [])}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Prepare AI Deep Review file-based handoff input and prompt.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--max-new-candidates", type=int, default=50)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    required = [
        run_root / "audit-map" / "AUDIT_MAP.json",
        run_root / "candidates" / "CANDIDATE_POOL.json",
        run_root / "threat" / "THREAT_MODEL.json",
        run_root / "coverage" / "COVERAGE_MAP.json",
    ]
    missing = [rel(x) for x in required if not x.is_file()]
    if missing:
        print("[FAIL] missing required input: " + ", ".join(missing), file=sys.stderr)
        return 2
    data = build_input(run_root, args.max_new_candidates)
    out = run_root / "ai" / "deep-review"
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "AI_DEEP_REVIEW_INPUT.json", data)
    (out / "AI_DEEP_REVIEW_PROMPT.md").write_text(render_prompt(run_root, data), encoding="utf-8")
    if args.print_summary:
        print_summary(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
