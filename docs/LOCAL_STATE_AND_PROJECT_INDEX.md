# Local state and project index

AI Audit Workbench keeps source-controlled workflow logic separate from local personal state.

## Directory policy

```text
dicts/                 committed dictionaries and controlled vocabularies
local/                 ignored local state, personal project index, manual overrides
.cache/                ignored rebuildable runtime cache
tmp/                   ignored temporary files
runs/                  ignored audit run outputs
```

## Recommended local layout

`local/` is ignored by Git and should not be committed.

```text
local/
  project-index/
    <repo_fingerprint>/
      PROJECT_INDEX.json
      PROJECT_INDEX.md
      HISTORY.jsonl
  overrides/
    <repo_fingerprint>/
      AUDIT_MAP_OVERRIDE.json
  tool-cache/
    TOOL_CACHE_STATUS.json
```

## Why not `.cache/` for project index?

`.cache/` is for rebuildable runtime cache. The project index may contain human-confirmed project facts, team information, historical corrections, and audit workflow notes. It is local and private, but it is not always safely rebuildable. Therefore `local/project-index/` is preferred.

## Project identity

The primary project identity should be derived from the remote Git repository URL when available.

Suggested fingerprint input order:

1. normalized `git remote get-url origin`
2. repository root path when remote URL is unavailable
3. explicit human-provided project code

The fingerprint should be stable and should not expose the full repository URL in filenames.

## Fact priority

Audit-map facts must follow this priority:

1. Human override for the current audit run
2. Current latest code and manifests
3. Current tool evidence and preflight output
4. AI inference from current code
5. AI extraction from current project documents
6. Local project index
7. Stale or unknown documents

The local project index is useful for stable project metadata, but it must not override current code facts such as framework versions, package managers, build systems, dependency manifests, or toolchain requirements.

## Share policy

By default, `local/project-index/` is personal and not shared with the workbench repository.

For team sharing, export a sanitized snapshot into a separate controlled location later, for example:

```text
exports/project-index-sanitized/
```

Do not commit raw project index data, customer-specific information, secrets, private URLs, or audit outputs into the workbench repository.
