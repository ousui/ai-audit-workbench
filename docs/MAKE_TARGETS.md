# Makefile 命令分组

Makefile 目标分为常用入口、验证入口、调试步骤和历史兼容入口。

## 常用入口

```bash
make install-deps
make check-deps
make env-summary
make tool-adapter-check
make tool-cache-check
make audit-static PROJECT_PATH=... PROJECT_CODE=... DRY_RUN=true
make audit-static PROJECT_PATH=... PROJECT_CODE=... ASSISTED_CHANGE=swag_init
make benchmark
```

## 验证入口

```bash
make py-compile
make smoke
make layout-verify
make verify
make verify-full
```

- `verify`：执行脚本编译、目录迁移校验、冒烟检查和 benchmark。
- `verify-full`：在 `verify` 基础上额外执行一次 `audit-static` dry-run。

## 调试步骤

这些命令用于 `audit-static` 某一步失败后的单步重跑：

```bash
make run-init PROJECT_PATH=... PROJECT_CODE=...
make audit-map RUN_ROOT=...
make project-doc-profile RUN_ROOT=...
make stack-env-check RUN_ROOT=...
make tool-adapter-check RUN_ROOT=...
make tool-cache-check RUN_ROOT=...
make tool-plan-stack RUN_ROOT=...
make preflight RUN_ROOT=...
make assisted-change RUN_ROOT=... ASSISTED_CHANGE=swag_init
make assisted-change-reset RUN_ROOT=...
make tool-execution-plan RUN_ROOT=...
make ext-tool-run RUN_ROOT=... DRY_RUN=true
make ext-tool-candidates RUN_ROOT=...
make evidence-pack RUN_ROOT=...
make tool-run RUN_ROOT=...
make candidates RUN_ROOT=...
make merge-external-candidates RUN_ROOT=...
make ai-triage RUN_ROOT=...
make merge RUN_ROOT=...
make delivery RUN_ROOT=...
make validate-run RUN_ROOT=...
make debug-trace RUN_ROOT=... DEBUG_LEVEL=basic
```

## 缓存更新入口

这些命令可能联网，必须显式设置 `ALLOW_NETWORK=true`。

```bash
make tool-cache-update TOOL_CACHE_TOOL=trivy ALLOW_NETWORK=true
make tool-cache-update TOOL_CACHE_TOOL=dependency-check ALLOW_NETWORK=true
```

## 历史兼容入口

```bash
make fast-static
make m0 ... m15
```

这些命令用于迁移期兼容和阶段性验证。后续主流程稳定后，可以逐步弱化或清理。
