---
id: SKL-SP-003
layer: CC
dimension: governance
type: skill
object_type: Pattern
tier: warm
tags: [superpowers, writing-skills, dream, seed-absorber, self-learning]
source_ep: EP-000
created_at: "2026-07-19"
version: 1
about_concepts: [concise-skills, degrees-of-freedom, eval-driven]
cites_files:
  - src/mms/memory/dream.py
  - src/mms/analysis/seed_absorber.py
---

# SKL-SP-003: 可吸收技能写作规范（自学习层）

## 技能（Skill）

源自 writing-skills + Anthropic skill best practices + evals 思想。
写入知识库的技能/记忆必须：**简洁、可发现、自由度匹配脆弱度、可验证**。

## 原则

1. **Concise**：假设模型已很聪明；只补它没有的项目特有知识
2. **Degrees of freedom**：脆弱步骤用高约束；探索性步骤给启发式
3. **可发现**：name/description/tags 足以被 injector 命中
4. **可验证**：关键行为应能用测试或 checklist 回归（类比 superpowers evals/drill）

## 与 MMS Layer5

- `dream`：拒绝空洞通用建议（已有 NO_NEW_KNOWLEDGE 精神，本技能强化「具体可执行」）
- `seed_absorber`：吸收 CONTRIBUTING/规则时要求可映射到约束或模式
- `promote_draft`：晋升前检查是否满足 SKL-SP-003

映射约束：`SP-LEARN-001`。
