---
id: SKL-SP-002
layer: CC_governance
dimension: governance
type: skill
object_type: Pattern
tier: warm
tags: [superpowers, code-review, plan-alignment, quality-gate]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [code-review, severity-calibration, plan-deviation]
cites_files:
  - src/mms/execution/internal_reviewer.py
---

# SKL-SP-002: 对照计划的代码评审

## 技能（Skill）

源自 requesting-code-review / code-reviewer 模板。
评审只读，对照计划与真实 diff，分级反馈。

## 检查维度

- 计划对齐：功能是否齐全；偏离是改进还是问题
- 代码质量：边界、错误处理、类型安全、边缘情况
- 架构：安全、可扩展、与周边集成
- 测试：测真实行为；关键路径有集成测
- 生产就绪：迁移、兼容、文档

## 输出格式

Strengths → Critical（必须修）→ Important（应修）→ Minor（可选）

## 与 MMS Layer4

`unit compare` / `internal_reviewer` 输出应对齐此分级，避免「事事 Critical」。
