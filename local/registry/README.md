# local/registry

`local/registry/` 是本地索引库，不提交。

## 结构

```text
local/registry/
  projects/   项目长期索引，按稳定 project_id 分目录
  hosts/      本机环境画像、工具安装状态、适配检测结果
  tools/      工具规则库/缓存状态摘要、工具适配状态
  knowledge/  可复用的审计经验、误报记忆、业务风险判断
```

## 项目索引主键

`local/registry/projects/<project_id>/` 不使用 `PROJECT_CODE` 或目录名作为主键。

默认策略固定为：

```text
manual > git-remote-subpath-hash > svn-url-subpath-hash > dir-hash
```

Git 项目的默认 ID：

```text
project_id = git-<sha256_16>
hash_input = git:<normalized_remote_url>#<repo_relative_path>
```

`PROJECT_CODE` 只作为 alias，不作为 registry 主键。

## 项目索引文件

每个项目只生成一个索引文件：

```text
local/registry/projects/<project_id>/PROJECT_INDEX.yaml
```

不拆分 `PROJECT_ID.yaml`、`PROJECT_OVERRIDES.yaml`、`PROJECT_NOTES.md`。

`PROJECT_INDEX.yaml` 顶层结构固定为：

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

## 存储格式规则

规则固定：

```text
var/runs/        JSON
local/registry/  YAML
```

后续新增 registry 存储也使用 YAML。

## 使用原则

索引库只能辅助审计，不允许覆盖当前代码事实。

事实优先级：

```text
人工本轮确认
当前代码和 manifest
当前工具证据
AI 当前推理
当前项目文档提取
本地索引历史
可能过期或来源不明的文档
```

## 清理原则

当前阶段可以保留历史兼容文件。最后整理阶段应删除不再生成、不再读取的过期内容。
