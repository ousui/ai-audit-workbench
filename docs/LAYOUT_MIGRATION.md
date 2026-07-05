# 工作台目录迁移验证指南

本次迁移目标是将工作台从分散目录收敛为 Linux 风格目录：

```text
benchmarks/  回归测试
conf/        默认配置
docs/        人类可读文档
local/       本地长期状态，不提交
scripts/     程序脚本
spec/        规则、协议、schema、prompt、工作流定义
templates/   模板
var/         运行时产物，不提交
```

## 兼容策略

本阶段是兼容迁移：

- 新流程优先使用 `spec/`、`conf/`、`local/`、`var/`。
- 旧目录暂时保留，便于回滚和对比验证。
- 验证通过后再进入清理旧目录阶段。

## 验证步骤

```bash
git pull
make py-compile
make layout-verify
make smoke
make benchmark
```

正式流程 dry-run 验证：

```bash
make audit-static \
  PROJECT_PATH=benchmarks/fixtures/static-demo \
  PROJECT_CODE=LAYOUT_STATIC_DEMO \
  PROJECT_NAME="Layout Static Demo" \
  NETWORK_AUTHORIZATION=once \
  DRY_RUN=true
```

检查新产物位置：

```bash
find var/runs/LAYOUT_STATIC_DEMO -maxdepth 3 -type f | sort | head -80
cat var/runs/LAYOUT_STATIC_DEMO/FAST_STATIC_*/debug/AUDIT_STATIC_FLOW.md
```

环境检测输出位置：

```bash
make env-summary
cat local/registry/hosts/current/ENV_CHECK_RESULT.local.json | head
```

## 通过标准

- `make py-compile` 通过
- `make layout-verify` 通过
- `make smoke` 通过
- `make benchmark` 通过
- `make audit-static ... DRY_RUN=true` 通过
- 新 run 默认写入 `var/runs/`
- 本地环境检测默认写入 `local/registry/hosts/current/`

## 暂不清理的旧目录

以下旧目录本阶段暂时保留：

```text
env/
rules/
prompts/
schemas/
config/
dicts/
projects/
runs/
deliveries/
tmp/
.cache/
```

验证通过后再删除或改为兼容提示目录。
