# var/runs

`var/runs/` 存放每次审计 run 的完整产物，不提交。

每个 run 应包含：

```text
meta/       运行元信息和人工确认
study-map/  审计地图
# 实际目录当前仍使用 audit-map/，后续迁移再统一命名
evidence/   工具证据和证据包
candidates/ 候选池
ai/         AI 输入输出
merge/      合并结果
delivery/   报告和整改追踪表
validate/   校验结果
debug/      调试和 trace
```

run 产物用于审计追溯，不应提交到工作台仓库。
