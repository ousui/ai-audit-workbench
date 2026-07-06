# M15.4：Audit Lifecycle / Candidate Taxonomy / AI Triage

本阶段目标：将候选、AI triage、merge、报告和整改清单统一到稳定的审计生命周期模型中，避免状态含义分散或过度设计。

## 状态模型

当前固定为三类状态：

```text
audit_status          审计判断状态：风险是否成立、是否误报、是否需要运行时验证、是否审计受阻
business_status       业务反馈状态：业务方对 FIND 的反馈口径，M16 CHK 阶段正式使用
verification_status   审计复核状态：审计方 CHK 后的复核结论，M16 CHK 阶段正式使用
```

M15.4 主要落地 `audit_status`，并在整改 CSV 中预留 `business_status` / `verification_status`。

## audit_status

固定枚举：

```text
CAND
REVIEW
FIND
FP
RUNTIME
BLOCKED
```

`ACCEPTED_RISK` 不属于 audit_status。业务接受风险应在后续 CHK 阶段表达为：

```text
audit_status = FIND
business_status = NO_FIX_CLAIMED
verification_status = NO_FIX_CONFIRMED
resolution_reason = ACCEPTED_RISK
```

## Candidate Pool 规则

Candidate Pool 只收集候选，不直接生成最终结论。

允许初始状态：

```text
CAND
REVIEW
RUNTIME
BLOCKED
```

禁止初始状态：

```text
FIND
FP
```

每个 candidate 必须包含：

```text
candidate_id
status
risk_parent
risk_subtype
risk_type
severity_hint
confidence_hint
tags
lifecycle_events
```

## tags

tags 用于表达辅助特征，不替代状态。示例：

```text
needs_runtime
needs_manual_confirm
missing_context
missing_codegen
private_dependency
tool_blocked
engineering_governance
accepted_risk
track_next_round
```

## lifecycle_events

不实现复杂状态机，只记录关键事件。

M15.4 当前使用：

```text
candidate_created
audit_decision
```

M16 CHK 后续再使用：

```text
business_response
verification_decision
audit_reclassified
```

## AI triage

AI 只允许输出 audit_status：

```text
FIND
REVIEW
RUNTIME
CAND
FP
BLOCKED
```

AI 不允许输出：

```text
business_status
verification_status
ACCEPTED_RISK
NO_FIX_CONFIRMED
```

AI 可以输出 tags、questions_for_human、knowledge_update_suggestions，但知识库写入不在 M15.4 自动执行。

## Merge / Delivery

Merge 结果中：

- `status` 仍表示 audit_status。
- FIND 默认进入整改清单。
- FIND 的 `business_status` 默认 `PENDING`。
- FIND 的 `verification_status` 默认 `PENDING`。

整改 CSV 增加生命周期字段：

```text
finding_id
candidate_id
audit_status
business_status
verification_status
resolution_reason
risk_parent
risk_subtype
tags
```

## 验证

```bash
make py-compile
make verify-full
```

真实项目：

```bash
make audit-static \
  PROJECT_PATH=/path/to/project \
  PROJECT_CODE=LIFECYCLE_TEST \
  NETWORK_AUTHORIZATION=once \
  DRY_RUN=true

cat var/runs/LIFECYCLE_TEST/FAST_STATIC_*/candidates/CANDIDATE_POOL.md
cat var/runs/LIFECYCLE_TEST/FAST_STATIC_*/merge/MERGE_RESULT.md
head -1 var/runs/LIFECYCLE_TEST/FAST_STATIC_*/delivery/AUDIT_TRACKING.csv
```
