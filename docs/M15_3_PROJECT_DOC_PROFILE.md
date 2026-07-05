# M15.3：PROJECT_DOC_PROFILE + local/registry 项目索引

本阶段目标：从当前项目文档、README、Makefile、CI 配置等材料中提取项目画像信息，并写入本轮 run 与本地项目索引。

## 重要原则

项目文档画像是辅助信息，不覆盖当前代码事实。

优先级：

```text
human_current_run_confirmation
current_code_manifest
current_tool_evidence
ai_inference_from_current_code
current_project_docs_extract
local_registry_history
stale_or_unknown_docs
```

如果文档写法和 `PROJECT_FACTS` 或工具结果冲突，以当前代码事实为准。

## registry 项目 ID

`local/registry/projects/<project_id>/` 不使用 `PROJECT_CODE` 或目录名作为主键。

默认策略：

```text
manual > git-remote-subpath-hash > svn-url-subpath-hash > dir-hash
```

Git 项目的默认 ID：

```text
project_id = git-<sha256_16>
hash_input = git:<normalized_remote_url>#<repo_relative_path>
```

`PROJECT_CODE` 只作为 `aliases.project_codes`，不是 registry 主键。

## 新增产物

单次 run：

```text
var/runs/<project>/<run>/audit-map/PROJECT_DOC_PROFILE.json
var/runs/<project>/<run>/audit-map/PROJECT_DOC_PROFILE.md
```

本地长期索引：

```text
local/registry/projects/<project_id>/PROJECT_INDEX.yaml
```

`local/registry` 默认不提交，用于保留本机长期项目画像。

## PROJECT_INDEX.yaml 结构

只使用一个 YAML 文件，不拆分多个 registry 文件。

```yaml
schema_version: project-index-0.2.0
identity: {}
aliases: {}
generated: {}
manual: {}
history: {}
```

- `identity`：稳定项目身份，程序维护。
- `aliases`：项目代码、项目名、目录名，程序追加合并，不随意删除。
- `generated`：当前 run 生成的摘要，程序覆盖。
- `manual`：人工维护区，程序只初始化，不覆盖。
- `history`：最近 run 摘要，程序保留最近 20 条。

## 当前提取内容

- 项目代码、仓库地址、主语言、构建系统、包管理器：来自当前代码事实。
- 项目名称：优先从 README 第一个标题提取，仅作为低置信文档线索。
- 构建命令、启动命令、测试命令：从 README、docs、Makefile、CI workflow 中用确定性规则提取。
- API 文档、运维文档、外部服务 URL：从文档路径和 URL 线索中提取。
- 已知风险/限制：从 TODO、FIXME、风险、限制、warning 等关键词提取，需复核。

## 新增命令

```bash
make project-doc-profile RUN_ROOT=...
```

## 主流程位置

`audit-static` 中的顺序：

```text
audit-map
project-doc-profile
stack-env-check
...
evidence-pack
```

`EVIDENCE_PACK` 会带上 `PROJECT_DOC_PROFILE` 摘要。

## 验证方式

```bash
make py-compile
make verify-full
```

真实项目：

```bash
make audit-static \
  PROJECT_PATH=/path/to/project \
  PROJECT_CODE=DOC_PROFILE_TEST \
  NETWORK_AUTHORIZATION=once \
  DRY_RUN=true

cat var/runs/DOC_PROFILE_TEST/FAST_STATIC_*/audit-map/PROJECT_DOC_PROFILE.md
find local/registry/projects -maxdepth 2 -name PROJECT_INDEX.yaml -print
cat local/registry/projects/*/PROJECT_INDEX.yaml
```
