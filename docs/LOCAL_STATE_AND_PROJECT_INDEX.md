# 本地状态与项目索引

AI Audit Workbench 将可提交的工作台规范与个人本地状态分离。

## 目录策略

```text
spec/                 已提交：流程规范、规则、schema、prompt、工具矩阵
conf/                 已提交：默认配置
local/                不提交：个人本地状态、项目源码、项目索引、环境画像
var/                  不提交：运行时产物、缓存、日志、临时文件
```

## 推荐 local 结构

`local/` 默认被 Git 忽略，不应提交。

```text
local/
  conf/               个人配置覆盖
  projects/           本地 clone 的被审项目源码
  deliveries/         人工整理后长期保留的交付材料
  registry/
    projects/         项目长期索引
    hosts/            本机环境画像
    tools/            工具适配状态、缓存状态摘要
    knowledge/        可复用经验、误报记忆、业务风险判断
```

## 为什么不用 `.cache/` 存项目索引

`.cache/` / `var/cache/` 语义是可重建缓存。项目索引可能包含人工确认过的项目事实、团队信息、历史纠偏和审计经验，不一定能安全重建，因此放在 `local/registry/`。

## 项目身份

项目身份优先从 Git 远程仓库地址派生。

建议 fingerprint 输入优先级：

1. 标准化后的 `git remote get-url origin`
2. 无远程地址时使用仓库根路径
3. 人工提供的项目代码

fingerprint 应稳定，且不在文件名中暴露完整仓库地址。

## 事实优先级

审计地图事实优先级：

1. 本轮人工确认
2. 当前最新版代码与 manifest
3. 当前工具证据与 preflight 输出
4. AI 基于当前代码推理
5. AI 从当前项目文档提取
6. 本地 registry 历史索引
7. 过期或来源不明的文档

本地 registry 可以辅助稳定项，例如项目负责人、中文名、运维团队、上下游依赖；但不得覆盖当前代码事实，例如框架版本、依赖版本、包管理器、构建系统、工具链要求。

## 分享策略

默认不分享 `local/registry/`。如后续团队需要共享，应先导出脱敏快照到单独位置，例如：

```text
exports/project-index-sanitized/
```

不得把原始项目索引、客户信息、私有仓库地址、人员信息、密钥或审计产物提交到工作台仓库。
