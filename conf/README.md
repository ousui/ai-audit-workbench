# conf

`conf/` 存放工作台默认配置。这里的配置是可提交的团队默认值。

## 覆盖顺序

配置读取顺序应遵循：

```text
程序内置默认值
→ conf/*.yaml
→ local/conf/*.yaml
→ 环境变量 / CLI 参数
→ run-init 固化到本次 run
```

## 是否提交

提交到 Git。不得包含个人路径、客户项目路径、凭据或私有网络地址。

## 与 local/conf 的关系

`conf/` 是默认配置；`local/conf/` 是个人覆盖配置，不提交。
