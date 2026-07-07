# docs

`docs/` 存放给人阅读的工作台说明、设计记录、使用手册和迁移说明。

## 是否提交

提交到 Git。这里可以放设计文档、操作指南、流程解释，但不放程序必须读取的规则或 AI 执行提示词。

## 与 spec 的区别

- `docs/`：给人读，AI 也可以参考阅读。
- `spec/`：给程序和 AI Agent 在流程中执行读取的固定规范。

## 重点文档

```text
ROADMAP.md                         后续阶段路线图
AI_JURY_AND_QUALITY_GATE.md         AI Jury 与质量门禁设计
AI_EXTENSION_LAYER.md               AI 插件 / SKILL / Agent 扩展层设计
THREAT_MODEL_AND_COVERAGE.md        威胁模型、覆盖面和攻击路径设计
MAKE_TARGETS.md                     Makefile 目标说明
M15_4_AUDIT_LIFECYCLE_AND_TRIAGE.md M15.4 状态、triage 和知识库设计
```
