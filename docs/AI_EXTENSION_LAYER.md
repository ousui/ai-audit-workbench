# AI Extension / Plugin Layer

## 定位

AI Extension / Plugin Layer 是工作台的可选增强层，用于接入 Codex Security plugin、Claude Skill、Cursor Rule、自定义安全 Agent 等外部 AI 审计能力。

它不是 Tool Matrix 的替代品。

```text
Tool Matrix：稳定扫描器，偏事实输出，可回归
AI Extension：AI Agent / Plugin / Skill，偏链路分析、威胁建模、覆盖面、复核和候选增强
```

不用插件时，工作台仍能完成审计；使用插件时，结果应更精准、覆盖更全面。

## 为什么不直接放入工具矩阵

工具矩阵要求：

```text
输出稳定
可重复
适合自动化回归
适合做事实证据
```

AI 插件 / SKILL / Agent 的特点是：

```text
依赖模型推理
依赖当前 Agent 能力
依赖 prompt / skill / plugin 版本
结果非完全确定
但能补足传统工具不擅长的链路分析
```

因此插件层应作为独立层，输出进入 candidate、reviewer、coverage 或 threat-model，而不是直接混入 tool matrix。

## 插件类型

见 `spec/ai/extensions.yaml`。

```text
candidate_source     发现新候选
reviewer             审阅已有候选
threat_modeler        生成威胁模型提示
coverage_analyzer     分析覆盖面
adjudicator           分歧仲裁
validator             bounded validation / CHK 建议
report_enhancer       报告增强
```

## Codex Security plugin 的位置

Codex Security plugin 可作为：

```text
external candidate source
external reviewer
coverage analyzer
threat model hint source
benchmark / 对照组
```

后续预留导入入口：

```bash
make import-codex-security RUN_ROOT=... CODEX_SECURITY_SCAN_DIR=...
```

计划导入：

```text
report.md
scan-manifest.json
findings.json
coverage.json
SARIF / CSV
```

## 目录约定

运行期扩展结果建议放在：

```text
var/runs/<project>/<run>/ai/extensions/<extension_id>/EXTENSION_RESULT.json
```

示例：

```text
ai/extensions/codex-security/EXTENSION_RESULT.json
ai/extensions/claude-skill/EXTENSION_RESULT.json
ai/extensions/custom-agent/EXTENSION_RESULT.json
```

## 结果口径

Extension 输出必须声明：

```text
extension_id
extension_type
provider
agent_name
input_refs
output_refs
summary
limitations
candidate_refs / new_candidates / reviewer_results / coverage_refs / threat_model_refs
```

Extension 结果不能直接覆盖：

```text
当前代码事实
工具证据
人工确认
最终 FIND / FP / REVIEW 判断
```

必须经过 merge / triage / jury / human gate。

## 当前阶段不做

```text
不自动调用 AI CLI
不自动调用 AI API
不自动导入 Codex Security 输出
不自动 promote extension findings
不自动写知识库
```

当前只固定规范和接入点。
