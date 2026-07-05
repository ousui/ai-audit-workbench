# spec/rules

`spec/rules/` 存放工作台规则、枚举和字典。

## 典型文件

```text
candidate-recipes.yaml    确定性静态候选生成规则
risk-taxonomy.yaml        风险分类和子类枚举
project-doc-fields.yaml   项目文档画像字段定义
```

## 原则

规则只生成候选或约束流程，不直接生成正式 FIND。正式问题必须经过 triage / merge / delivery。
