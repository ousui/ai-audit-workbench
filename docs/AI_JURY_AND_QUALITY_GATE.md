# AI Jury 与 Quality Gate

## 背景

单次 file-based AI triage 可以打通流程，但会出现结构正确、语义无效的结果，例如：

```text
大量 candidate 只沿用输入初始状态
FIND / FP / RUNTIME 全为 0
reason 模板化
FIND 没有 risk_chain / impact / negative_evidence_checked
FP 没有明确反证
```

因此需要在单次 AI triage 之上增加 AI Jury 和 Quality Gate。

## AI Jury 目标

```text
1. 让多个 reviewer 独立审计同一批 candidate
2. 通过一致性和分歧发现不稳定判断
3. 对高风险 FP、关键 FIND、分歧项做升级仲裁
4. 保留人工 file-based handoff，不自动调用 AI CLI/API
```

## Reviewer 角色

固定角色见 `spec/ai/jury-profiles.yaml`：

```text
balanced_auditor  平衡审计员
risk_hunter       漏报防御审计员
fp_skeptic        误报压制审计员
chain_verifier    链路验证审计员
adjudicator       仲裁员
```

## Profile

```text
fast                1 reviewer，用于调试和低风险快速审计
balanced            2 reviewers + on-demand adjudicator，日常默认
deep                3 reviewers + on-demand adjudicator，正式审计默认深度模式
strong              4 reviewers + on-demand adjudicator，高敏项目和交付前复核
cross_model_strong  4~5 reviewers，跨模型/跨插件/跨 Agent 对照
```

同一模型只堆更多 reviewer 收益有限。5 reviewer 更适合跨模型或跨插件，而不是同模型高/中/极高重复运行。

## 一致性原则

```text
全体 FIND 且证据强：可进入 FIND
多数 FIND 但存在 REVIEW/RUNTIME：进入 REVIEW 或仲裁
FIND vs FP：强分歧，必须仲裁
全体 FP 且有明确反证：可进入 FP，但高危 FP 仍可触发 QC
多数 RUNTIME：进入 RUNTIME，记录缺失运行时证据
无清晰结论：进入 REVIEW
```

## FP 质量保护

FP 不进入业务整改清单，但必须防止真实风险被错杀。

以下 FP 需要 QC：

```text
P0/P1 FP
高危 risk_parent FP
confidence=low
缺少 counterevidence / negative_evidence_checked
reason 过短或模板化
同类 FP 数量异常多
```

高危 risk_parent：

```text
CRYPTOGRAPHY_SECRETS
INPUT_INJECTION
ACCESS_CONTROL
AUTHENTICATION_SESSION
BUSINESS_LOGIC
FILE_OPERATION
DATA_PROTECTION_PRIVACY
```

## Quality Gate

Quality Gate 不替代人工判断，但可以拦截明显低质量 AI 输出。

当前已实现：

```text
scripts/77_review_ai_triage_quality.py
make ai-triage-quality RUN_ROOT=...
```

检查项：

```text
decision 分布异常
reason 重复率过高
reason 过短或模板化
AI 输出高度复刻输入初始 status
FIND 缺 evidence / risk_chain / impact / recommendation / negative_evidence_checked
FP 缺明确反证
RUNTIME 缺 missing_evidence 或 questions_for_human
高风险 FP 标记为 FP QC item
```

产物：

```text
ai/AI_TRIAGE_QUALITY_RESULT.json
ai/AI_TRIAGE_QUALITY_RESULT.md
```

`after-ai-triage` 会先执行 schema validation 和 quality gate；如果 quality gate 失败，不进入 merge / delivery。

STUB triage 仅用于流程验证，quality gate 会允许通过但写入 warning。

## 后续脚本计划

```text
scripts/78_build_ai_jury_prompts.py
scripts/79_merge_ai_jury_results.py
```

Makefile 计划：

```bash
make ai-jury-prompts RUN_ROOT=... AI_JURY_PROFILE=balanced
make ai-jury-merge RUN_ROOT=...
```
