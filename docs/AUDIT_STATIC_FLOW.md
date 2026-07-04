# AUDIT_STATIC formal flow

This document records the intended static audit execution order. Earlier `m1` to `m14` targets were built in capability-construction order. `audit-static` is the formal run order for real project audits.

## Principles

- Tool discovery and tool execution happen before AI triage.
- Offline and online tool profiles are separate evidence sources.
- Online profile execution depends on run-init authorization.
- Missing or failed recommended tools degrade coverage but do not silently become "no risk".
- Candidates never become FIND directly. AI triage / merge is required before delivery.
- CHK is not part of initial discovery. CHK is a later fix-verification flow based on existing findings.

## Formal order

1. `check-deps`
2. `run-init`
   - Creates `RUN_METADATA.json`.
   - Creates `AUTHORIZATION.json`.
   - Records output root and workspace mode.
3. `audit-map`
   - Detects stacks and source structure.
4. `stack-env-check`
   - Detects tools relevant to this project and shared static tools.
5. `tool-plan`
   - Decides selected / skipped / missing / blocked tools.
6. `tool-execution-plan`
   - Builds offline and online commands.
7. `ext-tool-run`
   - Executes planned external tools.
   - Records stdout / stderr / exit code / output files.
8. `ext-tool-candidates`
   - Normalizes external tool outputs to candidate format.
9. `evidence-pack`
10. `built-in-tool-run`
    - Runs deterministic built-in static recipes.
11. `candidate-pool`
    - Builds the base candidate pool.
12. `merge-external-candidates`
    - Imports external tool candidates into the main candidate pool.
13. `ai-triage`
14. `merge`
15. `delivery`
16. `validate`
17. `debug-trace` when debug is enabled.

## Main command

```bash
make audit-static \
  PROJECT_PATH=projects/demo \
  PROJECT_CODE=DEMO \
  PROJECT_NAME='Demo Project' \
  NETWORK_AUTHORIZATION=once
```

Use `DRY_RUN=true` to validate the external-tool execution layer without running external tools.

```bash
make audit-static \
  PROJECT_PATH=projects/demo \
  PROJECT_CODE=DEMO \
  PROJECT_NAME='Demo Project' \
  NETWORK_AUTHORIZATION=once \
  DRY_RUN=true
```

## Output modes

Workbench mode:

```bash
make audit-static PROJECT_PATH=/path/to/project OUTPUT_ROOT=runs WORKSPACE_MODE=workbench
```

Project mode:

```bash
make audit-static PROJECT_PATH=. OUTPUT_ROOT=.audit-runs WORKSPACE_MODE=project
```

## Authorization modes

- `deny`: offline profile only; online profile is skipped by policy.
- `once`: online profile is authorized for this run.
- `always`: online profile is authorized by user preference for this run invocation.

The effective authorization is recorded in `meta/AUTHORIZATION.json`.
