# spec/ai

`spec/ai/` 存放 AI 审计增强层的固定规范。

这里的内容会被程序、AI Agent 和人工审计员共同读取，用于约束 file-based AI triage、AI Jury、多模型/多插件扩展和后续 CLI/API adapter。

## 当前范围

```text
jury-profiles.yaml   AI Jury profile、reviewer 角色、推理级别和升级规则
extensions.yaml      AI Extension / Plugin Layer 的接入点和结果协议草案
```

## 分层原则

```text
Tool Matrix Layer          稳定工具，偏事实输出
AI Triage Layer            单次 AI 判断，生成 AI_TRIAGE_RESULT
AI Jury Layer              多 reviewer、多角色、一致性和仲裁
AI Extension Layer         Codex Security、Claude Skill、Cursor Rule、自定义 Agent 等增强来源
```

## 当前阶段

当前只固定规范和接入点，不自动调用 AI CLI，也不接 AI API。

默认实现仍是 file-based handoff：程序生成 prompt 和 JSON 输入，人工触发本地 AI 工具读取文件并写回结果。
