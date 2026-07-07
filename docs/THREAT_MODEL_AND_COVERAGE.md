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

## Threat Model

建议产物：

```text
audit-map/THREAT_MODEL.json
audit-map/THREAT_MODEL.md
```

建议字段：

```text
assets                  资产
entry_points            入口点
trust_boundaries        信任边界
security_invariants     安全不变量
sensitive_actions       敏感动作
external_services       外部服务
auth_session_model      认证与会话模型
file_surfaces           上传、下载、路径处理面
admin_surfaces          管理后台和高权限操作
payment_or_fund_surfaces 资金、积分、订单等业务资产
```

## Coverage

建议产物：

```text
evidence/COVERAGE.json
evidence/COVERAGE.md
```

建议字段：

```text
reviewed_surfaces       已覆盖面
deferred_surfaces       延后覆盖面
out_of_scope            明确排除范围
tool_blocked_areas      工具阻断区域
proof_gaps              证据缺口
unresolved_entrypoints  未解析入口点
manual_review_needed    需要人工确认的点
```

Coverage 的作用是说明：

```text
这轮审计看过什么
没有看什么
为什么没看
哪些风险仍然缺证据
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
M15.5A  生成基础 THREAT_MODEL / COVERAGE
M15.5B  Candidate Pool 增加 claim fields
M15.5C  AI triage prompt 增加 source/sink/trust boundary/proof gap 要求
M15.5D  Merge / Report 展示 attack path 和 coverage
M16     CHK / bounded validation 正式消化 proof gaps
```
