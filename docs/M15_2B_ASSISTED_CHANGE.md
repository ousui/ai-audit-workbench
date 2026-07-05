# M15.2B：Audit Assisted Change

本阶段目标：在人工授权后，允许工作台执行不改变业务逻辑的审计辅助性变更，使被阻断的工具可以继续运行；执行完成后必须 reset 回初始状态，并保留完整记录。

## 当前支持的 assisted change

```text
swag_init    针对 Go 项目缺失 Swagger/swag docs 包导致 go list ./... 失败的场景
none         默认值，不执行任何辅助变更
```

## 安全边界

- 默认不修改项目。
- 只有显式设置 `ASSISTED_CHANGE=swag_init` 才会执行 `swag init`。
- 执行前要求项目是 Git worktree，并且工作区干净。
- 执行后记录变更路径、命令输出、验证结果。
- 外部工具执行完成后自动 reset 这次辅助变更。
- 如果流程失败，会尽量先执行 reset，再退出。

## 新增产物

```text
evidence/assisted-change/ASSISTED_CHANGE_LOG.json
evidence/assisted-change/ASSISTED_CHANGE_LOG.md
evidence/assisted-change/ASSISTED_CHANGE_RESET.json
evidence/assisted-change/ASSISTED_CHANGE_RESET.md
candidates/ENGINEERING_GOVERNANCE_CANDIDATES.json
candidates/ENGINEERING_GOVERNANCE_CANDIDATES.md
```

## 运行方式

完整流程：

```bash
make audit-static \
  PROJECT_PATH=/path/to/go-project \
  PROJECT_CODE=GO_ASSISTED_CHANGE_TEST \
  NETWORK_AUTHORIZATION=once \
  ASSISTED_CHANGE=swag_init \
  DRY_RUN=true
```

单步调试：

```bash
make preflight RUN_ROOT=...
make assisted-change RUN_ROOT=... ASSISTED_CHANGE=swag_init
make preflight RUN_ROOT=...
make tool-execution-plan RUN_ROOT=...
make assisted-change-reset RUN_ROOT=...
```

## 预期行为

缺少 docs 时：

1. 第一次 preflight 发现 `go-package-load = blocked_requires_context`。
2. assisted-change 执行 `swag init`。
3. 第二次 preflight 重新执行 `go list ./...`。
4. 如果成功，`govulncheck` / `golangci-lint` 会进入 planned。
5. 外部工具 dry-run 或执行完成后，自动 reset 生成文件。
6. 候选池中会导入工程治理候选，提示项目缺少可复现生成上下文。

## 注意

M15.2B 只实现 `swag init` 这一类最小闭环。`go generate`、build tags、GOPRIVATE、私有依赖配置等后续再扩展。
