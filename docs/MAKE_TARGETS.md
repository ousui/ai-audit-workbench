# Makefile 命令分组

Makefile 目标分为常用入口、验证入口、调试步骤和历史兼容入口。

## 常用入口

```bash
make install-deps
make check-deps
make env-summary
make tool-adapter-check
make tool-cache-check
make audit-static PROJECT_PATH=... PROJECT_CODE=... DRY_RUN=true
make audit-static PROJECT_PATH=... PROJECT_CODE=... ASSISTED_CHANGE=swag_init
make audit-static PROJECT_PATH=... PROJECT_CODE=... AI_TRIAGE_MODE=file
make benchmark
```

## 验证入口

```bash
make py-compile
make smoke
make layout-verify
make verify
make verify-full
```

- `verify`：执行脚本编译、目录迁移校验、冒烟检查和 benchmark。
- `verify-full`：在 `verify` 基础上额外执行一次 `audit-static` dry-run。

## 调试步骤

这些命令用于 `audit-static` 某一步失败后的单步重跑：

```bash
make run-init PROJECT_PATH=... PROJECT_CODE=...
make audit-map RUN_ROOT=...
make project-doc-profile RUN_ROOT=...
make stack-env-check RUN_ROOT=...
make tool-adapter-check RUN_ROOT=...
make tool-cache-check RUN_ROOT=...
make tool-plan-stack RUN_ROOT=...
make preflight RUN_ROOT=...
make assisted-change RUN_ROOT=... ASSISTED_CHANGE=swag_init
make assisted-change-reset RUN_ROOT=...
make tool-execution-plan RUN_ROOT=...
make ext-tool-run RUN_ROOT=... DRY_RUN=true
make ext-tool-candidates RUN_ROOT=...
make evidence-pack RUN_ROOT=...
make tool-run RUN_ROOT=...
make candidates RUN_ROOT=...
make merge-external-candidates RUN_ROOT=...
make knowledge-match RUN_ROOT=...
make ai-triage-input RUN_ROOT=...
make ai-triage RUN_ROOT=...
make ai-triage-validate RUN_ROOT=...
make ai-triage-quality RUN_ROOT=...
make ai-jury-prompts RUN_ROOT=... AI_JURY_PROFILE=balanced
make ai-jury-merge RUN_ROOT=...
make after-ai-triage RUN_ROOT=...
make merge RUN_ROOT=...
make kb-suggestions RUN_ROOT=...
make delivery RUN_ROOT=...
make validate-run RUN_ROOT=...
make debug-trace RUN_ROOT=... DEBUG_LEVEL=basic
```

- `knowledge-match`：只读匹配 `local/registry/knowledge/AUDIT_KNOWLEDGE.yaml`，输出 `knowledge/KB_HITS.*`。
- `ai-triage-input`：只生成 `AI_TRIAGE_INPUT.json` 和 `AI_TRIAGE_HANDOFF.md`，不生成 stub，供真实 AI file-based handoff 使用。
- `ai-triage`：生成输入并写入 STUB 结果，仅用于流程验证。
- `ai-triage-validate`：校验人工或 AI 写入的 `AI_TRIAGE_RESULT.json`。
- `ai-triage-quality`：对 `AI_TRIAGE_RESULT.json` 做语义质量门禁，拦截分布异常、模板化、低质量 FIND/FP/RUNTIME，并输出 `AI_TRIAGE_QUALITY_RESULT.*`。
- `ai-jury-prompts`：根据 `spec/ai/jury-profiles.yaml` 生成 reviewer prompt pack、orchestrator prompt 和 reviewer 输出目录。
- `ai-jury-merge`：读取 `ai/reviewers/*/AI_TRIAGE_RESULT.json`，生成 consensus、disagreement 和 adjudication prompt，不写最终 `AI_TRIAGE_RESULT.json`。
- `after-ai-triage`：在真实 AI 输出写入并通过 schema 与 quality gate 后，继续执行 merge、kb-suggestions、delivery 和 validate-run。
- `kb-suggestions`：从 AI triage / merge 结果收集知识库更新建议，输出 `knowledge/KB_UPDATE_SUGGESTIONS.*`，不自动写入本地知识库。

## File-based AI triage

```bash
make audit-static \
  PROJECT_PATH=... \
  PROJECT_CODE=... \
  AI_TRIAGE_MODE=file \
  DRY_RUN=true

# 生成 AI Jury prompts：
make ai-jury-prompts RUN_ROOT=... AI_JURY_PROFILE=balanced

# reviewer 写入 ai/reviewers/<reviewer_id>/AI_TRIAGE_RESULT.json 后汇总：
make ai-jury-merge RUN_ROOT=...

# 写入 run_root/ai/AI_TRIAGE_RESULT.json 后继续：
make after-ai-triage RUN_ROOT=...
```

`after-ai-triage` 会先执行：

```text
ai-triage-validate
ai-triage-quality
```

如果质量门禁失败，不会继续进入 merge / delivery。

## 缓存更新入口

这些命令可能联网，必须显式设置 `ALLOW_NETWORK=true`。

```bash
make tool-cache-update TOOL_CACHE_TOOL=trivy ALLOW_NETWORK=true
make tool-cache-update TOOL_CACHE_TOOL=dependency-check ALLOW_NETWORK=true
```

## 历史兼容入口

```bash
make fast-static
make m0 ... m15
```

这些命令用于迁移期兼容和阶段性验证。后续主流程稳定后，可以逐步弱化或清理。
