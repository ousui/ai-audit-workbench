# spec

`spec/` 存放工作台的流程规范、规则、协议和 AI 提示词，是程序和 AI Agent 共同读取的“固定定义区”。

## 是否提交

提交到 Git。这里不允许放本地路径、客户项目信息、审计运行产物或密钥。

## 结构

```text
spec/
  env/        工具矩阵、安装建议、环境检测相关规范
  rules/      候选生成规则、风险分类、项目字段字典、工具门禁规则
  ai/         AI Jury、AI Extension、AI CLI/API adapter 预留规范
  schemas/    JSON Schema、AI 输出协议、流程产物协议
  prompts/    AI Agent 在流程中使用的提示词模板
  workflows/  正式审计流程、阶段顺序、状态机定义
  debug/      调试、追踪、回放相关规范
```

## 读取者

- 程序：读取规则、schema、工具矩阵和工作流定义。
- AI Agent：读取提示词、规则说明和流程边界。
- 人：维护规范和审核变更。
