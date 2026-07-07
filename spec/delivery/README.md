# Delivery Profile

Delivery profile controls how merge results are rendered into business-facing and audit-facing delivery artifacts.

Default profile:

```text
spec/delivery/delivery-profile.default.yaml
```

Local override example:

```text
local/conf/delivery-profile.local.yaml
```

The profile is intentionally conservative:

```text
AUDIT_TRACKING.csv       business action table: FIND / REVIEW / RUNTIME / BLOCKED
AUDIT_QUALITY_ITEMS.csv  audit quality table: FP / CAND
AUDIT_ALL_ITEMS.csv      optional internal full detail table
AUDIT_STATS_*.csv        status / severity / category statistics
```

`risk_parent` is used as the default category dimension. `risk_subtype` is kept in detail tables, but is not used as the primary report category to avoid over-fragmented delivery reports.

Validate a profile with:

```bash
make delivery-profile-validate DELIVERY_PROFILE=spec/delivery/delivery-profile.default.yaml
```
