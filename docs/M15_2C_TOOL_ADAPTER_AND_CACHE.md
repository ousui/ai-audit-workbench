# M15.2C：Tool Adapter / Tool Cache

本阶段目标：在正式执行外部安全工具前，先检查本机工具命令模板是否兼容，并检查常见工具缓存是否存在，避免审计过程中才发现 CLI 参数不兼容或规则库/漏洞库未初始化。

## 新增命令

```bash
make tool-adapter-check
make tool-cache-check
make tool-cache-update TOOL_CACHE_TOOL=trivy ALLOW_NETWORK=true
make tool-cache-update TOOL_CACHE_TOOL=dependency-check ALLOW_NETWORK=true
```

## 新增产物

本机长期状态：

```text
local/registry/hosts/current/TOOL_ADAPTER_STATUS.json
local/registry/hosts/current/TOOL_ADAPTER_STATUS.md
local/registry/tools/TOOL_CACHE_STATUS.json
local/registry/tools/TOOL_CACHE_STATUS.md
local/registry/tools/TOOL_CACHE_UPDATE_RESULT.json
local/registry/tools/TOOL_CACHE_UPDATE_RESULT.md
```

单次 run 快照：

```text
var/runs/<project>/<run>/evidence/TOOL_ADAPTER_STATUS.json
var/runs/<project>/<run>/evidence/TOOL_ADAPTER_STATUS.md
var/runs/<project>/<run>/evidence/TOOL_CACHE_STATUS.json
var/runs/<project>/<run>/evidence/TOOL_CACHE_STATUS.md
```

## 当前适配检测

- `golangci-lint`：检测 `--output.json.path` 与 `--out-format`，自动选择兼容命令模板。
- `govulncheck`：检测 JSON 输出能力。
- `semgrep`：检测 JSON 输出能力。
- `gitleaks`：检测 report-format/report-path 能力。
- `trivy`：检测 fs JSON 输出参数。
- `dependency-check`：检测 JSON/out 参数。

如果工具已安装但命令模板不兼容，`TOOL_EXECUTION_PLAN` 会将对应项标记为：

```text
blocked_tool_adapter_incompatible
```

## 当前缓存检测

缓存检测是保守的本地文件系统探测，只判断常见缓存目录是否存在，不判断漏洞库是否一定最新。

当前覆盖：

```text
trivy
dependency-check
semgrep
```

## 网络更新

缓存更新必须显式授权：

```bash
make tool-cache-update TOOL_CACHE_TOOL=trivy ALLOW_NETWORK=true
make tool-cache-update TOOL_CACHE_TOOL=dependency-check ALLOW_NETWORK=true
```

未设置 `ALLOW_NETWORK=true` 时只记录 blocked，不执行联网更新。

## 验证命令

```bash
make py-compile
make tool-adapter-check
make tool-cache-check
make verify-full
```

对真实项目：

```bash
make audit-static \
  PROJECT_PATH=/path/to/project \
  PROJECT_CODE=TOOL_ADAPTER_CACHE_TEST \
  NETWORK_AUTHORIZATION=once \
  DRY_RUN=true

cat var/runs/TOOL_ADAPTER_CACHE_TEST/FAST_STATIC_*/evidence/TOOL_ADAPTER_STATUS.md
cat var/runs/TOOL_ADAPTER_CACHE_TEST/FAST_STATIC_*/evidence/TOOL_CACHE_STATUS.md
cat var/runs/TOOL_ADAPTER_CACHE_TEST/FAST_STATIC_*/evidence/tool-execution/TOOL_EXECUTION_PLAN.md
```
