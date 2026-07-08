# spec/rules

`spec/rules/` 存放工作台规则、枚举和字典。

## 典型文件

```text
candidate-recipes.yaml    确定性静态候选生成规则
risk-taxonomy.yaml        风险分类和子类枚举
audit-lifecycle.yaml      审计生命周期状态、业务反馈状态、复核状态、事件和标签规范
audit-knowledge.yaml      知识库结构、匹配规则、建议类型和人工门禁规范
project-doc-fields.yaml   项目文档画像字段定义
threat-model.yaml         Threat Model / Coverage 基础规则
```

## 原则

规则只生成候选或约束流程，不直接生成正式 FIND。正式问题必须经过 triage / merge / delivery。

`audit-lifecycle.yaml` 是状态口径唯一来源。`ACCEPTED_RISK` 不作为 audit_status；业务方不修、延期、转需求等信息在后续 CHK 阶段通过 business_status / verification_status / resolution_reason 表达。

`audit-knowledge.yaml` 是知识库口径来源。知识库命中只能辅助判断，不能覆盖当前代码事实和工具证据；AI 或脚本只能生成 `KB_UPDATE_SUGGESTIONS`，不得自动写入 `local/registry/knowledge/AUDIT_KNOWLEDGE.yaml`。

`threat-model.yaml` 是安全视角映射规则来源，只生成 assets / entrypoints / trust boundaries / coverage priorities，不直接证明漏洞成立。
