# M15.2A：PROJECT_FACTS / Preflight / Manifest-aware Gating

本阶段目标：让工作台在执行外部工具前，先根据当前代码事实和工程制式判断工具是否适用，并记录无法继续执行的项目上下文问题。

## 新增/增强产物

```text
var/runs/<project>/<run>/audit-map/PROJECT_FACTS.json
var/runs/<project>/<run>/audit-map/PROJECT_FACTS.md
var/runs/<project>/<run>/evidence/PREFLIGHT_RESULT.json
var/runs/<project>/<run>/evidence/PREFLIGHT_RESULT.md
var/runs/<project>/<run>/evidence/tool-execution/TOOL_EXECUTION_PLAN.json
```

## 工具状态

```text
planned                      可以执行
not_applicable_by_manifest   当前项目 manifest 证明该工具不适用
blocked_requires_context     当前项目需要构建上下文/生成代码/私有依赖等处理后才能执行
skipped_by_policy            策略禁止执行，例如显式禁止工具联网
```

## 当前规则

- `mvn` 仅在发现 `pom.xml` 时执行。
- `gradle` 仅在发现 Gradle manifest 或 wrapper 时执行。
- `dependency-check` 当前仅在 Java/JVM 依赖 manifest 存在时执行。
- `govulncheck` / `golangci-lint` 要求 `go.mod`，并且 `go list ./...` preflight 成功。
- `npm` 要求 `package.json`。
- `pnpm` 要求 `pnpm-lock.yaml`。
- `yarn` 要求 `yarn.lock`。

## Go / swag 场景

如果 `go list ./...` 失败，并且项目存在 `xxx/docs` import 或 swag 注释，preflight 会给出提示：后续 assisted-change 阶段可以在授权后尝试 `swag init`，再重跑 Go 工具。

M15.2A 只做识别和阻断记录，不自动修改项目源码。自动或授权辅助变更属于 M15.2B。

## 验证命令

```bash
make py-compile
make verify-full
```

真实 Go 项目验证建议：

```bash
make audit-static \
  PROJECT_PATH=/path/to/go-project \
  PROJECT_CODE=GO_PREFLIGHT_TEST \
  NETWORK_AUTHORIZATION=once \
  DRY_RUN=true

cat var/runs/GO_PREFLIGHT_TEST/FAST_STATIC_*/evidence/PREFLIGHT_RESULT.md
cat var/runs/GO_PREFLIGHT_TEST/FAST_STATIC_*/evidence/tool-execution/TOOL_EXECUTION_PLAN.md
```
