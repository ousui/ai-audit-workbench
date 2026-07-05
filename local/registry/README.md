# local/registry

`local/registry/` 是本地索引库，不提交。

## 结构

```text
local/registry/
  projects/   以仓库地址或项目标识为 key 的项目长期信息
  hosts/      本机环境画像、工具安装状态、适配检测结果
  tools/      工具规则库/缓存状态摘要、工具适配状态
  knowledge/  可复用的审计经验、误报记忆、业务风险判断
```

## 使用原则

索引库只能辅助审计，不允许覆盖当前代码事实。
事实优先级：人工本轮确认 > 当前代码和 manifest > 当前工具证据 > AI 当前推理 > 文档 > 本地索引历史。
