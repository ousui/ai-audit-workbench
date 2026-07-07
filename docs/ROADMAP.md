# Roadmap

本文档记录当前工作台后续落地方向，避免阶段推进中遗漏关键设计。

## 当前主线

```text
M15.4E-fix  AI Jury Profile + Quality Gate + Extension 接口占位
M15.4F      Delivery / Tracking / Report 交付视图收敛
M15.5       Threat Model + Coverage + Attack Path
M15.6       AI Extension / Plugin Layer 规范和导入占位
M16         CHK 复核、业务反馈、知识库人工确认
M17         DAST / REVERSE / bounded validation
M18         团队化、CLI adapter、CI/CD、插件导入和 issue tracking
```

## M15.4E-fix：AI Jury Profile + Quality Gate

目标：解决单次 AI triage 结构正确但语义不可靠的问题。

已完成：

```text
1. 定义 AI Jury profile：fast / balanced / deep / strong / cross_model_strong
2. 预留 AI Extension / Plugin Layer 接口
3. 实现 AI_TRIAGE_QUALITY_RESULT，拦截分布异常、模板化、低质量 FIND/FP/RUNTIME
4. 生成 reviewer prompt pack：balanced、risk_hunter、fp_skeptic、chain_verifier、adjudicator
5. 支持 reviewer 独立结果目录：ai/reviewers/<reviewer_id>/AI_TRIAGE_RESULT.json
6. 支持 consensus 输出：ai/consensus/AI_TRIAGE_CONSENSUS.json
7. 支持 disagreement / adjudication prompt
8. 支持 AI_TRIAGE_ADJUDICATION_RESULT.json 导入
9. 支持从 consensus/adjudication 生成最终 AI_TRIAGE_RESULT.json
10. 增加 ai-jury-status，方便查看 reviewer 完成情况和断点恢复
11. 强化 reviewer / adjudication prompt，减少全 REVIEW/CAND 低价值结果
12. finalizer 记录 decision distribution，并对低价值分布给出 warning 和重跑建议
```

待做：

```text
1. 将 ai-jury-status 接入更完整的调试/重跑向导
2. 增强 jury finalization 在 delivery 报告中的展示
```

## M15.4F：Delivery / Tracking 收敛

目标：让报告接近真实交付视图。

已完成：

```text
1. AUDIT_TRACKING.csv 默认只进入业务需要处理的内容：FIND / REVIEW / RUNTIME / BLOCKED
2. FP / CAND 不进入业务整改表，进入 AUDIT_QUALITY_ITEMS.csv
3. 新增 AUDIT_QUALITY_SUMMARY.json/md，记录业务交付、审计质量、AI quality gate、AI Jury 摘要
4. 报告增加业务交付概览、审计质量概览、FP/CAND 审计侧附录
5. 报告明确 STUB / file-based / AI Jury 的 triage 来源
6. 增加 delivery profile：默认字段、字段可配置、表格可开关、报告章节可配置
7. 增加 delivery-profile-validate，校验字段、状态范围、统计项和章节配置
8. 增加统计 CSV：按状态、风险级别、风险大类、风险大类+级别
9. 报告按 profile 输出执行摘要、统计表、业务明细和审计质量附录
```

待做：

```text
1. FIND 增加 root_control、sink、entrypoint、proof_gap、counterevidence 字段
2. 报告增加整改优先级 priority / suggested_owner / due_date_policy
3. 对 FP QC、REVIEW 高占比、Jury 分歧高占比增加醒目提示
4. 后续如需 xlsx/docx/pptx、Logo、主题样式，放入 M18 交付自动化
```

## M15.5：Threat Model + Coverage + Attack Path

目标：借鉴 Codex Security plugin 的审计思想，从“规则命中”升级为“证明或推翻安全 claim”。

待做：

```text
1. 生成 THREAT_MODEL.json / THREAT_MODEL.md
2. 生成 COVERAGE.json / COVERAGE.md
3. Candidate claim model：claim、attacker_source、entrypoint、trust_boundary、root_control、sink
4. Attack path fields：reachable_path、evidence_for、evidence_against、proof_gaps、validation_method
5. AI triage prompt / schema / merge / report 逐步接入这些字段
```

## M15.6：AI Extension / Plugin Layer

目标：预留 Codex Security、Claude Skill、Cursor Rule、自定义 Agent 等增强审计来源。

当前定位：

```text
不用插件：工作台仍可审计
使用插件：增强候选发现、链路分析、威胁模型、覆盖面和复核质量
```

待做：

```text
1. 固定 spec/ai/extensions.yaml
2. 设计 extension result contract
3. 预留 ai/extensions/<extension_id>/EXTENSION_RESULT.json
4. 预留 import-codex-security / ai-extension-import / ai-triage-run 入口
5. 暂不自动调用 AI CLI / AI API
```

## M16：CHK / 业务反馈 / 知识库确认

目标：正式启用 business_status、verification_status、resolution_reason。

待做：

```text
1. 导入业务反馈
2. 生成 CHK 复核输入
3. 验证修复是否有效
4. 记录 lifecycle_events
5. 经确认的 FP / accepted risk / deferred 进入 KB_UPDATE_SUGGESTIONS
6. 人工批准后写入 local/registry/knowledge/AUDIT_KNOWLEDGE.yaml
```

## 暂不做

```text
1. 自动调用 AI CLI
2. 自动调用 AI API
3. 自动 promote 知识库
4. 自动写入业务 issue / 工单
5. 自动执行危险 PoC 或动态验证
```

这些能力后续必须在日志脱敏、权限门禁、可回放、可撤销和人工审批稳定后再做。
