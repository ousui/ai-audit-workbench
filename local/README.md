# local

`local/` 存放个人本地长期状态，不随工作台提交。

## 是否提交

默认不提交。仅保留本 README 说明目录职责。

## 结构

```text
local/
  conf/        个人配置覆盖
  projects/    本地 clone 的被审项目
  deliveries/  人工整理后需要长期保留的交付材料
  registry/    本地索引库、环境画像、工具画像、经验记忆
```

## 与 var 的区别

- `local/`：不应随意删除，可能包含人工确认过的信息。
- `var/`：运行时产物，可按策略清理。
