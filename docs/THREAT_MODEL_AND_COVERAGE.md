# Threat Model / Coverage / Attack Path

## 背景

当前工作台已经能通过工具和 AI triage 发现候选并形成审计结论，但候选仍偏“规则命中”。后续需要借鉴安全审计插件的思想，把候选升级为：

```text
待证明或待推翻的安全 claim
```

也就是从：

```text
命中了一个模式
```

升级为：

```text
该模式是否真的跨越信任边界、可被攻击者触发、到达危险 sink、造成实际影响？
```

## M15.5A 已实现：Threat Model / Coverage 基础产物

当前已实现：

```text
scripts/66_build_threat_model.py
scripts/67_build_coverage_map.py
spec/rules/threat-model.yaml

make threat-model RUN_ROOT=...
make coverage-map RUN_ROOT=...
```

输出：

```text
threat/THREAT_MODEL.json
threat/THREAT_MODEL.md
coverage/COVERAGE_MAP.json
coverage/COVERAGE_MAP.md
```

定位：

```text
Threat Model  识别资产、入口和信任边界
Coverage Map 识别覆盖维度、风险大类覆盖、覆盖缺口和 AI Deep Review 优先级
```

它们都是静态、只读、辅助性产物，不直接证明漏洞成立。

## M15.5B 已实现：AI Deep Review file-based scaffold

当前已实现：

```text
scripts/68_prepare_ai_deep_review.py
scripts/69_validate_ai_deep_review.py
spec/schemas/AI_DEEP_REVIEW_RESULT.schema.json

make ai-deep-review-input RUN_ROOT=...
make ai-deep-review-validate RUN_ROOT=...
```

输出：

```text
ai/deep-review/AI_DEEP_REVIEW_INPUT.json
ai/deep-review/AI_DEEP_REVIEW_PROMPT.md
ai/deep-review/AI_DEEP_REVIEW_RESULT.json              # 人工 / AI 工具写入
ai/deep-review/AI_DEEP_REVIEW_VALIDATION_RESULT.json   # validate 后生成
ai/deep-review/AI_DEEP_REVIEW_VALIDATION_RESULT.md
```

定位：

```text
AI Deep Review 是候选发现阶段，不是最终裁决阶段。
它模拟人工审计翻代码、看接口、看上下游链路，补充潜在候选风险。
AI Deep Review 输出不得包含最终 FIND/FP/REVIEW/RUNTIME 等 audit decision。
```

当前阶段只生成输入、提示词和结果校验；**不导入候选池**。导入候选是 M15.5C。

## Threat Model

字段：

```text
assets              资产，例如账号权限、业务交易、数据存储、文件存储、配置密钥
entrypoints         入口，例如 HTTP/API、前端 API 调用、异步回调
trust_boundaries    信任边界，例如外部到服务端、认证到授权、服务端到数据库
review_focus        后续 AI Deep Review 的审计关注点
```

生成依据：

```text
audit-map/AUDIT_MAP.json
audit-map/PROJECT_FACTS.json
audit-map/PROJECT_DOC_PROFILE.json
candidates/CANDIDATE_POOL.json
spec/rules/threat-model.yaml
```

## Coverage Map

字段：

```text
dimensions                  route/auth/data/file/high-risk/config 等覆盖维度
risk_parent_coverage         风险大类覆盖情况
coverage_gaps                覆盖缺口
ai_deep_review_priorities    AI Deep Review 优先审计方向
```

Coverage 的作用是说明：

```text
这轮审计看过什么
哪些维度有候选覆盖
哪些维度只有审计地图证据但没有候选
哪些位置应该交给 AI Deep Review 主动翻代码
```

## AI Deep Review 的位置

AI Deep Review 使用：

```text
THREAT_MODEL
COVERAGE_MAP
CANDIDATE_POOL
KB_HITS
PROJECT_FACTS
PROJECT_DOC_PROFILE
AUDIT_MAP focus files / signals
```

作为输入，像人工审计一样主动翻代码、看接口、看上下游链路，并补充候选。

重要边界：

```text
AI Deep Review 只发现/补充候选，不直接输出最终 FIND/FP。
Deep Review 候选仍需进入 AI triage / AI Jury 统一判断。
```

## Candidate Claim Model

后续 candidate 应逐步增加 claim 字段：

```text
claim                   风险主张
attacker_source         攻击者可控输入来源
entrypoint              入口点
trust_boundary          信任边界
root_control            根控制点 / root cause
sink                    危险 sink / 安全控制点
reachable_path          可达路径
evidence_for            支持风险成立的证据
evidence_against        反证
proof_gaps              证据缺口
validation_method       验证方法
```

## Attack Path

AI triage / merge / report 后续应支持：

```text
source -> trust_boundary -> control -> sink -> impact
```

并明确：

```text
preconditions           成立前提
reachability            可达性
counterevidence         反证
proof_gap               缺口
severity_rationale      等级依据
```

## 与当前状态模型的关系

```text
FIND      仓库证据足以证明 claim 成立
FP        仓库证据足以推翻 claim
REVIEW    静态证据不足，需要人工业务判断
RUNTIME   缺运行时、环境、调用方或数据流证据
BLOCKED   工具、依赖、环境、权限阻断
CAND      弱线索保留，尚未充分判断
```

## 分阶段落地

```text
M15.5A  生成基础 THREAT_MODEL / COVERAGE              已实现
M15.5B  AI Deep Review file-based scaffold             已实现
M15.5C  导入 AI Deep Review 候选                        待做
M15.5D  Candidate Pool 增加 claim/source/sink/proof_gap 待做
M15.5E  Merge / Report 展示 attack path 和 coverage     待做
M16     CHK / bounded validation 正式消化 proof gaps    待做
```
