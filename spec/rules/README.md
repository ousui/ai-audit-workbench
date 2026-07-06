# spec/rules

`spec/rules/` 存放工作台规则、枚举和字典。

## 典型文件

```text
candidate-recipes.yaml    确定性静态候选生成规则
risk-taxonomy.yaml        风险分类和子类枚举
audit-lifecycle.yaml      审计生命周期状态、业务反馈状态、复核状态、事件和标签规范
project-doc-fields.yaml   项目文档画像字段定义
```

## 原则

规则只生成候选或约束流程，不直接生成正式 FIND。正式问题必须经过 triage / merge / delivery。

`audit-lifecycle.yaml` 是状态口径唯一来源。`ACCEPTED_RISK` 不作为 audit_status；业务方不修、延期、转需求等信息在后续 CHK 阶段通过 business_status / verification_status / resolution_reason 表达。
