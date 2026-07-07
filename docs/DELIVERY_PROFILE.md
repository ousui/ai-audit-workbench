# Delivery Profile 使用说明

Delivery profile 用于控制审计交付物的字段、统计表和报告章节。

默认配置：

```text
spec/delivery/delivery-profile.default.yaml
```

本地可复制后修改：

```bash
mkdir -p local/conf
cp spec/delivery/delivery-profile.default.yaml local/conf/delivery-profile.local.yaml
```

验证本地配置：

```bash
make delivery-profile-validate DELIVERY_PROFILE=local/conf/delivery-profile.local.yaml
```

使用本地配置生成交付物：

```bash
make delivery RUN_ROOT="$RUN_ROOT" DELIVERY_PROFILE=local/conf/delivery-profile.local.yaml
```

## 字段配置

`tables.business_tracking.fields` 控制 `AUDIT_TRACKING.csv` 输出字段。默认只包含业务需要处理或确认的状态：

```text
FIND / REVIEW / RUNTIME / BLOCKED
```

`tables.audit_quality_items.fields` 控制 `AUDIT_QUALITY_ITEMS.csv` 输出字段。默认只包含审计侧质量状态：

```text
FP / CAND
```

`tables.all_items.enabled` 可选开启全量内部明细表 `AUDIT_ALL_ITEMS.csv`。

## 统计表

默认生成：

```text
AUDIT_STATS_BY_STATUS.csv
AUDIT_STATS_BY_SEVERITY.csv
AUDIT_STATS_BY_CATEGORY.csv
AUDIT_STATS_BY_CATEGORY_SEVERITY.csv
```

分类维度默认只使用风险大类 `risk_parent`，避免报告颗粒度过碎。

## 报告章节

`report.sections` 控制报告章节顺序和是否启用，例如：

```yaml
report:
  sections:
    - executive_summary
    - audit_scope
    - business_delivery_overview
    - stats_by_severity
    - stats_by_category
    - findings
    - review_items
    - runtime_items
    - blocked_items
    - audit_quality_appendix
    - limitations
```

当前阶段使用配置化章节，不引入复杂模板引擎。后续如需公司 Logo、主题、xlsx/docx/pptx，可在交付自动化阶段扩展。
