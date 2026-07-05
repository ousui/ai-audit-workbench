# dicts

`dicts/` stores committed dictionaries and controlled vocabularies used by AI Audit Workbench.

Use this directory for relatively stable, shareable, non-project-specific definitions, for example:

- risk taxonomy and subtype enums
- severity and priority labels
- project document profile fields
- audit-map field labels
- source-type and confidence enums

Do not store personal project index data, customer-specific information, raw audit outputs, secrets, or local cache data here.

Local, user-specific, or sensitive project index data belongs under ignored `local/`, for example:

```text
local/project-index/
local/tool-cache/
local/overrides/
```

## Naming rule

- YAML files in this directory define canonical dictionaries.
- Enum-like IDs must use stable uppercase snake case.
- Chinese labels are display labels, not IDs.
- Existing IDs should not be renamed casually; add aliases or deprecate instead.
