#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
JURY_SPEC = ROOT / "spec" / "ai" / "jury-profiles.yaml"

ROLE_GUIDANCE = {
    "balanced_auditor": [
        "平衡判断 FIND / FP / REVIEW / RUNTIME / CAND，不要过度激进，也不要把 REVIEW 当默认兜底。",
        "明显成立的安全问题要判 FIND；明显误报要判 FP；缺运行时输入或环境证据时才判 RUNTIME。",
        "每个判断都要写出 evidence_for、evidence_against、proof_gap 中的关键点，分别放入 evidence / negative_evidence_checked / missing_evidence / reason。",
    ],
    "risk_hunter": [
        "优先避免漏报，重点关注密钥、鉴权、注入、文件、资金、权限和业务链路。",
        "对高危 risk_parent 的 CAND/REVIEW 要尽量扩大上下文理解，寻找 source、sink、trust boundary 和 impact。",
        "明显硬编码凭据、可达的危险 sink、缺失鉴权的敏感操作，不能因为保守而降成 REVIEW。",
    ],
    "fp_skeptic": [
        "优先寻找反证，压制日志、变量名、配置 key、非 sink、不可达路径、测试代码、代码生成片段等误报。",
        "判 FP 时必须写清楚 counterevidence，不能只写“证据不足”。",
        "如果无法形成明确反证，不能为了压误报而 FP，应改为 REVIEW 或 RUNTIME。",
    ],
    "chain_verifier": [
        "重点分析入口点、source、sink、信任边界、可达性、控制点和 proof gap。",
        "优先补齐 risk_chain、negative_evidence_checked、missing_evidence 和 questions_for_human。",
        "如果需要调用方、环境变量、运行配置或业务权限边界才能判断，优先 RUNTIME 或 REVIEW，而不是 CAND。",
    ],
    "adjudicator": [
        "只处理分歧项、高风险 FP、关键 FIND 和质量门禁要求复核的条目。",
        "不要重新全量审计；聚焦争议点、证据质量和为什么接受或推翻 reviewer 判断。",
        "禁止把 high-risk low-action decision 简单映射为 CAND；高风险且证据不足时一般应为 REVIEW 或 RUNTIME。",
    ],
}

DECISION_CALIBRATION = [
    "FIND：当前静态证据足以证明风险成立，或至少可证明风险链路核心 source/sink/control/impact 成立。",
    "FP：存在明确反证，例如只是日志/变量名/非 DB SQL sink/不可达路径/测试样例/无外部输入/非敏感值。",
    "RUNTIME：静态证据显示风险可能存在，但必须依赖运行时配置、环境变量、权限边界、真实请求链路或调用方才能证明。",
    "REVIEW：需要人工业务上下文或跨模块设计判断；不能把 REVIEW 当作所有不确定项的默认出口。",
    "CAND：保留为低价值候选或证据极弱的待观察项；高风险项不要轻易落 CAND。",
    "BLOCKED：缺少关键文件、生成代码、私有依赖或工具执行受阻，导致无法完成判断。",
]

CATEGORY_CALIBRATION = [
    "硬编码密钥/Token/AK/SK/Secret：若不是测试假值、文档样例或明确无效值，优先 FIND；若是假值需 FP 并写反证。",
    "SQL/命令/模板注入：必须区分真实 sink 与日志、字符串常量、URL/Header、Redis/ES/Excel、代码生成文本。真实 sink 可达时 FIND；没有 sink 时 FP。",
    "文件路径/上传下载/解压：若缺少外部输入来源或路径规范化证据，优先 REVIEW/RUNTIME；已有可控 source 到危险 sink 时 FIND。",
    "鉴权/权限/业务逻辑：若敏感操作缺明显鉴权或权限边界，优先 REVIEW/FIND；需要业务规则确认时 REVIEW。",
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return value or "reviewer"


def profile_or_die(spec: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = spec.get("profiles") or {}
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        known = ", ".join(sorted(profiles.keys()))
        raise SystemExit(f"[FAIL] unknown AI jury profile: {profile_name}. Known: {known}")
    return profile


def reviewer_role_summary(spec: dict[str, Any], role: str) -> dict[str, Any]:
    roles = spec.get("reviewer_roles") or {}
    raw = roles.get(role) if isinstance(roles, dict) else {}
    return raw if isinstance(raw, dict) else {}


def reviewer_prompt(run_root: Path, triage_input: dict[str, Any], profile_name: str, reviewer: dict[str, Any], role_info: dict[str, Any], output_path: Path) -> str:
    reviewer_id = reviewer.get("id") or "reviewer"
    role = reviewer.get("role") or "balanced_auditor"
    reasoning = reviewer.get("reasoning") or "high"
    guidance = ROLE_GUIDANCE.get(role, ROLE_GUIDANCE["balanced_auditor"])
    candidate_count = len(triage_input.get("candidates") or [])
    output_rel = rel(output_path)
    input_rel = rel(run_root / "ai" / "AI_TRIAGE_INPUT.json")
    lines = [
        f"# AI Jury Reviewer Prompt: {reviewer_id}", "",
        "## Role", "",
        f"- Reviewer id: `{reviewer_id}`",
        f"- Role: `{role}`",
        f"- Role label: `{role_info.get('label_zh', role)}`",
        f"- Objective: {role_info.get('objective_zh', '')}",
        f"- Reasoning level: `{reasoning}`",
        f"- Jury profile: `{profile_name}`",
        f"- Candidate count: {candidate_count}", "",
        "## Model expectation", "",
        "本提示词面向高推理模型或强代码 Agent。请利用项目上下文做真实审计判断，不要用 REVIEW/CAND 批量兜底。", "",
        "## Independence rule", "",
        "你是独立 reviewer。你必须独立判断，不得读取其他 reviewer 的结果，不得读取 `ai/reviewers/*/AI_TRIAGE_RESULT.json`，也不得参考 consensus/adjudication 结果。", "",
        "## Files to read", "",
        "```text",
        input_rel,
        "spec/prompts/triage/FAST_STATIC.md",
        "spec/schemas/AI_TRIAGE_RESULT.schema.json",
        "spec/rules/audit-lifecycle.yaml",
        "spec/rules/audit-knowledge.yaml",
        "spec/ai/jury-profiles.yaml",
        "```", "",
        "## Output", "",
        "只允许写入以下文件，不要修改其他文件：", "",
        "```text",
        output_rel,
        "```", "",
        "## Review guidance", "",
    ]
    for item in guidance:
        lines.append(f"- {item}")
    lines.extend(["", "## Decision calibration", ""])
    for item in DECISION_CALIBRATION:
        lines.append(f"- {item}")
    lines.extend(["", "## Category calibration", ""])
    for item in CATEGORY_CALIBRATION:
        lines.append(f"- {item}")
    lines.extend([
        "", "## Evidence requirements", "",
        "每个非 CAND 判断都要尽量补齐：",
        "- `evidence`：支持当前 decision 的正向证据，包含关键文件、行号、代码片段或工具证据摘要。",
        "- `risk_chain`：source -> trust boundary/control -> sink -> impact；没有链路时写明缺口。",
        "- `negative_evidence_checked`：已经排除的误报可能，例如测试代码、日志、非 sink、不可达、固定假值等。",
        "- `missing_evidence`：还缺什么证据；RUNTIME/REVIEW 必须写清楚。",
        "- `reason`：为什么是这个 decision，而不是 FIND/FP/RUNTIME/REVIEW/CAND 中的其他状态。", "",
        "## Hard rules", "",
        "1. 只能使用 AI_TRIAGE_INPUT.json 中已有 candidate_id。",
        "2. 不得新增没有 candidate_id 的问题。",
        "3. decision 只能是 FIND / REVIEW / RUNTIME / CAND / FP / BLOCKED。",
        "4. 不得输出 business_status、verification_status、resolution_reason、ACCEPTED_RISK、NO_FIX_CONFIRMED。",
        "5. FIND 必须有 evidence、risk_chain、impact、recommendation、negative_evidence_checked、reason。",
        "6. FP 必须写清楚明确反证，不能只写“证据不足”。",
        "7. RUNTIME 必须说明需要什么运行时证据。",
        "8. REVIEW 必须说明需要什么人工上下文，不能作为默认兜底。",
        "9. CAND 只用于低价值或证据极弱候选；高风险项不要轻易判 CAND。",
        "10. knowledge_hits 只能作为辅助参考，不能覆盖当前代码事实和工具证据。",
        "11. 如果最终 FIND/FP/RUNTIME 全为 0，请在 notes 中解释为什么没有任何可成立、可排除或需要运行时验证的项。",
        "12. 输出必须是合法 JSON，不要在 JSON 外写解释。", "",
        "## Expected JSON skeleton", "",
        "```json",
        "{",
        "  \"schema_version\": \"ai-triage-result-0.2.0\",",
        "  \"triage_mode\": \"FAST_STATIC\",",
        "  \"items\": [],",
        "  \"knowledge_update_suggestions\": [],",
        f"  \"notes\": [\"AI Jury reviewer: {reviewer_id}\"]",
        "}",
        "```", "",
        "执行完成后停止，不要继续 merge，不要执行 after-ai-triage。",
    ])
    return "\n".join(lines) + "\n"


def orchestrator_prompt(run_root: Path, profile_name: str, profile: dict[str, Any], reviewer_outputs: list[dict[str, str]]) -> str:
    lines = [
        "# AI Jury Orchestrator Prompt", "",
        f"RUN_ROOT={run_root}",
        f"AI_JURY_PROFILE={profile_name}", "",
        "你现在执行 AI Jury reviewer prompt pack。", "",
        "## Goal", "",
        "让多个 reviewer 独立审计同一批 candidate，并分别写入自己的 AI_TRIAGE_RESULT.json。", "",
        "## Important independence rule", "",
        "每个 reviewer 必须独立判断，不能读取其他 reviewer 的输出。支持并行子代理时可以并行执行；不支持并行时顺序执行也可以，但要确保后一个 reviewer 不读取前一个 reviewer 的结果。", "",
        "## Resume rule", "",
        "如果额度耗尽或中断，不要重新生成整个 run。后续只需要继续未完成 reviewer 的 PROMPT.md。可运行 `make ai-jury-status RUN_ROOT=...` 查看缺失或无效结果。", "",
        "## Reviewer tasks", "",
    ]
    for item in reviewer_outputs:
        lines.append(f"- `{item['reviewer_id']}`: read `{item['prompt_path']}` and write `{item['result_path']}`")
    lines.extend([
        "", "## Files shared by all reviewers", "", "```text",
        rel(run_root / "ai" / "AI_TRIAGE_INPUT.json"),
        "spec/prompts/triage/FAST_STATIC.md",
        "spec/schemas/AI_TRIAGE_RESULT.schema.json",
        "spec/rules/audit-lifecycle.yaml",
        "spec/rules/audit-knowledge.yaml",
        "spec/ai/jury-profiles.yaml",
        "```", "",
        "## Stop condition", "",
        "所有 reviewer 的结果文件写入后停止。不要合并结果，不要写最终 `ai/AI_TRIAGE_RESULT.json`，不要执行 after-ai-triage。", "",
        "后续由工作台执行 consensus / adjudication / finalize / delivery。",
    ])
    return "\n".join(lines) + "\n"


def summary_md(result: dict[str, Any]) -> str:
    lines = [
        "# AI_JURY_PROMPT_PACK", "",
        f"- Profile: `{result['profile']}`",
        f"- Reviewers: {len(result['reviewers'])}",
        f"- Candidate count: {result['candidate_count']}",
        f"- Orchestrator prompt: `{result['orchestrator_prompt']}`", "",
        "## Reviewers", "",
        "| Reviewer | Role | Reasoning | Prompt | Output |",
        "|---|---|---|---|---|",
    ]
    for r in result["reviewers"]:
        lines.append(f"| `{r['reviewer_id']}` | `{r['role']}` | `{r['reasoning']}` | `{r['prompt_path']}` | `{r['result_path']}` |")
    lines.append("")
    return "\n".join(lines)


def build_prompts(run_root: Path, profile_name: str) -> dict[str, Any]:
    triage_input_path = run_root / "ai" / "AI_TRIAGE_INPUT.json"
    if not triage_input_path.is_file():
        raise SystemExit("[FAIL] AI_TRIAGE_INPUT.json not found. Run ai-triage-input first.")
    triage_input = load_json(triage_input_path)
    spec = load_yaml(JURY_SPEC)
    profile = profile_or_die(spec, profile_name)
    reviewers = profile.get("reviewers") or []
    if not isinstance(reviewers, list) or not reviewers:
        raise SystemExit(f"[FAIL] profile has no reviewers: {profile_name}")
    jury_dir = run_root / "ai" / "jury"
    reviewer_outputs: list[dict[str, str]] = []
    for raw in reviewers:
        if not isinstance(raw, dict):
            continue
        reviewer_id = slug(str(raw.get("id") or "reviewer"))
        role = str(raw.get("role") or "balanced_auditor")
        reviewer_dir = run_root / "ai" / "reviewers" / reviewer_id
        prompt_path = reviewer_dir / "PROMPT.md"
        result_path = reviewer_dir / "AI_TRIAGE_RESULT.json"
        reviewer_dir.mkdir(parents=True, exist_ok=True)
        prompt = reviewer_prompt(run_root, triage_input, profile_name, raw, reviewer_role_summary(spec, role), result_path)
        prompt_path.write_text(prompt, encoding="utf-8")
        reviewer_outputs.append({
            "reviewer_id": reviewer_id,
            "role": role,
            "reasoning": str(raw.get("reasoning") or "high"),
            "prompt_path": rel(prompt_path),
            "result_path": rel(result_path),
        })
    jury_dir.mkdir(parents=True, exist_ok=True)
    orchestrator_path = run_root / "ai" / "AI_JURY_ORCHESTRATOR_PROMPT.md"
    orchestrator_path.write_text(orchestrator_prompt(run_root, profile_name, profile, reviewer_outputs), encoding="utf-8")
    result = {
        "schema_version": "ai-jury-prompt-pack-0.2.0",
        "generated_at": now(),
        "profile": profile_name,
        "profile_spec_ref": "spec/ai/jury-profiles.yaml",
        "candidate_count": len(triage_input.get("candidates") or []),
        "triage_input_ref": rel(triage_input_path),
        "orchestrator_prompt": rel(orchestrator_path),
        "reviewers": reviewer_outputs,
        "adjudication": profile.get("adjudication") or {},
        "notes": [
            "Reviewer prompts are for independent file-based AI handoff.",
            "Do not let reviewers read each other's outputs before producing their own result.",
            "REVIEW is not a default fallback; low-value all REVIEW/CAND outputs should be rerun with stronger reasoning.",
            "This step only generates prompts; consensus merge is a later step.",
        ],
    }
    write_json(jury_dir / "AI_JURY_PROMPT_PACK.json", result)
    (jury_dir / "AI_JURY_PROMPT_PACK.md").write_text(summary_md(result), encoding="utf-8")
    return result


def print_summary(result: dict[str, Any]) -> None:
    print("ai-jury-prompts summary")
    print(f"  profile: {result['profile']}")
    print(f"  reviewers: {len(result['reviewers'])}")
    print(f"  candidates: {result['candidate_count']}")
    print(f"  orchestrator: {result['orchestrator_prompt']}")
    for r in result["reviewers"]:
        print(f"  reviewer: {r['reviewer_id']} role={r['role']} reasoning={r['reasoning']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build AI Jury reviewer prompt pack for file-based handoff.")
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--profile", default="balanced")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)
    run_root = Path(args.run_root)
    if not run_root.is_absolute():
        run_root = (ROOT / run_root).resolve()
    if not run_root.is_dir():
        print(f"[FAIL] run root does not exist: {run_root}", file=sys.stderr)
        return 2
    try:
        result = build_prompts(run_root, args.profile)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.print_summary:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
